"""Pure frozen RCA task pieces; current authorization is not a view flag."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.ai import rca_evidence_case_contract as k
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_source_contract as s
from app.ai.retry_policy import ProviderRetrySnapshot

TokenCount = Annotated[int, Field(strict=True, ge=0, le=2000000)]


class RcaFrozenCase(c.StrictModel):
    schema_version: Literal["rca_evidence_frozen_case_v1"]
    immutable: k.CaseImmutable
    content_hash: c.SHA
    governance: s.SourceGovernance
    governance_hash: c.SHA
    frozen_task_view: Literal[True]
    execution_current: Literal[False]

    @model_validator(mode="after")
    def frozen_publication(self):
        if self.governance.status != "published" or self.governance.revision != 2:
            raise ValueError("The task retains its actual original published governance, separate from current governance")
        if c.digest(self.immutable) != self.content_hash or c.digest({"case_id": self.immutable.case_id, "content_hash": self.content_hash, "governance": self.governance}) != self.governance_hash:
            raise ValueError("The complete frozen Case and publication hashes differ")
        if c.clock(self.governance.reviewed_at) < c.clock(self.immutable.recorded_at):
            raise ValueError("Original Case publication cannot precede its registration")
        return self

    @field_validator("frozen_task_view", "execution_current", mode="before")
    @classmethod
    def actual_flag(cls, value):
        if type(value) is not bool:
            raise ValueError("Frozen/current declarations are actual booleans")
        return value


class RcaFrozenProvider(ProviderRetrySnapshot, c.StrictModel):
    provider_id: i.PositiveId
    revision: i.PositiveId
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
            raise ValueError("The frozen provider permission is an actual explicit boolean")
        return value

    @model_validator(mode="after")
    def exact_limit(self):
        if self.effective_output_limit > self.max_output_tokens:
            raise ValueError("Actual effective output limit exceeds its configured maximum")
        return self


class RcaFrozenValidation(c.StrictModel):
    status: Literal["unreviewed", "pilot", "validated", "suspended"]
    note: str = Field(max_length=5000)
    validated_by: i.PositiveId | None
    validated_at: str | None = Field(max_length=64)
    feature_revision: i.PositiveId

    @model_validator(mode="after")
    def original_legacy_clock(self):
        import datetime as dt

        if (self.validated_by is None) != (self.validated_at is None):
            raise ValueError("Validation signer and original legacy clock must form a complete signature")
        if self.validated_at is not None:
            parsed = dt.datetime.fromisoformat(self.validated_at)
            if parsed.tzinfo is not None or str(parsed) != self.validated_at:
                raise ValueError("Retain the actual stored naive UTC validation clock without relabeling")
        return self


class RcaUsageReceipt(c.StrictModel):
    input_tokens: TokenCount | None
    output_tokens: TokenCount | None
    complete: bool
    model_call_attempted: bool | None

    @model_validator(mode="after")
    def real_independent_counts(self):
        if self.complete != (self.input_tokens is not None and self.output_tokens is not None):
            raise ValueError("Usage completeness follows only the independently received counts")
        if self.model_call_attempted is False and (self.input_tokens, self.output_tokens) != (0, 0):
            raise ValueError("Only a definitely unattempted call has known0/0 use")
        if self.model_call_attempted is None and (self.input_tokens is not None or self.output_tokens is not None):
            raise ValueError("An interrupted unknown call cannot invent token counts")
        return self


class RcaResultReference(c.StrictModel):
    schema_version: Literal["rca_evidence_result_ref_v1"]
    run_id: c.OpaqueId
    result_hash: c.SHA
    result_bytes: Annotated[int, Field(strict=True, ge=1, le=c.MAX_WIRE_BYTES)]
    accepted_lease: c.OpaqueId
    accept_audit_event_id: i.PositiveId
