"""Short Run/trace views. Large original, private Scope and result stay split."""

from fastapi.encoders import jsonable_encoder

from app.ai import document_change_storage as storage
from app.ai.document_change_view_contract import bounded_wire
from app.ai.models import AIFeedback

RUN_FIELDS = (
    "run_id",
    "feature_key",
    "status",
    "preview",
    "prompt_version",
    "provider_revision",
    "context_digest",
    "patient_id",
    "encounter_ref",
    "error_code",
    "error_message",
    "latency_ms",
    "create_time",
    "start_time",
    "finish_time",
)


def run_view(db, user, run, include_result=True, *, current=True):
    snapshot, metadata, evidence, binding, _, _ = storage.authorize_run(db, user, run, current=current)
    receipt = storage.usage_receipt(db, run)
    data = {key: getattr(run, key) for key in RUN_FIELDS}
    data.update(
        feature_name="双原文变更核对问题",
        requires_human_review=True,
        context_metadata=metadata,
        usage_receipt=receipt.model_dump(mode="json"),
        input_tokens=receipt.input_tokens,
        output_tokens=receipt.output_tokens,
        document_change_scope_id=binding.scope.scope_id,
        usage_receipt_status="pending" if run.latency_ms is None and run.status in {"queued", "running", "cancelled"} else "interrupted" if run.error_code == "WORKER_INTERRUPTED" else "recorded",
    )
    if include_result:
        if run.status == "succeeded":
            storage.expand_result(db, user, run, current=current)
        data.update(
            document_change_findings=snapshot["payload"]["context"],
            document_change_artifact=storage.artifact_record(db, user, run, current=current).model_dump(mode="json"),
            result=storage._json(run.result_json),
            evidence=evidence,
            split_artifacts=True,
        )
    data = jsonable_encoder(data)
    bounded_wire(data)
    return data


def trace_view(db, user, run):
    snapshot, _, _, _, _, _ = storage.authorize_run(db, user, run, current=False)
    feedback = db.query(AIFeedback).filter_by(run_id=run.run_id).order_by(AIFeedback.create_time.desc(), AIFeedback.feedback_id).limit(101).all()
    data = {
        **run_view(db, user, run, current=False),
        "requested_by": run.requested_by,
        "provider_id": run.provider_id,
        "frozen_request": snapshot,
        "frozen_request_json": run.input_json,
        "frozen_evidence_json": run.evidence_json,
        "frozen_context_metadata_json": run.context_metadata_json,
        "snapshot_complete": True,
        "feedback": [{key: getattr(item, key) for key in ("feedback_id", "reviewer_id", "outcome", "comment", "create_time")} for item in feedback[:100]],
        "feedback_truncated": len(feedback) > 100,
    }
    data = jsonable_encoder(data)
    bounded_wire(data)
    return data
