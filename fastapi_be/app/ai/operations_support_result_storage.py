"""Complete source-authorized result acceptance with actual usage, one SQL stage.

Caller owns rollback/commit. This never dispatches, aggregates private parts or
makes an unverified operations draft a diagnosis/current-environment finding.
"""

from fastapi import HTTPException

from app.ai import operations_support_attempts as attempts
from app.ai import operations_support_contract as c
from app.ai import operations_support_receipts as receipts
from app.ai import operations_support_registry as registry
from app.ai import operations_support_storage as storage
from app.ai.models import AIRun
from app.ai.operations_support_run_models import RESULT_SCHEMA, AIOperationsRunArtifact, AIOperationsRunResult
from app.ai.operations_support_task_contract import verify_result
from app.ai.operations_support_usage_contract import OperationsUsage
from app.ai.operations_support_write_guard import current_rows

ACCEPT_ACTION = "operations.task.result.accept"


def load_result(db, user, identifier):
    """Current Source/owner/configured role, then actual accepted whole bytes."""
    loaded = storage.load_artifact(db, user, identifier)
    run, artifact, source, private, prompt, execution, selection = loaded
    claim = attempts.claim_from_headers(db, attempts.phase_header(db, identifier), storage.run_header(db, identifier))
    actual = attempts.technical_attempt(db, claim, exclusive=False)
    receipt = receipts.read_receipt(db, actual)
    if run.status != "succeeded" or receipt is None or receipt.status != "succeeded":
        raise HTTPException(409, "本运维任务尚无实际已接受结果")
    metadata = receipts._accepted_header(db, actual, receipt)
    with db.no_autoflush:
        row = current_rows(db.query(AIOperationsRunResult).filter_by(run_id=identifier), shared=True).one_or_none()
    try:
        if (
            row is None
            or {column.name: getattr(row, column.name) for column in AIOperationsRunResult.__table__.columns if column.name != "result_json"} != metadata
            or len(row.result_json.encode()) != row.result_bytes
            or registry.raw_sha(row.result_json) != row.result_hash
        ):
            raise ValueError("The actual entire result bytes or immutable accepted metadata differ")
        result = verify_result(storage._json(row.result_json, c.MAX_WHOLE_BYTES), source, selection)
        if c.canonical_json(result) != row.result_json:
            raise ValueError("Entire canonical accepted result differs")
        return result
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "运维完整结果、原Source或逐字码点引用不能重算") from exc


