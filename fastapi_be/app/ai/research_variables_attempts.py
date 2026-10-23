"""Concrete76 claim/dispatch audit PKs; no provider call or transaction commit.

Technical prechecks only skip work. All actual phase mutations repeat current
Source/purpose/config authority, then lock Run/Artifact in their original order.
The caller must commit a returned delivery before sending its one model call.
"""

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select

from app.ai import research_variables_task_reader as reader
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_cohort_write_guard import current_research_rows
from app.ai.research_variables_run_models import AIResearchVariableRunArtifact
from app.ai.research_variables_task_contract import MAX_RUN_TEXT_BYTES, canonical


@dataclass(frozen=True)
class VariableClaim:
    run_id: str
    batch_id: str
    requested_by: int
    create_event_id: int
    claim_event_id: int
    lease: str
    claimed_at: str
    source_hash: str
    instructions_digest: str


@dataclass(frozen=True)
class VariableDelivery:
    claim: VariableClaim
    dispatch_event_id: int
    dispatched_at: str


def _phase_header(db, identifier):
    columns = (AIResearchVariableRunArtifact.run_id, AIResearchVariableRunArtifact.claim_event_id, AIResearchVariableRunArtifact.claim_lease, AIResearchVariableRunArtifact.dispatch_event_id)
    statement = select(*columns).where(AIResearchVariableRunArtifact.run_id == identifier)
    with db.no_autoflush:
        rows = set()
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                rows.update(tuple(row) for row in connection.execute(statement))
        rows.update(tuple(row) for row in db.execute(statement))
    if len(rows) > 1:
        # Different committed/local phase observations cannot authorize a send.
        return None
    return next(iter(rows), None)


def claim_from_task(task):
    row = task.artifact
    if row.claim_event_id is None or row.claim_lease is None or row.claimed_at is None:
        raise HTTPException(409, "原任务缺少完整实际领取三元组")
    return VariableClaim(row.run_id, row.batch_id, row.requested_by, row.create_event_id, row.claim_event_id, row.claim_lease, utc_text(row.claimed_at), row.source_hash, row.instructions_digest)


def _claim_detail(claim):
    return {"schema_version": "research_variable_claim_v1", **claim.__dict__, "lease": claim.lease}


def _dispatch_detail(delivery):
    return {"schema_version": "research_variable_dispatch_v1", "claim": _claim_detail(delivery.claim), "dispatch_event_id": delivery.dispatch_event_id, "dispatched_at": delivery.dispatched_at}


def _event(db, identifier, *, actor, action, target, clock, detail):
    length = current_research_rows(db.query(reader._bytes(db, AIAuditEvent.detail_json)).filter_by(event_id=identifier), shared=True).scalar()
    if type(length) is not int or not 0 < length <= MAX_RUN_TEXT_BYTES:
        raise HTTPException(409, "本次具体领取/分派Audit PK缺失或整件容量异常")
    row = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one_or_none()
    if row is None or (row.actor_id, row.action, row.target, row.create_time, row.detail_json) != (actor, action, target, clock.replace(microsecond=0), canonical(detail, MAX_RUN_TEXT_BYTES)):
        raise HTTPException(409, "本次具体领取/分派Audit PK、原lease或实际时钟不同")


def verify_claim(db, task, expected=None):
    claim = claim_from_task(task)
    if expected is not None and (not isinstance(expected, VariableClaim) or claim != expected):
        raise HTTPException(409, "实际领取PK、原lease、原Source或本次交付身份不同")
    if task.run.lease_token != claim.lease or task.run.start_time != task.artifact.claimed_at.replace(microsecond=0):
        raise HTTPException(409, "实际Run原lease或整秒开始时钟与领取锚不同")
    _event(db, claim.claim_event_id, actor=claim.requested_by, action="research_variable_run.claim", target=claim.run_id, clock=task.artifact.claimed_at, detail=_claim_detail(claim))
    return claim


