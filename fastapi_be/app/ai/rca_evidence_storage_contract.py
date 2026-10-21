"""Pure short task storage, frozen publication and exact nullable receipts."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_source_contract as s
from app.ai import rca_evidence_task_contract as t
from app.ai.rca_evidence_task_prompt import SYSTEM_PROMPT
from app.ai.rca_evidence_task_views import RcaFrozenProvider, RcaFrozenValidation, RcaUsageReceipt


class RcaTaskEvidence(c.StrictModel):
    source_id: str = Field(min_length=1, max_length=100)
    kind: Literal["rca_evidence_case"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=65535)


class RcaStoredPayload(c.StrictModel):
    input: t.RcaTaskSelection
    context: dict
    tools: dict
    evidence: list[RcaTaskEvidence] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def complete_short_task(self):
        binding = t.checked_context(self.context)
        if self.input.rca_evidence_case_id != binding.case_id or self.tools != {} or c.canonical(self.evidence) != c.canonical(t.evidence_for_binding(binding)):
            raise ValueError("Input, original evidence, short binding and no-tools contract differ")
        t.text_json(self)
        return self


class RcaActorEpoch(c.StrictModel):
    user_role: Literal["super_admin"]
    token_invalid_before: str | None

    @model_validator(mode="after")
    def original_epoch(self):
        if self.token_invalid_before is not None:
            c.clock(self.token_invalid_before)
        return self


class RcaTaskSnapshot(c.StrictModel):
    schema_version: Literal["rca_evidence_task_snapshot_v1"]
    catalog_version: str = Field(min_length=1, max_length=64)
    system_prompt: Literal[SYSTEM_PROMPT]
    task_prompt: str = Field(min_length=1, max_length=65535)
    payload: RcaStoredPayload
    provider_snapshot: RcaFrozenProvider
    feature_validation: RcaFrozenValidation
    source_case_governance: s.SourceGovernance
    actor_epoch: RcaActorEpoch
    run_clock_basis: Literal["legacy_utc_second_storage"]

    @model_validator(mode="after")
    def complete_original_snapshot(self):
        c.plain(self.task_prompt, 65535)
        binding = t.checked_context(self.payload.context)
        if self.source_case_governance.status != "published" or self.source_case_governance.revision != 2:
            raise ValueError("The actual original published Case signature is frozen independently")
        if c.digest({"case_id": binding.case_id, "content_hash": binding.case_content_hash, "governance": self.source_case_governance}) != binding.case_governance_hash:
            raise ValueError("The entire original signature differs from the bound Case governance")
        if self.source_case_governance.reviewed_at != binding.source_snapshot_time:
            raise ValueError("The actual frozen Source publication clock differs")
        t.text_json(self)
        return self


class RcaTaskMetadata(c.StrictModel):
    snapshot_time: str
    source_count: Annotated[int, Field(strict=True, ge=1, le=1)]
    department_ids: list[i.PositiveId] = Field(max_length=0)
    context_digest: c.SHA
    clinical_context_fingerprint: c.SHA
    missing_data: list[str] = Field(min_length=3, max_length=3)
    feature_revision: i.PositiveId
    validation_status: Literal["unreviewed", "pilot", "validated", "suspended"]
    tool_fingerprint: c.SHA
    instructions_digest: c.SHA
    model_version: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def exact_metadata(self):
        c.clock(self.snapshot_time)
        if self.missing_data != list(t.MISSING_DATA) or self.tool_fingerprint != c.digest({}):
            raise ValueError("Only the fixed evidence limitations and no-tools digest are retained")
        return self


def metadata_for_snapshot(snapshot):
    snapshot = RcaTaskSnapshot.model_validate(snapshot)
    context = snapshot.payload.context
    return RcaTaskMetadata(
        snapshot_time=context["snapshot_time"],
        source_count=1,
        department_ids=[],
        context_digest=c.digest(context),
        clinical_context_fingerprint=c.digest({key: value for key, value in context.items() if key != "snapshot_time"}),
        missing_data=list(t.MISSING_DATA),
        feature_revision=snapshot.feature_validation.feature_revision,
        validation_status=snapshot.feature_validation.status,
        tool_fingerprint=c.digest({}),
        instructions_digest=t.instructions_digest(snapshot.system_prompt, snapshot.task_prompt),
        model_version=snapshot.provider_snapshot.model,
    )


class RcaUsageEvent(c.StrictModel):
    schema_version: Literal["rca_evidence_usage_receipt_v1"]
    run_id: c.OpaqueId
    case_id: c.OpaqueId
    claim_event_id: i.PositiveId | None
    dispatch_event_id: i.PositiveId | None
    lease_token: c.OpaqueId | None
    binding_hash: c.SHA
    source_hash: c.SHA
    result_hash: c.SHA | None
    terminal_state_hash: c.SHA
    status: Literal["succeeded", "failed", "cancelled"]
    error_code: str | None = Field(max_length=80)
    usage: RcaUsageReceipt
    recorded_at: str
    run_clock_basis: Literal["legacy_utc_second_storage"]

    @model_validator(mode="after")
    def actual_terminal_receipt(self):
        c.clock(self.recorded_at)
        if (self.claim_event_id is None) != (self.lease_token is None):
            raise ValueError("The real claim PK and lease form one immutable attempt")
        if self.dispatch_event_id is not None and self.claim_event_id is None:
            raise ValueError("A dispatch must have its actual original claim")
        if self.usage.model_call_attempted is not False and self.dispatch_event_id is None:
            raise ValueError("Attempted or interrupted unknown calls require their committed dispatch")
        if self.usage.model_call_attempted is None and self.error_code != "WORKER_INTERRUPTED":
            raise ValueError("Only actual process interruption retains an unknown call state")
        if self.status == "succeeded":
            if not self.usage.complete or self.usage.model_call_attempted is not True or self.result_hash is None:
                raise ValueError("Accepted success requires independent complete actual usage")
        elif self.result_hash is not None:
            raise ValueError("Failure or cancellation cannot carry an accepted result hash")
        return self
