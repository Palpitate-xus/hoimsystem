"""Unique literal-label projection; pure proof mapping is not SQL authorization.

Call source_current(..., execution=True) before live projection. Frozen mapping
rebuilds the one retained publication without making it executable again. Neither
public shape validation nor its own hashes establish a private Source binding;
verify_projection compares the entire object to this mapper from a full Source.
"""

import hashlib
import hmac
import re
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.ai import document_evidence_contract as d
from app.ai import drug_label_contract as c

SKU_DOMAIN = "drug_label_sku_v1"
SCOPE_NOTE = (
    "Only the explicitly compared catalog identity and the complete submitted text/version were reviewed; official identity, complete official leaflet coverage and clinical meaning remain unverified."
)


class SourceBinding(d.StrictModel):
    source_binding_id: d.UUID
    content_hash: d.SHA256
    governance_hash: d.SHA256
    identity_hash: d.SHA256
    original: d.OriginalReference
    professional: c.ProfessionalReference


class PublicSKU(d.StrictModel):
    sku_token: Annotated[str, Field(pattern=r"^drug_label_sku:[a-f0-9]{64}$", strict=True)]
    name: str | None = Field(max_length=24)
    barcode: str | None = Field(max_length=64)
    status: int | None = Field(strict=True)
    comparison_fields: list[Literal["name", "barcode", "status"]]
    private_identity_basis: Literal["actual_pharmaceutical_id_name_barcode_status"]

    @model_validator(mode="after")
    def exact_comparison_scope(self):
        if self.comparison_fields != ["name", "barcode", "status"]:
            raise ValueError("Do not imply a wider catalog comparison or disclose the business PK")
        return self


class ProfessionalScope(d.StrictModel):
    signature_basis: Literal["current_application_pharmacist_role"]
    catalog_match_review: Literal["confirmed"]
    provided_text_version_review: Literal["confirmed"]
    basis_digest: d.SHA256
    scope_note: Literal[SCOPE_NOTE]
    licensure_status: Literal["unknown"]


class SourceClocks(d.StrictModel):
    original_recorded_at: d.UtcText
    original_published_at: d.UtcText
    source_recorded_at: d.UtcText
    professional_signed_at: d.UtcText
    source_published_at: d.UtcText

    @model_validator(mode="after")
    def exact_order(self):
        stamps = [getattr(self, field) for field in type(self).model_fields]
        for stamp in stamps:
            d.clock(stamp)
        if stamps != sorted(stamps):
            raise ValueError("Actual publication/signature clock order required")
        return self


class DrugLabelPublicSource(d.StrictModel):
    schema_version: Literal["drug_label_extraction_source_v1"]
    source_id: str
    binding: SourceBinding
    sku: PublicSKU
    text: str = Field(min_length=1, max_length=d.MAX_ORIGINAL_BYTES)
    raw_bytes_hash: d.SHA256
    raw_bytes_length: int = Field(strict=True, ge=1, le=d.MAX_ORIGINAL_BYTES)
    codepoint_length: int = Field(strict=True, ge=1, le=d.MAX_ORIGINAL_BYTES)
    declared_version: str = Field(min_length=1, max_length=80)
    version_basis: Literal["submitter_declared_not_independently_verified"]
    professional_scope: ProfessionalScope
    release_basis_digest: d.SHA256
    technical_review_basis_digest: d.SHA256
    clocks: SourceClocks
    missing_catalog_or_authority_evidence: list[str]
    clinical_validation: Literal["not_provided"]
    privacy_basis: Literal["technical_identifiers_are_pseudonymous_original_text_not_guaranteed_anonymous"]
    span_coordinate_space: Literal["unicode_codepoint_half_open"]
    normalization: Literal["none"]
    automatic_clinical_rule: Literal[False]

    @field_validator("automatic_clinical_rule", mode="before")
    @classmethod
    def actual_false(cls, value):
        if type(value) is not bool or value is not False:
            raise ValueError("No automatic clinical-rule creation")
        return value

    @model_validator(mode="after")
    def exact_text_and_scope(self):
        if self.source_id != f"drug_label_source:{self.binding.source_binding_id}:{self.binding.content_hash[:12]}":
            raise ValueError("Public Source ID must bind the immutable private source")
        if self.raw_bytes_length != len(d.utf8(self.text)) or self.codepoint_length != len(self.text) or self.raw_bytes_hash != d.bytes_hash(self.text):
            raise ValueError("Full original UTF8 bytes and Unicode codepoints required")
        if self.missing_catalog_or_authority_evidence != list(c.UNKNOWN_EVIDENCE):
            raise ValueError("Missing catalog/authority evidence cannot be removed by publication")
        d.meaningful(self.declared_version, minimum=1, maximum=8000)
        c.bounded(self)
        return self


