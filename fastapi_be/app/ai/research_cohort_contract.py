"""Pure closed research declarations and finite recorded-predicate AST.

These declarations do not prove IRB approval, legal consent, professional
qualification or clinical absence. They cannot express SQL or expand a cohort.
"""

import datetime as dt
import json
import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def scalar(value):
    value.encode("utf-8", errors="strict")
    return value


def basis(value):
    scalar(value)
    if len(value.encode("utf-8")) > 4000 or not value.replace("\ufeff", "").strip():
        raise ValueError("A complete meaningful basis must fit 4000 UTF8 bytes")
    return value


def canonical_uuid(value):
    if str(uuid.UUID(value)) != value:
        raise ValueError("A canonical UUID is required")
    return value


def clock(value):
    if dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%dT%H:%M:%S.%fZ") != value:
        raise ValueError("An exact UTC6 calendar clock is required")
    return value


def date(value):
    if dt.date.fromisoformat(value).isoformat() != value:
        raise ValueError("An exact calendar date is required")
    return value


UUID = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"), AfterValidator(canonical_uuid)]
SHA = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
UTC = Annotated[str, Field(strict=True, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"), AfterValidator(clock)]
Date = Annotated[str, Field(strict=True, pattern=r"^\d{4}-\d{2}-\d{2}$"), AfterValidator(date)]
Positive = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Basis = Annotated[str, Field(strict=True, min_length=20, max_length=4000), AfterValidator(basis)]
Label = Annotated[str, Field(strict=True, min_length=1, max_length=200), AfterValidator(scalar)]
Family = Literal["patient_demographics", "registrations", "admissions", "medical_records", "structured_medical_records"]
ReviewStatus = Literal["unknown", "recorded_reviewed", "not_confirmed"]
ResearchUse = Literal["cohort_criteria_review", "deidentification_review", "research_variable_extraction"]
PROTECTED_CASE_ACCESS_POLICY = "研究临床正文读取和新捕获包括超级管理员在内均须当前项目ACL及逐患者明确研究授权；权限失效仅安全manifest和opaque SHA，不借技术审计恢复患者正文。"
AUTHORIZATION_LIMITATION = "仅记录独立人工核查的项目用途与逐患者授权声明，不自动证明伦理审批、同意法律效力、研究者资格或数据匿名。"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def ordered(values):
    if values != sorted(set(values)):
        raise ValueError("Every complete explicit member must be sorted and distinct")
    return values


class RecordWindow(StrictModel):
    date_from: Date
    date_to: Date
    time_basis: Literal["legacy_naive_calendar_dates_timezone_unknown"]

    @model_validator(mode="after")
    def finite_period(self):
        if not 0 <= (dt.date.fromisoformat(self.date_to) - dt.date.fromisoformat(self.date_from)).days < 366:
            raise ValueError("The recorded legacy calendar window must contain 1..366 days")
        return self


class ScopeCreate(StrictModel):
    protocol_key: Annotated[str, Field(min_length=1, max_length=100), AfterValidator(scalar)]
    title: Annotated[str, Field(min_length=4, max_length=200), AfterValidator(scalar)]
    purpose: Basis
    patient_ids: Annotated[list[Positive], Field(min_length=1, max_length=256), AfterValidator(ordered)]
    proposed_user_ids: Annotated[list[Positive], Field(min_length=1, max_length=64), AfterValidator(ordered)]
    data_families: Annotated[list[Family], Field(min_length=1, max_length=5), AfterValidator(ordered)]
    permitted_uses: Annotated[list[ResearchUse], Field(min_length=1, max_length=3), AfterValidator(ordered)]
    record_window: RecordWindow
    valid_from: UTC
    valid_until: UTC
    external_model_use: Literal["unknown", "recorded_permitted", "not_permitted"]
    external_model_use_basis: Basis
    authority_reference: Label | None
    authorization_basis: Basis

    @model_validator(mode="after")
    def explicit_validity(self):
        if self.valid_until <= self.valid_from:
            raise ValueError("An explicit positive project authorization period is required")
        return self


class ScopeReference(StrictModel):
    scope_id: UUID
    scope_content_hash: SHA
    scope_governance_hash: SHA


class ProjectACLCreate(ScopeReference):
    user_id: Positive
    permission: Literal["read_only", "read_capture"]
    valid_from: UTC
    valid_until: UTC
    basis_note: Basis

    @model_validator(mode="after")
    def explicit_validity(self):
        if self.valid_until <= self.valid_from:
            raise ValueError("An explicit positive grant period is required")
        return self


class PatientAuthorizationCreate(ScopeReference):
    patient_id: Positive
    authorization_kind: Literal["permission_recorded", "waiver_recorded", "unknown", "withdrawn", "denied"]
    access_basis: Literal["explicit_project_acl", "current_care_or_grant"]
    valid_from: UTC | None
    valid_until: UTC | None
    authority_reference: Label | None
    original_authority_text: Annotated[str, Field(min_length=1, max_length=65535), AfterValidator(scalar)] | None
    basis_note: Basis

    @model_validator(mode="after")
    def preserve_unknown_validity(self):
        if (self.valid_from is None) != (self.valid_until is None) or self.valid_from is not None and self.valid_until <= self.valid_from:
            raise ValueError("Unknown periods stay null; a recorded period must remain positive")
        return self


class AuthorizationReview(StrictModel):
    expected_revision: Annotated[int, Field(strict=True, ge=1, le=1)]
    expected_content_hash: SHA
    decision: Literal["recorded_reviewed", "not_confirmed"]
    review_scope: Literal["documentary_authorization_review_not_irb_certification"]
    basis_note: Basis


class SourceReview(StrictModel):
    expected_revision: Annotated[int, Field(strict=True, ge=1, le=1)]
    decision: Literal["publish", "reject"]
    basis_note: Basis


class SourceRevoke(StrictModel):
    expected_revision: Annotated[int, Field(strict=True, ge=1, le=2)]
    basis_note: Annotated[str, Field(strict=True, min_length=20, max_length=1000), AfterValidator(basis)]


SCALAR_FIELDS = {
    "patient_demographics": {"sex"},
    "registrations": {"status", "specialist"},
    "admissions": {"status", "admission_type"},
    "medical_records": {"status"},
    "structured_medical_records": {"status", "record_type"},
}
DATE_FIELDS = {
    "patient_demographics": {"birthday"},
    "registrations": {"time"},
    "admissions": {"admission_time", "discharge_time", "create_time"},
    "medical_records": {"consultation_time", "sign_time"},
    "structured_medical_records": {"create_time", "update_time", "sign_time"},
}
TEXT_FIELDS = {
    "medical_records": {"symptom", "result"},
    "admissions": {"admission_diagnosis", "chief_complaint", "present_illness", "past_history", "discharge_diagnosis"},
    "structured_medical_records": {"chief_complaint", "present_illness", "past_history", "personal_history", "family_history", "physical_exam", "auxiliary_exam", "diagnosis", "treatment_plan"},
}


class RecordedScalarEqual(StrictModel):
    op: Literal["recorded_scalar_equal"]
    family: Family
    field: str
    expected: Annotated[int, Field(strict=True, ge=-2147483648, le=2147483647)]
    quantifier: Literal["any_record", "every_record"]

    @model_validator(mode="after")
    def supported_field(self):
        if self.field not in SCALAR_FIELDS.get(self.family, set()):
            raise ValueError("Unsupported recorded scalar predicate")
        return self


class RecordedDateCompare(StrictModel):
    op: Literal["recorded_date_compare"]
    family: Family
    field: str
    comparison: Literal["before", "on", "after"]
    expected: Date
    quantifier: Literal["any_record", "every_record"]
    time_basis: Literal["legacy_naive_calendar_dates_timezone_unknown"]

    @model_validator(mode="after")
    def supported_field(self):
        if self.field not in DATE_FIELDS.get(self.family, set()):
            raise ValueError("Unsupported original calendar predicate")
        return self


class RecordedTextContains(StrictModel):
    op: Literal["recorded_text_contains"]
    family: Family
    field: str
    literal: Annotated[str, Field(strict=True, min_length=1, max_length=2000), AfterValidator(scalar)]
    quantifier: Literal["any_record", "every_record"]

    @model_validator(mode="after")
    def supported_field(self):
        if self.field not in TEXT_FIELDS.get(self.family, set()):
            raise ValueError("Unsupported complete original text predicate")
        return self


class AllCriteria(StrictModel):
    op: Literal["all"]
    children: Annotated[list["CriteriaNode"], Field(min_length=1, max_length=64)]


class AnyCriteria(StrictModel):
    op: Literal["any"]
    children: Annotated[list["CriteriaNode"], Field(min_length=1, max_length=64)]


class NotCriteria(StrictModel):
    op: Literal["not"]
    child: "CriteriaNode"


CriteriaNode = Annotated[RecordedScalarEqual | RecordedDateCompare | RecordedTextContains | AllCriteria | AnyCriteria | NotCriteria, Field(discriminator="op")]
for model in (AllCriteria, AnyCriteria, NotCriteria):
    model.model_rebuild()


class CohortCriteria(StrictModel):
    schema_version: Literal["research_recorded_criteria_v1"]
    root: CriteriaNode

    @model_validator(mode="after")
    def bounded_finite_tree(self):
        count = 0

        def visit(node, depth):
            nonlocal count
            count += 1
            if count > 64 or depth > 8:
                raise ValueError("The entire supported criteria AST is bounded by64 nodes and8 levels")
            if isinstance(node, (AllCriteria, AnyCriteria)):
                for child in node.children:
                    visit(child, depth + 1)
            elif isinstance(node, NotCriteria):
                visit(node.child, depth + 1)

        visit(self.root, 1)
        return self


class CaptureRequest(ScopeReference):
    criteria: CohortCriteria


class CaseCreate(StrictModel):
    request: CaptureRequest
    expected_collection_digest: SHA
    basis_note: Basis


def canonical_json(value):
    serialized = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)
    serialized.encode("utf-8", errors="strict")
    return serialized


Truth = Literal["true", "false", "unknown"]
LeafPredicate = Annotated[RecordedScalarEqual | RecordedDateCompare | RecordedTextContains, Field(discriminator="op")]


class PublicRecordedEvidence(StrictModel):
    family: Family
    field: str
    record_token: SHA
    original_hash: SHA
    field_hash: SHA
    start: Annotated[int, Field(strict=True, ge=0)] | None
    end: Annotated[int, Field(strict=True, ge=0)] | None
    quote: Annotated[str, Field(strict=True, min_length=1, max_length=2000), AfterValidator(scalar)] | None
    recorded_value: Annotated[int, Field(strict=True)] | Annotated[str, Field(strict=True), AfterValidator(scalar)] | None
    reason: Literal["record_scope_or_parent_unknown", "original_field_missing", "recorded_predicate_only"]
    truth: Truth

    @model_validator(mode="after")
    def original_field_minimization(self):
        if self.field in TEXT_FIELDS.get(self.family, set()):
            if self.recorded_value is not None:
                raise ValueError("A whole original text field is not a minimized public quotation")
            if self.quote is not None:
                if self.start is None or self.end is None or self.end - self.start != len(self.quote) or self.truth != "true":
                    raise ValueError("Exact codepoint quotation bounds required")
            elif self.start is not None or self.end is not None or self.truth == "true":
                raise ValueError("A true recorded text predicate must carry its exact quotation")
        else:
            if self.quote is not None or self.start is not None or self.end is not None:
                raise ValueError("Scalar/date evidence does not invent a text quote")
            if self.field in SCALAR_FIELDS.get(self.family, set()):
                if self.recorded_value is not None and type(self.recorded_value) is not int:
                    raise ValueError("Recorded integer required")
            elif self.field in DATE_FIELDS.get(self.family, set()):
                if self.recorded_value is not None:
                    if type(self.recorded_value) is not str:
                        raise ValueError("Original calendar lexeme required")
                    date(self.recorded_value[:10])
                    if self.field != "birthday" and (
                        dt.datetime.fromisoformat(self.recorded_value).isoformat(timespec="microseconds") != self.recorded_value or dt.datetime.fromisoformat(self.recorded_value).tzinfo is not None
                    ):
                        raise ValueError("Original naive clock required")
            else:
                raise ValueError("Unimplemented evidence field")
        if self.reason != "recorded_predicate_only" and self.truth != "unknown":
            raise ValueError("Unresolved original evidence stays unknown")
        return self


class PublicRecordedLeaf(StrictModel):
    path: Annotated[str, Field(strict=True, pattern=r"^root(?:\.(?:[0-9]+|not))*$")]
    predicate: LeafPredicate
    truth: Truth
    reason: Literal["no_recorded_members", "whole_declared_recorded_family"]
    evidence: Annotated[list[PublicRecordedEvidence], Field(max_length=8192)]

    @model_validator(mode="after")
    def complete_leaf(self):
        if (not self.evidence) != (self.reason == "no_recorded_members") or not self.evidence and self.truth != "unknown":
            raise ValueError("An empty recorded family is explicitly unknown")
        for evidence in self.evidence:
            if (evidence.family, evidence.field) != (self.predicate.family, self.predicate.field):
                raise ValueError("Predicate evidence identity differs")
            if isinstance(self.predicate, RecordedTextContains) and evidence.quote is not None and evidence.quote != self.predicate.literal:
                raise ValueError("Text evidence must be the exact user-declared literal")
        return self


class PublicRecordedOutcome(StrictModel):
    patient_token: SHA
    truth: Truth
    interpretation: Literal["recorded_criteria_only_not_clinical_eligibility"]
    leaves: Annotated[list[PublicRecordedLeaf], Field(min_length=1, max_length=64)]


class PublicResearchMember(StrictModel):
    family: Family
    patient_token: SHA
    record_token: SHA
    original_hash: SHA
    parent_binding_hash: SHA
    window_status: Literal["unknown_clock", "recorded_calendar_in_scope"]


class ResearchRecipe(StrictModel):
    rule_id: Literal["research_recorded_predicates_kleene_v1"]
    implementation_sha256: dict[str, SHA]

    @model_validator(mode="after")
    def exact_modules(self):
        if set(self.implementation_sha256) != {"research_cohort_contract.py", "research_cohort_collection.py", "research_cohort_evaluator.py", "research_cohort_snapshot.py"}:
            raise ValueError("Every frozen algorithm module is declared exactly")
        return self


class PublicResearchCounts(StrictModel):
    declared_patients: Annotated[int, Field(strict=True, ge=1, le=256)]
    recorded_true: Annotated[int, Field(strict=True, ge=0, le=256)]
    recorded_false: Annotated[int, Field(strict=True, ge=0, le=256)]
    unknown: Annotated[int, Field(strict=True, ge=0, le=256)]


class ResearchCohortSource(StrictModel):
    schema_version: Literal["research_cohort_source_v1"]
    source_id: Annotated[str, Field(strict=True, pattern=r"^research_cohort:[a-f0-9-]{36}:[a-f0-9]{12}$")]
    content_hash: SHA
    governance_hash: SHA
    captured_at: UTC
    scope_token: SHA
    authorization_binding_hash: SHA
    collection_digest: SHA
    data_families: Annotated[list[Family], Field(min_length=1, max_length=5), AfterValidator(ordered)]
    record_window: RecordWindow
    member_manifest: Annotated[list[PublicResearchMember], Field(max_length=8192)]
    member_manifest_hash: SHA
    recipe: ResearchRecipe
    criteria: CohortCriteria
    outcomes: Annotated[list[PublicRecordedOutcome], Field(min_length=1, max_length=256)]
    counts: PublicResearchCounts
    limitations: Annotated[list[Annotated[str, Field(min_length=1, max_length=2000), AfterValidator(scalar)]], Field(min_length=1, max_length=16)]
    privacy_basis: Literal["project_authorized_identifier_minimization_not_anonymity"]
    external_model_use: Literal["unknown", "recorded_permitted", "not_permitted"]

    @model_validator(mode="after")
    def full_declared_source(self):
        import hashlib

        parts = self.source_id.split(":")
        canonical_uuid(parts[1])
        if parts[2] != self.content_hash[:12]:
            raise ValueError("Complete private original anchor differs")
        members = [m.model_dump() for m in self.member_manifest]
        if hashlib.sha256(canonical_json(members).encode("utf-8")).hexdigest() != self.member_manifest_hash:
            raise ValueError("Complete public manifest SHA differs")
        by_token = {m.record_token: m for m in self.member_manifest}
        patients = {o.patient_token for o in self.outcomes}
        if len(by_token) != len(self.member_manifest) or len(patients) != len(self.outcomes) or len(self.outcomes) != self.counts.declared_patients:
            raise ValueError("Distinct whole original/member/patient closure required")
        if any(m.patient_token not in patients or m.family not in self.data_families for m in self.member_manifest):
            raise ValueError("Original is outside the explicit declared source")
        for truth, count in (("true", self.counts.recorded_true), ("false", self.counts.recorded_false), ("unknown", self.counts.unknown)):
            if sum(o.truth == truth for o in self.outcomes) != count:
                raise ValueError("Recorded deterministic counts differ")
        expected_paths = {}

        def leaf_paths(node, path):
            if node.op in {"all", "any"}:
                for index, child in enumerate(node.children):
                    leaf_paths(child, f"{path}.{index}")
            elif node.op == "not":
                leaf_paths(node.child, path + ".not")
            else:
                if node.family not in self.data_families:
                    raise ValueError("A predicate cannot grow the project family scope")
                expected_paths[path] = node.model_dump()

        leaf_paths(self.criteria.root, "root")
        for outcome in self.outcomes:
            if {leaf.path: leaf.predicate.model_dump() for leaf in outcome.leaves} != expected_paths or len(outcome.leaves) != len(expected_paths):
                raise ValueError("Every finite criteria leaf is accounted exactly once")
            for leaf in outcome.leaves:
                expected = {m.record_token for m in self.member_manifest if m.patient_token == outcome.patient_token and m.family == leaf.predicate.family}
                actual = {e.record_token for e in leaf.evidence}
                if expected != actual or len(actual) != len(leaf.evidence):
                    raise ValueError("No original member may be dropped from a recorded predicate")
                for evidence in leaf.evidence:
                    member = by_token[evidence.record_token]
                    if evidence.original_hash != member.original_hash:
                        raise ValueError("Evidence original hash differs from whole manifest")
        return self