def verify_delivery(db, task, expected=None):
    claim = verify_claim(db, task, expected.claim if isinstance(expected, VariableDelivery) else None)
    row = task.artifact
    if row.dispatch_event_id is None or row.dispatched_at is None:
        raise HTTPException(409, "任务尚无实际分派PK，不能冒称模型已调用")
    delivery = VariableDelivery(claim, row.dispatch_event_id, utc_text(row.dispatched_at))
    if expected is not None and (not isinstance(expected, VariableDelivery) or expected != delivery):
        raise HTTPException(409, "终态不属于本次真实已提交分派PK")
    _event(db, delivery.dispatch_event_id, actor=claim.requested_by, action="research_variable_run.dispatch", target=claim.run_id, clock=row.dispatched_at, detail=_dispatch_detail(delivery))
    return delivery


def stage_claim(db, user, identifier):
    """One queued task -> one real claim; caller owns commit and daily quota."""
    try:
        phase = _phase_header(db, identifier)
        if phase is None or phase[1] is not None:
            return None
        task = reader.load_task(db, user, identifier, exclusive=True, for_execution=True)
        if task.run.status != "queued" or task.artifact.claim_event_id is not None or task.artifact.usage_event_id is not None:
            return None
        clock, lease = utcnow(), str(uuid.uuid4())
        if clock < task.artifact.recorded_at:
            raise HTTPException(409, "实际领取时钟早于任务登记，未伪造时钟")
        event = AIAuditEvent(actor_id=task.run.requested_by, action="research_variable_run.claim", target=identifier, detail_json="{}", create_time=clock.replace(microsecond=0))
        db.add(event)
        db.flush()
        task.artifact.claim_event_id, task.artifact.claim_lease, task.artifact.claimed_at = event.event_id, lease, clock
        task.run.status, task.run.lease_token, task.run.start_time = "running", lease, clock.replace(microsecond=0)
        task.run.finish_time = task.run.error_code = task.run.error_message = None
        claim = claim_from_task(task)
        event.detail_json = canonical(_claim_detail(claim), MAX_RUN_TEXT_BYTES)
        db.flush()
        actual = reader.load_task(db, task.authority.actor, identifier, exclusive=True, for_execution=True)
        if actual.run.status != "running" or actual.artifact.dispatch_event_id is not None or actual.artifact.usage_event_id is not None:
            raise HTTPException(409, "领取后实际状态或未分派/未结算锚已改变")
        verify_claim(db, actual, claim)
        return claim
    except Exception:
        db.rollback()
        raise


def stage_dispatch(db, user, claim):
    """One authentic claim -> one dispatch; duplicates only skip, never settle."""
    try:
        if not isinstance(claim, VariableClaim):
            raise HTTPException(422, "发送须持本次实际不可变领取对象")
        phase = _phase_header(db, claim.run_id)
        if phase is None or phase[1:3] != (claim.claim_event_id, claim.lease) or phase[3] is not None:
            return None
        task = reader.load_task(db, user, claim.run_id, exclusive=True, for_execution=True)
        if task.run.status != "running" or task.artifact.dispatch_event_id is not None or task.artifact.usage_event_id is not None:
            return None
        verify_claim(db, task, claim)
        clock = utcnow()
        if clock < task.artifact.claimed_at:
            raise HTTPException(409, "实际分派时钟早于领取，未伪造时钟")
        event = AIAuditEvent(actor_id=claim.requested_by, action="research_variable_run.dispatch", target=claim.run_id, detail_json="{}", create_time=clock.replace(microsecond=0))
        db.add(event)
        db.flush()
        task.artifact.dispatch_event_id, task.artifact.dispatched_at = event.event_id, clock
        delivery = VariableDelivery(claim, event.event_id, utc_text(clock))
        event.detail_json = canonical(_dispatch_detail(delivery), MAX_RUN_TEXT_BYTES)
        db.flush()
        actual = reader.load_task(db, task.authority.actor, claim.run_id, exclusive=True, for_execution=True)
        if actual.run.status != "running" or actual.artifact.usage_event_id is not None:
            raise HTTPException(409, "分派后实际状态或原结算锚已改变")
        verify_delivery(db, actual, delivery)
        return delivery
    except Exception:
        db.rollback()
        raise