def _published_governance(record):
    gov = record.governance
    if gov.professional is None or gov.status not in {"published", "revoked"} or gov.reviewed_by is None:
        raise ValueError("No actual retained publication to reconstruct")
    values = gov.model_dump(mode="json")
    values.update(status="published", revision=2, revoked_by=None, revoked_at=None, revoke_reason="")
    return c.SourceGovernance.model_validate(values)


def sku_token(secret, binding_id, pharmaceutical_id):
    if type(secret) is not str or re.fullmatch(r"[a-f0-9]{64}", secret) is None:
        raise ValueError("A private 32-byte canonical hexadecimal HMAC secret is required")
    message = d.utf8(d.canonical_json([SKU_DOMAIN, binding_id, pharmaceutical_id]))
    return "drug_label_sku:" + hmac.new(bytes.fromhex(secret), message, hashlib.sha256).hexdigest()


def project_source(record, *, secret, frozen=False):
    """Map a full source using the caller's immutable per-task mapping seed.

    The caller must persist and reuse this private seed. It is not a rotating
    provider/application credential; this pure function does not manage keys,
    authorize SQL, or establish anonymity. Source ID binds the original release;
    projection_hash separately binds this complete seeded model-visible object.
    """
    value = c.SourceRecord.model_validate(record.model_dump(mode="json") if isinstance(record, c.SourceRecord) else record)
    if type(frozen) is not bool:
        raise ValueError("Frozen mode must be explicit boolean")
    if not frozen and (not value.eligible or value.audit_only):
        raise ValueError("Live execution needs a currently eligible non-audit Source")
    governance = _published_governance(value)
    snapshot, original = value.snapshot, value.snapshot.original
    professional = value.professional_review
    if professional is None:
        raise ValueError("The retained independent pharmacist signature is required")
    p = professional.snapshot
    return DrugLabelPublicSource(
        schema_version="drug_label_extraction_source_v1",
        source_id=value.source_id,
        binding=SourceBinding(
            source_binding_id=snapshot.source_binding_id,
            content_hash=value.content_hash,
            governance_hash=d.digest(governance),
            identity_hash=snapshot.identity_hash,
            original=d.OriginalReference(original_id=original.snapshot.original_id, content_hash=original.content_hash, governance_hash=original.governance_hash),
            professional=governance.professional,
        ),
        sku=PublicSKU(
            sku_token=sku_token(secret, snapshot.source_binding_id, snapshot.identity.pharmaceutical_id),
            name=snapshot.identity.name,
            barcode=snapshot.identity.barcode,
            status=snapshot.identity.status,
            comparison_fields=["name", "barcode", "status"],
            private_identity_basis="actual_pharmaceutical_id_name_barcode_status",
        ),
        text=original.snapshot.text,
        raw_bytes_hash=original.snapshot.raw_bytes_hash,
        raw_bytes_length=original.snapshot.raw_bytes_length,
        codepoint_length=original.snapshot.codepoint_length,
        declared_version=original.snapshot.metadata.version,
        version_basis="submitter_declared_not_independently_verified",
        professional_scope=ProfessionalScope(
            signature_basis=p.signature_basis,
            catalog_match_review=p.catalog_match_review,
            provided_text_version_review=p.provided_text_version_review,
            basis_digest=d.digest(
                {"signature_basis": p.signature_basis, "catalog_match_review": p.catalog_match_review, "provided_text_version_review": p.provided_text_version_review, "basis_note": p.basis_note}
            ),
            scope_note=SCOPE_NOTE,
            licensure_status="unknown",
        ),
        release_basis_digest=d.bytes_hash(snapshot.basis_note),
        technical_review_basis_digest=d.bytes_hash(governance.review_basis_note),
        clocks=SourceClocks(
            original_recorded_at=original.snapshot.recorded_at,
            original_published_at=original.governance.reviewed_at,
            source_recorded_at=snapshot.recorded_at,
            professional_signed_at=p.signed_at,
            source_published_at=governance.reviewed_at,
        ),
        missing_catalog_or_authority_evidence=list(c.UNKNOWN_EVIDENCE),
        clinical_validation="not_provided",
        privacy_basis="technical_identifiers_are_pseudonymous_original_text_not_guaranteed_anonymous",
        span_coordinate_space="unicode_codepoint_half_open",
        normalization="none",
        automatic_clinical_rule=False,
    )


def verify_projection(candidate, record, *, secret, frozen=False):
    try:
        actual = DrugLabelPublicSource.model_validate(candidate.model_dump(mode="json") if isinstance(candidate, DrugLabelPublicSource) else candidate)
        expected = project_source(record, secret=secret, frozen=frozen)
        return d.canonical_json(actual) == d.canonical_json(expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def projection_hash(projected):
    """SHA256 of the full canonical public object, including its seeded token."""
    value = DrugLabelPublicSource.model_validate(projected.model_dump(mode="json") if isinstance(projected, DrugLabelPublicSource) else projected)
    return d.digest(value)
