"""Dedicated75 tasks: current research purpose, one call and durable paid usage."""

import datetime as dt
import time

from fastapi import HTTPException
from sqlalchemy import and_, or_

from app.ai import deidentification_storage as storage
from app.ai.deidentification_dispatch import claim_deidentification_run as claim_deidentification_run
from app.ai.deidentification_dispatch import stage_dispatch, validate_delivery
from app.ai.deidentification_gateway import DeidentificationExecutionError, generate, prepare_request
from app.ai.deidentification_receipts import CREATE, audit_expected, result_header, run_state, stage_terminal, usage, usage_receipt, verify_audit, verify_run_state
from app.ai.deidentification_spans import canonical, digest
from app.ai.deidentification_task_access import actor_for_lease, authorize_locator, opaque_locator, safe_task_metadata
from app.ai.deidentification_task_config import configuration
from app.ai.governance import provider_credential
from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_sources import utcnow
from app.ai.research_cohort_write_guard import current_research_rows, lock_research_gate
from app.config import settings
from app.models import User

FEATURE_KEY = "deidentification"


def _write_user(db, locator):
    # Technical lease closure does not assert the old role or restore body access.
    return current_research_rows(db.query(User.user_id).filter_by(user_id=locator["requested_by"]), shared=True).one_or_none()


def create_deidentification_run(db, user, values, *, preview=False):
    try:
        actor, config, provider, body, task, _, _, raw = storage.prepare(db, user, values, preview=preview)
        # Gate already serializes same-scope creation; count all genuine/old rows.
        start = dt.datetime.combine(utcnow().date(), dt.time.min)
        count = db.query(AIRun.run_id).filter(AIRun.feature_key == FEATURE_KEY, AIRun.requested_by == actor.user_id, AIRun.create_time >= start)
        if db.get_bind().dialect.name == "mysql":
            count = count.with_hint(AIRun, "FORCE INDEX (idx_ai_run_feature_time)", dialect_name="mysql")
        if len(current_research_rows(count.limit(config.daily_limit), shared=True).all()) >= config.daily_limit:
            raise HTTPException(429, "75今日任务额度已用完")
        # Whole actual model wire checked before any queued Run is persisted.
        prepare_request(body["provider"], provider_credential(provider), body, task["input"])
        run = AIRun(
            feature_key=FEATURE_KEY,
            provider_id=provider.provider_id,
            provider_revision=provider.revision,
            prompt_version=body["prompt"]["version"],
            prompt_hash=body["prompt"]["prompt_hash"],
            context_digest=digest(task["context"]),
            patient_id=body["source_snapshot"]["patient_id"],
            encounter_ref=None,
            requested_by=actor.user_id,
            preview=int(preview),
            status="queued",
            **raw,
        )
        db.add(run)
        db.flush()
        event = AIAuditEvent(actor_id=actor.user_id, action=CREATE, target=run.run_id, detail_json=canonical(storage.create_detail(run, body)))
        db.add(event)
        expected_audit = audit_expected(event)
        db.flush()
        verify_audit(db, event.event_id, expected_audit)
        storage.stage_source(db, run, body, event.event_id)
        source = storage.opaque_artifact(db, run.run_id)
        expected = run_state(run, source)
        db.flush()
        verify_run_state(db, run.run_id, expected, source)
        storage.load_snapshot(db, actor, run.run_id, execution=True)
        verify_audit(db, event.event_id, expected_audit)
        safe_identity = {key: getattr(run, key) for key in ("run_id", "feature_key", "status", "preview")}
        db.commit()
        # expire_on_commit must not turn a queued acknowledgement's PK/status
        # access into an unguarded full AIRun TEXT SELECT.
        from sqlalchemy.orm.attributes import set_committed_value

        for key, value in safe_identity.items():
            set_committed_value(run, key, value)
        return run
    except Exception:
        db.rollback()
        raise


def _terminal(db, run_id, lease, receipt, result, error, started, *, actor=None, commit=True):
    locator = opaque_locator(db, run_id)
    if locator is None:
        raise HTTPException(409, "原任务永久锚失效")
    _write_user(db, locator)
    run = storage.technical_run(db, run_id, writing=True)
    if run is None or run.lease_token != lease or run.status not in {"queued", "running", "cancelled"}:
        return False
    if result_header(db, run_id)["usage_event_id"] is not None:
        return False
    if run.status == "cancelled":
        result = None
        error = ("TASK_CANCELLED", "任务已停止；实际调用用量仍独立保留")
    elif error is not None:
        run.status, result = "failed", None
    else:
        run.status = "succeeded"
    run.error_code, run.error_message = error if error is not None else (None, None)
    run.latency_ms, run.finish_time = max(0, int((time.monotonic() - started) * 1000)), utcnow()
    source = storage.opaque_artifact(db, run_id)
    expected = stage_terminal(db, run, source, receipt, result, accepted_at=utcnow() if result is not None else None)
    if result is not None:
        # All parent locks were taken before Run X by the success caller.
        storage.load_snapshot(db, actor, run_id, execution=True)
        storage.load_result(db, actor, run_id)
        verify_run_state(db, run_id, expected, source)
    if commit:
        db.commit()
    return True


