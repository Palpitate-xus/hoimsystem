"""Pure released RCA evidence and unverified hypotheses, never Source authority.

Only a current server-side event/patient-purpose authorization and governed
snapshot builder may produce execution Sources. These types do not authorize
caller-supplied text or prove clinical causation, privacy, or completeness.
"""

import datetime as dt
import hashlib
import json
import re
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_WIRE_BYTES = 8 * 1024 * 1024
MAX_ORIGINAL_BYTES = 4 * 1024 * 1024
MAX_QUOTE_BYTES = 65535
MAX_MEMBERS = 4096
MAX_ITEMS = 256
MAX_TIMELINE = 512
MAX_HYPOTHESES = 64
# Includes both keys and values in the pre-parse lexical count. Actual closed
# Source maxima (4096 refs, 256 texts, 512 timelines *16 quotes) fit below this.
MAX_JSON_TOKENS = 200000
MAX_JSON_DEPTH = 32
COVERAGE = "partial_unverified_hypotheses_no_causal_or_liability_claim"

SHA = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
OpaqueId = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]
Index = Annotated[int, Field(strict=True, ge=0, le=MAX_ORIGINAL_BYTES)]
RawInt = Annotated[int, Field(strict=True, ge=-2147483648, le=2147483647)]
ItemKind = Literal["legacy_event", "legacy_rca", "manual_evidence", "human_timeline"]


def utf8(value: str) -> bytes:
    return value.encode("utf-8", errors="strict")


def clock(value: str) -> dt.datetime:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", value) is None:
        raise ValueError("An explicit actual UTC6 clock is required")
    return dt.datetime.fromisoformat(value[:-1] + "+00:00")


def plain(value: str, maximum: int) -> str:
    if not value or not value.strip() or len(utf8(value)) > maximum:
        raise ValueError("A nonempty whole UTF8 string within its byte budget is required")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")

    @field_validator("*", mode="after")
    @classmethod
    def unicode_strings(cls, value):
        if isinstance(value, str):
            utf8(value)
        return value


def canonical(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")

    def encode_model(item):
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        raise TypeError("Only JSON primitives and actual typed models are canonical data")

    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=encode_model)
    chunks, size = [], 0
    for chunk in encoder.iterencode(value):
        size += len(utf8(chunk))
        if size > MAX_WIRE_BYTES:
            raise ValueError("Complete canonical object exceeds8MiB; nothing is truncated")
        chunks.append(chunk)
    return "".join(chunks)


def digest(value) -> str:
    return hashlib.sha256(utf8(canonical(value))).hexdigest()


class OccurrenceUnknown(StrictModel):
    status: Literal["unknown"]
    basis_hash: SHA


class OccurrenceExact(StrictModel):
    status: Literal["human_declared_exact"]
    at: str
    basis_hash: SHA

    @field_validator("at")
    @classmethod
    def actual_clock(cls, value):
        clock(value)
        return value


class OccurrenceInterval(StrictModel):
    status: Literal["human_declared_interval"]
    start_at: str
    end_at: str
    basis_hash: SHA

    @model_validator(mode="after")
    def ordered(self):
        if clock(self.start_at) >= clock(self.end_at):
            raise ValueError("A declared occurrence interval must have positive extent")
        return self


Occurrence = Annotated[OccurrenceUnknown | OccurrenceExact | OccurrenceInterval, Field(discriminator="status")]


class LegacyClock(StrictModel):
    text: str
    basis: Literal["stored_naive_no_timezone"]

    @field_validator("text")
    @classmethod
    def retain_naive_clock(cls, value):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", value) is None:
            raise ValueError("Retain the stored naive timestamp without adding timezone")
        dt.datetime.fromisoformat(value)
        return value


class RecordedEventState(StrictModel):
    recorded_severity: RawInt | None
    recorded_status: RawInt | None
    report_time: LegacyClock | None
    patient_association: Literal["recorded_patient", "not_recorded"]
    encounter_assignment: Literal["not_recorded"]
    causal_approval: Literal["not_provided"]


class Member(StrictModel):
    member_id: OpaqueId
    kind: ItemKind
    content_hash: SHA
    governance_hash: SHA | None
    release_status: Literal["released", "not_released"]


class ReleasedItem(StrictModel):
    item_id: OpaqueId
    kind: ItemKind
    content_hash: SHA
    governance_hash: SHA | None
    text: str = Field(min_length=1, max_length=MAX_ORIGINAL_BYTES)
    text_hash: SHA
    available_at: str
    availability_basis: Literal["server_capture", "original_registration"]

    @model_validator(mode="after")
    def whole_original(self):
        if len(utf8(self.text)) > MAX_ORIGINAL_BYTES or hashlib.sha256(utf8(self.text)).hexdigest() != self.text_hash:
            raise ValueError("The exact whole released UTF8 original must match its text hash")
        clock(self.available_at)
        return self


