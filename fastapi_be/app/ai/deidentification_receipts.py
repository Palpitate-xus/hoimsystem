"""Specific-PK usage/acceptance receipts; no audit action/target range locks."""

from fastapi import HTTPException

from app.ai.deidentification_collection import _sql_hash
from app.ai.deidentification_run_models import RESULT_SCHEMA, AIDeidentificationRunResult, AIDeidentificationRunSource
from app.ai.deidentification_spans import canonical, text_digest, utf8
from app.ai.deidentification_storage import HASH_FIELDS, TEXT_FIELDS, opaque_artifact, original_json, text_json
from app.ai.models import AIAuditEvent, AIRun
from app.ai.native_acceptance import AUDIT_FIELDS, RUN_FIELDS
from app.ai.research_cohort_write_guard import current_research_rows

CREATE = "deidentification.task.create"
USAGE = "deidentification.task.usage"
ACCEPT = "deidentification.task.accept"
WRITE_FIELDS = (*RUN_FIELDS, "input_tokens", "output_tokens", "error_code", "error_message", "latency_ms")


def usage(inputs=None, outputs=None, attempted=None):
    value = {"input_tokens": inputs, "output_tokens": outputs, "complete": inputs is not None and outputs is not None, "model_call_attempted": attempted}
    for count in (inputs, outputs):
        if count is not None and (type(count) is not int or not 0 <= count <= 2000000):
            raise HTTPException(409, "实际用量只能为独立有效整数或NULL")
    if attempted is not None and type(attempted) is not bool or attempted is False and (inputs, outputs) != (0, 0):
        raise HTTPException(409, "未调用模型须实际0/0，未知不能当作未调用")
    return value


def result_header(db, run_id, *, writing=False):
    columns = [column for column in AIDeidentificationRunResult.__table__.columns if column.name != "result_json"]
    row = current_research_rows(db.query(*columns, _sql_hash(db, AIDeidentificationRunResult.result_json).label("stored_result_hash")).filter_by(run_id=run_id), shared=not writing).one_or_none()
    if row is None:
        raise HTTPException(409, "完整75结果永久锚缺失")
    return dict(row._mapping)


def run_state(run, source):
    hashes = dict(zip(TEXT_FIELDS, HASH_FIELDS, strict=True))
    return {field: source[hashes[field]] if field in hashes else getattr(run, field) for field in WRITE_FIELDS}


def verify_run_state(db, run_id, expected, source):
    fields = [_sql_hash(db, getattr(AIRun, field)).label(field) if field in TEXT_FIELDS else getattr(AIRun, field) for field in WRITE_FIELDS]
    row = current_research_rows(db.query(*fields).filter_by(run_id=run_id)).one_or_none()
    header = opaque_artifact(db, run_id)
    source_sha = current_research_rows(db.query(_sql_hash(db, AIDeidentificationRunSource.source_json)).filter_by(run_id=run_id), shared=True).scalar()
    if row is None or dict(row._mapping) != expected or header != source or source_sha != source["source_hash"]:
        raise HTTPException(409, "75实际22Task列/原raw3完整SHA/永久Source锚写后不一致")


def audit_expected(event):
    return {field: getattr(event, field) for field in AUDIT_FIELDS}


def verify_audit(db, identifier, expected):
    event = current_research_rows(db.query(*(getattr(AIAuditEvent, field) for field in AUDIT_FIELDS)).filter_by(event_id=identifier), shared=True).one_or_none()
    if identifier is None or event is None or dict(event._mapping) != expected:
        raise HTTPException(409, "75本次具体审计PK实际写入缺失或变更")


def pointer(run_id, raw):
    return {"schema_version": "deidentification_result_pointer_v1", "run_id": run_id, "result_hash": text_digest(raw), "result_bytes": len(utf8(raw))}


