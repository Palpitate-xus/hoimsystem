"""Closed private requests; local rule snapshots are never official groupers."""

import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.ai.supply_source_input import SourceReview, SourceRevoke, check_basis

UUID = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
SHA = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[int, Field(strict=True, gt=0, le=2147483647)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class CaptureRequest(StrictModel):
    patient_id: Positive
    admission_id: UUID
    home_id: UUID
    rule_package_id: UUID | None
    expected_rule_package_content_hash: SHA | None
    expected_rule_package_governance_hash: SHA | None

    @model_validator(mode="after")
    def package_binding(self):
        if len({self.rule_package_id is None, self.expected_rule_package_content_hash is None, self.expected_rule_package_governance_hash is None}) != 1:
            raise ValueError("An optional package requires all immutable and governance anchors")
        return self


class CaseCreate(StrictModel):
    request: CaptureRequest
    expected_collection_digest: SHA
    note: str = Field(max_length=4000)

    @model_validator(mode="after")
    def note_bytes(self):
        if len(self.note.encode()) > 4000:
            raise ValueError("Private note exceeds4000UTF8bytes")
        return self


class RulePackageCreate(StrictModel):
    package_kind: Literal["local_prefix_snapshot"]
    rule_ids: list[Positive] = Field(min_length=1, max_length=4096)
    basis_note: str = Field(min_length=20, max_length=4000)

    @model_validator(mode="after")
    def original_rules(self):
        check_basis(self.basis_note)
        if len(set(self.rule_ids)) != len(self.rule_ids):
            raise ValueError("Explicit original rule identifiers cannot repeat")
        return self


SOURCE_ROLES = frozenset({"admin", "super_admin", "doctor", "director"})
__all__ = ["CaptureRequest", "CaseCreate", "RulePackageCreate", "SourceReview", "SourceRevoke", "SOURCE_ROLES"]

# Exact private row schemas come from the real immutable SQL column sets, not
# relationships or arbitrary JSON. They preserve original Decimal text and
# legacy naive clocks; they do not give those clocks a UTC interpretation.
from pydantic import create_model
from sqlalchemy import Date, DateTime, Integer

from app import models as _models


def real_clock(value):
    datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ" if value.endswith("Z") else "%Y-%m-%dT%H:%M:%S.%f")
    return value


def real_date(value):
    datetime.date.fromisoformat(value)
    return value


UtcText = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"), AfterValidator(real_clock)]
LegacyClock = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}$"), AfterValidator(real_clock)]
DateText = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"), AfterValidator(real_date)]


def _row_type(name, model):
    fields = {}
    for column in model.__table__.columns:
        t = column.type
        annotation = int if isinstance(t, Integer) else LegacyClock if isinstance(t, DateTime) else DateText if isinstance(t, Date) else str
        fields[column.name] = ((annotation | None) if column.nullable or column.name in {"status", "is_primary", "kind"} else annotation, ...)
    return create_model(name, __base__=StrictModel, **fields)


HomeOriginal = _row_type("HomeOriginal", _models.MedicalRecordHome)
BindingOriginal = _row_type("BindingOriginal", _models.HomeIcdBinding)
DiagnosisDictionaryOriginal = _row_type("DiagnosisDictionaryOriginal", _models.Icd10Diagnosis)
OperationDictionaryOriginal = _row_type("OperationDictionaryOriginal", _models.Icd10Operation)
GroupOriginal = _row_type("GroupOriginal", _models.DrgGrouping)
RuleOriginal = _row_type("RuleOriginal", _models.DrgRule)


class Governance(StrictModel):
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: Annotated[int, Field(strict=True, ge=1, le=3)]
    reviewed_at: UtcText | None
    reviewed_by: Positive | None
    review_basis_note: str = Field(max_length=4000)
    revoked_at: UtcText | None
    revoked_by: Positive | None
    revoke_reason: str = Field(max_length=1000)


class PackageMetadata(Governance):
    package_id: UUID
    package_kind: Literal["local_prefix_snapshot"]
    schema_version: Literal["coding_rule_package_private_v1"]
    created_at: UtcText
    created_by: Positive
    collection_digest: SHA
    content_hash: SHA
    source_id: str
    governance_hash: SHA


class RuleSnapshot(StrictModel):
    schema_version: Literal["coding_local_prefix_package_v1"]
    rule_ids: list[Positive] = Field(min_length=1, max_length=4096)
    rules: list[RuleOriginal] = Field(min_length=1, max_length=4096)
    basis_note: str = Field(min_length=20, max_length=4000)


class PackageOriginalProof(PackageMetadata):
    snapshot: RuleSnapshot


class AdmissionBinding(StrictModel):
    admission_id: UUID
    patient_id: Positive
    doctor_id: Positive | None
    department_id: Positive | None


class MinimizationBasis(StrictModel):
    name: str | None
    identity: str | None
    phone: str | None
    address: str | None


class DictionaryEntry(StrictModel):
    kind: str | None
    code: str
    entry: DiagnosisDictionaryOriginal | OperationDictionaryOriginal | None


class LinkedRule(StrictModel):
    rule_id: Positive
    entry: RuleOriginal | None


class Member(StrictModel):
    kind: Literal["home", "admission_binding", "minimization_basis", "code_binding", "dictionary", "recorded_group", "local_rule", "rule_package"]
    record_id: str
    content_hash: SHA


class Collection(StrictModel):
    schema_version: Literal["coding_case_collection_v1"]
    request: CaptureRequest
    captured_at: UtcText
    home: HomeOriginal
    admission_binding: AdmissionBinding
    minimization_basis: MinimizationBasis
    code_bindings: list[BindingOriginal] = Field(max_length=4096)
    dictionary_entries: list[DictionaryEntry] = Field(max_length=4096)
    recorded_groups: list[GroupOriginal] = Field(max_length=256)
    linked_rules: list[LinkedRule] = Field(max_length=4096)
    rule_package: PackageOriginalProof | None
    member_manifest: list[Member] = Field(max_length=12600)
    manifest_hash: SHA
    collection_digest: SHA


class CaseSnapshot(StrictModel):
    schema_version: Literal["coding_case_snapshot_v1"]
    collection: Collection
    identity_secret: SHA
    note: str = Field(max_length=4000)
    projection_policy: dict[str, str]


class CaseMetadata(Governance):
    case_snapshot_id: UUID
    home_id: UUID
    admission_id: UUID
    patient_id: Positive
    rule_package_id: UUID | None
    schema_version: Literal["coding_case_private_v1"]
    created_at: UtcText
    created_by: Positive
    collection_digest: SHA
    content_hash: SHA
    source_id: str
    governance_hash: SHA


class CaseOriginalProof(CaseMetadata):
    snapshot: CaseSnapshot


class CaseWrapper(CaseMetadata):
    review_basis_note: str | None = Field(max_length=4000)
    revoke_reason: str | None = Field(max_length=1000)
    snapshot: CaseSnapshot | None
    public_source: dict | None
    projection_hash: SHA | None
    eligible: bool
    parent_current: bool
    exclusion_reasons: list[str]
    can_record: bool
    can_review: bool
    can_revoke: bool
    audit_only: bool


class PackageWrapper(PackageMetadata):
    review_basis_note: str | None = Field(max_length=4000)
    revoke_reason: str | None = Field(max_length=1000)
    snapshot: RuleSnapshot | None
    eligible: bool
    parent_current: bool
    exclusion_reasons: list[str]
    can_record: bool
    can_review: bool
    can_revoke: bool
    audit_only: bool
