"""Specific durable claim/dispatch receipts; no clinical authority or audit scans.

Only opaque task/artifact headers precede the complete Source authorization.
A delivery's original positive claim PK is mandatory, including duplicates.
"""

import uuid
from types import SimpleNamespace
from typing import NamedTuple

from fastapi import HTTPException
from sqlalchemy import update

from app.ai.deidentification_receipts import audit_expected, result_header, verify_audit
from app.ai.deidentification_run_models import AIDeidentificationRunResult
from app.ai.deidentification_spans import canonical
from app.ai.deidentification_storage import opaque_artifact
from app.ai.deidentification_task_access import opaque_locator
from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_cohort_write_guard import current_actor, current_research_rows

CLAIM = "deidentification.task.claim"
DISPATCH = "deidentification.task.dispatch.reserve"
HEADER_FIELDS = (
    "run_id",
    "feature_key",
    "requested_by",
    "status",
    "lease_token",
    "start_time",
    "finish_time",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "error_code",
    "error_message",
)


class DeidentificationClaim(NamedTuple):
    run_id: str
    lease_token: str
    claim_event_id: int


def header(db, run_id, *, writing=False):
    row = current_research_rows(db.query(*(getattr(AIRun, key) for key in HEADER_FIELDS)).filter_by(run_id=run_id), shared=not writing).one_or_none()
    return dict(row._mapping) if row is not None else None


def worker_locator(db, run_id):
    from app.dependencies import VALID_USER_ROLES

    locator = opaque_locator(db, run_id)
    if locator is not None:
        # The actual business role/purpose is checked by Source before dispatch.
        # A legitimate platform role demoted to patient still closes known use.
        current_actor(db, SimpleNamespace(user_id=locator["requested_by"]), allowed_roles=VALID_USER_ROLES)
    return locator


def claim_detail(state, source):
    return {
        "schema_version": "deidentification_claim_v1",
        "run_id": state["run_id"],
        "lease_token": state["lease_token"],
        "start_time": utc_text(state["start_time"]),
        "source_binding_hash": source["source_binding_hash"],
    }


def verify_claim(db, run_id, lease, claim_event_id, *, pending=True):
    if type(claim_event_id) is not int or claim_event_id < 1:
        raise HTTPException(409, "75执行须保留原具体claim AuditPK，未范围查找或代造回执")
    locator, state = opaque_locator(db, run_id), header(db, run_id)
    source, result = opaque_artifact(db, run_id), result_header(db, run_id)
    event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=claim_event_id), shared=True).one_or_none()
    if (
        locator is None
        or state is None
        or state["feature_key"] != "deidentification"
        or state["requested_by"] != locator["requested_by"]
        or state["lease_token"] != lease
        or state["start_time"] is None
        or result["claim_event_id"] != claim_event_id
        or claim_event_id == source["create_event_id"]
        or event is None
        or (event.actor_id, event.action, event.target, event.detail_json) != (locator["requested_by"], CLAIM, run_id, canonical(claim_detail(state, source)))
        or pending
        and (state["status"] not in {"running", "cancelled"} or result["usage_event_id"] is not None)
    ):
        raise HTTPException(409, "75原具体claim、租约、请求人和原start clock不一致")
    return state


