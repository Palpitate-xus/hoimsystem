"""Strict literal-label evidence; professional role is not verified licensure."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.ai import document_evidence_contract as d

SOURCE_ROLES = frozenset({"super_admin", "pharmacist"})
MAX_SOURCE_BYTES = 8 * 1024 * 1024
COMPARISON_FIELDS = ("pharmaceutical_id", "name", "barcode", "status")
UNKNOWN_EVIDENCE = (
    "manufacturer",
    "approval_number",
    "dosage_form",
    "strength",
    "ingredient",
    "quantity_unit",
    "official_version_authority",
    "pharmacist_licensure",
    "complete_official_leaflet_coverage",
)
Review = Literal["confirmed", "not_confirmed", "unknown"]


def bounded(value, maximum=MAX_SOURCE_BYTES):
    if len(d.utf8(d.canonical_json(value))) > maximum:
        raise ValueError("Complete drug-label object exceeds its UTF8 budget; not truncated")
    return value


class Note(d.StrictModel):
    basis_note: str = Field(min_length=10, max_length=4000)

    @field_validator("basis_note")
    @classmethod
    def actual_basis(cls, value):
        return d.meaningful(value)


class Identity(d.StrictModel):
    pharmaceutical_id: d.Positive
    name: str | None = Field(max_length=24)
    barcode: str | None = Field(max_length=64)
    status: int | None = Field(strict=True)


class SourceCreate(Note):
    pharmaceutical_id: d.Positive
    expected_identity_hash: d.SHA256
    original: d.OriginalReference


class CAS(d.StrictModel):
    expected_revision: d.Revision
    expected_content_hash: d.SHA256
    expected_governance_hash: d.SHA256


class RevokeRequest(CAS, Note):
    basis_note: str = Field(min_length=10, max_length=1000)


class ProfessionalSign(CAS, Note):
    catalog_match_review: Review
    provided_text_version_review: Review


class ProfessionalReference(d.StrictModel):
    professional_review_id: d.UUID
    content_hash: d.SHA256
    governance_hash: d.SHA256


class SourceReview(CAS, Note):
    decision: Literal["approve", "reject"]
    professional: ProfessionalReference | None

    @model_validator(mode="after")
    def approval_ref(self):
        if self.decision == "approve" and self.professional is None:
            raise ValueError("Technical approval requires the explicit professional signature")
        return self


class SourceSnapshot(Note):
    schema_version: Literal["drug_label_source_immutable_v1"]
    source_binding_id: d.UUID
    created_by: d.Positive
    recorded_at: d.UtcText
    identity: Identity
    identity_hash: d.SHA256
    original: d.OriginalRecord
    comparison_fields: list[Literal["pharmaceutical_id", "name", "barcode", "status"]]

    @model_validator(mode="after")
    def release_proof(self):
        if self.identity_hash != d.digest(self.identity) or self.comparison_fields != list(COMPARISON_FIELDS):
            raise ValueError("Exact declared SKU comparison required")
        if not self.original.eligible or self.original.snapshot.metadata.document_kind != "drug_label":
            raise ValueError("Explicitly released published drug_label Original required")
        if self.recorded_at < self.original.governance.reviewed_at:
            raise ValueError("Release cannot predate original publication")
        d.clock(self.recorded_at)
        bounded(self)
        return self


class ProfessionalSnapshot(Note):
    schema_version: Literal["drug_label_professional_immutable_v1"]
    professional_review_id: d.UUID
    source_binding_id: d.UUID
    source_content_hash: d.SHA256
    original_content_hash: d.SHA256
    original_governance_hash: d.SHA256
    identity_hash: d.SHA256
    signed_by: d.Positive
    signed_at: d.UtcText
    signature_basis: Literal["current_application_pharmacist_role"]
    catalog_match_review: Review
    provided_text_version_review: Review

    @model_validator(mode="after")
    def signature_size(self):
        d.clock(self.signed_at)
        bounded(self, 65535)
        return self


class ProfessionalGovernance(d.StrictModel):
    status: Literal["signed", "revoked"]
    revision: Literal[1, 2]
    revoked_by: d.Positive | None
    revoked_at: d.UtcText | None
    revoke_reason: str = Field(max_length=1000)

    @model_validator(mode="after")
    def actual_revocation(self):
        if self.status == "signed":
            if (self.revision, self.revoked_by, self.revoked_at, self.revoke_reason) != (1, None, None, ""):
                raise ValueError("Initial immutable professional signature has no withdrawal")
        else:
            if self.revision != 2 or self.revoked_by is None or self.revoked_at is None:
                raise ValueError("Complete actual withdrawal required")
            d.clock(self.revoked_at)
            d.meaningful(self.revoke_reason)
        return self


class ProfessionalRecord(d.StrictModel):
    schema_version: Literal["drug_label_professional_record_v1"]
    snapshot: ProfessionalSnapshot
    content_hash: d.SHA256
    governance: ProfessionalGovernance
    governance_hash: d.SHA256

    @model_validator(mode="after")
    def full_proof(self):
        if d.digest(self.snapshot) != self.content_hash or d.digest(self.governance) != self.governance_hash:
            raise ValueError("Full professional signature digest mismatch")
        if self.governance.revoked_at is not None and self.governance.revoked_at < self.snapshot.signed_at:
            raise ValueError("Withdrawal predates signature")
        return self


def signed_governance(record):
    return ProfessionalGovernance(status="signed", revision=1, revoked_by=None, revoked_at=None, revoke_reason="")


class SourceGovernance(d.StrictModel):
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: d.Revision
    professional: ProfessionalReference | None
    reviewed_by: d.Positive | None
    reviewed_at: d.UtcText | None
    review_basis_note: str = Field(max_length=4000)
    revoked_by: d.Positive | None
    revoked_at: d.UtcText | None
    revoke_reason: str = Field(max_length=1000)

    @model_validator(mode="after")
    def actual_governance(self):
        reviewed = self.reviewed_by is not None
        if reviewed != (self.reviewed_at is not None) or reviewed != bool(self.review_basis_note):
            raise ValueError("Complete technical signature required")
        revoked = self.revoked_by is not None
        if revoked != (self.revoked_at is not None) or revoked != bool(self.revoke_reason):
            raise ValueError("Complete technical withdrawal required")
        for stamp in (self.reviewed_at, self.revoked_at):
            if stamp is not None:
                d.clock(stamp)
        for note in (self.review_basis_note, self.revoke_reason):
            if note:
                d.meaningful(note)
        if self.status == "draft" and (self.revision != 1 or reviewed or revoked or self.professional is not None):
            raise ValueError("Draft has no technical signature")
        if self.status in {"published", "rejected"} and (self.revision != 2 or not reviewed or revoked):
            raise ValueError("Review is exactly the second revision")
        if self.status == "published" and self.professional is None:
            raise ValueError("Publication needs an exact independent professional reference")
        if self.status == "revoked" and (not revoked or self.revision != (3 if reviewed else 2)):
            raise ValueError("Withdrawal retains all earlier signatures")
        return self


class SourceRecord(d.StrictModel):
    schema_version: Literal["drug_label_source_record_v1"]
    source_id: str
    snapshot: SourceSnapshot
    content_hash: d.SHA256
    governance: SourceGovernance
    governance_hash: d.SHA256
    professional_review: ProfessionalRecord | None
    identity_current: bool
    original_current: bool
    signer_current: bool
    audit_only: bool
    eligible: bool
    exclusion_reasons: list[str]
    can_sign: bool
    can_review: bool
    can_revoke: bool
    clinical_validation: Literal["not_provided"]
    licensure_verification: Literal["not_provided"]
    missing_evidence: list[str]

    @model_validator(mode="after")
    def full_proof(self):
        if (
            self.source_id != f"drug_label_source:{self.snapshot.source_binding_id}:{self.content_hash[:12]}"
            or self.content_hash != d.digest(self.snapshot)
            or self.governance_hash != d.digest(self.governance)
        ):
            raise ValueError("Source full identity/governance mismatch")
        if self.missing_evidence != list(UNKNOWN_EVIDENCE):
            raise ValueError("Missing authoritative evidence cannot be silently removed")
        gov = self.governance
        for stamp in (gov.reviewed_at, gov.revoked_at):
            if stamp is not None and stamp < self.snapshot.recorded_at:
                raise ValueError("Governance predates release")
        if gov.reviewed_at is not None and gov.revoked_at is not None and gov.revoked_at < gov.reviewed_at:
            raise ValueError("Withdrawal predates review")
        prof = self.professional_review
        if prof is None:
            if self.signer_current or gov.professional is not None:
                raise ValueError("No phantom professional signature")
        else:
            p = prof.snapshot
            if (p.source_binding_id, p.source_content_hash, p.original_content_hash, p.original_governance_hash, p.identity_hash) != (
                self.snapshot.source_binding_id,
                self.content_hash,
                self.snapshot.original.content_hash,
                self.snapshot.original.governance_hash,
                self.snapshot.identity_hash,
            ):
                raise ValueError("Professional signature must cover this entire binding")
            if p.signed_at < self.snapshot.recorded_at or p.signed_by in {self.snapshot.created_by, self.snapshot.original.snapshot.created_by}:
                raise ValueError("Professional review must be independent and later than release")
            if gov.professional is not None:
                if (gov.professional.professional_review_id, gov.professional.content_hash, gov.professional.governance_hash) != (
                    p.professional_review_id,
                    prof.content_hash,
                    d.digest(signed_governance(prof)),
                ):
                    raise ValueError("Publication signature anchors must preserve the original signed decision")
                if gov.reviewed_by == p.signed_by or gov.reviewed_at < p.signed_at:
                    raise ValueError("Technical publication is independent of professional signature")
                if (p.catalog_match_review, p.provided_text_version_review) != ("confirmed", "confirmed"):
                    raise ValueError("Unknown professional outcomes cannot create a published source")
        reasons = []
        for condition, reason in (
            (gov.status == "published", "source_not_published"),
            (self.identity_current, "identity_changed"),
            (self.original_current, "original_not_current"),
            (prof is not None and prof.governance.status == "signed", "professional_not_current"),
            (self.signer_current, "signer_not_current"),
        ):
            if not condition:
                reasons.append(reason)
        if self.audit_only:
            reasons.append("audit_only")
        if self.exclusion_reasons != reasons or self.eligible != (not reasons):
            raise ValueError("Source eligibility must equal all explicit current conditions")
        if self.audit_only and (self.can_sign or self.can_review or self.can_revoke):
            raise ValueError("Frozen audit never restores operational capabilities")
        bounded(self)
        return self