def stage_result(db, user, claim, value, *, dispatch_event_id, usage, latency_ms):
    """This delivery only: current full Source, exact quoted draft and atomic receipt.

    Legitimate missing usage components remain null and do not invalidate an
    otherwise complete result. A cancelled task is settled by the terminal path.
    """
    try:
        claim = attempts.OperationsClaim.model_validate(claim, strict=True)
        actual_usage = OperationsUsage.model_validate(usage, strict=True)
        if actual_usage.model_call_attempted is not True or type(dispatch_event_id) is not int or dispatch_event_id < 1 or type(latency_ms) is not int or not 0 <= latency_ms <= 2147483647:
            raise ValueError("An actual attempted delivery, dispatch PK and latency are required")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "运维接受结果须绑定原实际交付与独立用量") from exc
    if attempts._phase_seen(db, claim.run_id, ("usage_event_id",)):
        return None
    # Current Source metadata and Config precede Run locks, then original claim
    # ownership precedes the first private Source or Task BODY.
    storage._before_bodies(db, user, claim.run_id, execution=True)
    attempt = attempts.technical_attempt(db, claim, exclusive=True)
    if attempt.artifact["dispatch_event_id"] != dispatch_event_id or attempt.artifact["usage_event_id"] is not None or attempt.header["status"] != "running":
        return None
    loaded = storage.load_artifact(db, user, claim.run_id, execution=True)
    run, artifact, source, private, prompt, execution, selection = loaded
    if run.result_json != "{}" or run.input_tokens != 0 or run.output_tokens != 0 or any(getattr(run, key) is not None for key in ("finish_time", "latency_ms", "error_code", "error_message")):
        raise HTTPException(409, "在途运维任务已有终态痕迹，未覆盖旧结果")
    receipts._no_accepted_result(db, claim.run_id)
    try:
        draft = verify_result(value, source, selection)
        blob = registry.bounded_json(draft)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "完整运维草稿不符合本次Source、目标或逐字码点引用") from exc
    when = registry.utcnow()
    if attempt.dispatch is None or when < attempts.clock(attempt.dispatch.dispatched_at):
        raise HTTPException(409, "结果接受时钟早于本次实际dispatch")
    result_header = {
        "run_id": run.run_id,
        "schema_version": RESULT_SCHEMA,
        "lease_token": claim.lease_token,
        "accepted_at": when,
        "result_bytes": len(blob.encode()),
        "result_hash": registry.raw_sha(blob),
        "source_binding_hash": artifact.source_binding_hash,
        "instructions_digest": artifact.instructions_digest,
    }
    pointer = receipts.result_reference(result_header)
    if len(pointer.encode()) > 65535:
        raise HTTPException(409, "完整运维结果短引用超过旧Run真实TEXT容量")
    expected_run = {column.name: getattr(run, column.name) for column in AIRun.__table__.columns}
    expected_artifact = {column.name: getattr(artifact, column.name) for column in AIOperationsRunArtifact.__table__.columns}
    result_header["accept_audit_event_id"] = registry.audit_event(db, artifact.requested_by, ACCEPT_ACTION, run.run_id, receipts.acceptance_detail(attempt, result_header), when)
    db.add(AIOperationsRunResult(**result_header, result_json=blob))
    db.flush()
    terminal = {
        "status": "succeeded",
        "error_code": None,
        "error_message": None,
        "input_tokens": actual_usage.input_tokens if actual_usage.input_tokens is not None else 0,
        "output_tokens": actual_usage.output_tokens if actual_usage.output_tokens is not None else 0,
        "latency_ms": latency_ms,
        "finish_time": when.replace(microsecond=0),
    }
    planned = {**attempt.header, **terminal}
    receipt = receipts.OperationsUsageEvent(
        schema_version="operations_support_usage_event_v1",
        run_id=run.run_id,
        case_id=artifact.case_id,
        requested_by=artifact.requested_by,
        created_audit_event_id=artifact.created_audit_event_id,
        claim_event_id=claim.claim_event_id,
        dispatch_event_id=dispatch_event_id,
        lease_token=claim.lease_token,
        source_projection_hash=artifact.source_projection_hash,
        source_binding_hash=artifact.source_binding_hash,
        instructions_digest=artifact.instructions_digest,
        usage=actual_usage,
        status="succeeded",
        error_code=None,
        latency_ms=latency_ms,
        result_hash=result_header["result_hash"],
        result_reference_hash=registry.raw_sha(pointer),
        terminal_header_hash=receipts.terminal_hash(planned, attempt.artifact),
        recorded_at=registry.utc_text(when),
    )
    usage_id = registry.audit_event(db, artifact.requested_by, receipts.USAGE_ACTION, run.run_id, receipt, when)
    changed = db.query(AIRun).filter_by(run_id=run.run_id, status="running", lease_token=claim.lease_token).update({**terminal, "result_json": pointer}, synchronize_session=False)
    saved = (
        db.query(AIOperationsRunArtifact)
        .filter_by(run_id=run.run_id, claim_event_id=claim.claim_event_id, dispatch_event_id=dispatch_event_id, usage_event_id=None)
        .update({"usage_event_id": usage_id}, synchronize_session=False)
    )
    if changed != 1 or saved != 1:
        raise HTTPException(409, "原运维任务接受结果CAS失败")
    expected_run.update(**terminal, result_json=pointer)
    expected_artifact["usage_event_id"] = usage_id
    # Triggers may change Source, actor, config, exact audit PKs or the blob.
    # Current Source/config must be checked again before any protected readback.
    attempts._postcheck(db, user, run.run_id, expected_run, expected_artifact)
    final = attempts.technical_attempt(db, claim, exclusive=True)
    if receipts.read_receipt(db, final) != receipt or load_result(db, user, run.run_id) != draft:
        raise HTTPException(409, "实际完整运维结果、原调用用量或具体接受回执读回不一致")
    return draft
