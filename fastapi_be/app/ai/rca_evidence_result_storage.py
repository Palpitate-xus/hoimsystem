"""Whole accepted result, exact accept/usage PKs and independent split reads.

Source -> original purposes -> Run -> Artifact remains the ordinary order.
The runtime caller owns current feature/provider/Prompt checks and commit;
this module never calls a model, enables a feature or writes legacy RCA/PDCA.
"""

from fastapi import HTTPException
from sqlalchemy import select

from app.ai import rca_evidence_attempts as attempts
from app.ai import rca_evidence_cases as cases
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_receipts as receipts
from app.ai import rca_evidence_result as result_types
from app.ai import rca_evidence_sources as originals
from app.ai import rca_evidence_storage as storage
from app.ai import rca_evidence_storage_contract as types
from app.ai import rca_evidence_task_contract as task_types
from app.ai.models import AIAuditEvent, AIRun
from app.ai.rca_evidence_run_models import RESULT_SCHEMA, AIRcaEvidenceRunArtifact, AIRcaEvidenceRunResult
from app.ai.rca_evidence_task_views import RcaResultReference, RcaUsageReceipt
from app.ai.rca_evidence_write_guard import current_rows

RESULT_COLUMNS = tuple(column.name for column in AIRcaEvidenceRunResult.__table__.columns)
RESULT_HEADER = tuple(key for key in RESULT_COLUMNS if key != "result_json")


def _accept_detail(header, artifact, result):
    return {
        "schema_version": "rca_evidence_accept_audit_v1",
        "result": {key: storage._clock_value(result[key]) for key in RESULT_HEADER if key != "accept_audit_event_id"},
        "create_event_id": artifact["create_event_id"],
        "claim_event_id": artifact["claim_event_id"],
        "dispatch_event_id": artifact["dispatch_event_id"],
        "binding_hash": artifact["binding_hash"],
        "terminal_state_hash": receipts.terminal_state_hash(header, artifact),
    }


def _exact_accept(db, header, artifact, result):
    identifier = result["accept_audit_event_id"]
    columns = (AIAuditEvent.event_id, originals._bytes_expression(db, AIAuditEvent.detail_json).label("detail_bytes"))
    metadata = current_rows(db.query(*columns).filter_by(event_id=identifier), shared=True).one_or_none()
    if metadata is None or metadata.detail_bytes is None or not 0 < metadata.detail_bytes <= task_types.MAX_RUN_TEXT_BYTES:
        raise HTTPException(409, "具体接受审计PK缺失或完整字节容量错误")
    row = current_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one()
    when = result["accepted_at"]
    expected = {**_accept_detail(header, artifact, result), "recorded_at_utc6": i.utc_text(when), "audit_clock_basis": "legacy_utc_second_storage"}
    if (row.actor_id, row.action, row.target, row.create_time, row.detail_json) != (
        artifact["requested_by"],
        "rca_run.accept",
        artifact["run_id"],
        when.replace(microsecond=0),
        c.canonical(expected),
    ):
        raise HTTPException(409, "具体接受审计与实际完整结果、原租约或终态头不同")


def _result_header(db, identifier):
    columns = [getattr(AIRcaEvidenceRunResult, key) for key in RESULT_HEADER]
    columns.append(originals._bytes_expression(db, AIRcaEvidenceRunResult.result_json).label("actual_bytes"))
    row = current_rows(db.query(*columns).filter_by(run_id=identifier), shared=True).one_or_none()
    if row is None or type(row.result_bytes) is not int or not 0 < row.result_bytes <= c.MAX_WIRE_BYTES or row.actual_bytes != row.result_bytes:
        raise HTTPException(409, "成功任务完整结果行缺失或实际UTF8字节锚不同")
    return {key: row._mapping[key] for key in RESULT_HEADER}


