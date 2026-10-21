"""Closed operations task views; parts never include private Source hashes."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai import operations_support_contract as c
from app.ai.operations_support_task_contract import Objective
from app.ai.operations_support_usage_contract import OperationsUsage

ErrorCode = Annotated[str, Field(strict=True, min_length=1, max_length=80, pattern=r"^[A-Z][A-Z0-9_]*$")]
PartsState = Literal["available", "requires_current_read", "current_parts_unavailable", "incomplete_native_artifact"]


class OperationsViewBinding(c.StrictModel):
    operations_case_id: c.Identifier
    objective: Objective
    source_projection_hash: c.Digest
    source_binding_hash: c.Digest
    prompt_snapshot_hash: c.Digest
    execution_snapshot_hash: c.Digest
    instructions_digest: c.Digest


class OperationsTaskMetadata(c.StrictModel):
    schema_version: Literal["operations_support_task_metadata_view_v1"]
    run_id: c.Identifier
    feature_key: Literal["operations_support"]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    requested_by: c.ActorId
    preview: bool
    create_time: c.Clock
    start_time: c.Clock | None
    finish_time: c.Clock | None
    finish_clock_basis: Literal["actual_usage_receipt_utc6", "legacy_run_seconds", "not_finished"]
    split_artifacts: Literal[True]
    input_mode: Literal["operations_support_evidence"]
    parts_wire: Literal["canonical_json_body_no_envelope"]
    parts_state: PartsState
    binding: OperationsViewBinding | None
    usage: OperationsUsage | None
    usage_event_id: c.ActorId | None
    receipt_pending: bool
    error_code: ErrorCode | None
    error_message: Annotated[str, Field(strict=True, max_length=2000)] | None

    @model_validator(mode="after")
    def body_permission_is_explicit(self):
        if (self.parts_state == "available") != (self.binding is not None):
            raise ValueError("Only a full current Source read may disclose task bindings")
        if (self.usage is None) != (self.usage_event_id is None):
            raise ValueError("Actual nullable usage must have its concrete usage audit PK")
        return self


class OperationsRawTaskParts(c.StrictModel):
    input_json: str
    evidence_json: str
    context_metadata_json: str

    @model_validator(mode="after")
    def entire_original_raw3(self):
        if any(not value or len(value.encode("utf-8")) > 65535 for value in self.model_dump().values()):
            raise ValueError("Each entire original raw3 field must fit its real SQL TEXT")
        return self


class OperationsTaskPart(c.StrictModel):
    schema_version: Literal["operations_support_task_part_v1"]
    run_id: c.Identifier
    binding: OperationsViewBinding
    prompt_snapshot_json: str
    execution_snapshot_json: str
    raw: OperationsRawTaskParts

    @model_validator(mode="after")
    def complete_frames_and_whole_part(self):
        if any(not value or len(value.encode("utf-8")) > 262144 for value in (self.prompt_snapshot_json, self.execution_snapshot_json)) or len(c.canonical_json(self).encode("utf-8")) > c.MAX_WHOLE_BYTES:
            raise ValueError("Complete frozen frames and whole part must fit without clipping")
        return self


class OperationsBindingPart(c.StrictModel):
    schema_version: Literal["operations_support_binding_part_v1"]
    run_id: c.Identifier
    binding: OperationsViewBinding
    requested_by: c.ActorId
    recorded_at: c.Clock
    source_bytes: Annotated[int, Field(strict=True, ge=1, le=c.MAX_WHOLE_BYTES)]
    provider_id: c.ActorId
    provider_revision: c.ActorId
    config_revision: c.ActorId
    prompt_id: c.Identifier | None
    prompt_version: Annotated[int, Field(strict=True, ge=0)]
    created_audit_event_id: c.ActorId
    claim_event_id: c.ActorId | None
    dispatch_event_id: c.ActorId | None
    usage_event_id: c.ActorId | None
    lease_token: c.Identifier | None
    claimed_at: c.Clock | None
    dispatched_at: c.Clock | None
    usage_receipt_json: str | None

    @model_validator(mode="after")
    def actual_receipt_and_lease(self):
        if (self.claim_event_id is None) != (self.lease_token is None) or (self.claim_event_id is None) != (self.claimed_at is None):
            raise ValueError("Actual claim, lease and UTC6 clock must agree")
        if (self.dispatch_event_id is None) != (self.dispatched_at is None) or (self.usage_event_id is None) != (self.usage_receipt_json is None):
            raise ValueError("Actual dispatch/usage must have their original details")
        if self.usage_receipt_json is not None and len(self.usage_receipt_json.encode("utf-8")) > 65535:
            raise ValueError("Complete concrete usage receipt must fit its actual audit TEXT")
        return self
