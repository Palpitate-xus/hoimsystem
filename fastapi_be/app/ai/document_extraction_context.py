"""Super-authorized complete originals and private frozen review proofs."""

from typing import Literal

from fastapi import HTTPException

from app.ai import document_evidence_contract as c
from app.ai import document_evidence_sources as sources
from app.ai.context import ContextBundle
from app.ai.document_extraction_contract import (
    INCOMPLETE_COVERAGE_NOTE,
    DocumentExtractionRequest,
    DocumentExtractionSource,
    build_extraction_source,
)


class DocumentExtractionBinding(c.StrictModel):
    schema_version: Literal["document_extraction_binding_v1"]
    feature_key: Literal["guideline_ingestion"]
    original: c.OriginalReference
    source_digest: c.SHA256


class DocumentExtractionContext(c.StrictModel):
    scope: Literal["document_extraction"]
    document_binding: DocumentExtractionBinding
    document_source: DocumentExtractionSource
    document_review: c.GovernedReview
    missing_data: list[str]


def selection(values):
    try:
        return DocumentExtractionRequest.model_validate(values)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "指南抽取仅接受明确原文ID和可选问题，请先核对当前已发布原件") from exc


def _context(source, review):
    return DocumentExtractionContext(
        scope="document_extraction",
        document_binding=DocumentExtractionBinding(schema_version="document_extraction_binding_v1", feature_key="guideline_ingestion", original=source.original, source_digest=c.digest(source)),
        document_source=source,
        document_review=review,
        missing_data=[INCOMPLETE_COVERAGE_NOTE],
    )


def _source_evidence(context):
    bound = context.document_binding
    return {
        "source_id": f"document_original:{bound.original.original_id}:{bound.original.content_hash[:12]}",
        "kind": "document_original",
        "original_id": bound.original.original_id,
        "content_hash": bound.original.content_hash,
        "governance_hash": bound.original.governance_hash,
        "source_digest": bound.source_digest,
        "raw_bytes_hash": context.document_source.raw_bytes_hash,
    }


def extraction_context(db, user, task_input):
    request = selection(task_input)
    original = sources.original_detail(db, user, request.document_original_id)
    try:
        context = _context(build_extraction_source(original), original.governance)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "原文未完成当前审核或完整原件超过抽取任务容量，未裁剪原文") from exc
    return ContextBundle(data=context.model_dump(mode="json"), evidence=[_source_evidence(context)])


def verify_context(db, user, value, *, current=True):
    """Audit old published review fields without treating a revoked row as current."""
    try:
        context = DocumentExtractionContext.model_validate(value)
        record = sources.original_detail(db, user, context.document_binding.original.original_id)
        if current:
            source = build_extraction_source(record)
            review = record.governance
        else:
            # Publication is a single transition, and revocation retains the
            # original review signature. Reconstruct only that historical
            # signature from actual stored fields, never a new publication.
            review_data = record.governance.model_dump(mode="json")
            review_data.update(status="published", revision=2, revoked_by=None, revoked_at=None, revoke_reason="")
            review = c.GovernedReview.model_validate(review_data)
            source = DocumentExtractionSource(
                schema_version="document_extraction_source_v1",
                original=c.OriginalReference(original_id=record.snapshot.original_id, content_hash=record.content_hash, governance_hash=c.digest(review)),
                raw_bytes_hash=record.snapshot.raw_bytes_hash,
                raw_bytes_length=record.snapshot.raw_bytes_length,
                codepoint_length=record.snapshot.codepoint_length,
                text=record.snapshot.text,
            )
        expected = _context(source, review)
        if context != expected:
            raise ValueError("The exact original, review signature or source closure differs")
        return expected
    except (ValueError, TypeError, UnicodeError, KeyError) as exc:
        raise HTTPException(409, "冻结原文、审核签署或完整区间资料已失效，请重新核对") from exc


def public_payload(payload):
    """Original authorization/review notes and operator identities stay local."""
    if not isinstance(payload, dict) or set(payload) != {"input", "context", "tools", "evidence"}:
        raise ValueError("The complete extraction envelope is required")
    request = selection(payload["input"])
    context = DocumentExtractionContext.model_validate(payload["context"])
    if context.document_binding.original.original_id != request.document_original_id or context.document_binding.source_digest != c.digest(context.document_source):
        raise ValueError("The selected original and exact outbound source differ")
    if context != _context(context.document_source, context.document_review):
        raise ValueError("The frozen context is not the closed extraction proof")
    if context.document_review.status != "published" or c.digest(context.document_review) != context.document_source.original.governance_hash:
        raise ValueError("The original published review is unavailable")
    if payload["tools"] != {} or payload["evidence"] != [_source_evidence(context)]:
        raise ValueError("Extraction cannot incorporate unrelated tools or evidence")
    return {"document_source": context.document_source.model_dump(mode="json"), "question": request.question}
