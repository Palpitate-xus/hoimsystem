"""Literal provenance checks for unreviewed coding drafts, never a grouper."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OUTPUT_BYTES = 8 * 1024 * 1024
MAX_BINDINGS = 4096
MAX_DOCUMENTS = 16
SHA = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Token = Annotated[str, Field(min_length=1, max_length=160)]
Offset = Annotated[int, Field(strict=True, ge=0, le=OUTPUT_BYTES)]


def text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LiteralCitation(Closed):
    document_source_id: Token
    text_hash: SHA
    start: Offset
    end: Offset
    quote: str = Field(min_length=1, max_length=16384)

    @field_validator("quote")
    @classmethod
    def scalar_text(cls, value):
        value.encode("utf-8")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("A literal citation requires a nonempty half-open span")
        return self


class CodingClaim(Closed):
    binding_token: Token
    model_assessment: Literal["support_claim", "conflict_claim", "insufficient_evidence", "clarification_requested"]
    review_note: str = Field(min_length=1, max_length=4000)
    clarification_question: str | None = Field(max_length=4000)
    citations: list[LiteralCitation] = Field(max_length=16)

    @field_validator("review_note", "clarification_question")
    @classmethod
    def nonblank_scalar_text(cls, value):
        if value is not None:
            value.encode("utf-8")
            if not value.strip():
                raise ValueError("Review text cannot contain only whitespace")
        return value

    @model_validator(mode="after")
    def explicit_claims(self):
        if self.model_assessment in {"support_claim", "conflict_claim"} and not self.citations:
            raise ValueError("A support/conflict claim requires an original projected-text citation")
        if self.model_assessment == "clarification_requested" and self.clarification_question is None:
            raise ValueError("A clarification claim requires the actual question")
        return self


class CodingEvidenceDraft(Closed):
    schema_version: Literal["coding_evidence_draft_v1"]
    source_id: Token
    source_projection_hash: SHA
    claims: list[CodingClaim] = Field(max_length=MAX_BINDINGS)


def _closed_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON member")
        value[key] = item
    return value


def parse_draft(text: str) -> CodingEvidenceDraft:
    """Reject oversize/duplicate-key/non-scalar/fenced replies before accepting JSON."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > OUTPUT_BYTES:
        raise ValueError("The complete coding draft exceeds its UTF8 byte budget")

    def invalid_constant(_value):
        raise ValueError("Non-finite JSON number")

    data = json.loads(text, object_pairs_hook=_closed_json_object, parse_constant=invalid_constant)
    return CodingEvidenceDraft.model_validate(data)


def validate_draft(public_source: dict, draft: CodingEvidenceDraft, projection_hash: str) -> CodingEvidenceDraft:
    """Check known member closure and literal text only, never clinical semantics.

    The caller must first verify the complete C-owned public/private Case proof.
    This function does not authorize a patient or manufacture a Source projection.
    """
    if not isinstance(public_source, dict) or not isinstance(draft, CodingEvidenceDraft):
        raise ValueError("A verified case projection and typed draft are required")
    if draft.source_id != public_source.get("source_id") or draft.source_projection_hash != projection_hash:
        raise ValueError("The draft does not bind the selected complete case projection")
    rows, documents = public_source.get("code_bindings"), public_source.get("documents")
    if not isinstance(rows, list) or len(rows) > MAX_BINDINGS or not isinstance(documents, list) or len(documents) > MAX_DOCUMENTS:
        raise ValueError("Case members are unavailable or exceed declared limits")
    tokens = [row.get("binding_token") if isinstance(row, dict) else None for row in rows]
    if any(not isinstance(token, str) or not token for token in tokens) or len(tokens) != len(set(tokens)):
        raise ValueError("Case binding membership is ambiguous")
    claims = [row.binding_token for row in draft.claims]
    if len(claims) != len(set(claims)) or set(claims) != set(tokens):
        raise ValueError("The draft must retain every original binding exactly once")
    texts = {}
    for document in documents:
        if not isinstance(document, dict):
            raise ValueError("Invalid projected document")
        identifier, text, digest = (document.get(key) for key in ("source_id", "text", "text_hash"))
        if not isinstance(identifier, str) or not identifier or identifier in texts or not isinstance(text, str) or text_digest(text) != digest:
            raise ValueError("Projected document identity or exact UTF8 digest is invalid")
        texts[identifier] = (text, digest)
    for claim in draft.claims:
        seen = set()
        for citation in claim.citations:
            document = texts.get(citation.document_source_id)
            identity = (citation.document_source_id, citation.start, citation.end)
            if document is None or identity in seen:
                raise ValueError("Unknown or duplicate literal citation")
            text, digest = document
            if citation.text_hash != digest or citation.end > len(text) or text[citation.start : citation.end] != citation.quote:
                raise ValueError("Citation is not the exact projected Unicode codepoint span")
            seen.add(identity)
    return draft


def structural_counts(public_source: dict) -> dict:
    """Describe recorded structure without asserting diagnosis/coding correctness."""
    rows = public_source["code_bindings"]
    dictionary_states = {}
    kinds_unknown = primary_unknown = primary_diagnosis = 0
    for row in rows:
        state = row["current_dictionary_state"]
        if not isinstance(state, str) or not state:
            raise ValueError("A distinct current dictionary state is required")
        dictionary_states[state] = dictionary_states.get(state, 0) + 1
        kinds_unknown += row["kind"] not in {"diagnosis", "operation"}
        flag = row["is_primary"]
        valid_flag = type(flag) is int and flag in {0, 1}
        primary_unknown += not valid_flag
        primary_diagnosis += row["kind"] == "diagnosis" and valid_flag and flag == 1
    return {
        "binding_count": len(rows),
        "dictionary_state_counts": dict(sorted(dictionary_states.items())),
        "unknown_binding_kind_count": kinds_unknown,
        "unknown_primary_flag_count": primary_unknown,
        "observed_primary_diagnosis_binding_count": primary_diagnosis,
        "clinical_semantics": "unverified",
        "dictionary_edition": "not_available",
        "historical_group_rule_basis": "not_available",
        "official_grouping": "not_performed",
    }