class ExactQuote(StrictModel):
    item_id: OpaqueId
    start: Index
    end: Index
    quote: str = Field(min_length=1, max_length=MAX_QUOTE_BYTES)

    @model_validator(mode="after")
    def exact_extent(self):
        if self.end <= self.start or self.end - self.start != len(self.quote) or len(utf8(self.quote)) > MAX_QUOTE_BYTES:
            raise ValueError("An exact nonempty Unicode codepoint [start,end) quote is required")
        return self


class HumanTimelineEntry(StrictModel):
    entry_id: OpaqueId
    source_item_id: OpaqueId
    statement: str = Field(min_length=1, max_length=4000)
    occurred_time: Occurrence
    recorded_at: str
    evidence: list[ExactQuote] = Field(max_length=16)
    assertion_status: Literal["human_recorded_statement_not_causal_verification"]

    @model_validator(mode="after")
    def explicit_statement(self):
        plain(self.statement, 16000)
        clock(self.recorded_at)
        return self


class SourcePublication(StrictModel):
    status: Literal["published"]
    privacy_review: Literal["confirmed"]
    faithfulness_review: Literal["confirmed"]
    provenance_review: Literal["confirmed"]
    reviewed_at: str

    @field_validator("reviewed_at")
    @classmethod
    def actual_clock(cls, value):
        clock(value)
        return value


def verify_quote(quote: ExactQuote, items: dict[str, ReleasedItem]):
    item = items.get(quote.item_id)
    if item is None or quote.end > len(item.text) or item.text[quote.start : quote.end] != quote.quote:
        raise ValueError("The complete literal quote must align to this released original")


class RcaEvidenceSource(StrictModel):
    schema_version: Literal["rca_evidence_source_v1"]
    case_id: OpaqueId
    source_id: str
    content_hash: SHA
    governance_hash: SHA
    snapshot_time: str
    review_mode: Literal["current_retrospective_investigation_not_historical_prediction"]
    event_state: RecordedEventState
    publication: SourcePublication
    members: list[Member] = Field(min_length=1, max_length=MAX_MEMBERS)
    member_manifest_hash: SHA
    items: list[ReleasedItem] = Field(max_length=MAX_ITEMS)
    timeline: list[HumanTimelineEntry] = Field(max_length=MAX_TIMELINE)
    evidence_coverage: Literal["finite_declared_snapshot_not_complete_causality_or_hospital_coverage"]

    @model_validator(mode="after")
    def closed_source(self):
        uuid.UUID(self.case_id)
        as_of = clock(self.snapshot_time)
        if self.source_id != f"rca_case:{self.case_id}:{self.content_hash[:12]}":
            raise ValueError("The source identity must bind the complete private case hash")
        if clock(self.publication.reviewed_at) > as_of:
            raise ValueError("A Source cannot precede its actual publication")
        members = {item.member_id: item for item in self.members}
        items = {item.item_id: item for item in self.items}
        timelines = {item.entry_id: item for item in self.timeline}
        if len(members) != len(self.members) or len(items) != len(self.items) or len(timelines) != len(self.timeline):
            raise ValueError("All finite member/item/timeline identities must be unique")
        if len(self.members) + len(self.items) + len(self.timeline) + sum(len(t.evidence) for t in self.timeline) > MAX_MEMBERS:
            raise ValueError("The single whole dependency budget cannot be bypassed with separate arrays")
        if list(members) != sorted(members) or list(items) != sorted(items) or list(timelines) != sorted(timelines):
            raise ValueError("The declared finite arrays must use canonical technical ID order")
        if sum(member.kind == "legacy_event" for member in self.members) != 1:
            raise ValueError("Exactly one actual event root must remain in the complete manifest")
        if digest(self.members) != self.member_manifest_hash:
            raise ValueError("The complete public member manifest must match its own hash")
        for item in self.items:
            member = members.get(item.item_id)
            if member is None or member.release_status != "released" or (member.kind, member.content_hash, member.governance_hash) != (item.kind, item.content_hash, item.governance_hash):
                raise ValueError("Each released text must match one complete declared member")
            if clock(item.available_at) > as_of:
                raise ValueError("A released original cannot become available after this snapshot")
        if {key for key, member in members.items() if member.release_status == "released"} != set(items):
            raise ValueError("Released members may not be silently omitted from the Source")
        for entry in self.timeline:
            item = items.get(entry.source_item_id)
            if item is None or item.kind != "human_timeline" or clock(entry.recorded_at) > as_of:
                raise ValueError("A human timeline needs its actual released human original and clock")
            if entry.statement not in item.text:
                raise ValueError("The human statement must remain literal in its actual released original")
            for quote in entry.evidence:
                verify_quote(quote, items)
        canonical(self)
        return self


