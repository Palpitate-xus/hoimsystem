"""Complete TEXT task proofs and immutable actual-SQL extraction anchors."""

import hashlib
import json

from fastapi import HTTPException

from app.ai import document_evidence_contract as c
from app.ai import document_evidence_sources as sources
from app.ai.context import ContextBundle, context_metadata
from app.ai.document_extraction_context import DocumentExtractionContext, public_payload, verify_context
from app.ai.document_extraction_contract import EXTRACTION_SYSTEM_PROMPT, require_text_capacity
from app.ai.document_extraction_models import ANCHOR_HASH_FIELDS, ANCHOR_SCHEMA, AIDocumentExtractionRunAnchor
from app.ai.document_extraction_prompt import instructions_digest
from app.ai.document_extraction_result import validate_result
from app.ai.document_extraction_run_record import parse_record, record_marker
from app.ai.document_extraction_view_contract import DocumentFrozenProvider, DocumentFrozenValidation
from app.ai.governance import digest

FEATURE_KEY = "guideline_ingestion"


def text_hash(value):
    if type(value) is not str or len(c.utf8(value)) > 65535:
        raise ValueError("Complete persisted task text must fit UTF8 TEXT")
    return hashlib.sha256(c.utf8(value)).hexdigest()


def _json(value):
    text_hash(value)
    parsed = c.parse_json(value)
    if c.canonical_json(parsed) != value:
        raise ValueError("Task JSON must preserve its complete canonical object")
    return parsed


def _has_markers(snapshot):
    if not isinstance(snapshot, dict):
        return False
    payload = snapshot.get("payload")
    if not isinstance(payload, dict):
        return False
    context, values = payload.get("context"), payload.get("input")
    return isinstance(context, dict) and bool({"document_binding", "document_source", "document_review"} & context.keys()) or isinstance(values, dict) and "document_original_id" in values


def is_extraction_run(db, run):
    if run.feature_key == FEATURE_KEY:
        return True
    if isinstance(run.input_json, str) and _has_markers(json.loads(run.input_json)):
        return True
    if isinstance(run.result_json, str):
        result = json.loads(run.result_json)
        if isinstance(result, dict) and ("document_extraction" in result or record_marker(result)):
            return True
    if db is None or not run.run_id:
        return False
    # A current Run read can coexist with an older RR snapshot. The durable
    # FK hint must therefore also be a current read, even with no JSON markers.
    with db.no_autoflush:
        return db.query(AIDocumentExtractionRunAnchor.run_id).filter_by(run_id=run.run_id).with_for_update(read=True).first() is not None


def _task(run):
    snapshot, evidence, metadata = _json(run.input_json), _json(run.evidence_json), _json(run.context_metadata_json)
    if not isinstance(snapshot, dict) or set(snapshot) != {"catalog_version", "system_prompt", "task_prompt", "payload", "provider_snapshot", "feature_validation"}:
        raise ValueError("The complete closed extraction task is required")
    if run.feature_key != FEATURE_KEY or run.patient_id is not None or run.encounter_ref is not None:
        raise ValueError("Extraction cannot change feature or acquire a patient/encounter scope")
    if type(run.requested_by) is not int or run.requested_by < 1:
        raise ValueError("An actual author is required")
    if snapshot["system_prompt"] != EXTRACTION_SYSTEM_PROMPT or type(snapshot["task_prompt"]) is not str or not snapshot["task_prompt"].strip() or type(snapshot["catalog_version"]) is not str:
        raise ValueError("The complete fixed system and task Prompt must be retained")
    payload = snapshot["payload"]
    public_payload(payload)
    context = DocumentExtractionContext.model_validate(payload["context"])
    provider = DocumentFrozenProvider.model_validate(snapshot["provider_snapshot"])
    validation = DocumentFrozenValidation.model_validate(snapshot["feature_validation"])
    if c.canonical_json(provider) != c.canonical_json(snapshot["provider_snapshot"]) or c.canonical_json(validation) != c.canonical_json(snapshot["feature_validation"]):
        raise ValueError("Frozen provider/validation scalar types must remain exact")
    if run.provider_id != provider.provider_id or run.provider_revision != provider.revision or type(run.prompt_version) is not int or run.prompt_version < 0:
        raise ValueError("The Run and frozen provider/Prompt identities differ")
    if payload["evidence"] != evidence or digest(payload["context"]) != run.context_digest or digest([EXTRACTION_SYSTEM_PROMPT, snapshot["task_prompt"]]) != run.prompt_hash:
        raise ValueError("The complete evidence, context or Prompt digest differs")
    expected = {
        **context_metadata(ContextBundle(data=context.model_dump(mode="json"), evidence=evidence)),
        "feature_revision": validation.feature_revision,
        "validation_status": validation.status,
        "tool_fingerprint": digest({}),
        "instructions_digest": instructions_digest(snapshot["task_prompt"]),
        "model_version": provider.model,
    }
    if not isinstance(metadata, dict) or c.canonical_json(metadata) != c.canonical_json(expected):
        raise ValueError("The complete original task metadata differs")
    require_text_capacity(snapshot)
    return snapshot, context, metadata


