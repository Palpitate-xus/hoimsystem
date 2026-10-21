"""Durable charged-ledger execution: no SQL session is held across inference."""

import datetime
import time

from fastapi import HTTPException

from app.ai import charge_reconciliation_receipts as receipts
from app.ai import charge_reconciliation_sources as sources
from app.ai.charge_reconciliation_gateway import generate_charge
from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.charge_reconciliation_runtime import actor_epoch, authorize_charge_run, current_actor, recheck
from app.ai.charge_reconciliation_storage import load_snapshot
from app.ai.charge_reconciliation_write_guard import lock_charge_gate
from app.ai.gateway import AIExecutionError
from app.ai.governance import audit
from app.ai.models import AIRun
from app.ai.native_acceptance import acceptance_state


def _locked_run(db, run_id, lease=None):
    # Global Billing X precedes actual Run/Artifact/Source locks, including errors.
    lock_charge_gate(db)
    query = db.query(AIRun).filter_by(run_id=run_id)
    if lease is not None:
        query = query.filter(AIRun.status.in_(["running", "cancelled"]), AIRun.lease_token == lease)
    return query.populate_existing().with_for_update().one_or_none()


def _account(run, receipt, started):
    run.input_tokens = receipt["input_tokens"] if receipt["input_tokens"] is not None else 0
    run.output_tokens = receipt["output_tokens"] if receipt["output_tokens"] is not None else 0
    run.latency_ms = int((time.monotonic() - started) * 1000)
    run.finish_time = sources.utcnow()


def _stage_audit(db, run, actor_id, action):
    audit(db, actor_id, action, run.run_id)
    expected = acceptance_state(db, run, action)
    expected["run"] = {key: getattr(run, key) for key in receipts.WRITE_FIELDS}
    row = db.get(AIChargeRunArtifact, run.run_id)
    expected["artifact"] = {key: getattr(row, key) for key in receipts.ARTIFACT_FIELDS}
    db.flush()
    receipts._verify_write(db, run, expected)
    return expected


def cancel_charge_run(db, user, run_id):
    try:
        # Actor takes Billing Gate before the Run X lock.
        actor = current_actor(db, user)
        epoch = actor_epoch(actor)
        run = _locked_run(db, run_id)
        if run is None:
            raise HTTPException(404, "AI 任务不存在")
        authorize_charge_run(db, actor, run)
        receipts.load_terminal(db, run)
        if run.status not in {"queued", "running"}:
            raise HTTPException(409, "任务已结束")
        queued = run.status == "queued"
        if queued and (
            run.lease_token is not None
            or run.start_time is not None
            or run.latency_ms is not None
            or run.finish_time is not None
            or run.result_json != "{}"
            or run.input_tokens != 0
            or run.output_tokens != 0
            or run.error_code is not None
            or run.error_message is not None
        ):
            raise HTTPException(409, "排队账目任务已有执行痕迹，不能声明未调用模型")
        run.status, run.finish_time = "cancelled", sources.utcnow()
        terminal = None
        if queued:
            run.latency_ms = 0
            terminal = receipts.stage_terminal(db, run, receipts.usage(0, 0, False))
        _stage_audit(db, run, actor.user_id, "run.cancel")
        if terminal is not None:
            receipts._verify_write(db, run, terminal)
            receipts.load_terminal(db, run)
        authorize_charge_run(db, actor, run)
        current_actor(db, actor, expected=epoch)
        db.commit()
    except Exception:
        db.rollback()
        raise