def _read_stored_result(db, stored):
    run, artifact = stored.run, stored.artifact
    if run.status != "succeeded":
        present = db.scalar(select(AIRcaEvidenceRunResult.run_id).where(AIRcaEvidenceRunResult.run_id == run.run_id))
        if present is not None or run.result_json != "{}":
            raise HTTPException(409, "未成功任务不能携带接受结果或短指针")
        return None
    proof = attempts.claim_proof(db, stored)
    if artifact.dispatch_event_id is None or artifact.usage_event_id is None or run.error_code is not None or run.error_message is not None:
        raise HTTPException(409, "成功任务必须有完整实际dispatch/usage且无错误状态")
    attempt = receipts.technical_attempt(db, proof)
    usage = receipts.read_receipt(db, attempt)
    header = _result_header(db, run.run_id)
    phase_ids = {artifact.create_event_id, artifact.claim_event_id, artifact.dispatch_event_id, artifact.usage_event_id, header["accept_audit_event_id"]}
    if None in phase_ids or len(phase_ids) != 5:
        raise HTTPException(409, "创建、claim、dispatch、usage与accept必须为五条具体不同审计PK")
    if (
        header["schema_version"] != RESULT_SCHEMA
        or (header["source_hash"], header["instructions_digest"], header["accepted_lease"]) != (artifact.source_hash, artifact.instructions_digest, artifact.claim_lease)
        or header["accepted_at"] < artifact.dispatched_at
        or usage.result_hash != header["result_hash"]
        or usage.recorded_at != i.utc_text(header["accepted_at"])
    ):
        raise HTTPException(409, "实际完整结果与原Source、Prompt、租约、UTC6或独立回执不同")
    _exact_accept(db, attempt.header, attempt.artifact, header)
    try:
        reference = RcaResultReference.model_validate(storage.canonical_value(run.result_json))
        expected_reference = RcaResultReference(
            schema_version="rca_evidence_result_ref_v1",
            run_id=run.run_id,
            result_hash=header["result_hash"],
            result_bytes=header["result_bytes"],
            accepted_lease=header["accepted_lease"],
            accept_audit_event_id=header["accept_audit_event_id"],
        )
        if reference != expected_reference:
            raise ValueError("The entire original canonical pointer differs")
        row = current_rows(db.query(AIRcaEvidenceRunResult).filter_by(run_id=run.run_id), shared=True).one()
        if storage.text_hash(row.result_json, c.MAX_WIRE_BYTES) != header["result_hash"]:
            raise ValueError("The exact full result bytes differ from their SQL anchor")
        result = result_types.validate_result(storage.canonical_value(row.result_json, c.MAX_WIRE_BYTES), stored.source, artifact.instructions_digest)
        cases.wire(result)
        return result
    except (ValueError, TypeError, UnicodeError, KeyError) as exc:
        raise HTTPException(409, "原完整结果、固定说明、逐字引文或短指针无法重算；未降级或裁剪") from exc


def read_result(db, user, identifier, *, frozen_audit=False):
    return _read_stored_result(db, storage.load_task(db, user, identifier, frozen_audit=frozen_audit))


def result_piece(db, user, identifier, *, frozen_audit=False):
    return cases.wire(read_result(db, user, identifier, frozen_audit=frozen_audit))


