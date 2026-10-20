"""Short, exact scenario references and public-only native surgery payloads."""

from typing import Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from app.ai.surgery_contract import SHA256, UUID, StrictModel, SurgerySource, canonical_json, hash_content, identity

SCOPE_NOTE = "仅在明确声明病例、有限开始时刻及共享阶段资源范围内核对候选；时长估计、资格、覆盖和政策保留原审核状态，不自动预订或改变手术执行"
MISSING_DATA = (
    SCOPE_NOTE,
    "固定搜索证明仅适用于所选目标与明确声明域；未知资料、搜索预算及原始业务记录缺口单独保留，不等于临床或真实运营验证。",
)


class SurgeryContextBinding(StrictModel):
    schema_version: Literal["surgery_context_binding_v1"]
    scenario_id: UUID
    pool_id: UUID
    department_id: int = Field(ge=1, le=2147483647)
    revision: Literal[2]
    source_id: str = Field(min_length=1, max_length=125)
    content_hash: SHA256
    governance_hash: SHA256
    projection_hash: SHA256
    scope_token: UUID
    original_scope_hash: SHA256
    collection_digest: SHA256
    case_collection_digest: SHA256
    resource_collection_digest: SHA256
    busy_collection_digest: SHA256
    fact_collection_digest: SHA256
    manifest_digest: SHA256
    rule_id: Literal["surgery_declared_stage_resources_v1"]
    rule_version: Literal["1"]
    profile_token: UUID
    profile_content_hash: SHA256
    profile_governance_hash: SHA256
    recipe_hash: SHA256
    input_policy_hash: SHA256

    @model_validator(mode="after")
    def original_identity(self):
        if self.source_id != f"surgery_scenario:{self.scenario_id}:{self.content_hash[:12]}":
            raise ValueError("Original surgery scenario identity differs")
        return self


def selection(values):
    if not isinstance(values, dict) or set(values) - {"surgery_scenario_id", "question"} or "surgery_scenario_id" not in values:
        raise HTTPException(422, "本地手术排程须明确引用一件受审完整场景，仅可另附院内问题；不能覆盖病例、目标、时间或资源")
    if "question" in values and (not isinstance(values["question"], str) or len(values["question"]) > 12000):
        raise HTTPException(422, "补充问题须为最多12000字文本，仅留院内核对")
    try:
        return identity(values["surgery_scenario_id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "手术排程场景须为规范UUID") from exc


def binding_for(source, *, pool_id, department_id):
    """Bind every original collection and policy identity without private bodies."""
    public = SurgerySource.model_validate(source).model_dump(mode="json")
    return SurgeryContextBinding(
        schema_version="surgery_context_binding_v1",
        pool_id=pool_id,
        department_id=department_id,
        revision=2,
        **{key: public[key] for key in ("scenario_id", "source_id", "content_hash", "governance_hash", "scope_token", "original_scope_hash")},
        projection_hash=hash_content(public),
        **public["collection"],
        **public["rule_binding"],
    ).model_dump(mode="json")


def surgery_evidence(binding):
    """One reconstructible citation; private case facts stay in their local blob."""
    bound = SurgeryContextBinding.model_validate(binding).model_dump(mode="json")
    return {
        "source_id": bound["source_id"],
        "kind": "operational_record",
        "title": "受审完整手术病例与阶段资源排程场景",
        "content": canonical_json({"surgery_binding": bound}),
    }


def public_payload(data):
    """Verify typed references, then return only the native public projection."""
    identifier = selection(data["input"])
    context = data["context"]
    public = SurgerySource.model_validate(context["surgery_source"]).model_dump(mode="json")
    bound = SurgeryContextBinding.model_validate(context["surgery_binding"])
    if identifier != bound.scenario_id or identifier != public["scenario_id"]:
        raise ValueError("Original selected surgery scenario differs")
    expected = binding_for(public, pool_id=bound.pool_id, department_id=bound.department_id)
    if expected != bound.model_dump(mode="json"):
        raise ValueError("Complete public surgery source, collections or policy binding differs")
    return {"context": {"surgery_source": public}}
