"""Pure short task bindings and bounded split responses, never live-current flags."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.ai import document_change_contract as c
from app.ai.document_change_draft import checked_source
from app.ai.document_change_json import require_case_json
from app.ai.document_change_result import DocumentChangeGenerationResult

FEATURE_KEY = "guideline_change_review"
MISSING_DATA = (
    "仅核对明确申明的有限院内目标范围，未提供全院规则覆盖。",
    "逐字差异问题与跨度重叠不是已确认临床语义、适用性或影响结论。",
    "不自动替代、撤销或修改原文、知识、规则或临床路径。",
)


class DocumentChangeRequest(c.e.StrictModel):
    document_change_scope_id: c.e.UUID
    question: str | None = Field(default=None, min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def exact_question(cls, value):
        if value is not None:
            c.e.meaningful(value, maximum=8000, minimum=1)
            if len(c.e.utf8(value)) > 8000:
                raise ValueError("The unchanged question exceeds 8000 UTF8 bytes")
        return value


class DocumentChangeBinding(c.e.StrictModel):
    schema_version: Literal["document_change_binding_v1"]
    feature_key: Literal["guideline_change_review"]
    scope: c.ScopeReference
    baseline_original: c.e.OriginalReference
    candidate_original: c.e.OriginalReference
    inventory_hash: c.e.SHA256
    member_count: int = Field(strict=True, ge=2, le=c.MAX_MEMBERS)
    source_digest: c.e.SHA256

    @model_validator(mode="after")
    def distinct_originals(self):
        if self.baseline_original.original_id == self.candidate_original.original_id:
            raise ValueError("Two actual original identities are required")
        return self


class DocumentChangeContext(c.e.StrictModel):
    scope: Literal["document_change_review"]
    snapshot_time: c.e.UtcText
    document_change_binding: DocumentChangeBinding
    missing_data: list[str]

    @model_validator(mode="after")
    def complete_short_context(self):
        c.e.clock(self.snapshot_time)
        if self.missing_data != list(MISSING_DATA):
            raise ValueError("The finite-coverage and unverified-impact declarations are fixed")
        return self


def binding_for_source(source):
    source = checked_source(source)
    return DocumentChangeBinding(
        schema_version="document_change_binding_v1",
        feature_key=FEATURE_KEY,
        scope=source.scope,
        baseline_original=source.baseline.original,
        candidate_original=source.candidate.original,
        inventory_hash=source.inventory_hash,
        member_count=source.member_count,
        source_digest=c.e.digest(source),
    )


def bounded_wire(value):
    """Budget the actual success wrapper, not only its individually bounded body."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    raw = require_case_json({"code": 200, "msg": "success", "data": value})
    return raw, c.e.bytes_hash(raw), len(c.e.utf8(raw))


class DocumentChangeSourcePacket(c.e.StrictModel):
    schema_version: Literal["document_change_source_packet_v1"]
    run_id: c.e.UUID
    document_change_binding: DocumentChangeBinding
    document_change_source: c.DocumentChangeSource

    @model_validator(mode="after")
    def exact_source(self):
        if binding_for_source(self.document_change_source) != self.document_change_binding:
            raise ValueError("The entire public source differs from the original task binding")
        return self


class DocumentChangePrivateScopePacket(c.e.StrictModel):
    schema_version: Literal["document_change_private_scope_packet_v1"]
    run_id: c.e.UUID
    document_change_binding: DocumentChangeBinding
    scope_snapshot: c.ScopeImmutable
    published_governance: c.Governance
    published_audit_event_ids: c.AuditReferences
    frozen_task_view: Literal[True]
    currentness: Literal["not_asserted_by_frozen_packet"]

    @field_validator("frozen_task_view", mode="before")
    @classmethod
    def actual_frozen(cls, value):
        if value is not True:
            raise ValueError("A frozen packet cannot masquerade as a live Source record")
        return value

    @model_validator(mode="after")
    def frozen_scope(self):
        binding = self.document_change_binding
        if self.scope_snapshot.scope_id != binding.scope.scope_id or c.e.digest(self.scope_snapshot) != binding.scope.content_hash:
            raise ValueError("The complete frozen private Scope differs")
        if self.published_governance.status != "published" or c.e.digest(self.published_governance) != binding.scope.governance_hash:
            raise ValueError("Only the actual task-time published signature can bind the frozen Scope")
        if self.published_audit_event_ids.reviewed is None or self.published_audit_event_ids.revoked is not None:
            raise ValueError("The published signature must retain its concrete create/review audit IDs")
        if self.scope_snapshot.request.baseline_original != binding.baseline_original or self.scope_snapshot.request.candidate_original != binding.candidate_original:
            raise ValueError("The two complete private original sides differ")
        if self.scope_snapshot.inventory_hash != binding.inventory_hash or self.scope_snapshot.inventory.member_count != binding.member_count:
            raise ValueError("The entire private dependency collection differs")
        c.check_clocks(self.scope_snapshot.recorded_at, self.published_governance)
        return self


