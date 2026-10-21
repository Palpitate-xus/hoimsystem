"""Literal record questions; no entitlement, tariff, cash-flow or execution claims."""

import hashlib
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_BYTES = 8 * 1024 * 1024
MAX_MEMBERS = 8192
MAX_OBSERVATIONS = 128
SHA = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
SourceID = Annotated[str, Field(min_length=1, max_length=160)]
Offset = Annotated[int, Field(strict=True, ge=0, le=MAX_BYTES)]
KINDS = {"charges": "charge", "orders": "order", "order_items": "order_item", "executions": "execution", "administrations": "administration"}
FIELDS = Literal[
    "item_name",
    "item_type",
    "unit",
    "quantity.value_text",
    "unit_price",
    "total_amount",
    "total_price",
    "days",
    "order_type",
    "category",
    "status",
    "priority",
    "start_time",
    "stop_time",
    "create_time",
    "planned_time",
    "execution_time",
    "verified_at",
    "administration_time",
    "charge_date",
    "settled_time",
    "refunded_time",
    "order_association",
]


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def text_hash(value):
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


def source_hash(value):
    return text_hash(canonical_json(value))


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, str_strip_whitespace=False)


class LiteralReference(Closed):
    source_id: SourceID
    field: FIELDS
    start: Offset
    end: Offset
    quote: str = Field(min_length=1, max_length=4000)

    @field_validator("quote")
    @classmethod
    def scalar_quote(cls, value):
        if len(value.encode("utf-8", errors="strict")) > 16000:
            raise ValueError("The literal quote exceeds its UTF8 budget")
        return value

    @model_validator(mode="after")
    def nonempty_span(self):
        if self.end <= self.start:
            raise ValueError("A nonempty Unicode codepoint span is required")
        return self


class Observation(Closed):
    kind: Literal["association_question", "repeated_record_question", "recorded_status_question", "quantity_unit_question", "recorded_amount_question", "insufficient_evidence"]
    referenced_source_ids: list[SourceID] = Field(min_length=1, max_length=16)
    review_note: str = Field(min_length=4, max_length=2000)
    clarification_question: str = Field(min_length=4, max_length=2000)
    citations: list[LiteralReference] = Field(max_length=16)

    @field_validator("review_note", "clarification_question")
    @classmethod
    def meaningful_scalar_text(cls, value):
        if len(value.strip()) < 4 or len(value.encode("utf-8", errors="strict")) > 8000:
            raise ValueError("An explicit UTF8 review question is required")
        return value

    @model_validator(mode="after")
    def unique_members_and_literal_basis(self):
        if len(set(self.referenced_source_ids)) != len(self.referenced_source_ids):
            raise ValueError("Referenced records must be distinct")
        if self.kind != "insufficient_evidence" and not self.citations:
            raise ValueError("A record question requires a literal projected-field basis")
        return self


class ChargeReconciliationDraft(Closed):
    schema_version: Literal["charge_reconciliation_draft_v1"]
    source_id: SourceID
    source_projection_hash: SHA
    coverage: Literal["partial_questions_no_completeness_or_correctness_claim"]
    observations: list[Observation] = Field(max_length=MAX_OBSERVATIONS)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def parse_draft(text):
    if not isinstance(text, str) or len(text.encode("utf-8", errors="strict")) > MAX_BYTES:
        raise ValueError("The complete draft exceeds its UTF8 budget")

    def nonfinite(_value):
        raise ValueError("Nonfinite JSON number")

    return ChargeReconciliationDraft.model_validate(json.loads(text, object_pairs_hook=_object, parse_constant=nonfinite))


def source_members(source):
    """Caller supplies a separately authorized, complete, mechanically projected Case."""
    if not isinstance(source, dict) or source.get("schema_version") != "charge_ledger_source_v1":
        raise ValueError("A verified recorded-ledger projection is required")
    rows = {}
    for name, kind in KINDS.items():
        members = source.get(name)
        if not isinstance(members, list):
            raise ValueError("Every recorded member collection is required, including empty collections")
        for member in members:
            identifier = member.get("source_id") if isinstance(member, dict) else None
            if not isinstance(identifier, str) or not re.fullmatch(r"charge_" + kind + r":[a-f0-9]{64}", identifier) or identifier in rows:
                raise ValueError("A recorded member has an invalid or repeated opaque token")
            rows[identifier] = member
            if len(rows) > MAX_MEMBERS:
                raise ValueError("The complete recorded membership exceeds its declared limit")
    return rows


def _field(row, field):
    for name in field.split("."):
        if not isinstance(row, dict) or name not in row:
            raise ValueError("The cited recorded field is unavailable")
        row = row[name]
    if not isinstance(row, str):
        raise ValueError("A literal citation requires an actual projected string, never formatted null or number")
    return row


def validate_draft(source, draft, projection_hash):
    if not isinstance(draft, ChargeReconciliationDraft):
        raise ValueError("A typed closed draft is required")
    encoded = canonical_json(source)
    if len(encoded.encode("utf-8", errors="strict")) > MAX_BYTES or source_hash(source) != projection_hash:
        raise ValueError("The complete source projection differs from its exact digest")
    if draft.source_id != source.get("source_id") or draft.source_projection_hash != projection_hash:
        raise ValueError("The draft belongs to another complete source projection")
    members = source_members(source)
    identities = set()
    for observation in draft.observations:
        refs = set(observation.referenced_source_ids)
        identity = (observation.kind, tuple(sorted(refs)))
        if not refs <= members.keys() or identity in identities:
            raise ValueError("An observation has foreign members or repeats the same record question")
        identities.add(identity)
        citations = set()
        for citation in observation.citations:
            identity = (citation.source_id, citation.field, citation.start, citation.end)
            if citation.source_id not in refs or identity in citations:
                raise ValueError("The literal reference is repeated or outside the observation's recorded members")
            text = _field(members[citation.source_id], citation.field)
            if citation.end > len(text) or text[citation.start : citation.end] != citation.quote:
                raise ValueError("The quote is not the exact projected Unicode codepoint span")
            citations.add(identity)
    return draft


def structural_counts(source):
    source_members(source)
    counts = {name + "_count": len(source[name]) for name in KINDS}
    counts["charge_order_association_counts"] = {
        state: sum(row.get("order_association") == state for row in source["charges"]) for state in ("not_recorded", "recorded_same_admission", "unresolved_or_out_of_scope")
    }
    counts["cash_receipt"] = counts["cash_refund"] = "not_provided"
    counts["billing_entitlement"] = counts["currency_and_historical_tariff"] = "unknown"
    counts["line_level_execution_allocation"] = "not_provided"
    counts["automatic_charge_or_refund"] = False
    counts["model_question_coverage"] = "not_exhaustive"
    return counts
