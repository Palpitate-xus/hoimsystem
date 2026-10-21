"""Pure bounded split RCA task views; shape and self-consistency grant no rights."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_storage_contract as s
from app.ai import rca_evidence_task_contract as t
from app.ai.rca_evidence_task_views import RcaResultReference, RcaUsageReceipt

Nonnegative = Annotated[int, Field(strict=True, ge=0, le=2147483647)]


class RcaShortContext(c.StrictModel):
    schema_version: Literal["rca_evidence_context_v1"]
    scope: Literal["input"]
    source_domain: Literal[t.SOURCE_DOMAIN]
    selected_sources: dict[Literal["rca_evidence_case_id"], c.OpaqueId]
    rca_evidence_binding: t.RcaTaskBinding
    scope_note: Literal[t.SCOPE_NOTE]
    missing_data: list[str] = Field(min_length=3, max_length=3)
    snapshot_time: str

    @model_validator(mode="after")
    def actual_whole_context(self):
        t.checked_context(self.model_dump(mode="json"))
        return self


class RcaArtifactRecord(c.StrictModel):
    schema_version: Literal["rca_evidence_run_artifact_v1"]
    run_id: c.OpaqueId
    case_id: c.OpaqueId
    event_id: i.PositiveId
    patient_id_at_capture: i.PositiveId | None
    requested_by: i.PositiveId
    event_grant_id: c.OpaqueId
    patient_grant_id: c.OpaqueId | None
    recorded_at: str
    actor_token_invalid_before: str | None
    source_bytes: Annotated[int, Field(strict=True, ge=1, le=c.MAX_WIRE_BYTES)]
    binding_bytes: Annotated[int, Field(strict=True, ge=1, le=t.MAX_RUN_TEXT_BYTES)]
    input_hash: c.SHA
    evidence_hash: c.SHA
    metadata_hash: c.SHA
    prompt_hash: c.SHA
    context_digest: c.SHA
    instructions_digest: c.SHA
    source_hash: c.SHA
    binding_hash: c.SHA
    create_event_id: i.PositiveId
    claim_event_id: i.PositiveId | None
    claim_lease: c.OpaqueId | None
    claimed_at: str | None
    dispatch_event_id: i.PositiveId | None
    dispatched_at: str | None
    usage_event_id: i.PositiveId | None

    @model_validator(mode="after")
    def actual_metadata(self):
        for value in (self.recorded_at, self.actor_token_invalid_before, self.claimed_at, self.dispatched_at):
            if value is not None:
                c.clock(value)
        if (self.claim_event_id is None) != (self.claim_lease is None) or (self.claim_event_id is None) != (self.claimed_at is None):
            raise ValueError("The exact claim tuple cannot be partially reconstructed")
        if (self.dispatch_event_id is None) != (self.dispatched_at is None) or self.dispatch_event_id is not None and self.claim_event_id is None:
            raise ValueError("A committed dispatch requires its real claim tuple")
        if (self.patient_grant_id is None) != (self.patient_id_at_capture is None):
            raise ValueError("Actual associated patient and independent purpose differ")
        refs = [v for v in (self.create_event_id, self.claim_event_id, self.dispatch_event_id, self.usage_event_id) if v is not None]
        if len(refs) != len(set(refs)):
            raise ValueError("Distinct real task phase PKs are retained")
        return self


class RcaPieceLocations(c.StrictModel):
    source: str
    case: str
    result: str
    receipt: str


def piece_locations(identifier, frozen_audit=False):
    root = "/api/ai/admin/runs" if frozen_audit else "/api/ai/runs"
    return RcaPieceLocations(**{key: f"{root}/{identifier}/rca-evidence/{key}" for key in RcaPieceLocations.model_fields})


class RcaPreviewRequest(t.RcaTaskSelection):
    preview: bool = False


class RcaPreview(c.StrictModel):
    context: RcaShortContext
    metadata: s.RcaTaskMetadata
    evidence: list[s.RcaTaskEvidence] = Field(min_length=1, max_length=1)
    model_preview: Literal["no_model_call"]
    source_url: str
    case_url: str
    automatic_legacy_write: Literal[False]


class RcaTaskFindings(c.StrictModel):
    context: RcaShortContext
    input: t.RcaTaskSelection
    rca_evidence_binding: t.RcaTaskBinding
    frozen_task_view: Literal[True]
    automatic_legacy_write: Literal[False]

    @model_validator(mode="after")
    def exact_original_selection(self):
        if self.context.rca_evidence_binding != self.rca_evidence_binding or self.input.rca_evidence_case_id != self.rca_evidence_binding.case_id:
            raise ValueError("The finite Case selection and original context differ")
        return self


class RcaRunSummary(c.StrictModel):
    run_id: c.OpaqueId
    feature_key: Literal[t.FEATURE_KEY]
    feature_name: Literal["事件受审资料的未核实RCA假设"]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    preview: Annotated[int, Field(strict=True, ge=0, le=1)]
    prompt_version: Nonnegative
    provider_revision: i.PositiveId
    context_digest: c.SHA
    patient_id: None
    encounter_ref: None
    error_code: str | None = Field(max_length=80)
    error_message: str | None = Field(max_length=500)
    latency_ms: Nonnegative | None
    create_time: str
    start_time: str | None
    finish_time: str | None
    run_clock_basis: Literal["legacy_utc_second_storage"]
    requires_human_review: Literal[True]
    context_metadata: s.RcaTaskMetadata
    rca_evidence_case_id: c.OpaqueId
    usage_receipt: RcaUsageReceipt | None
    input_tokens: Annotated[int, Field(strict=True, ge=0, le=2000000)] | None
    output_tokens: Annotated[int, Field(strict=True, ge=0, le=2000000)] | None
    usage_receipt_status: Literal["recorded", "pending"]

    @model_validator(mode="after")
    def no_inferred_usage_or_clocks(self):
        for value in (self.create_time, self.start_time, self.finish_time):
            if value is not None and c.clock(value).microsecond != 0:
                raise ValueError("Run legacy clocks retain their explicitly declared second storage")
        expected = (None, None) if self.usage_receipt is None else (self.usage_receipt.input_tokens, self.usage_receipt.output_tokens)
        if (self.input_tokens, self.output_tokens) != expected or (self.usage_receipt_status == "recorded") != (self.usage_receipt is not None):
            raise ValueError("No legacy integer placeholder may impersonate independently received usage")
        return self


class RcaRunDetail(RcaRunSummary):
    result: None
    result_reference: RcaResultReference | None
    evidence: list[s.RcaTaskEvidence] = Field(min_length=1, max_length=1)
    rca_evidence_artifact: RcaArtifactRecord
    rca_evidence_findings: RcaTaskFindings
    parts: RcaPieceLocations

    @model_validator(mode="after")
    def whole_short_proof(self):
        artifact, binding = self.rca_evidence_artifact, self.rca_evidence_findings.rca_evidence_binding
        if (artifact.run_id, artifact.case_id, artifact.context_digest) != (self.run_id, self.rca_evidence_case_id, self.context_digest):
            raise ValueError("Actual task metadata and scope are inconsistent")
        if (binding.case_id, binding.source_projection_hash, c.digest(binding)) != (artifact.case_id, artifact.source_hash, artifact.binding_hash):
            raise ValueError("Short context does not bind the original whole pieces")
        if [x.model_dump(mode="json") for x in self.evidence] != t.evidence_for_binding(binding):
            raise ValueError("The sole original citation differs")
        if (
            c.digest(self.rca_evidence_findings.context) != artifact.context_digest
            or self.context_metadata.context_digest != artifact.context_digest
            or self.context_metadata.instructions_digest != artifact.instructions_digest
        ):
            raise ValueError("Original short context, server metadata and Artifact instruction anchors differ")
        if self.parts not in (piece_locations(self.run_id), piece_locations(self.run_id, True)):
            raise ValueError("Only this actual task's explicitly scoped split endpoints are retained")
        if self.result_reference is not None and (self.result_reference.run_id, self.result_reference.accepted_lease) != (self.run_id, artifact.claim_lease):
            raise ValueError("The accepted result belongs to another task or lease")
        if (self.result_reference is not None) != (self.status == "succeeded"):
            raise ValueError("Only successful tasks have an accepted exact result reference")
        return self


class RcaRawFrozenJson(c.StrictModel):
    input_json: str = Field(min_length=1, max_length=t.MAX_RUN_TEXT_BYTES)
    evidence_json: str = Field(min_length=1, max_length=t.MAX_RUN_TEXT_BYTES)
    context_metadata_json: str = Field(min_length=1, max_length=t.MAX_RUN_TEXT_BYTES)


class RcaAuditRecord(c.StrictModel):
    event_id: i.PositiveId
    actor_id: i.PositiveId
    action: str = Field(max_length=80)
    target: str = Field(max_length=120)
    detail_json: str = Field(max_length=t.MAX_RUN_TEXT_BYTES)
    create_time: str


class RcaPhaseAudits(c.StrictModel):
    create: RcaAuditRecord
    claim: RcaAuditRecord | None
    dispatch: RcaAuditRecord | None
    usage: RcaAuditRecord | None
    accept: RcaAuditRecord | None


class RcaRunTrace(RcaRunDetail):
    requested_by: i.PositiveId
    provider_id: i.PositiveId
    snapshot_complete: Literal[True]
    frozen_request: s.RcaTaskSnapshot
    raw_frozen_json: RcaRawFrozenJson
    phase_audits: RcaPhaseAudits
