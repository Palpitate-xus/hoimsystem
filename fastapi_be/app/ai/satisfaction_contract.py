"""Closed review evidence contracts; legacy dates and manual claims remain explicit."""

import datetime
import hashlib
import json
import math
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

UUID = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
SHA = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[int, Field(strict=True, gt=0, le=2147483647)]
Count = Annotated[int, Field(strict=True, ge=0, le=8192)]


def real_date(value):
    datetime.date.fromisoformat(value)
    return value


def real_utc(value):
    datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    return value


Date = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"), AfterValidator(real_date)]
UTC = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"), AfterValidator(real_utc)]
ScopeKind = Literal["hospital_reviews", "explicit_doctor_cohort"]
SOURCE_ROLES = frozenset({"admin", "director", "super_admin"})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


def check_basis(value):
    if len(value) < 20 or not value.strip() or len(value.encode("utf-8")) > 4000:
        raise ValueError("Explicit nonblank20..4000characters and at most4000UTF8bytes required")
    return value


Basis = Annotated[str, Field(min_length=20, max_length=4000), AfterValidator(check_basis)]


class CaptureRequest(StrictModel):
    scope_kind: ScopeKind
    doctor_ids: list[Positive] = Field(max_length=256)
    date_from: Date
    date_to: Date

    @model_validator(mode="after")
    def closed_scope(self):
        if self.doctor_ids != sorted(set(self.doctor_ids)):
            raise ValueError("Doctor cohort must be sorted unique actual identifiers")
        if bool(self.doctor_ids) != (self.scope_kind == "explicit_doctor_cohort"):
            raise ValueError("Hospital scope has no doctor filter; explicit cohort requires1..256Doctors")
        days = (datetime.date.fromisoformat(self.date_to) - datetime.date.fromisoformat(self.date_from)).days + 1
        if not 1 <= days <= 366:
            raise ValueError("An explicit1..366day legacy naive calendar interval is required")
        return self


class ExcerptSelection(StrictModel):
    excerpt_id: UUID
    review_token: SHA
    content_hash: SHA
    governance_hash: SHA


class CaseCreate(StrictModel):
    request: CaptureRequest
    expected_collection_digest: SHA
    selected_excerpts: list[ExcerptSelection] = Field(max_length=8192)
    basis_note: Basis

    @model_validator(mode="after")
    def unique_versions(self):
        if len({v.excerpt_id for v in self.selected_excerpts}) != len(self.selected_excerpts):
            raise ValueError("An excerpt version cannot be selected twice")
        return self


class SourceReview(StrictModel):
    expected_revision: Annotated[int, Field(strict=True, ge=1, le=3)]
    decision: Literal["publish", "reject"]
    basis_note: Basis


class SourceRevoke(StrictModel):
    expected_revision: Annotated[int, Field(strict=True, ge=1, le=3)]
    basis_note: Annotated[str, Field(min_length=20, max_length=1000), AfterValidator(check_basis)]


class LegacyScalar(StrictModel):
    kind: Literal["null", "integer", "real", "text"]
    text: str | None

    @model_validator(mode="after")
    def null_value(self):
        if (self.kind == "null") != (self.text is None):
            raise ValueError("Original SQL scalar type/text must agree")
        if self.kind == "integer" and str(int(self.text)) != self.text:
            raise ValueError("Integer scalar lexeme must be canonical")
        return self


class ReviewOriginal(StrictModel):
    review_id: Positive
    patient_id: Positive | None
    doctor_id: Positive | None
    visit_id: str | None
    score: LegacyScalar
    comment: str | None
    review_time: str | None


class ExcerptOriginal(StrictModel):
    excerpt_id: UUID
    review_id: Positive
    version: int | None
    source_hash: str
    department_id: Positive
    redacted_text: str
    text_hash: str
    change_note: str
    status: str | None
    revision: int | None
    privacy_checked: int
    faithfulness_checked: int
    review_note: str
    created_by: Positive
    create_time: str
    reviewed_by: Positive | None
    reviewed_at: str | None
    retired_by: Positive | None
    retired_at: str | None


class DoctorOriginal(StrictModel):
    doctor_id: Positive
    department_id: Positive | None
    user_id: Positive | None
    name: str | None
    phone: str | None


class PatientOriginal(StrictModel):
    patient_id: Positive
    name: str | None
    identity: str | None
    phone: str | None
    address: str | None


