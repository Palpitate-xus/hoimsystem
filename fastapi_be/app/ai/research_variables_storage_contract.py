"""Pure short76 frozen task and independently nullable usage contracts.

These types check original bytes and self-consistency, never current SQL
permission. The actual ACL/patient anchors are loaded separately before TEXT.
"""

import datetime as dt
import hashlib
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.ai.research_cohort_contract import SHA, UTC, UUID, Basis, Positive, StrictModel, scalar
from app.ai.research_variables_fields import LIMITATIONS
from app.ai.research_variables_prompt import SYSTEM_PROMPT
from app.ai.research_variables_task_binding import VariableTaskBinding, binding_reference, evidence_for_binding
from app.ai.research_variables_task_contract import MAX_RUN_TEXT_BYTES, SOURCE_DOMAIN, TaskRole, VariableTaskSelection, canonical, digest, validate_question


class VariableFrozenProvider(StrictModel):
    provider_id: Positive
    revision: Positive
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["chat", "responses"]
    api_base: str = Field(min_length=1, max_length=2000)
    model: str = Field(min_length=1, max_length=200)
    timeout_seconds: Annotated[int, Field(strict=True, ge=3, le=120)]
    max_output_tokens: Annotated[int, Field(strict=True, ge=256, le=16000)]
    validation_report: str = Field(max_length=5000)
    temperature: float = Field(ge=0, le=1, allow_inf_nan=False)
    allows_patient_data: Literal[True]
    effective_output_limit: Annotated[int, Field(strict=True, ge=1, le=16000)]

    @field_validator("allows_patient_data", mode="before")
    @classmethod
    def actual_permission(cls, value):
        if value is not True:
            raise ValueError("An explicitly permitted model provider is required, not an integer flag")
        return value

    @model_validator(mode="after")
    def exact_limit(self):
        if self.effective_output_limit > self.max_output_tokens:
            raise ValueError("Effective output capacity cannot exceed the actual provider limit")
        return self


class VariableFrozenValidation(StrictModel):
    status: Literal["unreviewed", "pilot", "validated", "suspended"]
    note: str = Field(max_length=5000)
    validated_by: Positive | None
    validated_at: str | None = Field(max_length=64)
    feature_revision: Positive

    @model_validator(mode="after")
    def actual_legacy_clock(self):
        if (self.validated_by is None) != (self.validated_at is None):
            raise ValueError("The original actual validation signer and naive clock are one pair")
        if self.validated_at is not None:
            stamp = dt.datetime.fromisoformat(self.validated_at)
            if stamp.tzinfo is not None or str(stamp) != self.validated_at:
                raise ValueError("Retain the original stored naive validation clock without relabeling")
        return self


class VariablePromptOrigin(StrictModel):
    prompt_id: UUID | None
    prompt_version: Annotated[int, Field(strict=True, ge=0, le=2147483647)]

    @model_validator(mode="after")
    def exact_origin(self):
        if (self.prompt_version == 0) != (self.prompt_id is None):
            raise ValueError("A custom Prompt has its real UUID and positive version; default has neither")
        return self


class VariableBindingReference(StrictModel):
    schema_version: Literal["research_variable_task_binding_ref_v1"]
    batch_id: UUID
    scope_id: UUID
    requested_by: Positive
    binding_hash: SHA
    request_authorization_hash: SHA
    source_projection_hash: SHA
    private_scope_hash: SHA


class VariableShortScope(StrictModel):
    source_domain: Literal[SOURCE_DOMAIN]
    selected_sources: dict[str, UUID]

    @model_validator(mode="after")
    def only_reference(self):
        if set(self.selected_sources) != {"research_variable_batch_id"}:
            raise ValueError("Only the explicit variable Batch may be selected")
        return self


class VariableShortContext(StrictModel):
    scope: VariableShortScope
    snapshot_time: UTC
    research_variable_binding: VariableBindingReference
    question: str | None
    missing_data: list[str] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete_original_context(self):
        if self.scope.selected_sources["research_variable_batch_id"] != self.research_variable_binding.batch_id or self.missing_data != list(LIMITATIONS):
            raise ValueError("Original Batch and complete fixed limitations must remain unchanged")
        if self.question is not None:
            validate_question(self.question)
        canonical(self, MAX_RUN_TEXT_BYTES)
        return self


class VariableTaskEvidence(StrictModel):
    source_id: str = Field(min_length=1, max_length=100)
    kind: Literal["research_variable_batch"]
    content_hash: SHA
    governance_hash: SHA
    source_digest: SHA
    documents_hash: SHA
    coverage: Literal["all_declared_recorded_candidates_no_inferred_absence_or_automatic_winner"]