class Hypothesis(StrictModel):
    hypothesis: str = Field(min_length=1, max_length=4000)
    supporting_quotes: list[ExactQuote] = Field(max_length=16)
    conflicting_quotes: list[ExactQuote] = Field(max_length=16)
    timeline_entry_ids: list[OpaqueId] = Field(max_length=64)
    evidence_needed: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(max_length=16)
    investigation_questions: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(max_length=16)

    @model_validator(mode="after")
    def unverified(self):
        plain(self.hypothesis, 16000)
        if len(set(self.timeline_entry_ids)) != len(self.timeline_entry_ids):
            raise ValueError("Timeline references cannot be repeated")
        for text in (*self.evidence_needed, *self.investigation_questions):
            plain(text, 8000)
        if not self.supporting_quotes and not self.evidence_needed:
            raise ValueError("An unsupported hypothesis must retain explicit evidence gaps")
        return self


class ProviderDraft(StrictModel):
    hypotheses: list[Hypothesis] = Field(max_length=MAX_HYPOTHESES)
    clarification_questions: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(max_length=64)

    @model_validator(mode="after")
    def whole_draft(self):
        for text in self.clarification_questions:
            plain(text, 8000)
        canonical(self)
        return self


class RcaEvidenceDraft(ProviderDraft):
    schema_version: Literal["rca_evidence_draft_v1"]
    case_id: OpaqueId
    source_projection_hash: SHA
    instructions_digest: SHA
    coverage: Literal["partial_unverified_hypotheses_no_causal_or_liability_claim"]


def validate_source(value) -> RcaEvidenceSource:
    """Validate whole data only; this never grants Source/patient authorization."""
    source = RcaEvidenceSource.model_validate(value)
    canonical(source)
    return source


def provider_payload(source: RcaEvidenceSource) -> dict:
    return {"rca_source": validate_source(source).model_dump(mode="json")}


def validate_draft(value, source: RcaEvidenceSource, instructions_digest: str) -> RcaEvidenceDraft:
    source = validate_source(source)
    draft = RcaEvidenceDraft.model_validate(value)
    if draft.case_id != source.case_id or draft.source_projection_hash != digest(source) or draft.instructions_digest != instructions_digest:
        raise ValueError("The full frozen Source and actual instructions digest must match")
    items = {item.item_id: item for item in source.items}
    timeline = {entry.entry_id for entry in source.timeline}
    for hypothesis in draft.hypotheses:
        if not set(hypothesis.timeline_entry_ids) <= timeline:
            raise ValueError("A hypothesis cannot invent an actual human timeline entry")
        for quote in (*hypothesis.supporting_quotes, *hypothesis.conflicting_quotes):
            verify_quote(quote, items)
    canonical(draft)
    return draft


def _strict_reply(text: str):
    if type(text) is not str or len(utf8(text)) > MAX_WIRE_BYTES:
        raise ValueError("The entire UTF8 reply must fit8MiB")
    depth = tokens = 0
    quoted = escaped = atom = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
            tokens += 1
        elif char in "[{":
            depth += 1
            tokens += 1
        elif char in "]}":
            depth -= 1
            atom = False
        elif char in ",:" or char.isspace():
            atom = False
        elif not atom:
            atom = True
            tokens += 1
        if depth > MAX_JSON_DEPTH or tokens > MAX_JSON_TOKENS:
            raise ValueError("Whole JSON exceeds the explicit depth/token budget before decoding")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Nonfinite JSON numbers are forbidden")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def parse_rca_reply(text: str, source: RcaEvidenceSource, instructions_digest: str) -> RcaEvidenceDraft:
    source = validate_source(source)
    provider = ProviderDraft.model_validate(_strict_reply(text))
    return validate_draft(
        {
            **provider.model_dump(mode="json"),
            "schema_version": "rca_evidence_draft_v1",
            "case_id": source.case_id,
            "source_projection_hash": digest(source),
            "instructions_digest": instructions_digest,
            "coverage": COVERAGE,
        },
        source,
        instructions_digest,
    )