class VisitOriginal(StrictModel):
    medical_record_id: str
    patient_id: Positive | None
    doctor_id: Positive | None
    registration_uuid: str | None


class RegistrationOriginal(StrictModel):
    registration_uuid: str
    patient_id: Positive | None
    doctor_id: Positive | None
    department_id: Positive | None


class ReviewerOriginal(StrictModel):
    user_id: Positive
    user_role: str | None


class Parents(StrictModel):
    doctors: list[DoctorOriginal] = Field(max_length=8192)
    patients: list[PatientOriginal] = Field(max_length=8192)
    visits: list[VisitOriginal] = Field(max_length=8192)
    registrations: list[RegistrationOriginal] = Field(max_length=8192)
    department_ids: list[Positive] = Field(max_length=8192)
    reviewers: list[ReviewerOriginal] = Field(max_length=8192)


class Collection(StrictModel):
    schema_version: Literal["satisfaction_collection_private_v1"]
    request: CaptureRequest
    captured_at: UTC
    reviews: list[ReviewOriginal] = Field(max_length=8192)
    excerpts: list[ExcerptOriginal] = Field(max_length=8192)
    parents: Parents
    collection_digest: SHA


class Snapshot(StrictModel):
    schema_version: Literal["satisfaction_case_private_v1"]
    case_id: UUID
    created_at: UTC
    created_by: Positive
    identity_secret: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    request: CaseCreate
    collection: Collection
    policy: dict


class ExactFraction(StrictModel):
    numerator: Annotated[int, Field(strict=True, ge=1, le=40960)]
    denominator: Annotated[int, Field(strict=True, ge=1, le=8192)]


