"""Pure quote-span draft protocol; callers submit an ID, never source text.

The application must resolve that ID using its current original authorization
before ``build_extraction_source`` and recheck it before accepting a result.
This module performs no model calls, persistence or clinical interpretation.
"""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.ai.document_evidence_contract import (
    MAX_KNOWLEDGE_BYTES,
    SHA256,
    UUID,
    CandidateCreate,
    OriginalRecord,
    OriginalReference,
    StrictModel,
    bytes_hash,
    canonical_json,
    digest,
    meaningful,
    parse_json,
    utf8,
)
from app.ai.document_extraction_prompt_constants import EXTRACTION_SYSTEM_PROMPT as EXTRACTION_SYSTEM_PROMPT
from app.ai.document_extraction_prompt_constants import EXTRACTION_TASK_PROMPT as EXTRACTION_TASK_PROMPT

MAX_EXTRACTION_SPANS = 64
MAX_EXTRACTION_TEXT_BYTES = 65535
MAX_QUESTION_BYTES = 8000
INCOMPLETE_COVERAGE_NOTE = "未核实模型草稿；空集合不表示全文没有条款，任何结果均不证明完整覆盖、临床含义或适用性正确。"


class DocumentExtractionRequest(StrictModel):
    document_original_id: UUID
    question: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def explicit_question(self):
        if self.question is not None:
            meaningful(self.question, minimum=1, maximum=MAX_QUESTION_BYTES)
        return self


class DocumentExtractionSource(StrictModel):
    """Server-built source; deliberately not a request-body input model."""

    schema_version: Literal["document_extraction_source_v1"]
    original: OriginalReference
    raw_bytes_hash: SHA256
    raw_bytes_length: int = Field(strict=True, ge=1, le=MAX_EXTRACTION_TEXT_BYTES)
    codepoint_length: int = Field(strict=True, ge=1, le=MAX_EXTRACTION_TEXT_BYTES)
    text: str = Field(min_length=1, max_length=MAX_EXTRACTION_TEXT_BYTES)

    @model_validator(mode="after")
    def exact_original_bytes(self):
        if self.raw_bytes_length != len(utf8(self.text)) or self.codepoint_length != len(self.text) or self.raw_bytes_hash != bytes_hash(self.text):
            raise ValueError("Exact complete original bytes and codepoint counts are required")
        require_text_capacity(self)
        return self


class DocumentSpanDraft(StrictModel):
    proposed_heading: str = Field(min_length=1, max_length=200)
    clause_kind: Literal["recommendation", "definition", "applicability", "warning", "other"]
    start: int = Field(strict=True, ge=0, le=MAX_EXTRACTION_TEXT_BYTES)
    end: int = Field(strict=True, ge=1, le=MAX_EXTRACTION_TEXT_BYTES)
    quote: str = Field(min_length=1, max_length=MAX_KNOWLEDGE_BYTES)

    @model_validator(mode="after")
    def complete_span(self):
        meaningful(self.proposed_heading, minimum=1, maximum=800)
        if self.start >= self.end or len(self.quote) != self.end - self.start or len(utf8(self.quote)) > MAX_KNOWLEDGE_BYTES:
            raise ValueError("A complete nonempty bounded codepoint span is required")
        return self


class DocumentExtractionReply(StrictModel):
    spans: list[DocumentSpanDraft] = Field(max_length=MAX_EXTRACTION_SPANS)

    @model_validator(mode="after")
    def whole_reply(self):
        require_text_capacity(self)
        identities = [(v.start, v.end, v.quote, v.proposed_heading, v.clause_kind) for v in self.spans]
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate model draft items must not be silently repeated")
        return self


class DocumentExtractionDraft(StrictModel):
    schema_version: Literal["document_extraction_draft_v1"]
    original: OriginalReference
    raw_bytes_hash: SHA256
    source_digest: SHA256
    instructions_digest: SHA256
    spans: list[DocumentSpanDraft] = Field(max_length=MAX_EXTRACTION_SPANS)
    provenance: Literal["unverified_model_draft"]
    automatic_candidate_creation: Literal[False]
    automatic_knowledge_publication: Literal[False]
    coverage_note: Literal["未核实模型草稿；空集合不表示全文没有条款，任何结果均不证明完整覆盖、临床含义或适用性正确。"]

    @field_validator("automatic_candidate_creation", "automatic_knowledge_publication", mode="before")
    @classmethod
    def actual_false(cls, value):
        if type(value) is not bool or value:
            raise ValueError("Automatic-action flags must be actual false booleans")
        return value

    @model_validator(mode="after")
    def bounded_draft(self):
        DocumentExtractionReply(spans=self.spans)
        require_text_capacity(self)
        return self


