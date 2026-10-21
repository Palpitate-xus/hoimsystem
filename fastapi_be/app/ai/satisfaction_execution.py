"""Dedicated durable execution with no SQL transaction held across model await."""

import datetime
import time
import uuid
from types import SimpleNamespace

from fastapi import HTTPException

from app.ai import satisfaction_receipts as receipts
from app.ai.gateway import AIExecutionError
from app.ai.models import AIAuditEvent, AIRun
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_draft import canonical_json
from app.ai.satisfaction_gateway import generate_satisfaction
from app.ai.satisfaction_runtime import actor_epoch, authorize_satisfaction_run, current_actor, recheck
from app.ai.satisfaction_sources import utcnow
from app.ai.satisfaction_storage import load_snapshot, stage_result
from app.ai.satisfaction_write_guard import current_actor as read_actor
from app.ai.satisfaction_write_guard import lock_satisfaction_gate


def _factory(value):
    if value is not None:
        return value
    from app.database import SessionLocal

    return SessionLocal


def locked_run(db, run_id, lease=None):
    """Gate -> technical owner locator -> current User SHARE -> actual Run UPDATE.

    The locator makes no permission decision and loads no task body. A retained
    RR locator is compared again after the current locked Run read. Final error
    accounting may record a demoted requester's paid usage, without granting that
    account access to Source/result bodies or a new model call.
    """
    from app.dependencies import VALID_USER_ROLES

    lock_satisfaction_gate(db)
    with db.no_autoflush:
        owner = db.query(AIRun.requested_by).filter_by(run_id=run_id).scalar()
    if owner is None:
        return None
    read_actor(db, SimpleNamespace(user_id=owner), allowed_roles=VALID_USER_ROLES)
    query = db.query(AIRun).filter_by(run_id=run_id)
    if lease is not None:
        query = query.filter(AIRun.status.in_(["running", "cancelled"]), AIRun.lease_token == lease)
    with db.no_autoflush:
        run = query.populate_existing().with_for_update().one_or_none()
    if run is not None and run.requested_by != owner:
        raise HTTPException(409, "评价任务当前所属账户已变化")
    return run


def _event(db, run, actor_id, action):
    event = AIAuditEvent(actor_id=actor_id, action=action, target=run.run_id, detail_json=canonical_json({"status": run.status, "lease_token": run.lease_token}))
    expected = {"run": {key: getattr(run, key) for key in receipts.WRITE_FIELDS}, "audit": {key: getattr(event, key) for key in ("actor_id", "action", "target", "detail_json")}, "event": event}
    artifact = db.get(AISatisfactionRunArtifact, run.run_id)
    expected["artifact"] = {key: getattr(artifact, key) for key in receipts.ARTIFACT_FIELDS}
    db.add(event)
    db.flush()
    receipts.readback(db, run, expected)
    return expected


def claim_satisfaction_run(db, run_id):
    """One actual SQL claim; execution performs Source/config checks before call."""
    try:
        run = locked_run(db, run_id)
        if run is None or run.status != "queued":
            db.rollback()
            return None
        load_snapshot(db, run)
        if (
            run.lease_token is not None
            or run.start_time is not None
            or run.finish_time is not None
            or run.latency_ms is not None
            or run.result_json != "{}"
            or run.error_code is not None
            or run.error_message is not None
            or run.input_tokens != 0
            or run.output_tokens != 0
        ):
            raise HTTPException(409, "排队评价任务已有执行痕迹，不能重新领取")
        run.status, run.lease_token, run.start_time = "running", str(uuid.uuid4()), utcnow()
        lease = run.lease_token
        expected = _event(db, run, run.requested_by, "run.satisfaction.claim")
        receipts.readback(db, run, expected)
        db.commit()
        return lease
    except Exception:
        db.rollback()
        raise


def _account(run, receipt, started):
    run.input_tokens = receipt["input_tokens"] if receipt["input_tokens"] is not None else 0
    run.output_tokens = receipt["output_tokens"] if receipt["output_tokens"] is not None else 0
    run.latency_ms = max(0, int((time.monotonic() - started) * 1000))
    run.finish_time = utcnow()


def cancel_satisfaction_run(db, user, run_id):
    try:
        actor = current_actor(db, user)
        epoch = actor_epoch(actor)
        run = locked_run(db, run_id)
        if run is None:
            raise HTTPException(404, "评价任务不存在")
        authorize_satisfaction_run(db, actor, run, audit_only=actor.user_role == "super_admin")
        receipts.load_terminal(db, run)
        if run.status not in {"queued", "running"}:
            raise HTTPException(409, "评价任务已结束")
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
            raise HTTPException(409, "排队评价任务已有执行痕迹，不能声称未调用模型")
        run.status, run.finish_time = "cancelled", utcnow()
        terminal = None
        if queued:
            run.latency_ms = 0
            terminal = receipts.stage_terminal(db, run, receipts.usage(0, 0, False))
        expected = _event(db, run, actor.user_id, "run.satisfaction.cancel")
        if terminal is not None:
            receipts.readback(db, run, terminal)
        authorize_satisfaction_run(db, actor, run, audit_only=actor.user_role == "super_admin")
        current_actor(db, actor, expected=epoch)
        receipts.readback(db, run, expected)
        db.commit()
    except Exception:
        db.rollback()
        raise