class VariableStoredPayload(StrictModel):
    input: VariableTaskSelection
    context: VariableShortContext
    tools: dict
    evidence: list[VariableTaskEvidence] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def whole_short_payload(self):
        bound = self.context.research_variable_binding
        if self.input.research_variable_batch_id != bound.batch_id or self.input.question != self.context.question or self.tools != {}:
            raise ValueError("Task input, original question and no-tools context must agree")
        if self.evidence[0].source_digest != bound.source_projection_hash:
            raise ValueError("The original complete Source SHA must remain in its sole citation")
        canonical(self, MAX_RUN_TEXT_BYTES)
        return self


class VariableActorEpoch(StrictModel):
    user_role: TaskRole
    token_invalid_before: UTC | None


class VariablePublishedBatchGovernance(StrictModel):
    status: Literal["published"]
    revision: Literal[2]
    reviewed_by: Positive
    reviewed_at: UTC
    review_basis_note: Basis
    revoked_by: None
    revoked_at: None
    revoke_reason: Literal[""]


class VariableTaskSnapshot(StrictModel):
    schema_version: Literal["research_variable_task_snapshot_v1"]
    catalog_version: str = Field(min_length=1, max_length=64)
    system_prompt: Literal[SYSTEM_PROMPT]
    task_prompt: str = Field(min_length=1, max_length=65535)
    prompt_origin: VariablePromptOrigin
    payload: VariableStoredPayload
    provider_snapshot: VariableFrozenProvider
    feature_validation: VariableFrozenValidation
    batch_publication: VariablePublishedBatchGovernance
    actor_epoch: VariableActorEpoch
    run_clock_basis: Literal["legacy_utc_second_storage"]

    @model_validator(mode="after")
    def whole_storage_budget(self):
        scalar(self.task_prompt)
        if self.actor_epoch.token_invalid_before is not None and self.actor_epoch.token_invalid_before > self.payload.context.snapshot_time:
            raise ValueError("Actual original token epoch cannot follow the task preparation clock")
        if self.batch_publication.reviewed_at > self.payload.context.snapshot_time:
            raise ValueError("The actual selected publication must precede task preparation")
        canonical(self, MAX_RUN_TEXT_BYTES)
        return self


def checked_snapshot(value, binding):
    snapshot = VariableTaskSnapshot.model_validate(value)
    binding = VariableTaskBinding.model_validate(binding)
    if snapshot.payload.context.research_variable_binding.model_dump() != binding_reference(binding):
        raise ValueError("The independent complete permission/Source Binding differs from the short Run")
    if snapshot.payload.evidence[0].model_dump() != evidence_for_binding(binding)[0]:
        raise ValueError("The exact one original citation cannot be rewritten by both copies")
    access = binding.request_authorization
    if snapshot.actor_epoch.model_dump() != {"user_role": access.actor_role, "token_invalid_before": access.actor_token_invalid_before}:
        raise ValueError("Actual original request epoch differs from the full permission manifest")
    if (
        digest({"batch_id": binding.batch_id, "content_hash": binding.batch_content_hash, "governance": snapshot.batch_publication.model_dump(), "last_event_id": binding.batch_last_event_id})
        != binding.batch_governance_hash
    ):
        raise ValueError("Actual full original publication signature differs from the independent Batch anchor")
    return snapshot


def prompt_hash(snapshot):
    value = VariableTaskSnapshot.model_validate(snapshot)
    return digest([value.system_prompt, value.task_prompt])


def instructions_digest(snapshot):
    value = VariableTaskSnapshot.model_validate(snapshot)
    return hashlib.sha256((value.system_prompt + "\n\n" + value.task_prompt).encode("utf-8")).hexdigest()


Count = Annotated[int, Field(strict=True, ge=0, le=2000000)]


class VariableUsageReceipt(StrictModel):
    input_tokens: Count | None
    output_tokens: Count | None
    complete: bool
    model_call_attempted: bool | None

    @model_validator(mode="after")
    def real_independent_counts(self):
        if self.complete != (self.input_tokens is not None and self.output_tokens is not None):
            raise ValueError("Completeness follows only the two independently reported actual counts")
        if self.model_call_attempted is False and (self.input_tokens, self.output_tokens) != (0, 0):
            raise ValueError("A definitely unattempted delivery alone permits known0/0")
        if self.model_call_attempted is None and (self.input_tokens is not None or self.output_tokens is not None):
            raise ValueError("A truly interrupted unknown call cannot invent received usage")
        return self
