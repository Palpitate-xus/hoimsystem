"""Private RCA purpose governance. These DTOs do not grant read authority."""

import datetime as dt
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.ai import rca_evidence_contract as c

PositiveId = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Revision = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
PermissionKind = Literal["event_investigation", "associated_patient_processing"]
ReviewStatus = Literal["unknown", "confirmed", "not_confirmed"]
Basis = Annotated[str, Field(strict=True, min_length=1, max_length=1000)]


def utc_text(value: dt.datetime) -> str:
    """Only server UTC columns use this conversion, never naive legacy clocks."""
    if value.tzinfo is not None:
        value = value.astimezone(dt.UTC).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds") + "Z"


class GrantCreate(c.StrictModel):
    event_id: PositiveId
    expected_event_patient_id: PositiveId | None
    grantee_id: PositiveId
    permission_kind: PermissionKind
    purpose: Literal["incident_rca"]
    valid_until: str
    basis_note: Basis
    explicit_scope_review: Literal[True]

    @field_validator("valid_until")
    @classmethod
    def explicit_utc(cls, value):
        c.clock(value)
        return value

    @field_validator("basis_note")
    @classmethod
    def complete_basis(cls, value):
        return c.plain(value, 4000)

    @field_validator("explicit_scope_review", mode="before")
    @classmethod
    def actual_true(cls, value):
        if value is not True:
            raise ValueError("An actual explicit scope review boolean is required")
        return value

    @model_validator(mode="after")
    def independent_patient_scope(self):
        if self.permission_kind == "associated_patient_processing" and self.expected_event_patient_id is None:
            raise ValueError("A patient-processing grant requires the actual associated patient")
        return self


class GrantIdentity(c.StrictModel):
    schema_version: Literal["rca_purpose_grant_v1"]
    grant_id: c.OpaqueId
    event_id: PositiveId
    patient_id_at_grant: PositiveId | None
    grantee_id: PositiveId
    permission_kind: PermissionKind
    purpose: Literal["incident_rca"]
    valid_until: str
    basis_note: Basis
    explicit_scope_review: Literal[True]
    issued_by: PositiveId
    issued_at: str

    @model_validator(mode="after")
    def explicit_scope_and_clocks(self):
        if self.permission_kind == "associated_patient_processing" and self.patient_id_at_grant is None:
            raise ValueError("Patientless events cannot acquire a fictional patient-purpose grant")
        if c.clock(self.valid_until) <= c.clock(self.issued_at):
            raise ValueError("A grant must have a real future expiry when issued")
        c.plain(self.basis_note, 4000)
        c.canonical(self)
        return self

    @field_validator("explicit_scope_review", mode="before")
    @classmethod
    def actual_true(cls, value):
        if value is not True:
            raise ValueError("A review flag cannot be coerced from a number")
        return value


class CompareAndSwap(c.StrictModel):
    expected_revision: Revision
    expected_content_hash: c.SHA
    expected_governance_hash: c.SHA


class Revoke(CompareAndSwap):
    basis_note: Basis

    @field_validator("basis_note")
    @classmethod
    def complete_basis(cls, value):
        return c.plain(value, 4000)


class GrantGovernance(c.StrictModel):
    status: Literal["active", "revoked"]
    revision: Revision
    revoked_by: PositiveId | None
    revoked_at: str | None
    revoke_reason: str = Field(max_length=1000)
    created_audit_event_id: PositiveId
    revoked_audit_event_id: PositiveId | None

    @model_validator(mode="after")
    def whole_state(self):
        fields = (self.revoked_by, self.revoked_at, self.revoked_audit_event_id)
        if self.status == "active":
            if self.revision != 1 or any(value is not None for value in fields) or self.revoke_reason:
                raise ValueError("An active grant cannot contain revocation fields")
        elif self.revision != 2 or any(value is None for value in fields) or not self.revoke_reason:
            raise ValueError("A revoked grant needs one exact actual revocation")
        else:
            c.clock(self.revoked_at)
            c.plain(self.revoke_reason, 4000)
        return self


class GrantRecord(c.StrictModel):
    identity: GrantIdentity
    content_hash: c.SHA
    governance: GrantGovernance
    governance_hash: c.SHA
    evaluated_at: str
    event_patient_id_now: PositiveId | None
    grantee_current_super: bool
    current_scope: bool
    scope_reasons: list[Literal["grant_expired", "grant_revoked", "event_patient_changed", "grantee_not_current_super"]] = Field(max_length=4)

    @model_validator(mode="after")
    def independent_integrity(self):
        if c.digest(self.identity) != self.content_hash:
            raise ValueError("The entire immutable grant differs from its independent SHA")
        expected = c.digest({"grant_id": self.identity.grant_id, "content_hash": self.content_hash, "governance": self.governance})
        if expected != self.governance_hash:
            raise ValueError("The complete grant governance differs from its independent SHA")
        if self.governance.revoked_at is not None and c.clock(self.governance.revoked_at) < c.clock(self.identity.issued_at):
            raise ValueError("Revocation cannot precede actual grant issue")
        expected_reasons = []
        if c.clock(self.identity.valid_until) <= c.clock(self.evaluated_at):
            expected_reasons.append("grant_expired")
        if self.governance.status == "revoked":
            expected_reasons.append("grant_revoked")
        if self.identity.patient_id_at_grant != self.event_patient_id_now:
            expected_reasons.append("event_patient_changed")
        if not self.grantee_current_super:
            expected_reasons.append("grantee_not_current_super")
        if self.scope_reasons != expected_reasons or self.current_scope != (not expected_reasons):
            raise ValueError("Current permission and every actual scope reason differ")
        c.canonical(self)
        return self


class SourceReview(CompareAndSwap):
    decision: Literal["publish", "reject"]
    privacy_review: ReviewStatus
    faithfulness_review: ReviewStatus
    provenance_review: ReviewStatus
    basis_note: Basis

    @model_validator(mode="after")
    def explicit_statement(self):
        all_confirmed = self.privacy_review == self.faithfulness_review == self.provenance_review == "confirmed"
        if (self.decision == "publish") != all_confirmed:
            raise ValueError("Publication needs all three explicit reviews; rejection cannot claim all confirmed")
        c.plain(self.basis_note, 4000)
        return self
