"""Pure frozen extraction view types; no hospital settings or database imports."""

import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.ai import document_evidence_contract as c
from app.ai.document_extraction_contract import DocumentExtractionSource


class DocumentExtractionBinding(c.StrictModel):
    schema_version: Literal["document_extraction_binding_v1"]
    feature_key: Literal["guideline_ingestion"]
    original: c.OriginalReference
    source_digest: c.SHA256


class DocumentExtractionContext(c.StrictModel):
    scope: Literal["document_extraction"]
    snapshot_time: c.UtcText
    document_binding: DocumentExtractionBinding
    document_source: DocumentExtractionSource
    document_review: c.GovernedReview
    missing_data: list[str]


class DocumentFrozenProvider(c.StrictModel):
    provider_id: c.Positive
    revision: c.Positive
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["chat", "responses"]
    api_base: str = Field(min_length=1, max_length=2000)
    model: str = Field(min_length=1, max_length=200)
    timeout_seconds: int = Field(strict=True, ge=3, le=120)
    max_output_tokens: int = Field(strict=True, ge=256, le=16000)
    validation_report: str = Field(max_length=5000)
    temperature: float = Field(ge=0, le=1, allow_inf_nan=False)
    allows_patient_data: Literal[True]
    effective_output_limit: int = Field(strict=True, ge=1, le=16000)

    @model_validator(mode="after")
    def actual_limit(self):
        if self.effective_output_limit > self.max_output_tokens:
            raise ValueError("Effective output exceeds its actual provider limit")
        return self


class DocumentFrozenValidation(c.StrictModel):
    status: Literal["unreviewed", "pilot", "validated", "suspended"]
    note: str = Field(max_length=5000)
    validated_by: c.Positive | None
    validated_at: str | None = Field(max_length=64)
    feature_revision: c.Positive

    @model_validator(mode="after")
    def original_clock(self):
        if self.validated_at is not None:
            clock = datetime.datetime.fromisoformat(self.validated_at)
            if clock.tzinfo is not None or str(clock) != self.validated_at:
                raise ValueError("Preserve the original naive UTC validation clock without relabeling")
        if (self.validated_at is None) != (self.validated_by is None):
            raise ValueError("The actual validation signer and clock form one signature")
        return self


class DocumentExtractionAnchorRecord(c.StrictModel):
    run_id: c.UUID
    original_id: c.UUID
    requested_by: c.Positive
    schema_version: Literal["document_extraction_run_anchor_v1"]
    recorded_at: c.UtcText
    original_content_hash: c.SHA256
    original_governance_hash: c.SHA256
    source_digest: c.SHA256
    prompt_hash: c.SHA256
    context_digest: c.SHA256
    input_hash: c.SHA256
    evidence_hash: c.SHA256
    metadata_hash: c.SHA256

    @model_validator(mode="after")
    def actual_clock(self):
        c.clock(self.recorded_at)
        return self
