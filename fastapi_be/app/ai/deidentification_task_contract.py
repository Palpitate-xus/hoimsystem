"""Closed75 task snapshots. None of these pure types grants research access."""

import datetime as dt
from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, Field, model_validator

from app.ai.deidentification_contract import SOURCE_ROLES, StrictModel
from app.ai.deidentification_frozen import DeidentificationFrozenPrompt
from app.ai.deidentification_protocol import question_valid
from app.ai.research_cohort_contract import SHA, UTC, UUID, Positive, scalar

FEATURE_KEY = "deidentification"


def original_clock(value):
    if value is not None:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is not None or str(parsed) != value:
            raise ValueError("Original naive UTC SQL clock required")
    return value


NaiveClock = Annotated[str, Field(strict=True, min_length=19, max_length=26), AfterValidator(original_clock)]
Role = Literal["super_admin", "admin", "director", "doctor", "pharmacist"]


def actual_true(value):
    if type(value) is not bool or value is not True:
        raise ValueError("Actual explicit patient-data permission required")
    return value


class TaskInput(StrictModel):
    deidentification_case_id: UUID
    question: Annotated[str, Field(strict=True, max_length=2000), AfterValidator(scalar)] | None = None

    @model_validator(mode="after")
    def literal_question(self):
        if not question_valid(self.question):
            raise ValueError("Original optional question exceeds2000CP/8000UTF8B")
        return self


def selection(value):
    checked = TaskInput.model_validate(value, strict=True)
    return checked.model_dump(exclude_unset=True)


class FrozenProvider(StrictModel):
    provider_id: Positive
    revision: Positive
    name: Annotated[str, Field(strict=True, min_length=1, max_length=80), AfterValidator(scalar)]
    kind: Literal["chat", "responses"]
    api_base: Annotated[str, Field(strict=True, min_length=1, max_length=1000), AfterValidator(scalar)]
    model: Annotated[str, Field(strict=True, min_length=1, max_length=160), AfterValidator(scalar)]
    timeout_seconds: Annotated[int, Field(strict=True, ge=3, le=120)]
    max_output_tokens: Annotated[int, Field(strict=True, ge=256, le=16000)]
    validation_report: Annotated[str, Field(strict=True, max_length=5000), AfterValidator(scalar)]
    temperature: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
    allows_patient_data: Annotated[Literal[True], BeforeValidator(actual_true)]
    effective_output_limit: Annotated[int, Field(strict=True, ge=1, le=16000)]

    @model_validator(mode="after")
    def actual_output_limit(self):
        if self.effective_output_limit > self.max_output_tokens:
            raise ValueError("Effective output cannot exceed configured maximum")
        return self


class FrozenValidation(StrictModel):
    status: Literal["unreviewed", "pilot", "validated", "suspended"]
    note: Annotated[str, Field(strict=True, max_length=5000), AfterValidator(scalar)]
    validated_by: Positive | None
    validated_at: NaiveClock | None
    feature_revision: Positive


class RequesterEpoch(StrictModel):
    user_id: Positive
    user_role: Role
    token_invalid_before: NaiveClock | None


class FrozenExecution(StrictModel):
    feature_key: Literal["deidentification"]
    feature_revision: Positive
    allowed_roles: Annotated[list[Role], Field(min_length=1, max_length=len(SOURCE_ROLES))]
    requester_epoch: RequesterEpoch
    preview: bool
    snapshot_time: UTC

    @model_validator(mode="after")
    def exact_roles(self):
        if self.allowed_roles != sorted(set(self.allowed_roles)) or self.requester_epoch.user_role not in self.allowed_roles:
            raise ValueError("Complete sorted allowed roles and original role required")
        return self


class PublicBinding(StrictModel):
    case_id: UUID
    source_id: str
    content_hash: SHA
    governance_hash: SHA
    collection_digest: SHA
    projection_hash: SHA


class FrozenTaskRecord(StrictModel):
    schema_version: Literal["deidentification_task_v1"]
    catalog_version: str
    input: TaskInput
    context: PublicBinding
    provider: FrozenProvider
    validation: FrozenValidation
    execution: FrozenExecution
    prompt: dict


class TaskSourceRecord(StrictModel):
    schema_version: Literal["deidentification_task_source_v1"]
    source_snapshot: dict
    publication: dict
    public_source: dict
    prompt: DeidentificationFrozenPrompt
    provider: FrozenProvider
    validation: FrozenValidation
    execution: FrozenExecution
