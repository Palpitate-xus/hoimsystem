"""Atomic whole results and exact primary-key terminal usage receipts.

The caller owns current actor/source/configuration authorization and Run X lock.
This module stages and verifies SQL writes, and never commits or calls a model.
"""

from fastapi import HTTPException

from app.ai import charge_reconciliation_contract as c
from app.ai.charge_reconciliation_context import expand_context
from app.ai.charge_reconciliation_result import validate_result
from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.charge_reconciliation_storage import _json, load_snapshot
from app.ai.charge_reconciliation_view_contract import ChargeReceiptEvent, ChargeResultReference, ChargeUsage
from app.ai.governance import audit
from app.ai.models import AIAuditEvent, AIRun
from app.ai.native_acceptance import AUDIT_FIELDS, RUN_FIELDS, acceptance_state

WRITE_FIELDS = (*RUN_FIELDS, "input_tokens", "output_tokens", "error_code", "error_message", "latency_ms")
ARTIFACT_FIELDS = tuple(column.name for column in AIChargeRunArtifact.__table__.columns)
ACCEPT = "run.charge_reconciliation.accept"
FAIL = "run.charge_reconciliation.fail"
CANCEL = "run.charge_reconciliation.cancel"


def usage(inputs=None, outputs=None, attempted=None):
    return ChargeUsage(input_tokens=inputs, output_tokens=outputs, complete=inputs is not None and outputs is not None, model_call_attempted=attempted).model_dump(mode="json")


def _artifact(db, run, *, writing=False):
    row = db.query(AIChargeRunArtifact).filter_by(run_id=run.run_id).populate_existing().with_for_update(read=not writing).one_or_none()
    if row is None:
        raise HTTPException(409, "完整账目任务锚点不存在")
    return row


def _read_result(db, run, snapshot, binding, row):
    reference = ChargeResultReference.model_validate(_json(run.result_json))
    if c.canonical_json(reference) != run.result_json:
        raise ValueError("The complete result reference must retain its exact scalar types")
    expected = {
        "schema_version": "charge_result_ref_v1",
        "run_id": run.run_id,
        "case_snapshot_id": binding["case_snapshot_id"],
        "lease_token": run.lease_token,
        "content_hash": row.result_hash,
        "result_bytes": row.result_bytes,
        "source_binding_hash": c.digest(binding),
        "receipt_event_id": row.receipt_event_id,
    }
    if reference.model_dump(mode="json") != expected or row.accepted_lease != run.lease_token:
        raise ValueError("The actual result/source/lease/receipt reference differs")
    raw = row.result_json
    if type(raw) is not str or not 0 < len(c.utf8(raw)) <= c.MAX_BYTES or len(c.utf8(raw)) != row.result_bytes:
        raise ValueError("The whole saved result differs from its exact UTF8 size")
    from app.ai.charge_reconciliation_sources import parse_json

    result = parse_json(raw)
    if c.canonical_json(result) != raw or c.digest(result) != row.result_hash:
        raise ValueError("The original complete result bytes or hash differ")
    expanded = expand_context(db, snapshot["payload"]["context"])
    validate_result(result, expanded["charge_source"], binding["projection_hash"])
    return result


def load_terminal(db, run):
    """Authorization belongs to the caller; pending usage remains independently unknown."""
    try:
        snapshot, binding, _, _ = load_snapshot(db, run)
        row = _artifact(db, run)
        if row.receipt_event_id is None:
            if run.result_json != "{}" or any(getattr(row, key) is not None for key in ("result_json", "result_hash", "result_bytes", "accepted_lease")):
                raise ValueError("A pending task cannot carry accepted result material")
            if run.status not in {"queued", "running"} and not (run.status == "cancelled" and run.latency_ms is None):
                raise ValueError("A terminal task needs its exact receipt")
            return None, usage()
        action = ACCEPT if run.status == "succeeded" else FAIL if run.status == "failed" else CANCEL if run.status == "cancelled" else None
        if action is None or row.accepted_lease != run.lease_token:
            raise ValueError("Actual terminal status or lease differs")
        event = db.query(AIAuditEvent).filter_by(event_id=row.receipt_event_id).populate_existing().with_for_update(read=True).one_or_none()
        if event is None or event.actor_id != run.requested_by or event.action != action or event.target != run.run_id:
            raise ValueError("The actual terminal audit primary key, actor or action differs")
        detail = ChargeReceiptEvent.model_validate(_json(event.detail_json))
        if (
            c.canonical_json(detail) != event.detail_json
            or detail.lease_token != run.lease_token
            or detail.source_binding_hash != c.digest(binding)
            or detail.error_code != run.error_code
            or detail.usage.model_call_attempted is None
            and not (run.status in {"failed", "cancelled"} and run.error_code == "WORKER_INTERRUPTED")
        ):
            raise ValueError("The closed original receipt differs from its actual task")
        for name in ("input_tokens", "output_tokens"):
            count = getattr(detail.usage, name)
            if getattr(run, name) != (count if count is not None else 0):
                raise ValueError("Legacy counters differ from the nullable original receipt")
        if run.status == "succeeded":
            if not detail.usage.complete or detail.usage.model_call_attempted is not True:
                raise ValueError("An accepted model result requires its actual complete usage")
            result = _read_result(db, run, snapshot, binding, row)
            if detail.result_hash != row.result_hash:
                raise ValueError("The specific acceptance event binds a different whole result")
        else:
            if run.result_json != "{}" or any(getattr(row, key) is not None for key in ("result_json", "result_hash", "result_bytes")) or detail.result_hash is not None:
                raise ValueError("An unsuccessful task cannot retain an accepted draft")
            result = None
        return result, detail.usage.model_dump(mode="json")
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "完整账目结果、实际用量或具体接收审计无效，未降级展示") from exc


