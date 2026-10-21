"""Dedicated durable research claim/cancel/execute, no SQL held across HTTP await.

Shared dispatch preserves this module's concrete ResearchClaim receipt. Only
explicit bounded research Case tasks are handled. Permission loss never grants a frozen clinical bypass;
paid/unknown terminal accounting uses exclusively opaque technical headers.
"""

import datetime as dt
import time
import uuid
from dataclasses import dataclass
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import update

from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_gateway import ResearchCallError, generate_research, request
from app.ai.research_cohort_receipts import ResearchDispatchEvent, _header, read_dispatch_event, read_usage_event, stage_terminal_receipt, usage
from app.ai.research_cohort_result_storage import stage_result
from app.ai.research_cohort_runtime import _fixed_role, _technical_access
from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_cohort_storage import _json, load_artifact, opaque_locator
from app.ai.research_cohort_write_guard import current_actor, current_research_rows, lock_research_gate

ALREADY_RESERVED = object()


@dataclass(frozen=True)
class ResearchClaim:
    run_id: str
    lease_token: str
    claim_event_id: int


def _factory(value):
    if value is not None:
        return value
    from app.database import SessionLocal

    return SessionLocal


def _worker_locator(db, run_id):
    """Technical actor/owner only, never a clinical permission or TEXT read."""
    from app.dependencies import VALID_USER_ROLES

    lock_research_gate(db)
    locator = opaque_locator(db, run_id)
    if locator is None:
        return None
    current_actor(db, SimpleNamespace(user_id=locator.requested_by), allowed_roles=VALID_USER_ROLES)
    return locator


def _claim_detail(header, source_binding_hash):
    return {
        "schema_version": "research_claim_v1",
        "run_id": header["run_id"],
        "lease_token": header["lease_token"],
        "start_time": utc_text(header["start_time"]),
        "source_binding_hash": source_binding_hash,
    }


def verify_claim(db, run_id, lease_token, claim_event_id):
    from app.ai.models import AIAuditEvent

    if type(claim_event_id) is not int or claim_event_id < 1:
        raise HTTPException(409, "科研领取须保留原具体AuditPK，不范围查找替代回执")
    locator = opaque_locator(db, run_id)
    header = _header(db, run_id, shared=True)
    artifact = current_research_rows(
        db.query(AIResearchCohortRunArtifact.source_binding_hash, AIResearchCohortRunArtifact.created_audit_event_id, AIResearchCohortRunArtifact.usage_event_id).filter_by(run_id=run_id), shared=True
    ).one_or_none()
    event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=claim_event_id), shared=True).one_or_none()
    if (
        locator is None
        or header is None
        or artifact is None
        or header["feature_key"] != "research_cohort"
        or header["requested_by"] != locator.requested_by
        or header["status"] not in {"running", "cancelled"}
        or header["lease_token"] != lease_token
        or header["start_time"] is None
        or artifact.usage_event_id is not None
        or event is None
        or event.event_id == artifact.created_audit_event_id
        or event.actor_id != locator.requested_by
        or event.target != run_id
        or event.action != "research.task.claim"
        or event.detail_json != canonical_json(_claim_detail(header, artifact.source_binding_hash))
    ):
        raise HTTPException(409, "科研原领取AuditPK、实际租约与原start clock不一致")
    return header


