"""Current complete training parts and separate bodyless Super metadata."""

import json

from fastapi import HTTPException

from app.ai import clinical_training_attempts as attempts
from app.ai import clinical_training_contract as c
from app.ai import clinical_training_receipts as receipts
from app.ai import clinical_training_registry as registry
from app.ai import clinical_training_result_storage as results
from app.ai import clinical_training_shared as shared
from app.ai import clinical_training_storage as storage
from app.ai.clinical_training_task_view_contract import TrainingBindingPart, TrainingTaskMetadata, TrainingTaskPart, TrainingViewBinding
from app.ai.clinical_training_write_guard import lock_training_write
from app.ai.native_task_routing import locate_native_task

PARTS = ("task", "source", "binding", "result")


def generic_audit_detail(action, raw):
    """Generic Super audit carries no learner selections or hash oracle.

    Full immutable originals stay in SQL. The current owner's native parts
    separately prove current Source before returning their exact receipts.
    """
    if action == "training_practice_submit" or action.startswith("training.task."):
        return dict(schema_version="clinical_training_technical_audit_v1", detail_scope="technical_event_only", current_owner_source_read_required=True)
    return json.loads(raw)


def _view(model, **value):
    try:
        return model(**value)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "培训实际任务视图不能组成完整闭集，未补造状态或裁剪资料") from exc


def _binding(header):
    return _view(TrainingViewBinding, clinical_training_submission_id=header["submission_id"], **{key: header[key] for key in ("objective", "source_projection_hash", "source_binding_hash", "prompt_snapshot_hash", "execution_snapshot_hash", "instructions_digest")})


def _metadata(header, *, attempt=None, binding=None, state="requires_current_read", receipt=None):
    begin = registry.references.utc_text(header["start_time"]) if header["start_time"] is not None else None
    if attempt is not None and attempt.claim is not None:
        begin = attempt.claim.claimed_at
    finish = registry.references.utc_text(header["finish_time"]) if header["finish_time"] is not None else None
    if receipt is not None:
        finish = receipt.recorded_at
    return _view(
        TrainingTaskMetadata,
        schema_version="clinical_training_task_metadata_view_v1",
        run_id=header["run_id"],
        feature_key="clinical_training",
        status=header["status"],
        requested_by=header["requested_by"],
        preview=bool(header["preview"]),
        create_time=registry.references.utc_text(attempt.artifact["recorded_at"] if attempt is not None else header["create_time"]),
        start_time=begin,
        finish_time=finish,
        finish_clock_basis="actual_usage_receipt_utc6" if receipt is not None else "legacy_run_seconds" if finish is not None else "not_finished",
        split_artifacts=True,
        input_mode="clinical_training_evidence",
        parts_wire="canonical_json_body_no_envelope",
        parts_state=state,
        binding=binding,
        usage=receipt.usage if receipt is not None else None,
        usage_event_id=attempt.artifact["usage_event_id"] if receipt is not None else None,
        receipt_pending=attempt is not None and attempt.dispatch is not None and attempt.artifact["usage_event_id"] is None,
        error_code=header["error_code"],
        error_message=header["error_message"],
    )


def technical_metadata(db, user, identifier, *, state="requires_current_read"):
    """Current Super only, no Source/Task/Result BODY and no binding hashes."""
    lock_training_write(db, user, governance=True)
    identity = locate_native_task(db, identifier)
    if identity is None:
        if not shared.is_training_task(db, identifier):
            raise HTTPException(404, "培训任务不存在")
        header = storage.run_header(db, identifier)
        return _metadata(header, state="incomplete_native_artifact")
    if identity.domain != "clinical_training":
        raise HTTPException(409, "原生任务域不属于培训资料")
    try:
        actual = attempts.technical_header(db, identifier, exclusive=False)
        receipt = receipts.read_receipt(db, actual)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        # Corrupt anchors remain inspectable as opaque technical status. The
        # directory never tries private parts to repair or guess their data.
        return _metadata(storage.run_header(db, identifier), state="incomplete_native_artifact")
    return _metadata(actual.header, attempt=actual, state=state, receipt=receipt)