def _verify_write(db, run, expected):
    actual = db.query(*(getattr(AIRun, key) for key in WRITE_FIELDS)).filter_by(run_id=run.run_id).with_for_update().one_or_none()
    row = db.query(*(getattr(AIChargeRunArtifact, key) for key in ARTIFACT_FIELDS)).filter_by(run_id=run.run_id).with_for_update().one_or_none()
    event = db.query(*(getattr(AIAuditEvent, key) for key in AUDIT_FIELDS)).filter_by(event_id=expected["event"].event_id).with_for_update(read=True).one_or_none()
    if actual is None or dict(actual._mapping) != expected["run"] or row is None or dict(row._mapping) != expected["artifact"] or event is None or dict(event._mapping) != expected["audit"]:
        raise HTTPException(409, "本次账目任务22字段、完整结果或具体审计实际写入不同")
    db.refresh(run)


def stage_terminal(db, run, receipt, result=None):
    """Require the caller's current source/actor/config and Run X lock; never commit."""
    snapshot, binding, _, _ = load_snapshot(db, run)
    row = _artifact(db, run, writing=True)
    if run.result_json != "{}" or any(getattr(row, key) is not None for key in ("result_json", "result_hash", "result_bytes", "receipt_event_id", "accepted_lease")):
        raise HTTPException(409, "本任务已接收完整结果或回执，不能覆盖")
    checked = ChargeUsage.model_validate(receipt)
    if checked.model_call_attempted is None and not (run.status in {"failed", "cancelled"} and run.error_code == "WORKER_INTERRUPTED"):
        raise HTTPException(409, "终态须保留明确的实际调用状态")
    action = ACCEPT if run.status == "succeeded" else FAIL if run.status == "failed" else CANCEL if run.status == "cancelled" else None
    if action is None or (result is not None) != (action == ACCEPT):
        raise HTTPException(409, "实际终态与完整模型结果不一致")
    if action == ACCEPT:
        expanded = expand_context(db, snapshot["payload"]["context"])
        result = validate_result(result, expanded["charge_source"], binding["projection_hash"]).model_dump(mode="json")
        raw = c.canonical_json(result)
        if not 0 < len(c.utf8(raw)) <= c.MAX_BYTES:
            raise HTTPException(409, "完整账目结果超过8MiB，未接收或截断")
        row.result_json, row.result_hash, row.result_bytes = raw, c.digest(result), len(c.utf8(raw))
    row.accepted_lease = run.lease_token
    detail = ChargeReceiptEvent(
        schema_version="charge_reconciliation_receipt_v1", lease_token=run.lease_token, usage=checked, result_hash=row.result_hash, source_binding_hash=c.digest(binding), error_code=run.error_code
    )
    audit(db, run.requested_by, action, run.run_id, detail.model_dump(mode="json"))
    expected = acceptance_state(db, run, action)
    expected["run"] = {key: getattr(run, key) for key in WRITE_FIELDS}
    expected["artifact"] = {key: getattr(row, key) for key in ARTIFACT_FIELDS}
    db.flush()
    _verify_write(db, run, expected)
    row.receipt_event_id = expected["event"].event_id
    expected["artifact"]["receipt_event_id"] = row.receipt_event_id
    if action == ACCEPT:
        reference = ChargeResultReference(
            schema_version="charge_result_ref_v1",
            run_id=run.run_id,
            case_snapshot_id=binding["case_snapshot_id"],
            lease_token=run.lease_token,
            content_hash=row.result_hash,
            result_bytes=row.result_bytes,
            source_binding_hash=c.digest(binding),
            receipt_event_id=row.receipt_event_id,
        )
        run.result_json = c.canonical_json(reference)
        expected["run"]["result_json"] = run.result_json
    db.flush()
    _verify_write(db, run, expected)
    load_terminal(db, run)
    return expected
