"""Current-authorized short RCA task headers and independently bounded pieces."""

import functools

from fastapi import HTTPException

from app.ai import rca_evidence_cases as cases
from app.ai import rca_evidence_configuration as configuration
from app.ai import rca_evidence_context as context
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_receipts as receipts
from app.ai import rca_evidence_result_storage as results
from app.ai import rca_evidence_sources as originals
from app.ai import rca_evidence_storage as storage
from app.ai import rca_evidence_storage_contract as s
from app.ai import rca_evidence_task_wire_contract as v
from app.ai.models import AIAuditEvent
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunResult
from app.ai.rca_evidence_task_views import RcaResultReference
from app.ai.rca_evidence_write_guard import current_rows


def response(value):
    try:
        return cases.wire(value)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "完整RCA分件响应超过8MiB或不能逐字核对，未截断返回") from exc


def checked_view(function):
    @functools.wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise HTTPException(409, "完整RCA任务视图、原字节或分件锚无法核对，未降级或裁剪") from exc

    return checked


@checked_view
def preview(db, user, request):
    values = request.model_dump(mode="json")
    preview_flag = values.pop("preview")
    prepared = context.prepare_context(db, user, values)
    current = configuration.for_context(db, user, prepared, preview_flag)
    snapshot = configuration.snapshot_for_context(prepared, current)
    root = f"/api/ai/admin/rca-evidence/cases/{prepared.binding.case_id}"
    return v.RcaPreview(
        context=prepared.data,
        metadata=s.metadata_for_snapshot(snapshot),
        evidence=prepared.evidence,
        model_preview="no_model_call",
        source_url=root + "/public-source",
        case_url=root,
        automatic_legacy_write=False,
    )


def _artifact_record(stored):
    return v.RcaArtifactRecord.model_validate({key: storage._clock_value(getattr(stored.artifact, key)) for key in v.RcaArtifactRecord.model_fields})


def _checked_parts(db, stored):
    attempt = receipts.technical_header(db, stored.run.run_id)
    actual = receipts.read_receipt(db, attempt)
    # Both successful and non-success states have a complete pointer/blob
    # consistency check; ordinary receipts never revive content authority.
    results._read_stored_result(db, stored)
    reference = RcaResultReference.model_validate(storage.canonical_value(stored.run.result_json)) if stored.run.status == "succeeded" else None
    return actual, reference


@checked_view
def run_view(db, user, identifier, include_result=True, *, frozen_audit=False):
    stored = storage.load_task(db, user, identifier, frozen_audit=frozen_audit)
    run = stored.run
    actual, reference = _checked_parts(db, stored)
    value = {
        key: getattr(run, key)
        for key in ("run_id", "feature_key", "status", "preview", "prompt_version", "provider_revision", "context_digest", "patient_id", "encounter_ref", "error_code", "error_message", "latency_ms")
    }
    value.update({key: i.utc_text(getattr(run, key)) if getattr(run, key) is not None else None for key in ("create_time", "start_time", "finish_time")})
    usage = actual.usage if actual is not None else None
    value.update(
        feature_name="事件受审资料的未核实RCA假设",
        requires_human_review=True,
        run_clock_basis="legacy_utc_second_storage",
        context_metadata=stored.metadata,
        rca_evidence_case_id=stored.binding.case_id,
        usage_receipt=usage,
        input_tokens=usage.input_tokens if usage is not None else None,
        output_tokens=usage.output_tokens if usage is not None else None,
        usage_receipt_status="recorded" if actual is not None else "pending",
    )
    if not include_result:
        return v.RcaRunSummary.model_validate(value)
    value.update(
        result=None,
        result_reference=reference,
        evidence=stored.snapshot.payload.evidence,
        rca_evidence_artifact=_artifact_record(stored),
        rca_evidence_findings={
            "context": stored.snapshot.payload.context,
            "input": stored.snapshot.payload.input,
            "rca_evidence_binding": stored.binding,
            "frozen_task_view": True,
            "automatic_legacy_write": False,
        },
        parts=v.piece_locations(run.run_id, frozen_audit),
    )
    return v.RcaRunDetail.model_validate(value)


@checked_view
def trace_view(db, user, identifier):
    stored = storage.load_task(db, user, identifier, frozen_audit=True)
    value = run_view(db, user, identifier, frozen_audit=True).model_dump(mode="json")
    row = current_rows(db.query(AIRcaEvidenceRunResult.accept_audit_event_id).filter_by(run_id=identifier), shared=True).one_or_none()
    ids = {
        "create": stored.artifact.create_event_id,
        "claim": stored.artifact.claim_event_id,
        "dispatch": stored.artifact.dispatch_event_id,
        "usage": stored.artifact.usage_event_id,
        "accept": row[0] if row else None,
    }
    audits = {}
    for phase, pk in ids.items():
        audit = current_rows(db.query(AIAuditEvent).filter_by(event_id=pk), shared=True).one_or_none() if pk is not None else None
        if pk is not None and audit is None:
            raise HTTPException(409, "原任务具体阶段审计PK缺失，未返回不完整证明")
        audits[phase] = {key: i.utc_text(getattr(audit, key)) if key == "create_time" else getattr(audit, key) for key in v.RcaAuditRecord.model_fields} if audit is not None else None
    _auth, current_case = cases._load(db, user, stored.binding.case_id)
    current_governance = originals._governance(current_case)
    value.update(
        current_case_governance=current_governance,
        current_case_governance_hash=c.digest({"case_id": stored.binding.case_id, "content_hash": stored.binding.case_content_hash, "governance": current_governance}),
        current_source_execution_qualification="not_evaluated_or_regranted_by_frozen_audit",
        requested_by=stored.artifact.requested_by,
        provider_id=stored.run.provider_id,
        snapshot_complete=True,
        frozen_request=stored.snapshot,
        raw_frozen_json={key: getattr(stored.run, key) for key in v.RcaRawFrozenJson.model_fields},
        phase_audits=audits,
    )
    return v.RcaRunTrace.model_validate(value)


@checked_view
def receipt_piece(db, user, identifier, *, frozen_audit=False):
    storage.load_task(db, user, identifier, frozen_audit=frozen_audit)
    return response(receipts.read_receipt(db, receipts.technical_header(db, identifier)))


@checked_view
def source_piece(db, user, identifier, *, frozen_audit=False):
    return response(storage.load_task(db, user, identifier, frozen_audit=frozen_audit).source)


@checked_view
def case_piece(db, user, identifier, *, frozen_audit=False):
    return response(storage.load_task(db, user, identifier, frozen_audit=frozen_audit).frozen_case)


@checked_view
def result_piece(db, user, identifier, *, frozen_audit=False):
    return response(results.read_result(db, user, identifier, frozen_audit=frozen_audit))
