"""Exact nullable terminal receipts without restoring lost Source authority.

The worker's original claim is a narrow technical capability to settle its one
attempt. It is never a capability to read Source/Task TEXT, accept content or
start another call. Ordinary receipt reads still use the full current Source
guard. All helpers stage one transaction; their caller owns commit.
"""

import re
from dataclasses import dataclass
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select, update

from app.ai import rca_evidence_attempts as attempts
from app.ai import rca_evidence_cases as cases
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_sources as originals
from app.ai import rca_evidence_storage as storage
from app.ai import rca_evidence_storage_contract as types
from app.ai.models import AIAuditEvent, AIRun
from app.ai.rca_evidence_run_models import ANCHOR_FIELDS, AIRcaEvidenceRunArtifact, AIRcaEvidenceRunResult
from app.ai.rca_evidence_task_views import RcaUsageReceipt
from app.ai.rca_evidence_write_guard import current_rows


@dataclass(frozen=True)
class RcaTechnicalAttempt:
    header: dict
    artifact: dict
    claim: attempts.RcaClaimProof
    dispatch: attempts.RcaDispatchProof | None


def technical_attempt(db, proof, *, exclusive=False):
    """Trusted one-lease settlement exception: no Source or Task body read."""
    proof = attempts.RcaClaimProof.model_validate(proof)
    identity = storage.locate_artifact(db, proof.run_id)
    if identity != (proof.run_id, proof.case_id, proof.requested_by):
        raise HTTPException(409, "本次技术回执与实际任务身份不同")
    header = storage._actual_run_header(db, proof.run_id, exclusive=exclusive)
    row = storage._artifact_metadata(db, proof.run_id, exclusive=exclusive)
    storage._exact_creation_audit(db, header, row)
    if (row["run_id"], row["case_id"], row["requested_by"]) != identity or header["requested_by"] != identity[2]:
        raise HTTPException(409, "本次技术回执的实际Run/Artifact归属不同")
    value = SimpleNamespace(run=SimpleNamespace(**header), artifact=SimpleNamespace(**row))
    actual = attempts.claim_proof(db, value)
    if proof != actual:
        raise HTTPException(409, "回执不是原claim实际PK与原租约")
    dispatch = attempts.dispatch_proof(db, value) if row["dispatch_event_id"] is not None else None
    return RcaTechnicalAttempt(header, row, actual, dispatch)


def terminal_state_hash(header, artifact):
    """Safe real header plus original anchors, with no receipt-PK cycle."""
    return c.digest(
        {
            "run_header": {key: storage._run_clock(header[key]) for key in storage.RUN_HEADER},
            "artifact": {key: storage._clock_value(artifact[key]) for key in (*ANCHOR_FIELDS, "create_event_id", "claim_event_id", "claim_lease", "claimed_at", "dispatch_event_id", "dispatched_at")},
        }
    )


def _usage_body(db, identifier):
    metadata = current_rows(db.query(AIAuditEvent.event_id, originals._bytes_expression(db, AIAuditEvent.detail_json).label("detail_bytes")).filter_by(event_id=identifier), shared=True).one_or_none()
    if metadata is None or metadata.detail_bytes is None or not 0 < metadata.detail_bytes <= 65535:
        raise HTTPException(409, "实际用量回执审计PK缺失或完整字节超限")
    row = current_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one()
    try:
        raw = storage.canonical_value(row.detail_json)
        when = raw.pop("recorded_at_utc6", None)
        basis = raw.pop("audit_clock_basis", None)
        receipt = types.RcaUsageEvent.model_validate(raw)
    except (ValueError, TypeError, UnicodeError, AttributeError) as exc:
        raise HTTPException(409, "该具体审计PK不是完整闭集实际用量回执") from exc
    if when != receipt.recorded_at or basis != "legacy_utc_second_storage":
        raise HTTPException(409, "实际用量回执的UTC6与旧审计秒级时钟不一致")
    return row, receipt


def read_receipt(db, attempt):
    """Internal metadata-only reader, called only after exact claim validation."""
    header, row = attempt.header, attempt.artifact
    if row["usage_event_id"] is None:
        return None
    event, receipt = _usage_body(db, row["usage_event_id"])
    when = c.clock(receipt.recorded_at).replace(tzinfo=None)
    expected = {
        "run_id": row["run_id"],
        "case_id": row["case_id"],
        "claim_event_id": row["claim_event_id"],
        "dispatch_event_id": row["dispatch_event_id"],
        "lease_token": row["claim_lease"],
        "binding_hash": row["binding_hash"],
        "source_hash": row["source_hash"],
        "status": header["status"],
        "error_code": header["error_code"],
        "terminal_state_hash": terminal_state_hash(header, row),
    }
    if any(getattr(receipt, key) != value for key, value in expected.items()) or (event.actor_id, event.action, event.target, event.create_time) != (
        row["requested_by"],
        "rca_run.usage",
        row["run_id"],
        when.replace(microsecond=0),
    ):
        raise HTTPException(409, "具体用量审计、原租约或实际终态头无法核对")
    if header["finish_time"] != when.replace(microsecond=0) or when < (row["dispatched_at"] or row["claimed_at"]):
        raise HTTPException(409, "本次实际用量回执与真实结束时钟不同")
    if (header["input_tokens"], header["output_tokens"]) != (receipt.usage.input_tokens or 0, receipt.usage.output_tokens or 0):
        raise HTTPException(409, "旧Run整数计数与独立nullable回执不同")
    if header["status"] != "succeeded":
        # A scalar comparison reveals no Task/result body. Failed/cancelled
        # attempts never retain accepted text or even an accepted result row.
        empty = db.scalar(select((AIRun.result_json == "{}").label("terminal_result_is_empty")).where(AIRun.run_id == row["run_id"]))
        result_id = db.scalar(select(AIRcaEvidenceRunResult.run_id).where(AIRcaEvidenceRunResult.run_id == row["run_id"]))
        if empty is not True or result_id is not None or receipt.result_hash is not None:
            raise HTTPException(409, "失败或取消任务不能保留接受正文或结果行")
    return receipt