async def execute_charge_claimed(run_id, lease, *, transport=None):
    from app import database

    started, error, result, epoch = time.monotonic(), None, None, None
    receipt = receipts.usage(0, 0, False)
    try:
        with database.SessionLocal() as db:
            run = _locked_run(db, run_id, lease)
            if run is None:
                return
            load_snapshot(db, run)
            cancelled_before_call = run.status == "cancelled"
            if cancelled_before_call:
                if run.latency_ms is not None:
                    return
                receipts.load_terminal(db, run)
            else:
                spec, provider, snapshot, epoch = recheck(db, run)
                db.expunge(provider)
        if not cancelled_before_call:
            result, inputs, outputs = await generate_charge(provider, spec, snapshot["task_prompt"], snapshot["payload"], transport=transport)
            receipt = receipts.usage(inputs, outputs, True)
    except AIExecutionError as exc:
        attempted = getattr(exc, "model_call_attempted", receipt["model_call_attempted"])
        receipt = receipts.usage(exc.input_tokens, exc.output_tokens, True) if attempted else receipts.usage(0, 0, False)
        error = exc.code, exc.message
    except HTTPException as exc:
        error = "TASK_NO_LONGER_AUTHORIZED", str(exc.detail)
    except Exception:
        # Gateway converts provider-side exceptions with its precise attempt flag.
        error = "TASK_EXECUTION_ERROR", "账目任务处理失败，请联系管理员核对状态"
    with database.SessionLocal() as db:
        run = _locked_run(db, run_id, lease)
        if run is None or run.status == "cancelled" and run.latency_ms is not None:
            return
        try:
            if run.status != "cancelled" and error is None:
                try:
                    recheck(db, run, expected_epoch=epoch)
                except AIExecutionError as exc:
                    error = exc.code, exc.message
                except HTTPException as exc:
                    error = "TASK_NO_LONGER_AUTHORIZED", str(exc.detail)
            _account(run, receipt, started)
            if run.status != "cancelled":
                if error:
                    run.status, (run.error_code, run.error_message) = "failed", error
                else:
                    run.status = "succeeded"
            accepted = result.model_dump(mode="json") if run.status == "succeeded" else None
            expected = receipts.stage_terminal(db, run, receipt, accepted)
            if run.status == "succeeded":
                recheck(db, run, expected_epoch=epoch)
                receipts._verify_write(db, run, expected)
                if receipts.load_terminal(db, run)[0] != accepted:
                    raise HTTPException(409, "实际完整结果与本次模型草稿不同")
            db.commit()
        except Exception:
            db.rollback()
            failed = _locked_run(db, run_id, lease)
            if failed is not None and not (failed.status == "cancelled" and failed.latency_ms is not None):
                failed.status = "cancelled" if failed.status == "cancelled" else "failed"
                failed.result_json = "{}"
                failed.error_code = "RESULT_STORAGE_ERROR"
                failed.error_message = "完整账目结果与具体接收审计未能原子保存，结果未接收"
                _account(failed, receipt, started)
                try:
                    receipts.stage_terminal(db, failed, receipt)
                    db.commit()
                except Exception:
                    db.rollback()
                    raise


def expire_interrupted_charge_runs(db):
    """Record unknown call/usage after interruption; never repeat a billable call."""
    lock_charge_gate(db)
    deadline = sources.utcnow() - datetime.timedelta(minutes=10)
    rows = (
        db.query(AIRun)
        .join(AIChargeRunArtifact, AIRun.run_id == AIChargeRunArtifact.run_id)
        .filter(AIRun.status.in_(["running", "cancelled"]), AIRun.start_time < deadline, AIRun.lease_token.is_not(None), AIChargeRunArtifact.receipt_event_id.is_(None))
        .order_by(AIRun.run_id)
        .populate_existing()
        .with_for_update()
        .all()
    )
    try:
        for run in rows:
            run.status = "cancelled" if run.status == "cancelled" else "failed"
            run.error_code = "WORKER_INTERRUPTED"
            run.error_message = "执行进程中断，实际模型调用状态和用量未知，未自动重试"
            run.input_tokens = run.output_tokens = 0
            run.finish_time = sources.utcnow()
            run.latency_ms = max(0, int((sources.utcnow() - run.start_time).total_seconds() * 1000))
            receipts.stage_terminal(db, run, receipts.usage())
        db.commit()
        return len(rows)
    except Exception:
        db.rollback()
        raise
