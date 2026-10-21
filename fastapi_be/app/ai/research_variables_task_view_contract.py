"""Pure76 SQL-anchor view; technical identity never grants data permission."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai.research_cohort_contract import SHA, UTC, UUID, Positive, StrictModel
from app.ai.research_variables_task_contract import MAX_BINDING_BYTES, MAX_WIRE_BYTES, TaskRole


class VariableTaskAnchorRecord(StrictModel):
    schema_version: Literal["research_variable_run_artifact_v1"]
    run_id: UUID
    batch_id: UUID
    scope_id: UUID
    requested_by: Positive
    task_acl_id: UUID
    actor_role: TaskRole
    actor_token_invalid_before: UTC | None
    recorded_at: UTC
    source_bytes: Annotated[int, Field(strict=True, ge=1, le=MAX_WIRE_BYTES)]
    binding_bytes: Annotated[int, Field(strict=True, ge=1, le=MAX_BINDING_BYTES)]
    input_hash: SHA
    evidence_hash: SHA
    metadata_hash: SHA
    prompt_hash: SHA
    context_digest: SHA
    instructions_digest: SHA
    source_hash: SHA
    binding_hash: SHA
    batch_content_hash: SHA
    scope_content_hash: SHA
    scope_governance_hash: SHA
    request_authorization_hash: SHA
    create_event_id: Positive
    claim_event_id: Positive | None
    claim_lease: UUID | None
    claimed_at: UTC | None
    dispatch_event_id: Positive | None
    dispatched_at: UTC | None
    usage_event_id: Positive | None

    @model_validator(mode="after")
    def actual_phases(self):
        present = [self.claim_event_id is not None, self.claim_lease is not None, self.claimed_at is not None]
        if any(present) != all(present) or (self.dispatch_event_id is None) != (self.dispatched_at is None):
            raise ValueError("Actual claim/dispatch tuples must remain complete")
        if self.dispatched_at is not None and (self.claimed_at is None or self.dispatched_at < self.claimed_at):
            raise ValueError("An actual dispatch follows its concrete claim")
        if self.claimed_at is not None and self.claimed_at < self.recorded_at:
            raise ValueError("An actual claim follows task registration")
        identifiers = [value for value in (self.create_event_id, self.claim_event_id, self.dispatch_event_id, self.usage_event_id) if value is not None]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Actual task phase audit PKs cannot be reused")
        return self
