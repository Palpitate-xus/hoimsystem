"""Pure leaflet artifact pointer and independently nullable terminal usage."""

from typing import Literal

from pydantic import Field, model_validator

from app.ai import document_evidence_contract as d
from app.ai.document_extraction_view_contract import DocumentFrozenProvider as DrugLabelFrozenProvider
from app.ai.document_extraction_view_contract import DocumentFrozenValidation as DrugLabelFrozenValidation

CREATE_ACTION = "run.drug_label.create"
USAGE_ACTION = "run.drug_label.usage"
ACCEPT_ACTION = "run.drug_label.accept"
MAX_TEXT_BYTES = 65535
MAX_RESULT_BYTES = 8 * 1024 * 1024


class DrugLabelResultPointer(d.StrictModel):
    schema_version: Literal["drug_label_result_pointer_v1"]
    run_id: d.UUID
    result_hash: d.SHA256
    result_bytes: int = Field(strict=True, ge=1, le=MAX_RESULT_BYTES)


class DrugLabelUsageReceipt(d.StrictModel):
    schema_version: Literal["drug_label_usage_receipt_v1"]
    run_id: d.UUID
    source_binding_hash: d.SHA256
    input_hash: d.SHA256
    evidence_hash: d.SHA256
    metadata_hash: d.SHA256
    lease_token: d.UUID | None
    model_call_attempted: bool | None
    input_tokens: int | None = Field(ge=0, le=2000000, strict=True)
    output_tokens: int | None = Field(ge=0, le=2000000, strict=True)
    result_hash: d.SHA256 | None
    status: Literal["succeeded", "failed", "cancelled"]

    @model_validator(mode="after")
    def actual_known_or_unknown(self):
        if self.model_call_attempted is False and (self.input_tokens, self.output_tokens) != (0, 0):
            raise ValueError("A proven uncalled model has a real zero receipt")
        if self.model_call_attempted is None and (self.input_tokens is not None or self.output_tokens is not None):
            raise ValueError("A known token count proves the model was called")
        if (self.result_hash is not None) != (self.status == "succeeded"):
            raise ValueError("Only accepted success has a complete result hash")
        if self.status == "succeeded" and (self.lease_token is None or self.model_call_attempted is not True or self.input_tokens is None or self.output_tokens is None):
            raise ValueError("Acceptance requires a real leased call and both actual counts")
        return self


__all__ = ["DrugLabelFrozenProvider", "DrugLabelFrozenValidation", "DrugLabelResultPointer", "DrugLabelUsageReceipt", "CREATE_ACTION", "USAGE_ACTION", "ACCEPT_ACTION"]