def claim_research_run(db, run_id):
    """Technical intent only; actual current model authority is checked before call."""
    from app.ai.models import AIAuditEvent, AIRun

    try:
        locator = _worker_locator(db, run_id)
        if locator is None:
            db.rollback()
            return None
        header = _header(db, run_id)
        artifact = current_research_rows(db.query(AIResearchCohortRunArtifact.source_binding_hash, AIResearchCohortRunArtifact.usage_event_id).filter_by(run_id=run_id)).one()
        if header is None or header["feature_key"] != "research_cohort" or header["requested_by"] != locator.requested_by or header["status"] != "queued":
            db.rollback()
            return None
        if (
            any(header[key] is not None for key in ("lease_token", "start_time", "finish_time", "latency_ms", "error_code", "error_message"))
            or header["input_tokens"] != 0
            or header["output_tokens"] != 0
            or artifact.usage_event_id is not None
            or current_research_rows(db.query(AIRun.result_json == "{}").filter_by(run_id=run_id), shared=True).scalar() is not True
        ):
            raise HTTPException(409, "排队科研任务已有执行痕迹，未重新领取或重放模型")
        lease, clock = str(uuid.uuid4()), utcnow().replace(microsecond=0)
        expected = {**header, "status": "running", "lease_token": lease, "start_time": clock}
        db.execute(
            update(AIRun)
            .where(AIRun.run_id == run_id, AIRun.status == "queued", AIRun.lease_token.is_(None))
            .values(status="running", lease_token=lease, start_time=clock)
            .execution_options(synchronize_session=False)
        )
        event = AIAuditEvent(actor_id=locator.requested_by, action="research.task.claim", target=run_id, detail_json=canonical_json(_claim_detail(expected, artifact.source_binding_hash)))
        db.add(event)
        db.flush()
        claim = ResearchClaim(run_id, lease, event.event_id)
        if verify_claim(db, run_id, lease, event.event_id) != expected:
            raise HTTPException(409, "科研领取原Run header与具体AuditPK同事务不一致")
        db.commit()
        return claim
    except Exception:
        db.rollback()
        raise


def cancel_research_run(db, user, run_id):
    """Stopping an owned/managed task does not expose or revive clinical Source."""
    from app.ai.models import AIAuditEvent, AIRun

    try:
        actor, locator = _technical_access(db, user, run_id, audit_only=False)
        header = _header(db, run_id)
        if header is None or header["feature_key"] != "research_cohort" or header["requested_by"] != locator.requested_by or header["status"] not in {"queued", "running"}:
            raise HTTPException(409, "科研任务不存在或已经结束")
        if header["status"] == "queued":
            stage_terminal_receipt(db, run_id, None, usage(0, 0, False), status="cancelled", latency_ms=0)
        else:
            if header["lease_token"] is None:
                raise HTTPException(409, "在途科研任务缺少原worker租约")
            db.execute(
                update(AIRun)
                .where(AIRun.run_id == run_id, AIRun.status == "running", AIRun.lease_token == header["lease_token"])
                .values(status="cancelled")
                .execution_options(synchronize_session=False)
            )
        expected = _header(db, run_id, shared=True)
        detail = canonical_json(
            {"schema_version": "research_cancel_v1", "run_id": run_id, "original_status": header["status"], "lease_token": header["lease_token"], "cancellation_pending": header["status"] == "running"}
        )
        event = AIAuditEvent(actor_id=actor.user_id, action="research.task.cancel", target=run_id, detail_json=detail)
        db.add(event)
        db.flush()
        fresh_actor, _ = _technical_access(db, actor, run_id, audit_only=False)
        actual_event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=event.event_id), shared=True).one()
        if expected != _header(db, run_id, shared=True) or (actual_event.actor_id, actual_event.action, actual_event.target, actual_event.detail_json) != (
            fresh_actor.user_id,
            "research.task.cancel",
            run_id,
            detail,
        ):
            raise HTTPException(409, "科研停止状态与具体AuditPK同事务不一致")
        db.commit()
    except Exception:
        db.rollback()
        raise


