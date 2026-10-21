"""Closed task anchors; concrete SQL permissions are explained independently."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai.research_cohort_contract import SHA, UUID, Positive, StrictModel
from app.ai.research_variables_task_contract import MAX_BINDING_BYTES, MAX_WIRE_BYTES, VariableTaskAccessManifest, canonical, digest

ByteCount = Annotated[int, Field(strict=True, ge=1, le=MAX_WIRE_BYTES)]


class VariableTaskBinding(StrictModel):
    schema_version: Literal["research_variable_task_binding_v1"]
    batch_id: UUID
    batch_content_hash: SHA
    batch_governance_hash: SHA
    batch_created_event_id: Positive
    batch_last_event_id: Positive
    dictionary_id: UUID
    dictionary_content_hash: SHA
    dictionary_governance_hash: SHA
    dictionary_created_event_id: Positive
    dictionary_last_event_id: Positive
    collection_digest: SHA
    member_manifest_hash: SHA
    source_projection_hash: SHA
    source_id: Annotated[str, Field(strict=True, pattern=r"^research_variables:[a-f0-9-]{36}:[a-f0-9]{12}$")]
    documents_hash: SHA
    source_recipe_hash: SHA
    source_bytes: ByteCount
    private_scope_hash: SHA
    private_scope_bytes: ByteCount
    request_authorization: VariableTaskAccessManifest
    request_authorization_hash: SHA

    @model_validator(mode="after")
    def actual_request_and_whole_original(self):
        if self.request_authorization_hash != digest(self.request_authorization, MAX_BINDING_BYTES):
            raise ValueError("Every original ACL/patient permission and request epoch must explain the authorization SHA")
        if self.source_id != f"research_variables:{self.batch_id}:{self.batch_content_hash[:12]}":
            raise ValueError("Source identity must anchor the complete actual Batch")
        canonical(self, MAX_BINDING_BYTES)
        return self


def binding_reference(binding):
    """A reference grants no authority and never substitutes for the full piece."""
    value = VariableTaskBinding.model_validate(binding)
    return {
        "schema_version": "research_variable_task_binding_ref_v1",
        "batch_id": value.batch_id,
        "scope_id": value.request_authorization.scope_id,
        "requested_by": value.request_authorization.requested_by,
        "binding_hash": digest(value, MAX_BINDING_BYTES),
        "request_authorization_hash": value.request_authorization_hash,
        "source_projection_hash": value.source_projection_hash,
        "private_scope_hash": value.private_scope_hash,
    }


def evidence_for_binding(binding):
    value = VariableTaskBinding.model_validate(binding)
    return [
        {
            "source_id": value.source_id,
            "kind": "research_variable_batch",
            "content_hash": value.batch_content_hash,
            "governance_hash": value.batch_governance_hash,
            "source_digest": value.source_projection_hash,
            "documents_hash": value.documents_hash,
            "coverage": "all_declared_recorded_candidates_no_inferred_absence_or_automatic_winner",
        }
    ]