def _terminal_values(header, usage, status, error_code, latency_ms, when):
    if status not in {"failed", "cancelled"} or type(error_code) is not str or re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", error_code) is None:
        raise ValueError("Only an explicit terminal failure/cancellation code can settle without Source")
    if type(latency_ms) is not int or not 0 <= latency_ms <= 2147483647:
        raise ValueError("Actual bounded latency milliseconds are required")
    if header["status"] == "cancelled":
        status, error_code = "cancelled", "WORKER_INTERRUPTED" if usage.model_call_attempted is None else "TASK_CANCELLED"
    return {
        "status": status,
        "error_code": error_code,
        "error_message": "本次任务未接受调查草稿；用量仅依实际收到的回执保留，未知不补零。",
        "input_tokens": usage.input_tokens if usage.input_tokens is not None else 0,
        "output_tokens": usage.output_tokens if usage.output_tokens is not None else 0,
        "latency_ms": latency_ms,
        "finish_time": when.replace(microsecond=0),
    }


@grants._write
def stage_terminal(db, proof, *, usage, status, error_code, latency_ms):
    """Only the trusted original worker/lease may settle its real paid attempt.

    Current Source/role loss is intentionally not bypassed for content: this
    controlled exception never loads Task TEXT, accepts a result or returns
    private pieces. The caller must not expose this worker API as a user route.
    """
    usage = RcaUsageReceipt.model_validate(usage)
    attempt = technical_attempt(db, proof, exclusive=True)
    header, row = attempt.header, attempt.artifact
    if row["usage_event_id"] is not None:
        read_receipt(db, attempt)
        return None
    if header["status"] not in {"running", "cancelled"}:
        raise HTTPException(409, "本次原租约已不是可结算的执行或取消任务")
    when = grants.utcnow()
    if when < (row["dispatched_at"] or row["claimed_at"]):
        raise HTTPException(409, "终态真实钟点早于实际claim/dispatch，未改写时钟或结算")
    values = _terminal_values(header, usage, status, error_code, latency_ms, when)
    expected_header = {**header, **values, "bytes_result_json": 2}
    receipt = types.RcaUsageEvent(
        schema_version="rca_evidence_usage_receipt_v1",
        run_id=row["run_id"],
        case_id=row["case_id"],
        claim_event_id=row["claim_event_id"],
        dispatch_event_id=row["dispatch_event_id"],
        lease_token=row["claim_lease"],
        binding_hash=row["binding_hash"],
        source_hash=row["source_hash"],
        result_hash=None,
        terminal_state_hash=terminal_state_hash(expected_header, row),
        status=values["status"],
        error_code=values["error_code"],
        usage=usage,
        recorded_at=i.utc_text(when),
        run_clock_basis="legacy_utc_second_storage",
    )
    db.execute(update(AIRun).where(AIRun.run_id == row["run_id"]).values(**values, result_json="{}"), execution_options={"synchronize_session": False})
    actor = SimpleNamespace(user_id=row["requested_by"])
    audit_id, expected_audit = grants._audit(db, actor, "rca_run.usage", row["run_id"], receipt.model_dump(mode="json"), when)
    db.execute(update(AIRcaEvidenceRunArtifact).where(AIRcaEvidenceRunArtifact.run_id == row["run_id"]).values(usage_event_id=audit_id), execution_options={"synchronize_session": False})
    db.flush()
    actual = technical_attempt(db, proof, exclusive=True)
    expected_artifact = {**row, "usage_event_id": audit_id}
    if actual.header != expected_header or actual.artifact != expected_artifact:
        raise HTTPException(409, "实际终态安全头或完整Artifact技术锚在写回后改变")
    grants._exact_audit(db, audit_id, expected_audit)
    if read_receipt(db, actual) != receipt:
        raise HTTPException(409, "具体用量PK或完整实际终态未原子保存")
    return receipt


def receipt_piece(db, user, identifier, *, frozen_audit=False):
    stored = storage.load_task(db, user, identifier, frozen_audit=frozen_audit)
    proof = attempts.claim_proof(db, stored)
    return cases.wire(read_receipt(db, technical_attempt(db, proof)))