async def execute_satisfaction_claimed(run_id, lease, *, transport=None, session_factory=None):
    factory = _factory(session_factory)
    started, result, error, epoch = time.monotonic(), None, None, None
    receipt = receipts.usage(0, 0, False)
    try:
        with factory() as db:
            run = locked_run(db, run_id, lease)
            if run is None:
                return
            load_snapshot(db, run)
            cancelled = run.status == "cancelled"
            if cancelled:
                if run.latency_ms is not None:
                    return
                receipts.load_terminal(db, run)
            else:
                spec, provider, snapshot, epoch = recheck(db, run)
                db.expunge(provider)
        if not cancelled:
            result, inputs, outputs = await generate_satisfaction(provider, spec, snapshot["task_prompt"], snapshot["payload"], transport=transport)
            receipt = receipts.usage(inputs, outputs, True)
    except AIExecutionError as exc:
        attempted = getattr(exc, "model_call_attempted", False)
        receipt = receipts.usage(exc.input_tokens, exc.output_tokens, True) if attempted else receipts.usage(0, 0, False)
        error = exc.code, exc.message
    except HTTPException as exc:
        error = "TASK_NO_LONGER_AUTHORIZED", str(exc.detail)
    except Exception:
        error = "TASK_EXECUTION_ERROR", "评价任务处理失败，请联系管理员核对状态"
    with factory() as db:
        run = locked_run(db, run_id, lease)
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
            # Full-result acceptance checks the still-running SQL lease before
            # any terminal fields are assigned. Usage has a different Audit PK.
            accepted = None
            if run.status != "cancelled" and error is None:
                accepted = result.model_dump(mode="json")
                run.result_json = stage_result(db, run, lease, accepted)
            _account(run, receipt, started)
            if run.status != "cancelled":
                if error:
                    run.status, (run.error_code, run.error_message) = "failed", error
                else:
                    run.status = "succeeded"
            expected = receipts.stage_terminal(db, run, receipt)
            if run.status == "succeeded":
                recheck(db, run, expected_epoch=epoch)
                receipts.readback(db, run, expected)
                if receipts.load_terminal(db, run)[0] != accepted:
                    raise HTTPException(409, "评价实际完整结果与本次模型草稿不同")
            db.commit()
        except Exception:
            db.rollback()
            failed = locked_run(db, run_id, lease)
            if failed is None or failed.status == "cancelled" and failed.latency_ms is not None:
                return
            failed.status = "cancelled" if failed.status == "cancelled" else "failed"
            failed.result_json = "{}"
            failed.error_code = "RESULT_STORAGE_ERROR"
            failed.error_message = "评价完整结果与具体接收及用量审计未能原子保存，未接收结果"
            _account(failed, receipt, started)
            try:
                receipts.stage_terminal(db, failed, receipt)
                db.commit()
            except Exception:
                db.rollback()
                raise


def expire_interrupted_satisfaction_runs(db):
    """Use a fresh worker Session; record unknown usage and never replay a call."""
    lock_satisfaction_gate(db)
    deadline = utcnow() - datetime.timedelta(minutes=10)
    # A bounded technical locator, not a permission or history-completeness read.
    # Each selected row is then re-read current under User -> Run locking order.
    identifiers = (
        db.query(AIRun.run_id)
        .join(AISatisfactionRunArtifact, AIRun.run_id == AISatisfactionRunArtifact.run_id)
        .filter(AIRun.status.in_(["running", "cancelled"]), AIRun.start_time < deadline, AIRun.lease_token.is_not(None), AISatisfactionRunArtifact.usage_event_id.is_(None))
        .order_by(AIRun.run_id)
        .limit(8193)
        .all()
    )
    if len(identifiers) > 8192:
        db.rollback()
        raise HTTPException(409, "待核对中断任务超过完整恢复上限，未截断处理")
    count = 0
    try:
        for (identifier,) in identifiers:
            run = locked_run(db, identifier)
            if run is None or run.status not in {"running", "cancelled"} or run.start_time is None or run.start_time >= deadline:
                continue
            artifact = db.query(AISatisfactionRunArtifact).filter_by(run_id=identifier).populate_existing().with_for_update().one()
            if artifact.usage_event_id is not None:
                continue
            run.status = "cancelled" if run.status == "cancelled" else "failed"
            run.error_code, run.error_message = "WORKER_INTERRUPTED", "执行进程中断，实际模型调用状态和用量未知，未自动重试"
            run.input_tokens = run.output_tokens = 0
            run.finish_time = utcnow()
            run.latency_ms = max(0, int((utcnow() - run.start_time).total_seconds() * 1000))
            receipts.stage_terminal(db, run, receipts.usage())
            count += 1
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