def claim_deidentification_run(db, run_id):
    try:
        locator = worker_locator(db, run_id)
        if locator is None:
            db.rollback()
            return None
        state, result = header(db, run_id, writing=True), result_header(db, run_id, writing=True)
        if state is None or state["feature_key"] != "deidentification" or state["requested_by"] != locator["requested_by"] or state["status"] != "queued":
            db.rollback()
            return None
        clean_result = current_research_rows(db.query(AIRun.result_json == "{}").filter_by(run_id=run_id), shared=True).scalar()
        if (
            any(state[key] is not None for key in ("lease_token", "start_time", "finish_time", "latency_ms", "error_code", "error_message"))
            or (state["input_tokens"], state["output_tokens"]) != (0, 0)
            or clean_result is not True
            or any(result[key] is not None for key in ("claim_event_id", "dispatch_event_id", "usage_event_id", "accept_event_id", "stored_result_hash"))
        ):
            raise HTTPException(409, "75排队原件已有执行痕迹，未重新领取")
        expected = {**state, "status": "running", "lease_token": str(uuid.uuid4()), "start_time": utcnow().replace(microsecond=0)}
        changed = db.execute(
            update(AIRun)
            .where(AIRun.run_id == run_id, AIRun.status == "queued", AIRun.lease_token.is_(None))
            .values(status="running", lease_token=expected["lease_token"], start_time=expected["start_time"])
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise HTTPException(409, "75原排队领取CAS已变化")
        source = opaque_artifact(db, run_id)
        event = AIAuditEvent(actor_id=locator["requested_by"], action=CLAIM, target=run_id, detail_json=canonical(claim_detail(expected, source)))
        db.add(event)
        audit = audit_expected(event)
        db.flush()
        changed = db.execute(
            update(AIDeidentificationRunResult)
            .where(AIDeidentificationRunResult.run_id == run_id, AIDeidentificationRunResult.claim_event_id.is_(None), AIDeidentificationRunResult.usage_event_id.is_(None))
            .values(claim_event_id=event.event_id)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1 or verify_claim(db, run_id, expected["lease_token"], event.event_id) != expected:
            raise HTTPException(409, "75具体claim和原Run同事务回读不符")
        verify_audit(db, event.event_id, audit)
        claimed = DeidentificationClaim(run_id, expected["lease_token"], event.event_id)
        db.commit()
        return claimed
    except Exception:
        db.rollback()
        raise


def read_dispatch(db, run_id):
    result, source = result_header(db, run_id), opaque_artifact(db, run_id)
    identifier = result["dispatch_event_id"]
    if type(identifier) is not int or identifier < 1 or identifier in {source["create_event_id"], result["claim_event_id"], result["usage_event_id"], result["accept_event_id"]}:
        raise HTTPException(409, "75发送具体AuditPK缺失或与其他回执混用")
    state = verify_claim(db, run_id, header(db, run_id)["lease_token"], result["claim_event_id"], pending=False)
    event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one_or_none()
    from app.ai.deidentification_storage import original_json

    detail = original_json(event.detail_json, 65535) if event is not None else None
    expected = {
        "schema_version": "deidentification_dispatch_reserved_v1",
        "run_id": run_id,
        "lease_token": state["lease_token"],
        "claim_event_id": result["claim_event_id"],
        "source_binding_hash": source["source_binding_hash"],
        "instructions_digest": source["instructions_digest"],
        "reserved_at": detail.get("reserved_at") if type(detail) is dict else None,
    }
    from pydantic import TypeAdapter

    from app.ai.research_cohort_contract import UTC

    try:
        TypeAdapter(UTC).validate_python(expected["reserved_at"], strict=True)
    except ValueError as exc:
        raise HTTPException(409, "75发送回执clock无效") from exc
    if event is None or (event.actor_id, event.action, event.target, detail) != (state["requested_by"], DISPATCH, run_id, expected):
        raise HTTPException(409, "75发送具体Audit和完整原锚不一致")
    return expected


def validate_delivery(db, run_id, lease, claim_event_id):
    """Technical precheck must run before the worker's exception-to-terminal path."""
    if type(claim_event_id) is not int or claim_event_id < 1:
        raise HTTPException(409, "75交付缺少原具体claim AuditPK，未改变任务或调用模型")
    if worker_locator(db, run_id) is None:
        raise HTTPException(409, "75持久Task Source不存在，未降级")
    result = result_header(db, run_id)
    if result["dispatch_event_id"] is not None:
        detail = read_dispatch(db, run_id)
        if (detail["lease_token"], detail["claim_event_id"]) != (lease, claim_event_id):
            raise HTTPException(409, "75重复交付与原具体claim不符，未终结首worker")
        return False
    verify_claim(db, run_id, lease, claim_event_id, pending=result["usage_event_id"] is None)
    if result["usage_event_id"] is not None:
        from app.ai.deidentification_receipts import usage_receipt
        from app.ai.deidentification_storage import technical_run

        usage_receipt(db, technical_run(db, run_id))
        return False
    return True


def stage_dispatch(db, run_id, lease, claim_event_id):
    """Caller holds complete Source/current config before Run X; never commits."""
    state = verify_claim(db, run_id, lease, claim_event_id)
    result, source = result_header(db, run_id, writing=True), opaque_artifact(db, run_id)
    if state["status"] != "running" or result["dispatch_event_id"] is not None:
        raise HTTPException(409, "75发送状态已变化，未重复调用")
    detail = {
        "schema_version": "deidentification_dispatch_reserved_v1",
        "run_id": run_id,
        "lease_token": lease,
        "claim_event_id": claim_event_id,
        "source_binding_hash": source["source_binding_hash"],
        "instructions_digest": source["instructions_digest"],
        "reserved_at": utc_text(utcnow()),
    }
    event = AIAuditEvent(actor_id=state["requested_by"], action=DISPATCH, target=run_id, detail_json=canonical(detail))
    db.add(event)
    audit = audit_expected(event)
    db.flush()
    changed = db.execute(
        update(AIDeidentificationRunResult)
        .where(
            AIDeidentificationRunResult.run_id == run_id,
            AIDeidentificationRunResult.claim_event_id == claim_event_id,
            AIDeidentificationRunResult.dispatch_event_id.is_(None),
            AIDeidentificationRunResult.usage_event_id.is_(None),
        )
        .values(dispatch_event_id=event.event_id)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1 or read_dispatch(db, run_id) != detail:
        raise HTTPException(409, "75发送具体AuditPK同事务CAS回读不符")
    verify_audit(db, event.event_id, audit)
    return detail
