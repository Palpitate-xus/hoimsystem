"""Closed wire-only task views; validates shape, never grants SQL authority."""

import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.ai import document_evidence_contract as d
from app.ai.drug_label_context_contract import MISSING_DATA, SCOPE_NOTE, DrugLabelContextBinding, DrugLabelRequest
from app.ai.drug_label_contract import SourceRecord
from app.ai.drug_label_draft import MAX_JSON_BYTES, bounded_json
from app.ai.drug_label_projection import DrugLabelPublicSource
from app.ai.drug_label_result import DrugLabelGenerationResult
from app.ai.drug_label_run_contract import DrugLabelFrozenProvider, DrugLabelFrozenValidation, DrugLabelUsageReceipt

Nonnegative = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
TokenCount = Annotated[int, Field(strict=True, ge=0, le=2000000)]


class DrugLabelShortContext(d.StrictModel):
    scope: Literal["input"]
    source_domain: Literal["released_drug_label_original"]
    selected_sources: dict[Literal["drug_label_source_binding_id"], d.UUID]
    drug_label_binding: DrugLabelContextBinding
    scope_note: Literal[SCOPE_NOTE]
    missing_data: list[str] = Field(min_length=3, max_length=3)
    truncated_sources: list[str] = Field(max_length=0)
    snapshot_time: d.UtcText

    @model_validator(mode="after")
    def exact_scope(self):
        if self.selected_sources != {"drug_label_source_binding_id": self.drug_label_binding.source.source_binding_id} or self.missing_data != list(MISSING_DATA):
            raise ValueError("Exact single released Source and missing evidence are retained")
        return self


class DrugLabelTaskMetadata(d.StrictModel):
    snapshot_time: d.UtcText
    source_count: Literal[2]
    department_ids: list[d.Positive] = Field(max_length=0)
    context_digest: d.SHA256
    clinical_context_fingerprint: d.SHA256
    missing_data: list[str] = Field(min_length=3, max_length=3)
    feature_revision: d.Positive
    validation_status: Literal["unreviewed", "pilot", "validated", "suspended"]
    tool_fingerprint: d.SHA256
    instructions_digest: d.SHA256
    model_version: str = Field(min_length=1, max_length=200)


class DrugLabelArtifactView(d.StrictModel):
    schema_version: Literal["drug_label_run_artifact_v1"]
    run_id: d.UUID
    source_binding_id: d.UUID
    requested_by: d.Positive
    created_at: d.UtcText
    input_hash: d.SHA256
    evidence_hash: d.SHA256
    metadata_hash: d.SHA256
    prompt_hash: d.SHA256
    context_digest: d.SHA256
    source_binding_hash: d.SHA256
    create_event_id: d.Positive
    receipt_event_id: d.Positive | None
    accept_event_id: d.Positive | None
    accepted_at: d.UtcText | None
    result_hash: d.SHA256 | None
    result_bytes: int | None = Field(strict=True, ge=1, le=MAX_JSON_BYTES)

    @model_validator(mode="after")
    def actual_acceptance(self):
        fields = [self.accept_event_id, self.accepted_at, self.result_hash, self.result_bytes]
        if any(v is not None for v in fields) != all(v is not None for v in fields) or self.accept_event_id is not None and (self.receipt_event_id is None or self.accepted_at < self.created_at):
            raise ValueError("An actual acceptance has the entire result tuple and receipt")
        refs = [v for v in (self.create_event_id, self.receipt_event_id, self.accept_event_id) if v is not None]
        if len(refs) != len(set(refs)):
            raise ValueError("Creation, usage and acceptance are distinct audit events")
        return self


class DrugLabelTaskFindings(d.StrictModel):
    context: DrugLabelShortContext
    input: DrugLabelRequest
    drug_label_binding: DrugLabelContextBinding
    drug_label_source: DrugLabelPublicSource
    drug_label_source_record: SourceRecord
    frozen_task_view: Literal[True]
    can_record: Literal[False]
    can_review: Literal[False]
    can_revoke: Literal[False]


class DrugLabelTaskEvidence(d.StrictModel):
    source_id: str = Field(min_length=1, max_length=100)
    kind: Literal["drug_label_source", "document_original"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=65535)


class DrugLabelRunSummary(d.StrictModel):
    run_id: d.UUID
    feature_key: Literal["drug_label_extraction"]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    preview: int = Field(strict=True, ge=0, le=1)
    prompt_version: Nonnegative
    provider_revision: d.Positive
    context_digest: d.SHA256
    patient_id: None
    encounter_ref: None
    error_code: str | None = Field(max_length=80)
    error_message: str | None = Field(max_length=2000)
    latency_ms: Nonnegative | None
    create_time: str
    start_time: str | None
    finish_time: str | None
    feature_name: Literal["药品说明书逐字字段草稿"]
    requires_human_review: Literal[True]
    context_metadata: DrugLabelTaskMetadata
    drug_label_source_binding_id: d.UUID
    usage_receipt: DrugLabelUsageReceipt | None
    input_tokens: TokenCount | None
    output_tokens: TokenCount | None
    usage_receipt_status: Literal["recorded", "pending"]

    @field_validator("create_time", "start_time", "finish_time")
    @classmethod
    def actual_legacy_second_clock(cls, value):
        if value is not None:
            parsed = datetime.datetime.fromisoformat(value)
            if parsed.tzinfo is not None or parsed.microsecond != 0 or parsed.isoformat() != value:
                raise ValueError("Actual legacy Run DATETIME(0) has a naive ISO second clock, separate from UTC6 Artifact")
        return value


class DrugLabelRunDetail(DrugLabelRunSummary):
    result: DrugLabelGenerationResult | None
    evidence: list[DrugLabelTaskEvidence] = Field(min_length=2, max_length=2)
    drug_label_artifact: DrugLabelArtifactView
    drug_label_findings: DrugLabelTaskFindings


class DrugLabelRawFrozenJson(d.StrictModel):
    input_json: str = Field(min_length=1, max_length=65535)
    evidence_json: str = Field(min_length=1, max_length=65535)
    context_metadata_json: str = Field(min_length=1, max_length=65535)


class DrugLabelFrozenPayload(d.StrictModel):
    input: DrugLabelRequest
    context: DrugLabelShortContext
    tools: dict = Field(max_length=0)
    evidence: list[DrugLabelTaskEvidence] = Field(min_length=2, max_length=2)


class DrugLabelFrozenTask(d.StrictModel):
    catalog_version: str = Field(min_length=1, max_length=80)
    system_prompt: str = Field(min_length=1, max_length=65535)
    task_prompt: str = Field(min_length=1, max_length=65535)
    payload: DrugLabelFrozenPayload
    provider_snapshot: DrugLabelFrozenProvider
    feature_validation: DrugLabelFrozenValidation


class DrugLabelRunTrace(DrugLabelRunDetail):
    requested_by: d.Positive
    provider_id: d.Positive
    snapshot_complete: Literal[True]
    frozen_request: DrugLabelFrozenTask
    raw_frozen_json: DrugLabelRawFrozenJson


def checked_wire(value, model=DrugLabelRunDetail):
    """The actual combined HTTP wrapper, not the sum of promised per-blob caps."""
    return model.model_validate(bounded_json(value))