def _anchor_values(run, context):
    return {
        "original_content_hash": context.document_binding.original.content_hash,
        "original_governance_hash": context.document_binding.original.governance_hash,
        "source_digest": context.document_binding.source_digest,
        "prompt_hash": run.prompt_hash,
        "context_digest": run.context_digest,
        "input_hash": text_hash(run.input_json),
        "evidence_hash": text_hash(run.evidence_json),
        "metadata_hash": text_hash(run.context_metadata_json),
    }


def stage_anchor(db, run):
    snapshot, context, _ = _task(run)
    recorded_at = sources.utcnow()
    if recorded_at < c.clock(context.snapshot_time):
        raise HTTPException(409, "服务器时钟早于本次原件核对，任务未入队")
    anchor = AIDocumentExtractionRunAnchor(
        run_id=run.run_id,
        original_id=context.document_binding.original.original_id,
        requested_by=run.requested_by,
        schema_version=ANCHOR_SCHEMA,
        recorded_at=recorded_at,
        **_anchor_values(run, context),
    )
    db.add(anchor)
    db.flush()
    from app.ai.native_task_routing import remember_staged_identity

    remember_staged_identity(db, anchor)
    load_snapshot(db, run)
    return snapshot


def load_snapshot(db, run):
    try:
        snapshot, context, metadata = _task(run)
        if db is None:
            raise ValueError("A real retained SQL anchor is required")
        anchor = db.query(AIDocumentExtractionRunAnchor).filter_by(run_id=run.run_id).populate_existing().with_for_update(read=True).one_or_none()
        if anchor is None or anchor.schema_version != ANCHOR_SCHEMA or anchor.original_id != context.document_binding.original.original_id or anchor.requested_by != run.requested_by:
            raise ValueError("The durable extraction/author/original identity is unavailable")
        expected = _anchor_values(run, context)
        if any(getattr(anchor, field) != expected[field] for field in ANCHOR_HASH_FIELDS) or anchor.recorded_at < c.clock(context.snapshot_time):
            raise ValueError("The actual retained complete task anchors differ")
        return snapshot, context, metadata
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "完整抽取任务、原件、模型或Prompt锚点无效，未降级展示") from exc


def authorize_document_run(db, user, run, *, current=False):
    actor = sources.current_super(db, user)
    snapshot, context, metadata = load_snapshot(db, run)
    verify_context(db, actor, context.model_dump(mode="json"), current=current)
    return snapshot, context, metadata


def load_result(db, run):
    snapshot, context, metadata = load_snapshot(db, run)
    try:
        value = c.parse_json(run.result_json)
        if record_marker(value):
            record = parse_record(run.result_json)
            if run.status not in {"succeeded", "failed", "cancelled"} or (record.result is not None) != (run.status == "succeeded"):
                raise ValueError("The complete record and actual terminal state differ")
            value = record.result.model_dump(mode="json") if record.result is not None else None
        elif run.status == "succeeded":
            # Literal-storage compatibility only. Runtime/API/save callers also
            # require the actual receipt reference through usage_receipt.
            value = run.result_json
        elif run.result_json == "{}":
            value = None
        else:
            raise ValueError("An unsuccessful task cannot carry an accepted draft")
        return validate_result(value, context.document_source, metadata["instructions_digest"]).model_dump(mode="json") if value is not None else None
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "已存结果与完整原文或Prompt不一致，未展示草稿") from exc