def require_text_capacity(value) -> None:
    """Whole JSON must fit existing AIRun UTF8 TEXT; never truncate a field.

    Integration must ALSO call this on its final complete frozen input/result;
    passing for one nested source is not proof that the enclosing run fits.
    """
    if len(utf8(canonical_json(value))) > MAX_EXTRACTION_TEXT_BYTES:
        raise ValueError("Complete extraction task JSON exceeds existing 65535-byte TEXT capacity")


def build_extraction_source(original: OriginalRecord) -> DocumentExtractionSource:
    # Revalidate even a mutated model instance; only current governed rows from
    # the application's authorized original lookup may reach this function.
    checked = OriginalRecord.model_validate(original.model_dump(mode="json"))
    if not checked.eligible or checked.governance.status != "published" or checked.governance.privacy_review != "confirmed" or checked.governance.faithfulness_review != "confirmed":
        raise ValueError("Only the current explicitly privacy/fidelity-reviewed published original is eligible")
    return DocumentExtractionSource(
        schema_version="document_extraction_source_v1",
        original=OriginalReference(original_id=checked.snapshot.original_id, content_hash=checked.content_hash, governance_hash=checked.governance_hash),
        raw_bytes_hash=checked.snapshot.raw_bytes_hash,
        raw_bytes_length=checked.snapshot.raw_bytes_length,
        codepoint_length=checked.snapshot.codepoint_length,
        text=checked.snapshot.text,
    )


def validate_spans(reply: DocumentExtractionReply, source: DocumentExtractionSource) -> None:
    for span in reply.spans:
        if span.end > source.codepoint_length or source.text[span.start : span.end] != span.quote:
            raise ValueError("Every complete quote must exactly equal its original codepoint interval")


def parse_extraction_reply(value: str | dict, source: DocumentExtractionSource, instructions_digest: str) -> DocumentExtractionDraft:
    source = DocumentExtractionSource.model_validate(source.model_dump(mode="json"))
    if isinstance(value, str):
        if len(value) > MAX_EXTRACTION_TEXT_BYTES or len(utf8(value)) > MAX_EXTRACTION_TEXT_BYTES:
            raise ValueError("Complete model reply exceeds existing TEXT capacity")
        value = parse_json(value)
    else:
        require_text_capacity(value)
    reply = DocumentExtractionReply.model_validate(value)
    validate_spans(reply, source)
    return DocumentExtractionDraft(
        schema_version="document_extraction_draft_v1",
        original=source.original,
        raw_bytes_hash=source.raw_bytes_hash,
        source_digest=digest(source),
        instructions_digest=instructions_digest,
        spans=reply.spans,
        provenance="unverified_model_draft",
        automatic_candidate_creation=False,
        automatic_knowledge_publication=False,
        coverage_note=INCOMPLETE_COVERAGE_NOTE,
    )


def validate_extraction_binding(draft: DocumentExtractionDraft, source: DocumentExtractionSource, instructions_digest: str) -> DocumentExtractionDraft:
    checked = DocumentExtractionDraft.model_validate(draft.model_dump(mode="json"))
    expected = parse_extraction_reply({"spans": [v.model_dump(mode="json") for v in checked.spans]}, source, instructions_digest)
    if checked != expected:
        raise ValueError("Complete draft must match the frozen original and exact Prompt digest")
    return checked


def candidate_from_draft(draft: DocumentExtractionDraft, source: DocumentExtractionSource, instructions_digest: str, ordinal: int) -> CandidateCreate:
    """Explicit zero-based choice only; returns data and never persists it."""
    checked = validate_extraction_binding(draft, source, instructions_digest)
    if type(ordinal) is not int or not 0 <= ordinal < len(checked.spans):
        raise ValueError("An explicit valid zero-based draft ordinal is required")
    span = checked.spans[ordinal]
    return CandidateCreate(original=source.original, **span.model_dump(mode="json"), provenance="unverified_submission")
