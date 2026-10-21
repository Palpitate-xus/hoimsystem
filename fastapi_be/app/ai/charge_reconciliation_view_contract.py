"""Strict public artifact identity without importing runtime or SQL models."""

from typing import Annotated, Literal

from pydantic import Field

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