def reserve_research_dispatch(db, run_id, lease_token, claim_event_id):
    from app.ai.governance import provider_credential
    from app.ai.models import AIProvider
    from app.config import settings

    locator = _worker_locator(db, run_id)
    if locator is None:
        return None
    reserved = current_research_rows(db.query(AIResearchCohortRunArtifact.dispatch_event_id).filter_by(run_id=run_id), shared=True).scalar()
    if reserved is not None:
        read_dispatch_event(db, run_id)
        return ALREADY_RESERVED
    # Current Source is deliberately before any private Task SELECT or Run lock.
    user = SimpleNamespace(user_id=locator.requested_by)
    run, artifact, _, source = load_artifact(db, user, run_id, execution=True)
    actor = current_actor(db, user)
    _fixed_role(actor)
    header = verify_claim(db, run_id, lease_token, claim_event_id)
    if header["status"] == "cancelled":
        return None
    if run.create_time > utcnow() or utcnow() - run.create_time > dt.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS):
        raise HTTPException(409, "科研任务原创建时钟异常或等待过期；未调用或重放模型")
    if any(header[key] is not None for key in ("finish_time", "latency_ms", "error_code", "error_message")) or header["input_tokens"] != 0 or header["output_tokens"] != 0:
        raise HTTPException(409, "原在途科研任务已有终态或用量痕迹")
    provider = current_research_rows(db.query(AIProvider).filter_by(provider_id=artifact.provider_id), shared=True).one()
    detached = SimpleNamespace(**{column.name: getattr(provider, column.name) for column in provider.__table__.columns})
    original_input = _json(run.input_json, 65535)
    prompt = _json(artifact.prompt_snapshot_json, 262144)
    provider_credential(detached)
    _, _, actual_instructions = request(detached, source, original_input["question"], prompt["task_prompt"])
    if actual_instructions != artifact.instructions_digest:
        raise HTTPException(409, "科研模型请求未使用原固定System与完整Task版本")
    from app.ai.models import AIAuditEvent

    detail = ResearchDispatchEvent(
        schema_version="research_dispatch_reserved_v1",
        run_id=run_id,
        lease_token=lease_token,
        claim_event_id=claim_event_id,
        source_binding_hash=artifact.source_binding_hash,
        instructions_digest=artifact.instructions_digest,
        execution_snapshot_hash=artifact.execution_snapshot_hash,
        reserved_at=utc_text(utcnow()),
    ).model_dump(mode="json")
    event = AIAuditEvent(actor_id=locator.requested_by, action="research.task.dispatch.reserve", target=run_id, detail_json=canonical_json(detail))
    db.add(event)
    db.flush()
    changed = db.execute(
        update(AIResearchCohortRunArtifact)
        .where(AIResearchCohortRunArtifact.run_id == run_id, AIResearchCohortRunArtifact.dispatch_event_id.is_(None))
        .values(dispatch_event_id=event.event_id)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise HTTPException(409, "科研同一租约不能二次登记dispatch")
    db.flush()
    load_artifact(db, user, run_id, execution=True)
    verify_claim(db, run_id, lease_token, claim_event_id)
    if read_dispatch_event(db, run_id) != detail:
        raise HTTPException(409, "科研dispatch具体AuditPK与原Source同事务回读不一致")
    return detached, source, original_input["question"], prompt["task_prompt"], locator.requested_by


def _finish_failure(db, run_id, lease_token, receipt, code, message, elapsed):
    locator = _worker_locator(db, run_id)
    if locator is None:
        db.rollback()
        return False
    header = _header(db, run_id)
    if header is None or header["lease_token"] != lease_token or header["status"] not in {"running", "cancelled"}:
        db.rollback()
        return False
    present = current_research_rows(db.query(AIResearchCohortRunArtifact.usage_event_id).filter_by(run_id=run_id), shared=True).scalar()
    if present is not None:
        read_usage_event(db, run_id)
        db.rollback()
        return False
    cancelled = header["status"] == "cancelled"
    stage_terminal_receipt(
        db, run_id, lease_token, receipt, status="cancelled" if cancelled else "failed", error_code=None if cancelled else code, error_message=None if cancelled else message, latency_ms=elapsed
    )
    db.commit()
    return True


async def execute_research_claimed(run_id, lease_token, *, claim_event_id, transport=None, session_factory=None):
    factory = _factory(session_factory)
    started, receipt, draft, requester = time.monotonic(), usage(0, 0, False), None, None
    code, message, dispatch_started = "TASK_NOT_CURRENT", "科研权限、来源、配置或原任务已变化，未继续处理", False
    try:
        with factory() as db:
            prepared = reserve_research_dispatch(db, run_id, lease_token, claim_event_id)
            # Close *all* SQL locks/read views before awaiting any model I/O.
            db.commit()
        if prepared is ALREADY_RESERVED:
            return False
        if prepared is not None:
            provider, source, question, task, requester = prepared
            dispatch_started = True
            draft, receipt, _ = await generate_research(provider, source, question, task, transport=transport)
    except ResearchCallError as exc:
        receipt, code, message = exc.usage, exc.code, exc.message
    except HTTPException:
        pass
    except Exception:
        receipt = usage(None, None, True) if dispatch_started else usage(0, 0, False)
        code, message = "RESEARCH_EXECUTION_ERROR", "科研任务执行未完成；未自动重试或推断实际用量"
    elapsed = max(0, int((time.monotonic() - started) * 1000))
    if draft is not None:
        with factory() as db:
            try:
                stage_result(db, SimpleNamespace(user_id=requester), run_id, lease_token, draft, receipt, latency_ms=elapsed)
                db.commit()
                return True
            except Exception:
                db.rollback()
                code, message = "RESULT_NOT_ACCEPTED", "科研当前权限、原租约、来源或完整结果回执未闭合；保留实际用量且未接收结果"
    with factory() as db:
        try:
            return _finish_failure(db, run_id, lease_token, receipt, code, message, elapsed)
        except Exception:
            db.rollback()
            raise


def recover_interrupted_research_runs(db, *, older_than_seconds=600):
    """Fresh worker Session only; bounded technical recovery never replays.

    The first plain PK scan is current under a newly established RR view after
    Gate X. No candidate Run is prelocked before its actual current User. The
    feature Gate serializes every dedicated task writer while this scan runs.
    """
    from app.ai.models import AIRun

    try:
        if type(older_than_seconds) is not int or older_than_seconds < 1:
            raise HTTPException(422, "科研中断阈值须为明确正整数秒")
        if db.in_transaction():
            raise HTTPException(409, "科研恢复须使用全新worker Session，不能复用旧RR读取视图")
        lock_research_gate(db)
        cutoff = utcnow() - dt.timedelta(seconds=older_than_seconds)
        rows = (
            db.query(AIRun.run_id)
            .join(AIResearchCohortRunArtifact, AIRun.run_id == AIResearchCohortRunArtifact.run_id)
            .filter(
                AIRun.feature_key == "research_cohort",
                AIRun.status.in_(["running", "cancelled"]),
                AIRun.start_time < cutoff,
                AIRun.lease_token.is_not(None),
                AIResearchCohortRunArtifact.usage_event_id.is_(None),
            )
            .order_by(AIRun.run_id)
            .limit(8193)
            .all()
        )
        if len(rows) > 8192:
            raise HTTPException(409, "科研恢复集合超过8192，未截断或重放任何任务")
        count = 0
        for (identifier,) in rows:
            if _worker_locator(db, identifier) is None:
                continue
            header = _header(db, identifier)
            if header is None or header["status"] not in {"running", "cancelled"} or header["start_time"] is None or header["start_time"] >= cutoff:
                continue
            reserved = current_research_rows(db.query(AIResearchCohortRunArtifact.dispatch_event_id).filter_by(run_id=identifier), shared=True).scalar()
            stage_terminal_receipt(
                db,
                identifier,
                header["lease_token"],
                usage(None, None, None) if reserved is not None else usage(0, 0, False),
                status="cancelled" if header["status"] == "cancelled" else "failed",
                error_code="WORKER_INTERRUPTED",
                error_message="执行进程在dispatch预约后中断，调用和用量未知；未重放模型" if reserved is not None else "执行进程在dispatch预约前中断，未尝试模型调用",
                latency_ms=max(0, int((utcnow() - header["start_time"]).total_seconds() * 1000)),
            )
            count += 1
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
