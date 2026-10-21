"""Shared queue adapters preserve research claim identity and current authority.

Only opaque technical routing/claim receipts are checked here. The dedicated
worker still authorizes the complete Source before private Task TEXT and model
dispatch. A technical precheck Session must close before that Source transaction.
"""

from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, update
from sqlalchemy.orm import load_only

from app.ai.models import AIAuditEvent, AIRun
from app.ai.native_task_routing import _domains, locate_native_task
from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_execution import verify_claim
from app.ai.research_cohort_receipts import read_dispatch_event
from app.ai.research_cohort_runtime import create_research_run, selection
from app.ai.research_cohort_sources import utcnow
from app.ai.research_cohort_storage import opaque_locator
from app.ai.research_cohort_write_guard import current_actor, current_research_rows, lock_research_gate


def create_shared_research_run(db, user, request):
    if request.feature_key != "research_cohort" or request.patient_id is not None or request.encounter_ref is not None or type(request.preview) is not bool:
        raise HTTPException(422, "科研任务只接受明确Case与原问题，不使用患者或就诊替代范围")
    selection(request.input)
    identifier = create_research_run(db, user, request.input, preview=request.preview)
    # Return an attached identity for the existing shared describe_run adapter;
    # do not SELECT private Task TEXT again after creation committed.
    return db.query(AIRun).options(load_only(AIRun.run_id, AIRun.feature_key)).filter_by(run_id=identifier).one()


def validate_shared_research_claim(db, run_id, lease, claim_event_id):
    """Exact original AuditPK; wrong delivery cannot terminate a live worker."""
    from app.dependencies import VALID_USER_ROLES

    if type(claim_event_id) is not int or claim_event_id < 1:
        raise HTTPException(409, "科研共享执行必须保留原具体claim AuditPK，未范围查找或替造回执")
    lock_research_gate(db)
    locator = opaque_locator(db, run_id)
    if locator is None:
        raise HTTPException(409, "科研持久任务分件不存在，未沿用通用执行")
    current_actor(db, SimpleNamespace(user_id=locator.requested_by), allowed_roles=VALID_USER_ROLES)
    reserved = current_research_rows(db.query(AIResearchCohortRunArtifact.dispatch_event_id).filter_by(run_id=run_id), shared=True).scalar()
    if reserved is not None:
        original = read_dispatch_event(db, run_id)
        if (original["claim_event_id"], original["lease_token"]) != (claim_event_id, lease):
            raise HTTPException(409, "重复科研交付不符合原具体claim和租约，未改首worker状态")
        return False
    verify_claim(db, run_id, lease, claim_event_id)
    return True


def quarantine_orphan_research_run(db, run_id):
    """Stop a queued marker-only row without reading question or source TEXT."""
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
        missing_all_domains = [~exists().where(model.run_id == AIRun.run_id) for _, model, _ in _domains()]
        changed = db.execute(
            update(AIRun)
            .where(AIRun.run_id == run_id, AIRun.status == "queued", AIRun.requested_by == actor.user_id, *missing_all_domains)
            .values(status="failed", error_code="NATIVE_ARTIFACT_REQUIRED", error_message="科研任务缺少完整持久来源，仅保留技术状态；未读取原问题或执行模型", finish_time=utcnow())
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            db.rollback()
            return False
        event = AIAuditEvent(
            actor_id=actor.user_id,
            action="research.task.quarantine",
            target=run_id,
            detail_json=canonical_json({"schema_version": "research_orphan_quarantine_v1", "run_id": run_id, "reason": "missing_durable_research_artifact"}),
        )
        db.add(event)
        db.flush()
        # This operation makes no model-call or paid-use assertion.
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def queue_candidate_condition(db):
    """Known impossible technical headers do not monopolize a bounded poll.

    This predicate grants no research or model authority. Actual current actor,
    Source, config, claim and receipt checks remain in the dedicated services.
    Corrupt durable artifacts stay retained, with no invented terminal/usage.
    Other native domains keep their own routing priority and qualification.
    """
    from app.ai.research_cohort_shared import research_marker_expression
    from app.dependencies import VALID_USER_ROLES
    from app.models import User

    model = AIResearchCohortRunArtifact
    research = exists().where(model.run_id == AIRun.run_id).correlate(AIRun)
    known_actor = exists().where(User.user_id == AIRun.requested_by, User.user_role.in_(sorted(VALID_USER_ROLES))).correlate(AIRun)
    claimable_artifact = exists().where(model.run_id == AIRun.run_id, model.requested_by == AIRun.requested_by, model.usage_event_id.is_(None), model.dispatch_event_id.is_(None)).correlate(AIRun)
    clean_header = and_(
        AIRun.feature_key == "research_cohort",
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
    other_domains = or_(*(exists().where(other.run_id == AIRun.run_id).correlate(AIRun) for domain, other, _ in _domains() if domain != "research_cohort"))
    marker = research_marker_expression(mysql=db.get_bind().dialect.name in {"mysql", "mariadb"})
    return or_(and_(research, known_actor, claimable_artifact, clean_header), and_(~research, or_(other_domains, ~marker, known_actor)))