class ScoreStatistics(StrictModel):
    record_count: Count
    valid_score_count: Count
    null_score_count: Count
    invalid_score_count: Count
    histogram: dict[Literal["1", "2", "3", "4", "5"], Count]
    mean_valid_score: ExactFraction | None

    @model_validator(mode="after")
    def exact_counts(self):
        if set(self.histogram) != {"1", "2", "3", "4", "5"} or sum(self.histogram.values()) != self.valid_score_count:
            raise ValueError("Five exact valid-score histogram buckets required")
        if self.record_count != self.valid_score_count + self.null_score_count + self.invalid_score_count:
            raise ValueError("Every recorded rating must have one score bucket")
        total = sum(int(k) * v for k, v in self.histogram.items())
        if not self.valid_score_count:
            if self.mean_valid_score is not None:
                raise ValueError("No valid scores has an unknown mean, not zero")
        else:
            divisor = math.gcd(total, self.valid_score_count)
            if self.mean_valid_score is None or self.mean_valid_score.model_dump() != {"numerator": total // divisor, "denominator": self.valid_score_count // divisor}:
                raise ValueError("Mean must be the reduced exact fraction of valid scores only")
        return self


class PublicMember(StrictModel):
    kind: Literal["review", "excerpt"]
    member_token: SHA
    review_token: SHA
    content_hash: SHA
    governance_hash: SHA | None
    status: Literal["not_applicable", "draft", "published", "rejected", "retired", "unknown"]
    version: int | None
    revision: int | None
    selected: bool
    eligibility: Literal["original_record", "eligible_manual_claim", "ineligible_manual_claim"]
    exclusion_reasons: list[str]


class SafeReview(StrictModel):
    review_token: SHA
    content_hash: SHA
    recorded_date: Date | None
    date_status: Literal["in_period_legacy_naive", "unknown_legacy_clock"]
    recorded_score: Annotated[int, Field(strict=True, ge=1, le=5)] | None
    score_status: Literal["valid_1_to_5", "null", "invalid"]
    parent_status: Literal["consistent_actual_links", "unresolved_actual_links"]
    has_comment: bool


class SafeExcerpt(StrictModel):
    excerpt_token: SHA
    review_token: SHA
    original_content_hash: SHA
    original_governance_hash: SHA
    text: str
    text_hash: SHA
    version: int
    review_basis_hash: SHA
    claim: Literal["legacy_manual_privacy_and_faithfulness_review_not_anonymity_or_fact_verification"]


class SafeSnapshot(StrictModel):
    schema_version: Literal["satisfaction_safe_snapshot_v1"]
    case_id: UUID
    scope_kind: ScopeKind
    doctor_cohort_size: Annotated[int, Field(strict=True, ge=0, le=256)] | None
    date_from: Date
    date_to: Date
    time_basis: Literal["stored_legacy_naive_calendar_timezone_unknown"]
    unknown_date_member_count: Count
    unresolved_parent_count: Count
    all_member_statistics: ScoreStatistics
    known_period_statistics: ScoreStatistics
    reviews: list[SafeReview] = Field(max_length=8192)
    selected_excerpts: list[SafeExcerpt] = Field(max_length=8192)
    member_manifest: list[PublicMember] = Field(max_length=8192)
    member_manifest_hash: SHA
    policy_hash: SHA


class SatisfactionSource(StrictModel):
    schema_version: Literal["satisfaction_source_v1"]
    source_id: str
    case_id: UUID
    content_hash: SHA
    governance_hash: SHA
    collection_digest: SHA
    safe_projection_hash: SHA
    safe_snapshot: SafeSnapshot

    @model_validator(mode="after")
    def exact_anchor(self):
        if self.source_id != f"satisfaction_case:{self.case_id}:{self.content_hash[:12]}" or self.case_id != self.safe_snapshot.case_id:
            raise ValueError("Safe source identity and protected immutable anchor differ")
        raw = json.dumps(self.safe_snapshot.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if hashlib.sha256(raw).hexdigest() != self.safe_projection_hash:
            raise ValueError("Complete safe projection SHA differs")
        return self


class ExcerptOption(ExcerptSelection):
    status: Literal["draft", "published", "rejected", "retired", "unknown"]
    version: int | None
    eligible: bool
    exclusion_reasons: list[str]
    reviewed_text: str | None


class SafeCapture(StrictModel):
    schema_version: Literal["satisfaction_capture_safe_v1"]
    request: CaptureRequest
    captured_at: UTC
    collection_digest: SHA
    safe_snapshot: SafeSnapshot
    safe_projection_hash: SHA
    excerpt_options: list[ExcerptOption] = Field(max_length=8192)


class CaseMetadata(StrictModel):
    case_id: UUID
    schema_version: Literal["satisfaction_case_private_v1"]
    scope_kind: ScopeKind
    date_from: Date
    date_to: Date
    created_at: UTC
    created_by: Positive
    content_hash: SHA
    collection_digest: SHA
    source_id: str
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: Annotated[int, Field(strict=True, ge=1, le=3)]
    reviewed_at: UTC | None
    reviewed_by: Positive | None
    review_basis_note: str | None
    revoked_at: UTC | None
    revoked_by: Positive | None
    revoke_reason: str | None
    governance_hash: SHA


class CaseWrapper(CaseMetadata):
    snapshot: Snapshot | None
    safe_snapshot: SafeSnapshot | None
    safe_projection_hash: SHA | None
    public_source: SatisfactionSource | None
    projection_hash: SHA | None
    parent_current: bool
    eligible: bool
    exclusion_reasons: list[str]
    can_record: Literal[False]
    can_review: bool
    can_revoke: bool
    audit_only: bool
    raw_content_hash_verification: Literal["protected_full_original_verified_server_side_not_reconstructible_from_safe_view"]

    @model_validator(mode="after")
    def ordinary_privacy(self):
        if not self.audit_only and (self.snapshot is not None or self.review_basis_note is not None or self.revoke_reason is not None):
            raise ValueError("Ordinary responses never contain raw originals or private governance notes")
        return self


POLICY = {
    "schema_version": "satisfaction_projection_policy_v1",
    "scope": "hospital_reviews_or_explicit_finite_current_doctor_cohort_not_historical_department",
    "time": "legacy_naive_calendar_unknown_timezone_null_or_unparseable_clocks_retained",
    "statistics": "all_records_and_known_period_separately_valid_1_to_5_exact_fraction_not_nps_response_rate_or_complaint_handling",
    "text": "only_explicit_selected_current_published_legacy_manual_privacy_and_faithfulness_claims_not_guaranteed_anonymous_or_professional_facts",
    "closure": "all_related_review_and_excerpt_versions_all_or_refuse_no_latest_or_favourable_winner",
    "privacy": "per_case_random_hmac_tokens_raw_comments_patient_visit_identifiers_and_private_basis_never_in_ordinary_or_model_source",
    "limits": {"max_roots": 8192, "max_private_utf8_bytes": 8388608, "max_scope_metadata_scanned": 200000},
}
