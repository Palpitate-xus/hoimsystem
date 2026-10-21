"""Private immutable human RCA records and explicit review signatures.

A literal record or a three-way publication is not a verified causal finding.
No text is normalized, no legacy local clock acquires an invented timezone.
"""

import datetime as dt
import hashlib
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_input as i


class EventSnapshot(c.StrictModel):
    event_id: i.PositiveId
    event_type: str | None
    patient_id: i.PositiveId | None
    description: str | None
    severity: c.RawInt | None
    reporter_id: i.PositiveId | None
    report_time: c.LegacyClock | None
    status: c.RawInt | None
    handle_result: str | None


class RcaSnapshot(c.StrictModel):
    rca_id: i.PositiveId
    event_id: i.PositiveId
    event_summary: str
    timeline: str | None
    root_cause: str
    corrective_actions: str
    pdca_cycle: str | None
    responsible_dept: str | None
    due_date: str | None
    completed_date: str | None
    effect_evaluation: str | None
    analyst_id: i.PositiveId | None
    create_time: c.LegacyClock
    update_time: c.LegacyClock | None

    @field_validator("due_date", "completed_date")
    @classmethod
    def original_date(cls, value):
        if value is not None and dt.date.fromisoformat(value).isoformat() != value:
            raise ValueError("Retain an actual Gregorian date without a timezone")
        return value


class AuthoredProvenance(c.StrictModel):
    method: Literal["human_authored_record"]
    provenance_note: i.Basis


class DerivativeProvenance(c.StrictModel):
    method: Literal["human_declared_derivative"]
    witness_kind: Literal["legacy_event", "legacy_rca"]
    witness_id: i.PositiveId
    expected_raw_hash: c.SHA
    provenance_note: i.Basis


Provenance = Annotated[AuthoredProvenance | DerivativeProvenance, Field(discriminator="method")]


class OwnQuote(c.StrictModel):
    start: c.Index
    end: c.Index
    quote: str = Field(min_length=1, max_length=c.MAX_QUOTE_BYTES)

    @model_validator(mode="after")
    def exact_extent(self):
        if self.end <= self.start or self.end - self.start != len(self.quote) or len(c.utf8(self.quote)) > c.MAX_QUOTE_BYTES:
            raise ValueError("An exact nonempty own-original codepoint quote is required")
        return self


class TimelineDeclaration(c.StrictModel):
    entry_id: c.OpaqueId
    statement: str = Field(min_length=1, max_length=4000)
    occurred_time: c.Occurrence
    evidence: list[OwnQuote] = Field(max_length=16)
    assertion_status: Literal["human_recorded_statement_not_causal_verification"]


class OriginalCreate(c.StrictModel):
    event_id: i.PositiveId
    expected_event_patient_id: i.PositiveId | None
    origin_kind: c.ItemKind
    text: str = Field(min_length=1, max_length=c.MAX_ORIGINAL_BYTES)
    provenance: Provenance
    timeline: list[TimelineDeclaration] = Field(max_length=c.MAX_TIMELINE)

    @model_validator(mode="after")
    def exact_original(self):
        if len(c.utf8(self.text)) > c.MAX_ORIGINAL_BYTES:
            raise ValueError("The exact original exceeds4MiB; it is not truncated")
        c.plain(self.provenance.provenance_note, 4000)
        if self.provenance.method == "human_declared_derivative":
            if self.origin_kind != self.provenance.witness_kind:
                raise ValueError("A derivative retains the actual legacy origin kind and witness FK")
        elif self.origin_kind not in {"manual_evidence", "human_timeline"}:
            raise ValueError("An authored record may not pretend to be a legacy raw witness")
        if (self.origin_kind == "human_timeline") != bool(self.timeline):
            raise ValueError("Only an explicitly authored human timeline has timeline declarations")
        if len({entry.entry_id for entry in self.timeline}) != len(self.timeline):
            raise ValueError("Human declaration IDs must be unique")
        if len(self.timeline) + sum(len(entry.evidence) for entry in self.timeline) > c.MAX_MEMBERS:
            raise ValueError("The complete timeline dependency budget is shared")
        for entry in self.timeline:
            c.plain(entry.statement, 16000)
            if entry.statement not in self.text:
                raise ValueError("The human statement must remain literal in its own original")
            for quote in entry.evidence:
                if self.text[quote.start : quote.end] != quote.quote:
                    raise ValueError("A declared own-original quote must match exact codepoints")
        c.canonical(self)
        return self


