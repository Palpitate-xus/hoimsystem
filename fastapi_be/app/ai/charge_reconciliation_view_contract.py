"""Closed task and receipt DTOs with no runtime, settings or database engine."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai import charge_reconciliation_contract as c
from app.ai.charge_reconciliation_contract import MAX_BYTES, SHA, UUID, Positive, StrictModel, UtcText


class ChargeArtifactRecord(StrictModel):
    schema_version: Literal["charge_run_artifact_v1"]
    run_id: UUID
    case_snapshot_id: UUID
    requested_by: Positive
    created_at: UtcText
    input_hash: SHA
    evidence_hash: SHA
    metadata_hash: SHA
    prompt_hash: SHA
    context_digest: SHA
    source_binding_hash: SHA
    result_hash: SHA | None
    result_bytes: Annotated[int, Field(strict=True, ge=1, le=MAX_BYTES)] | None
    receipt_event_id: Positive | None
    accepted_lease: UUID | None


Count = Annotated[int, Field(strict=True, ge=0, le=2000000)]


class ChargeUsage(c.StrictModel):
    input_tokens: Count | None
    output_tokens: Count | None
    complete: bool
    model_call_attempted: bool | None

    @model_validator(mode="after")
    def actual_receipt(self):
        if self.complete != (self.input_tokens is not None and self.output_tokens is not None):
            raise ValueError("Receipt completeness must preserve independently reported counts")
        if self.model_call_attempted is False and (self.input_tokens, self.output_tokens) != (0, 0):
            raise ValueError("An actual unattempted call has known zero usage")
        if self.model_call_attempted is None and (self.input_tokens is not None or self.output_tokens is not None):
            raise ValueError("Pending call state cannot invent token counts")
        return self


class ChargeResultReference(c.StrictModel):
    schema_version: Literal["charge_result_ref_v1"]
    run_id: c.UUID
    case_snapshot_id: c.UUID
    lease_token: c.UUID
    content_hash: c.SHA
    result_bytes: Annotated[int, Field(strict=True, ge=1, le=c.MAX_BYTES)]
    source_binding_hash: c.SHA
    receipt_event_id: c.Positive


class ChargeReceiptEvent(c.StrictModel):
    schema_version: Literal["charge_reconciliation_receipt_v1"]
    lease_token: c.UUID | None
    usage: ChargeUsage
    result_hash: c.SHA | None
    source_binding_hash: c.SHA
    error_code: str | None = Field(max_length=80)
