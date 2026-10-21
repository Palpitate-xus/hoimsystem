"""Closed selected-field deidentification declarations, not anonymity proof."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, Field, model_validator

from app.ai.research_cohort_contract import SHA, UTC, UUID, Basis, Label, Positive, ScopeReference, StrictModel, basis, scalar

MAX_BYTES = 8 * 1024 * 1024
MAX_ROOTS = 8192
MAX_DOCUMENTS = 64
MAX_EDITS = 1024
SOURCE_ROLES = frozenset({"super_admin", "admin", "director", "doctor", "pharmacist"})
TEXT_FIELDS = {
    "medical_records": ("symptom", "result"),
    "admissions": ("admission_diagnosis", "chief_complaint", "present_illness", "past_history", "discharge_diagnosis"),
    "structured_medical_records": ("chief_complaint", "present_illness", "past_history", "personal_history", "family_history", "physical_exam", "auxiliary_exam", "diagnosis", "treatment_plan"),
}
LIMITATIONS = (
    "仅处理本项目中单个明确患者所选的完整文字字段，不代表完整病历或数据集。",
    "逐字位置、规则匹配和人工核查均不能保证识别全部姓名、组合标识或重识别风险；未额外读取姓名字典。",
    "不自动日期偏移、跨文书假名映射、临床值改写或匿名保证。",
    "项目、逐患者和导出依据仅为受审记录，不构成服务器对伦理批准、同意法律效力或专业资质的认证。",
)
MASKS = {"mask": "[已遮蔽]", "remove": ""}
Text = Annotated[str, Field(strict=True, max_length=MAX_BYTES), AfterValidator(scalar)]
# Legacy PKs are actual bounded strings, not necessarily canonical UUIDs.
RecordID = Annotated[str, Field(strict=True, min_length=1, max_length=36), AfterValidator(scalar)]


def confirmed(value):
    if type(value) is not bool or value is not True:
        raise ValueError("A real explicit confirmation is required")
    return value


Confirmed = Annotated[Literal[True], BeforeValidator(confirmed)]


class FieldSelection(StrictModel):
    family: Literal["medical_records", "admissions", "structured_medical_records"]
    record_id: RecordID
    field: str
    expected_original_hash: SHA

    @model_validator(mode="after")
    def supported_field(self):
        if self.field not in TEXT_FIELDS[self.family]:
            raise ValueError("Only an explicitly supported complete text field may be selected")
        return self


class PatientScopeRequest(ScopeReference):
    patient_id: Positive


class CaptureRequest(PatientScopeRequest):
    documents: Annotated[list[FieldSelection], Field(min_length=1, max_length=MAX_DOCUMENTS)]

    @model_validator(mode="after")
    def complete_explicit_selection(self):
        keys = [(x.family, x.record_id, x.field) for x in self.documents]
        if keys != sorted(set(keys)):
            raise ValueError("Explicit fields must be sorted and distinct")
        return self


class CaseCreate(StrictModel):
    request: CaptureRequest
    expected_collection_digest: SHA
    basis_note: Basis


class SpanEdit(StrictModel):
    document_source_id: Annotated[str, Field(strict=True, min_length=1, max_length=160), AfterValidator(scalar)]
    text_hash: SHA
    start: Annotated[int, Field(strict=True, ge=0, le=MAX_BYTES)]
    end: Annotated[int, Field(strict=True, ge=1, le=MAX_BYTES)]
    quote: Annotated[str, Field(strict=True, min_length=1, max_length=MAX_BYTES), AfterValidator(scalar)]
    action: Literal["mask", "remove"]

    @model_validator(mode="after")
    def positive_span(self):
        if self.start >= self.end:
            raise ValueError("A selected edit must cover a nonempty original codepoint range")
        return self


class ReviewCreate(StrictModel):
    case_id: UUID
    expected_content_hash: SHA
    expected_governance_hash: SHA
    edits: Annotated[list[SpanEdit], Field(max_length=MAX_EDITS)]
    selection_confirmed: Confirmed
    unselected_fields_not_covered: Confirmed
    basis_note: Basis


class ResidualReview(StrictModel):
    expected_revision: Annotated[int, Field(strict=True, ge=1, le=1)]
    expected_content_hash: SHA
    decision: Literal["reviewed_residual_risk_remains", "not_confirmed"]
    review_scope: Literal["complete_selected_output_only_not_anonymity_certification"]
    residual_risks: Annotated[list[Label], Field(min_length=1, max_length=64)]
    basis_note: Basis


class GovernanceReview(StrictModel):
    expected_revision: Annotated[int, Field(strict=True, ge=1, le=1)]
    expected_content_hash: SHA
    decision: Literal["publish", "reject"]
    basis_note: Basis


class GovernanceRevoke(StrictModel):
    expected_revision: Annotated[int, Field(strict=True, ge=1, le=2)]
    expected_content_hash: SHA
    basis_note: Annotated[str, Field(strict=True, min_length=20, max_length=1000), AfterValidator(basis)]


class ReleaseCreate(StrictModel):
    review_id: UUID
    expected_content_hash: SHA
    expected_governance_hash: SHA
    authority_status: Literal["unknown", "recorded_permitted", "not_permitted"]
    authority_reference: Label | None
    original_authority_text: Annotated[str, Field(strict=True, min_length=1, max_length=65535), AfterValidator(scalar)] | None
    recipient_scope: Literal["internal_named_recipient", "explicit_external_recipient"]
    recipient_reference: Label
    declared_purpose: Basis
    valid_from: UTC | None
    valid_until: UTC | None
    maximum_downloads: Annotated[int, Field(strict=True, ge=1, le=100)]
    residual_risk_acknowledged: Confirmed
    basis_note: Basis

    @model_validator(mode="after")
    def original_unknown_period(self):
        if (self.valid_from is None) != (self.valid_until is None) or self.valid_from is not None and self.valid_until <= self.valid_from:
            raise ValueError("Unknown validity stays null; a stated interval must be positive")
        return self


class ReleaseAuthorityReview(ResidualReview):
    # A reviewer explicitly checks the recorded authority, recipient and period,
    # in addition to the selected output. Neither signature certifies legality.
    review_scope: Literal["recorded_authority_recipient_period_and_selected_output_not_legal_certification"]