class DocumentChangeResultPacket(c.e.StrictModel):
    schema_version: Literal["document_change_result_packet_v1"]
    run_id: c.e.UUID
    document_change_binding: DocumentChangeBinding
    instructions_digest: c.e.SHA256
    result: DocumentChangeGenerationResult

    @model_validator(mode="after")
    def exact_result_identity(self):
        task, proof = self.document_change_binding, self.result.document_change.binding
        if (proof.scope_id, proof.scope_content_hash, proof.scope_governance_hash, proof.source_projection_hash, proof.instructions_digest) != (
            task.scope.scope_id,
            task.scope.content_hash,
            task.scope.governance_hash,
            task.source_digest,
            self.instructions_digest,
        ):
            raise ValueError("The result and actual frozen task/Prompt binding differ")
        return self


class DocumentChangeResultReference(c.e.StrictModel):
    schema_version: Literal["document_change_result_ref_v1"]
    run_id: c.e.UUID
    scope_id: c.e.UUID
    lease_token: c.e.UUID
    content_hash: c.e.SHA256
    result_bytes: int = Field(strict=True, gt=0, le=c.MAX_CASE_BYTES)
    source_binding_hash: c.e.SHA256
    accept_audit_event_id: c.e.Positive


def source_packet(run_id, binding, source):
    result = DocumentChangeSourcePacket(schema_version="document_change_source_packet_v1", run_id=run_id, document_change_binding=binding, document_change_source=source)
    bounded_wire(result)
    return result


def private_scope_packet(run_id, binding, snapshot, governance, audit_ids):
    result = DocumentChangePrivateScopePacket(
        schema_version="document_change_private_scope_packet_v1",
        run_id=run_id,
        document_change_binding=binding,
        scope_snapshot=snapshot,
        published_governance=governance,
        published_audit_event_ids=audit_ids,
        frozen_task_view=True,
        currentness="not_asserted_by_frozen_packet",
    )
    bounded_wire(result)
    return result


def result_packet(run_id, binding, instructions_digest, value):
    result = DocumentChangeResultPacket(schema_version="document_change_result_packet_v1", run_id=run_id, document_change_binding=binding, instructions_digest=instructions_digest, result=value)
    bounded_wire(result)
    return result


class DocumentChangeArtifactRecord(c.e.StrictModel):
    """Actual SQL anchor values; does not itself assert live Source eligibility."""

    schema_version: Literal["document_change_run_artifact_v1"]
    run_id: c.e.UUID
    requested_by: c.e.Positive
    recorded_at: c.e.UtcText
    document_change_binding: DocumentChangeBinding
    source_bytes: int = Field(strict=True, gt=0, le=c.MAX_CASE_BYTES)
    prompt_hash: c.e.SHA256
    context_digest: c.e.SHA256
    input_hash: c.e.SHA256
    evidence_hash: c.e.SHA256
    metadata_hash: c.e.SHA256
    scope_created_audit_event_id: c.e.Positive
    scope_review_audit_event_id: c.e.Positive
    created_audit_event_id: c.e.Positive
    usage_event_id: c.e.Positive | None

    @model_validator(mode="after")
    def anchor_clock(self):
        c.e.clock(self.recorded_at)
        ids = [self.scope_created_audit_event_id, self.scope_review_audit_event_id, self.created_audit_event_id]
        if self.usage_event_id is not None:
            ids.append(self.usage_event_id)
        if len(ids) != len(set(ids)):
            raise ValueError("Task creation, Scope governance and actual receipt use distinct audit events")
        return self