class OriginalImmutable(c.StrictModel):
    schema_version: Literal["rca_evidence_original_v1"]
    original_id: c.OpaqueId
    event_id: i.PositiveId
    patient_id_at_capture: i.PositiveId | None
    origin_kind: c.ItemKind
    text: str = Field(min_length=1, max_length=c.MAX_ORIGINAL_BYTES)
    text_hash: c.SHA
    provenance: Provenance
    raw_witness: EventSnapshot | RcaSnapshot | None
    event_grant_id: c.OpaqueId
    patient_grant_id: c.OpaqueId | None
    created_by: i.PositiveId
    recorded_at: str
    timeline: list[TimelineDeclaration] = Field(max_length=c.MAX_TIMELINE)
    causal_verification: Literal["not_provided"]

    @model_validator(mode="after")
    def exact_identity(self):
        c.clock(self.recorded_at)
        if (self.patient_id_at_capture is None) != (self.patient_grant_id is None) or self.event_grant_id == self.patient_grant_id:
            raise ValueError("Actual independent creation purpose receipts must retain the patient association")
        if hashlib.sha256(c.utf8(self.text)).hexdigest() != self.text_hash:
            raise ValueError("Whole original UTF8 SHA differs")
        provenance = self.provenance
        if provenance.method == "human_authored_record":
            if self.raw_witness is not None:
                raise ValueError("Authored evidence must not invent a legacy witness")
        else:
            witness = self.raw_witness
            correct = isinstance(witness, EventSnapshot) if provenance.witness_kind == "legacy_event" else isinstance(witness, RcaSnapshot)
            if not correct or witness.event_id != self.event_id or c.digest(witness) != provenance.expected_raw_hash:
                raise ValueError("Derivative must bind the actual complete same-event raw witness")
            identifier = witness.event_id if isinstance(witness, EventSnapshot) else witness.rca_id
            if identifier != provenance.witness_id:
                raise ValueError("Derivative witness identity differs")
            if isinstance(witness, EventSnapshot) and witness.patient_id != self.patient_id_at_capture:
                raise ValueError("The actual captured event/patient association differs")
        OriginalCreate(
            event_id=self.event_id,
            expected_event_patient_id=self.patient_id_at_capture,
            origin_kind=self.origin_kind,
            text=self.text,
            provenance=provenance,
            timeline=self.timeline,
        )
        c.canonical(self)
        return self


class SourceGovernance(c.StrictModel):
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: Annotated[int, Field(strict=True, ge=1, le=3)]
    privacy_review: i.ReviewStatus
    faithfulness_review: i.ReviewStatus
    provenance_review: i.ReviewStatus
    reviewed_by: i.PositiveId | None
    reviewed_at: str | None
    review_basis_note: str = Field(max_length=1000)
    revoked_by: i.PositiveId | None
    revoked_at: str | None
    revoke_reason: str = Field(max_length=1000)
    created_audit_event_id: i.PositiveId
    reviewed_audit_event_id: i.PositiveId | None
    revoked_audit_event_id: i.PositiveId | None

    @model_validator(mode="after")
    def exact_review(self):
        review = (self.reviewed_by, self.reviewed_at, self.reviewed_audit_event_id)
        revoke = (self.revoked_by, self.revoked_at, self.revoked_audit_event_id)
        has_review = all(value is not None for value in review) and bool(self.review_basis_note)
        no_review = all(value is None for value in review) and not self.review_basis_note and self.privacy_review == self.faithfulness_review == self.provenance_review == "unknown"
        no_revoke = all(value is None for value in revoke) and not self.revoke_reason
        if self.status == "draft":
            valid = self.revision == 1 and no_review and no_revoke
        elif self.status in {"published", "rejected"}:
            valid = self.revision == 2 and has_review and no_revoke
        else:
            valid = all(value is not None for value in revoke) and bool(self.revoke_reason) and ((self.revision == 2 and no_review) or (self.revision == 3 and has_review))
        if not valid:
            raise ValueError("The complete actual review/revoke state differs")
        all_confirmed = self.privacy_review == self.faithfulness_review == self.provenance_review == "confirmed"
        if self.status == "published" and not all_confirmed or self.status == "rejected" and all_confirmed:
            raise ValueError("Published means three explicit signatures, never technical approval alone")
        for value in (self.reviewed_at, self.revoked_at):
            if value is not None:
                c.clock(value)
        for value in (self.review_basis_note, self.revoke_reason):
            if value:
                c.plain(value, 4000)
        if self.reviewed_at is not None and self.revoked_at is not None and c.clock(self.revoked_at) < c.clock(self.reviewed_at):
            raise ValueError("Revocation cannot precede the actual review")
        return self


class OriginalRecord(c.StrictModel):
    immutable: OriginalImmutable
    content_hash: c.SHA
    governance: SourceGovernance
    governance_hash: c.SHA
    evaluated_at: str
    current_raw_witness_matches: bool
    eligible: bool
    causal_verification: Literal["not_provided"]

    @model_validator(mode="after")
    def whole_record(self):
        if c.digest(self.immutable) != self.content_hash:
            raise ValueError("The entire private original differs from its content SHA")
        if c.digest({"original_id": self.immutable.original_id, "content_hash": self.content_hash, "governance": self.governance}) != self.governance_hash:
            raise ValueError("The entire original governance/signature differs")
        recorded = c.clock(self.immutable.recorded_at)
        if c.clock(self.evaluated_at) < recorded:
            raise ValueError("Evaluation cannot precede actual original registration")
        for clock in (self.governance.reviewed_at, self.governance.revoked_at):
            if clock is not None and c.clock(clock) < recorded:
                raise ValueError("Actual governance cannot precede registration")
        if self.eligible != (self.governance.status == "published" and self.current_raw_witness_matches):
            raise ValueError("Current eligibility differs from publication and original witness")
        c.canonical(self)
        return self
