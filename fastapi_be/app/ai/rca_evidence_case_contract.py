"""Finite private RCA captures and separately budgeted public releases."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_source_contract as s


class RestrictedOriginal(c.StrictModel):
    original_id: c.OpaqueId
    event_id: i.PositiveId
    patient_association: Literal["different_from_current_not_disclosed"]
    content_hash: c.SHA
    json_bytes: Annotated[int, Field(strict=True, ge=1, le=c.MAX_WIRE_BYTES)]
    origin_kind: c.ItemKind
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: Annotated[int, Field(strict=True, ge=1, le=3)]
    technical_governance_hash: c.SHA
    visibility: Literal["association_changed_not_disclosed"]


class VisibleOriginal(c.StrictModel):
    record: s.OriginalRecord
    visibility: Literal["current_patient_purpose_authorized"]


OriginalMember = Annotated[RestrictedOriginal | VisibleOriginal, Field(discriminator="visibility")]


def stable_original(item):
    if item.visibility == "association_changed_not_disclosed":
        return item.model_dump(mode="json")
    record = item.record
    return {
        "original_id": record.immutable.original_id,
        "event_id": record.immutable.event_id,
        "patient_id_at_capture": record.immutable.patient_id_at_capture,
        "content_hash": record.content_hash,
        "governance_hash": record.governance_hash,
        "current_raw_witness_matches": record.current_raw_witness_matches,
        "visibility": item.visibility,
    }


class Capture(c.StrictModel):
    event: s.EventSnapshot
    rcas: list[s.RcaSnapshot] = Field(max_length=c.MAX_MEMBERS)
    originals: list[OriginalMember] = Field(max_length=c.MAX_MEMBERS)
    collection_hash: c.SHA
    coverage: Literal["all_current_same_event_roots_finite_not_complete_causality"]

    @model_validator(mode="after")
    def complete_members(self):
        rca_ids = [row.rca_id for row in self.rcas]
        original_ids = [stable_original(item)["original_id"] for item in self.originals]
        if len(rca_ids) != len(set(rca_ids)) or rca_ids != sorted(rca_ids) or len(original_ids) != len(set(original_ids)) or original_ids != sorted(original_ids):
            raise ValueError("The complete finite capture has unique canonical root order")
        if 1 + len(self.rcas) + len(self.originals) > c.MAX_MEMBERS:
            raise ValueError("All roots share one whole member budget")
        if any(row.event_id != self.event.event_id for row in self.rcas):
            raise ValueError("A capture cannot include another actual event's RCA")
        for item in self.originals:
            body = stable_original(item)
            if body["event_id"] != self.event.event_id:
                raise ValueError("Each original belongs to this actual event")
            if item.visibility == "current_patient_purpose_authorized" and body["patient_id_at_capture"] != self.event.patient_id:
                raise ValueError("A new patient purpose cannot restore another captured patient's private text")
        expected = {"event": self.event, "rcas": self.rcas, "originals": [stable_original(item) for item in self.originals]}
        if c.digest(expected) != self.collection_hash:
            raise ValueError("The complete membership, raw rows and original governance differ from the collection SHA")
        c.canonical(self)
        return self


class CaseCreate(c.StrictModel):
    event_id: i.PositiveId
    expected_event_patient_id: i.PositiveId | None
    expected_collection_hash: c.SHA
    basis_note: i.Basis

    @model_validator(mode="after")
    def explicit_basis(self):
        c.plain(self.basis_note, 4000)
        return self


class CaseImmutable(c.StrictModel):
    schema_version: Literal["rca_evidence_case_v1"]
    case_id: c.OpaqueId
    event_id: i.PositiveId
    patient_id_at_capture: i.PositiveId | None
    identity_secret: c.SHA
    created_by: i.PositiveId
    recorded_at: str
    event_grant: i.GrantRecord
    patient_grant: i.GrantRecord | None
    basis_note: i.Basis
    capture: Capture
    causal_verification: Literal["not_provided"]

    @model_validator(mode="after")
    def actual_scope(self):
        when = c.clock(self.recorded_at)
        if (self.event_id, self.patient_id_at_capture) != (self.capture.event.event_id, self.capture.event.patient_id):
            raise ValueError("The complete capture and its actual event/patient identity differ")
        if (self.patient_grant is None) != (self.patient_id_at_capture is None):
            raise ValueError("The actual patient-purpose receipt must remain independent")
        for grant, kind in ((self.event_grant, "event_investigation"), (self.patient_grant, "associated_patient_processing")):
            if grant is None:
                continue
            identity = grant.identity
            if not grant.current_scope or (identity.event_id, identity.patient_id_at_grant, identity.grantee_id, identity.permission_kind) != (
                self.event_id,
                self.patient_id_at_capture,
                self.created_by,
                kind,
            ):
                raise ValueError("The actual creation grants do not authorize this whole event/patient/purpose")
            if c.clock(identity.issued_at) > when or c.clock(identity.valid_until) <= when:
                raise ValueError("A creation purpose grant was not valid at actual case capture")
        if self.patient_grant is not None and self.patient_grant.identity.grant_id == self.event_grant.identity.grant_id:
            raise ValueError("One purpose grant cannot be substituted for two independent permissions")
        for member in self.capture.originals:
            if member.visibility == "current_patient_purpose_authorized" and c.clock(member.record.immutable.recorded_at) > when:
                raise ValueError("The case cannot precede registration of its actual originals")
        c.plain(self.basis_note, 4000)
        c.canonical(self)
        return self


class CaseRecord(c.StrictModel):
    immutable: CaseImmutable
    content_hash: c.SHA
    governance: s.SourceGovernance
    governance_hash: c.SHA
    current_collection_hash: c.SHA
    current_collection_matches: bool
    eligible: bool
    evaluated_at: str
    public_source_endpoint: Literal["separate_typed_8MiB_response"]
    causal_verification: Literal["not_provided"]

    @model_validator(mode="after")
    def complete_record(self):
        if c.digest(self.immutable) != self.content_hash or c.digest({"case_id": self.immutable.case_id, "content_hash": self.content_hash, "governance": self.governance}) != self.governance_hash:
            raise ValueError("The complete private case and governance hashes differ")
        if self.current_collection_matches != (self.current_collection_hash == self.immutable.capture.collection_hash):
            raise ValueError("Current complete collection membership differs")
        if self.eligible != (self.governance.status == "published" and self.current_collection_matches):
            raise ValueError("A stale/unknown/unpublished case is not current executable evidence")
        if c.clock(self.evaluated_at) < c.clock(self.immutable.recorded_at):
            raise ValueError("Evaluation precedes actual capture")
        for value in (self.governance.reviewed_at, self.governance.revoked_at):
            if value is not None and c.clock(value) < c.clock(self.immutable.recorded_at):
                raise ValueError("Case governance precedes registration")
        c.canonical(self)
        return self