def stage_terminal(db, run, source, receipt, result=None, *, accepted_at=None):
    """Caller already holds Gate→actor/parents→Run X; never returns to Source.

    Failure/cancel uses opaque hashes only. Successful callers must reauthorize
    the full source/config before and after this write in their transaction.
    """
    raw = canonical(result) if result is not None else None
    if (run.status == "succeeded") != (raw is not None):
        raise HTTPException(409, "仅成功状态可接收完整候选")
    run.result_json = text_json(pointer(run.run_id, raw)) if raw is not None else "{}"
    run.input_tokens = receipt["input_tokens"] if receipt["input_tokens"] is not None else 0
    run.output_tokens = receipt["output_tokens"] if receipt["output_tokens"] is not None else 0
    expected = run_state(run, source)
    db.flush()
    verify_run_state(db, run.run_id, expected, source)
    detail = {
        "schema_version": "deidentification_usage_receipt_v1",
        "run_id": run.run_id,
        "lease": run.lease_token,
        "status": run.status,
        "usage": receipt,
        "result_hash": text_digest(raw) if raw is not None else None,
        "error_code": run.error_code,
    }
    event = AIAuditEvent(actor_id=run.requested_by, action=USAGE, target=run.run_id, detail_json=canonical(detail))
    db.add(event)
    audit = audit_expected(event)
    db.flush()
    verify_audit(db, event.event_id, audit)
    verify_run_state(db, run.run_id, expected, source)
    accepted = None
    accept_expected = None
    if raw is not None:
        accepted = AIAuditEvent(
            actor_id=run.requested_by,
            action=ACCEPT,
            target=run.run_id,
            detail_json=canonical(
                {
                    "schema_version": "deidentification_accept_receipt_v1",
                    "run_id": run.run_id,
                    "lease": run.lease_token,
                    "usage_event_id": event.event_id,
                    "result_hash": text_digest(raw),
                    "result_bytes": len(utf8(raw)),
                    "source_binding_hash": source["source_binding_hash"],
                    "prompt_hash": source["prompt_hash"],
                }
            ),
        )
        db.add(accepted)
        accept_expected = audit_expected(accepted)
        db.flush()
        verify_audit(db, accepted.event_id, accept_expected)
        verify_run_state(db, run.run_id, expected, source)
    row = current_research_rows(db.query(AIDeidentificationRunResult).filter_by(run_id=run.run_id)).one()
    if row.usage_event_id is not None or row.accept_event_id is not None or row.result_json is not None:
        raise HTTPException(409, "原任务已有终态回执，未重复记用量或接收")
    row.usage_event_id = event.event_id
    if accepted is not None:
        row.accept_event_id, row.result_json, row.result_hash, row.result_bytes = accepted.event_id, raw, text_digest(raw), len(utf8(raw))
        row.accepted_lease, row.accepted_at = run.lease_token, accepted_at
    db.flush()
    verify_run_state(db, run.run_id, expected, source)
    verify_audit(db, event.event_id, audit)
    if accepted is not None:
        verify_audit(db, accepted.event_id, accept_expected)
    actual = result_header(db, run.run_id)
    expected_result = {
        "run_id": run.run_id,
        "schema_version": RESULT_SCHEMA,
        "created_at": source["created_at"],
        "usage_event_id": event.event_id,
        "accept_event_id": accepted.event_id if accepted is not None else None,
        "result_hash": text_digest(raw) if raw is not None else None,
        "result_bytes": len(utf8(raw)) if raw is not None else None,
        "accepted_lease": run.lease_token if raw is not None else None,
        "accepted_at": accepted_at if raw is not None else None,
        "stored_result_hash": text_digest(raw) if raw is not None else None,
    }
    if actual != expected_result:
        raise HTTPException(409, "完整75结果Artifact或真实用量/接收关联写后不符")
    usage_receipt(db, run, source=source)
    return expected


def usage_receipt(db, run, *, source=None):
    """Internal technical reader. Public callers must authorize owner/current role."""
    source = source or opaque_artifact(db, run.run_id)
    header = result_header(db, run.run_id)
    if header["usage_event_id"] is None:
        # A running cancellation can retain the durable pre-call reservation
        # (latency_ms=0) while its one-shot worker is still awaiting HTTP. It is
        # not a completed zero-cost call. Completed/corrupt terminal writes must
        # still have their specific usage PK; do not downgrade them to pending.
        pending_result = all(header[key] is None for key in ("result_hash", "result_bytes", "accepted_lease", "accepted_at", "accept_event_id", "stored_result_hash"))
        pending_cancel = (
            run.status == "cancelled"
            and run.lease_token is not None
            and run.start_time is not None
            and run.latency_ms in (None, 0)
            and run.error_code is None
            and run.error_message is None
            and (run.input_tokens, run.output_tokens) == (0, 0)
            and pending_result
        )
        if run.status not in {"queued", "running"} and not pending_cancel:
            raise HTTPException(409, "终态实际用量回执缺失")
        return usage()
    event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=header["usage_event_id"]), shared=True).one_or_none()
    if event is None or header["usage_event_id"] == source["create_event_id"] or (event.actor_id, event.action, event.target) != (run.requested_by, USAGE, run.run_id):
        raise HTTPException(409, "实际用量具体审计身份不符")
    detail = original_json(event.detail_json, 65535)
    try:
        receipt = detail["usage"]
        checked = usage(receipt["input_tokens"], receipt["output_tokens"], receipt["model_call_attempted"])
        expected = {
            "schema_version": "deidentification_usage_receipt_v1",
            "run_id": run.run_id,
            "lease": run.lease_token,
            "status": run.status,
            "usage": checked,
            "result_hash": header["result_hash"] if run.status == "succeeded" else None,
            "error_code": run.error_code,
        }
        if (
            canonical(detail) != canonical(expected)
            or canonical(receipt) != canonical(checked)
            or (run.input_tokens, run.output_tokens) != (checked["input_tokens"] or 0, checked["output_tokens"] or 0)
        ):
            raise ValueError("Whole usage/lease/state/legacy counter tuple differs")
        if run.status == "succeeded":
            if header["accept_event_id"] in {None, source["create_event_id"], header["usage_event_id"]} or header["stored_result_hash"] != header["result_hash"]:
                raise ValueError("Actual complete result or three distinct audit PKs missing")
            accepted = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=header["accept_event_id"]), shared=True).one_or_none()
            expected_accept = {
                "schema_version": "deidentification_accept_receipt_v1",
                "run_id": run.run_id,
                "lease": run.lease_token,
                "usage_event_id": header["usage_event_id"],
                "result_hash": header["result_hash"],
                "result_bytes": header["result_bytes"],
                "source_binding_hash": source["source_binding_hash"],
                "prompt_hash": source["prompt_hash"],
            }
            if accepted is None or (accepted.actor_id, accepted.action, accepted.target, accepted.detail_json) != (run.requested_by, ACCEPT, run.run_id, canonical(expected_accept)):
                raise ValueError("Specific acceptance audit differs")
        return checked
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, "75实际nullable用量/接受回执无法核对") from exc