def describe_task(db, user, identifier):
    try:
        shared.guard_training_task(db, user, identifier)
        actual = attempts.technical_header(db, identifier, exclusive=False)
        receipt = receipts.read_receipt(db, actual)
        return _metadata(actual.header, attempt=actual, binding=_binding(actual.artifact), state="available", receipt=receipt)
    except HTTPException as exc:
        if exc.status_code not in {403, 404, 409}:
            raise
        # The independently current Super check inside this path is required;
        # ordinary users cannot use the technical exception after Source loss.
        return technical_metadata(db, user, identifier, state="current_parts_unavailable")


def read_part(db, user, identifier, part):
    if part not in PARTS:
        raise HTTPException(404, "培训独立完整part不存在")
    run, artifact, source, prompt, execution, selection = shared.guard_training_task(db, user, identifier)
    if part == "source":
        return source
    if part == "result":
        actual = attempts.technical_header(db, identifier, exclusive=False)
        receipt = receipts.read_receipt(db, actual)
        header = actual.header
        if header["status"] == "succeeded":
            return results.load_result(db, user, identifier)
        if header["status"] not in {"queued", "running", "failed", "cancelled"}:
            raise HTTPException(409, "培训任务状态不能构成明确的未接受结果")
        receipts._no_accepted_result(db, identifier)
        if header["status"] == "queued":
            original = storage._verify_created(db, actual.artifact, header)["original_run_header"]
            if actual.claim is not None or receipt is not None or any(value != original[key] for key, value in storage.encoded_header(header).items()):
                raise HTTPException(409, "排队培训任务与原实际创建状态不一致")
        elif header["status"] == "running":
            if actual.claim is None or receipt is not None or any(header[key] is not None for key in ("finish_time", "latency_ms", "error_code", "error_message")) or header["input_tokens"] != 0 or header["output_tokens"] != 0:
                raise HTTPException(409, "在途培训任务的原claim或未结束状态损坏")
        elif receipt is None:
            # Actual in-flight cancellation can await its original delivery's
            # paid receipt. Null is no accepted draft, never a zero-use claim.
            if header["status"] != "cancelled" or actual.dispatch is None or header["error_code"] != "TASK_CANCELLED" or header["finish_time"] is None or header["latency_ms"] is not None or header["input_tokens"] != 0 or header["output_tokens"] != 0:
                raise HTTPException(409, "培训终态缺少实际用量回执或原在途取消阶段")
        return None
    header = attempts.phase_header(db, identifier)
    binding = _binding(header)
    if part == "task":
        return _view(
            TrainingTaskPart,
            schema_version="clinical_training_task_part_v1",
            run_id=identifier,
            binding=binding,
            prompt_snapshot_json=artifact.prompt_snapshot_json,
            execution_snapshot_json=artifact.execution_snapshot_json,
            raw={key: getattr(run, key) for key in storage.RAW_FIELDS},
        )
    actual = attempts.technical_header(db, identifier, exclusive=False)
    receipt = receipts.read_receipt(db, actual)
    return _view(
        TrainingBindingPart,
        schema_version="clinical_training_binding_part_v1",
        run_id=identifier,
        binding=binding,
        requested_by=artifact.requested_by,
        recorded_at=registry.references.utc_text(artifact.recorded_at),
        source_bytes=artifact.source_bytes,
        provider_id=artifact.provider_id,
        provider_revision=artifact.provider_revision,
        config_revision=artifact.config_revision,
        prompt_id=artifact.prompt_id,
        prompt_version=artifact.prompt_version,
        **{key: actual.artifact[key] for key in ("created_audit_event_id", "claim_event_id", "dispatch_event_id", "usage_event_id")},
        lease_token=actual.claim.lease_token if actual.claim is not None else None,
        claimed_at=actual.claim.claimed_at if actual.claim is not None else None,
        dispatched_at=actual.dispatch.dispatched_at if actual.dispatch is not None else None,
        usage_receipt_json=c.canonical_json(receipt) if receipt is not None else None,
    )


def split_trace(db, user, identifier):
    # A current Super can inspect another learner's technical state, but no
    # source/feedback/binding fingerprint is returned without own-source access.
    metadata = describe_task(db, user, identifier)
    return {
        "schema_version": "clinical_training_split_trace_v1",
        "run": metadata.model_dump(mode="json"),
        "parts_require_independent_current_reads": True,
        "parts_wire": "canonical_json_body_no_envelope",
        "parts": {part: f"/api/ai/clinical-training/tasks/{identifier}/parts/{part}" for part in PARTS} if metadata.parts_state == "available" else {},
    }