async def execute_deidentification_claimed(run_id, lease, claim_event_id=None, *, transport=None):
    from app import database

    # Exact delivery validation is outside the error-to-terminal handler: a
    # wrong/missing PK must not terminate the original worker or assert usage.
    with database.SessionLocal() as delivery_db:
        if not validate_delivery(delivery_db, run_id, lease, claim_event_id):
            return

    started, error, result = time.monotonic(), None, None
    receipt = usage(0, 0, False)
    attempted = False
    try:
        with database.SessionLocal() as db:
            locator = opaque_locator(db, run_id)
            if locator is None:
                return
            # No Task TEXT is read by this classification/status peek.
            peek = current_research_rows(db.query(AIRun.status, AIRun.lease_token, AIRun.latency_ms).filter_by(run_id=run_id), shared=True).one_or_none()
            if peek is None or peek.lease_token != lease or peek.status not in {"running", "cancelled"} or peek.latency_ms is not None:
                db.rollback()
                return
            if peek.status == "cancelled":
                db.rollback()
                error = ("TASK_CANCELLED", "任务在本worker发送前已停止")
            else:
                # Release the status SHARE before taking the complete parent chain.
                db.rollback()
                locator = opaque_locator(db, run_id)
                actor = actor_for_lease(db, locator)
                loaded = storage.load_snapshot(db, actor, run_id, execution=True)
                actor, run, _, body, task = loaded[:5]
                if utcnow() - run.create_time > dt.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS):
                    raise HTTPException(409, "任务等待过期，未调用模型")
                _, provider, _, _, _, _ = configuration(db, actor, bool(run.preview))
                request = prepare_request(body["provider"], provider_credential(provider), body, task["input"])
                run = current_research_rows(db.query(AIRun).filter_by(run_id=run_id)).one()
                if run.status != "running" or run.lease_token != lease or run.latency_ms is not None:
                    db.rollback()
                    return
                # Durable one-shot reservation before releasing SQL. A crash
                # after this point recovers unknown usage, never retries the call.
                run.latency_ms = 0
                source = storage.opaque_artifact(db, run_id)
                expected = run_state(run, source)
                db.flush()
                verify_run_state(db, run_id, expected, source)
                stage_dispatch(db, run_id, lease, claim_event_id)
                storage.load_snapshot(db, actor, run_id, execution=True)
                db.commit()
        if error is None:

            def sent():
                nonlocal attempted
                attempted = True

            result, inputs, outputs = await generate(request, body["provider"], body, transport=transport, on_attempt=sent)
            receipt = usage(inputs, outputs, attempted)
    except DeidentificationExecutionError as exc:
        receipt, error = usage(exc.input_tokens, exc.output_tokens, attempted), (exc.code, exc.message)
    except HTTPException:
        receipt = usage(None, None, True) if attempted else usage(0, 0, False)
        error = ("TASK_NO_LONGER_AUTHORIZED", "当前来源、研究授权、模型或原请求epoch已变化")
    except Exception:
        receipt = usage(None, None, True) if attempted else usage(0, 0, False)
        error = ("TASK_EXECUTION_ERROR", "任务处理失败，未自动重试可能付费调用")
    # Accept only after a new transaction's current authority/config checks.
    if error is None and result is not None:
        try:
            with database.SessionLocal() as db:
                locator = opaque_locator(db, run_id)
                actor = actor_for_lease(db, locator)
                storage.load_snapshot(db, actor, run_id, execution=True)
                if _terminal(db, run_id, lease, receipt, result, None, started, actor=actor):
                    return
        except Exception:
            error = ("TASK_ACCEPTANCE_REJECTED", "实际付费用量已保留，当前来源或写后证明失效，未接收候选")
    with database.SessionLocal() as db:
        try:
            _terminal(db, run_id, lease, receipt, None, error or ("TASK_EXECUTION_ERROR", "未接收完整候选"), started)
        except Exception:
            db.rollback()
            # If the receipt/audit itself cannot persist, do not commit a bad
            # terminal state. Operations must reconcile the retained lease.
            raise HTTPException(409, "实际终态审计未能原子保存，须人工核对原租约与可能付费用量") from None


