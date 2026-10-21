"""Shared75 create/queue adapters preserve actual durable receipts and progress."""

from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, update
from sqlalchemy.orm import load_only

from app.ai.deidentification_run_models import AIDeidentificationRunResult, AIDeidentificationRunSource
from app.ai.models import AIAuditEvent, AIRun
from app.ai.native_task_routing import _domains, locate_native_task
from app.ai.research_cohort_sources import utcnow
from app.ai.research_cohort_write_guard import current_actor, lock_research_gate


def create_shared_run(db, user, request):
    from app.ai.deidentification_runtime import create_deidentification_run
    from app.ai.deidentification_task_contract import selection

    if request.feature_key != "deidentification" or request.patient_id is not None or request.encounter_ref is not None or type(request.preview) is not bool:
        raise HTTPException(422, "75只接受明确受控Case和原问题，不以患者或就诊代授项目用途权限")
    selection(request.input)
    run = create_deidentification_run(db, user, request.input, preview=request.preview)
    return db.query(AIRun).options(load_only(AIRun.run_id, AIRun.feature_key)).filter_by(run_id=run.run_id).one()


def queue_candidate_condition(db):
    from app.ai.deidentification_shared import marker_expression
    from app.dependencies import VALID_USER_ROLES
    from app.models import User

    model, result = AIDeidentificationRunSource, AIDeidentificationRunResult
    native = exists().where(model.run_id == AIRun.run_id).correlate(AIRun)
    actor = exists().where(User.user_id == AIRun.requested_by, User.user_role.in_(sorted(VALID_USER_ROLES))).correlate(AIRun)
    artifact = exists().where(model.run_id == AIRun.run_id, model.requested_by == AIRun.requested_by).correlate(AIRun)
    pending = (
        exists()
        .where(result.run_id == AIRun.run_id, result.claim_event_id.is_(None), result.dispatch_event_id.is_(None), result.usage_event_id.is_(None), result.accept_event_id.is_(None))
        .correlate(AIRun)
    )
    clean = and_(
        AIRun.feature_key == "deidentification",
        AIRun.lease_token.is_(None),
        AIRun.start_time.is_(None),
        AIRun.finish_time.is_(None),
        AIRun.latency_ms.is_(None),
        AIRun.error_code.is_(None),
        AIRun.error_message.is_(None),
        AIRun.input_tokens == 0,
        AIRun.output_tokens == 0,
        AIRun.result_json == "{}",
    )
    other = or_(*(exists().where(other.run_id == AIRun.run_id).correlate(AIRun) for domain, other, _ in _domains() if domain != "deidentification"))
    marker = marker_expression(mysql=db.get_bind().dialect.name in {"mysql", "mariadb"})
    # No clinical/business role prefilter. A real patient-role demotion is
    # claimed, then the dedicated worker records its actual pre-call zero.
    return or_(and_(native, actor, artifact, pending, clean), and_(~native, or_(other, ~marker, actor)))


def quarantine_orphan(db, run_id):
    from app.ai.deidentification_spans import canonical
    from app.dependencies import VALID_USER_ROLES

    try:
        lock_research_gate(db)
        owner = db.query(AIRun.requested_by).filter_by(run_id=run_id, status="queued").scalar()
        if owner is None:
            db.rollback()
            return False
        actor = current_actor(db, SimpleNamespace(user_id=owner), allowed_roles=VALID_USER_ROLES)
        if locate_native_task(db, run_id) is not None:
            db.rollback()
            return False
        missing = [~exists().where(model.run_id == AIRun.run_id) for _, model, _ in _domains()]
        changed = db.execute(
            update(AIRun)
            .where(AIRun.run_id == run_id, AIRun.status == "queued", AIRun.requested_by == actor.user_id, *missing)
            .values(status="failed", error_code="NATIVE_ARTIFACT_REQUIRED", error_message="75任务缺少完整持久来源；仅隔离技术状态，未读取正文、猜测用量或执行通用模型", finish_time=utcnow())
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            db.rollback()
            return False
        db.add(
            AIAuditEvent(
                actor_id=actor.user_id,
                action="deidentification.task.quarantine",
                target=run_id,
                detail_json=canonical({"schema_version": "deidentification_orphan_quarantine_v1", "run_id": run_id, "reason": "missing_durable_deidentification_source"}),
            )
        )
        db.flush()
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