@grants._write
def stage_result(db, user, proof, result, *, dispatch_event_id, usage, latency_ms):
    """Stage Source-bound content plus two exact terminal audit PKs atomically."""
    proof = attempts.RcaClaimProof.model_validate(proof)
    if type(dispatch_event_id) is not int or dispatch_event_id < 1:
        raise ValueError("Only the caller's actual committed dispatch PK can accept its content")
    stored = storage.load_task(db, user, proof.run_id, exclusive=True)
    run, artifact = stored.run, stored.artifact
    if attempts.claim_proof(db, stored) != proof or artifact.dispatch_event_id is None:
        raise HTTPException(409, "成功结果不是原实际claim与dispatch")
    attempts.dispatch_proof(db, stored)
    if artifact.dispatch_event_id != dispatch_event_id:
        return None
    if run.status != "running" or artifact.usage_event_id is not None or run.result_json != "{}":
        raise HTTPException(409, "原任务已取消、结束或已有结果，不能再次接受正文")
    if db.scalar(select(AIRcaEvidenceRunResult.run_id).where(AIRcaEvidenceRunResult.run_id == run.run_id)) is not None:
        raise HTTPException(409, "原任务已有完整结果行，不能覆盖或重放")
    usage = RcaUsageReceipt.model_validate(usage)
    if usage.model_call_attempted is not True:
        raise ValueError("Accepted content requires an actually attempted call, not invented or inferred usage")
    result = result_types.validate_result(result, stored.source, artifact.instructions_digest)
    cases.wire(result)  # The actual entire split wire, not only the inner JSON.
    raw = c.canonical(result)
    when = grants.utcnow()
    if when < artifact.dispatched_at or type(latency_ms) is not int or not 0 <= latency_ms <= 2147483647:
        raise ValueError("The actual bounded latency and non-reversed UTC6 acceptance clock are required")
    run.status, run.finish_time, run.latency_ms = "succeeded", when.replace(microsecond=0), latency_ms
    run.error_code = run.error_message = None
    run.input_tokens = usage.input_tokens if usage.input_tokens is not None else 0
    run.output_tokens = usage.output_tokens if usage.output_tokens is not None else 0
    header = {key: getattr(run, key) for key in storage.RUN_HEADER}
    artifact_header = {key: getattr(artifact, key) for key in storage.ART_COLUMNS if key not in storage.ART_TEXT}
    result_header = {
        "run_id": run.run_id,
        "schema_version": RESULT_SCHEMA,
        "source_hash": artifact.source_hash,
        "instructions_digest": artifact.instructions_digest,
        "accepted_lease": artifact.claim_lease,
        "accepted_at": when,
        "result_bytes": len(c.utf8(raw)),
        "result_hash": storage.text_hash(raw, c.MAX_WIRE_BYTES),
    }
    accept_id, expected_accept = grants._audit(db, stored.authorized.actor, "rca_run.accept", run.run_id, _accept_detail(header, artifact_header, result_header), when)
    result_header["accept_audit_event_id"] = accept_id
    row = AIRcaEvidenceRunResult(**result_header, result_json=raw)
    db.add(row)
    reference = RcaResultReference(
        schema_version="rca_evidence_result_ref_v1",
        run_id=run.run_id,
        result_hash=result_header["result_hash"],
        result_bytes=result_header["result_bytes"],
        accepted_lease=artifact.claim_lease,
        accept_audit_event_id=accept_id,
    )
    run.result_json = task_types.text_json(reference)
    receipt = types.RcaUsageEvent(
        schema_version="rca_evidence_usage_receipt_v1",
        run_id=run.run_id,
        case_id=artifact.case_id,
        claim_event_id=artifact.claim_event_id,
        dispatch_event_id=artifact.dispatch_event_id,
        lease_token=artifact.claim_lease,
        binding_hash=artifact.binding_hash,
        source_hash=artifact.source_hash,
        result_hash=result_header["result_hash"],
        terminal_state_hash=receipts.terminal_state_hash(header, artifact_header),
        status="succeeded",
        error_code=None,
        usage=usage,
        recorded_at=i.utc_text(when),
        run_clock_basis="legacy_utc_second_storage",
    )
    usage_id, expected_usage = grants._audit(db, stored.authorized.actor, "rca_run.usage", run.run_id, receipt.model_dump(mode="json"), when)
    artifact.usage_event_id = usage_id
    expected_run = {key: getattr(run, key) for key in storage.RUN_COLUMNS}
    expected_artifact = {key: getattr(artifact, key) for key in storage.ART_COLUMNS}
    expected_result = {key: getattr(row, key) for key in RESULT_COLUMNS}
    db.flush()
    verified = storage.load_task(db, user, run.run_id, exclusive=True)
    if _read_stored_result(db, verified) != result:
        raise HTTPException(409, "完整结果未能由原完整Source与固定解释重算")
    actual_run = current_rows(db.query(*(getattr(AIRun, key) for key in storage.RUN_COLUMNS)).filter_by(run_id=run.run_id)).one()
    actual_artifact = current_rows(db.query(*(getattr(AIRcaEvidenceRunArtifact, key) for key in storage.ART_COLUMNS)).filter_by(run_id=run.run_id)).one()
    actual_result = current_rows(db.query(*(getattr(AIRcaEvidenceRunResult, key) for key in RESULT_COLUMNS)).filter_by(run_id=run.run_id)).one()
    if dict(actual_run._mapping) != expected_run or dict(actual_artifact._mapping) != expected_artifact or dict(actual_result._mapping) != expected_result:
        raise HTTPException(409, "实际Run25字段、完整Artifact或完整结果在原子写回后改变")
    grants._exact_audit(db, accept_id, expected_accept)
    grants._exact_audit(db, usage_id, expected_usage)
    return result