def cancel_deidentification_run(db, user, run_id, *, audit_only=False):
    try:
        actor, locator = authorize_locator(db, user, run_id, audit_only=audit_only)
        # Cancellation needs current research permission, but not current model
        # transfer permission or a still-executable publication.
        run = storage.technical_run(db, run_id, writing=True)
        if run is None or run.status not in {"queued", "running"}:
            raise HTTPException(409, "任务已结束")
        queued = run.status == "queued"
        if queued and (run.lease_token is not None or run.start_time is not None or run.latency_ms is not None):
            raise HTTPException(409, "排队任务存在调用痕迹，不能补假0")
        run.status, run.finish_time = "cancelled", utcnow()
        # Current-read helpers deliberately reload SQL. Persist and verify the
        # requested cancellation before terminal code performs that reload.
        source = storage.opaque_artifact(db, run_id)
        expected = run_state(run, source)
        db.flush()
        verify_run_state(db, run_id, expected, source)
        if queued:
            _terminal(db, run_id, None, usage(0, 0, False), None, ("TASK_CANCELLED", "任务发送前已停止"), time.monotonic(), commit=False)
            authorize_locator(db, actor, run_id, audit_only=audit_only)
            db.commit()
        else:
            authorize_locator(db, actor, run_id, audit_only=audit_only)
            db.commit()
    except Exception:
        db.rollback()
        raise


def describe_deidentification_run(db, user, run_id, *, audit_only=False, include_result=True):
    loaded, result = storage.load_result(db, user, run_id, audit_only=audit_only)
    actor, run, artifact, body, task, evidence, metadata = loaded
    receipt = usage_receipt(db, run)
    value = {
        "run_id": run.run_id,
        "feature_key": FEATURE_KEY,
        "patient_id": run.patient_id,
        "encounter_ref": None,
        "status": run.status,
        "preview": bool(run.preview),
        "input_tokens": receipt["input_tokens"],
        "output_tokens": receipt["output_tokens"],
        "usage_receipt": receipt,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "create_time": str(run.create_time),
        "finish_time": str(run.finish_time) if run.finish_time is not None else None,
        "source_binding": task["context"],
        "source": body["public_source"] if include_result else None,
        "result": result if include_result else None,
        "audit_only": audit_only,
        "can_execute": False,
        "can_review": False,
        "can_export": False,
        "source_hash": artifact.source_hash,
    }
    # Every combined response gets its own budget; two8MiB artifacts need not fit.
    from app.ai.deidentification_http import response_bytes

    response_bytes(value)
    return value


def technical_deidentification_status(db, user, run_id):
    value = safe_task_metadata(db, user, run_id)
    run = storage.technical_run(db, run_id)
    value["usage_receipt"] = usage_receipt(db, run)
    value["opaque_hashes"] = {key: storage.opaque_artifact(db, run_id)[key] for key in ("source_hash", "source_binding_hash", "prompt_hash", "input_hash", "evidence_hash", "metadata_hash")}
    return value


def expire_interrupted_deidentification_runs(db):
    try:
        lock_research_gate(db)
        # PK-only enumeration; complete task bodies are not needed for recovery.
        from app.ai.deidentification_run_models import AIDeidentificationRunResult, AIDeidentificationRunSource

        # Bounded technical maintenance with persistent progress: completed rows
        # leave this predicate. Each worker poll supplies its own fresh Session.
        queued_before = utcnow() - dt.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS)
        running_before = queued_before - dt.timedelta(seconds=150)
        ids = (
            db.query(AIDeidentificationRunSource.run_id)
            .join(AIRun, AIRun.run_id == AIDeidentificationRunSource.run_id)
            .join(AIDeidentificationRunResult, AIDeidentificationRunResult.run_id == AIRun.run_id)
            .filter(
                AIRun.status.in_(("queued", "running", "cancelled")),
                AIDeidentificationRunResult.usage_event_id.is_(None),
                or_(and_(AIRun.start_time.is_(None), AIRun.create_time < queued_before), and_(AIRun.start_time.is_not(None), AIRun.start_time < running_before)),
            )
            .order_by(AIRun.create_time, AIRun.run_id)
            .limit(256)
            .all()
        )
        expired = 0
        for (identifier,) in ids:
            locator = opaque_locator(db, identifier)
            _write_user(db, locator)
            run = storage.technical_run(db, identifier, writing=True)
            if run is None or run.status not in {"queued", "running", "cancelled"} or result_header(db, identifier)["usage_event_id"] is not None:
                continue
            origin = run.start_time or run.create_time
            allowance = settings.AI_MAX_QUEUE_AGE_SECONDS + (150 if run.start_time is not None else 0)
            if utcnow() - origin <= dt.timedelta(seconds=allowance):
                continue
            receipt = usage(0, 0, False) if run.latency_ms is None and result_header(db, identifier)["dispatch_event_id"] is None else usage()
            _terminal(db, identifier, run.lease_token, receipt, None, ("TASK_INTERRUPTED", "任务已中断；未重放模型，实际用量按已知或未知保留"), time.monotonic())
            expired += 1
        db.commit()
        return expired
    except Exception:
        db.rollback()
        raise
