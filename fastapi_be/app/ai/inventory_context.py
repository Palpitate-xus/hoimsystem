"""Exact scenario references; only typed opaque whole candidates reach the native comparator."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from app.ai.inventory_contract import SHA256, UUID, InventorySource, StrictModel, canonical_json, hash_content, identity, utc

SCOPE_NOTE = "仅比较单物资、明确物理范围及数量与成本计量单位下的完整声明采购候选；逐日核对受审未来数量情景、效期、冻结量、约束和明确采购成本，不自动下单或改变库存"
MISSING_DATA = (
    SCOPE_NOTE,
    "零、未知、单位不符及原账冲突分别保留；最优或不可行证明仅限完整声明候选集合，未知候选阻断全集证明，不代表所有可能采购组合或真实运营效果验证。",
)


class InventoryContextBinding(StrictModel):
    schema_version: Literal["inventory_context_binding_v1"]
    scenario_id: UUID
    item_kind: Literal["pharmaceutical", "consumable"]
    item_id: int = Field(ge=1, le=2147483647)
    scope: Literal["hospital_inventory"]
    unit_definition_id: UUID
    revision: Literal[2]
    source_id: str = Field(min_length=1, max_length=110)
    content_hash: SHA256
    scenario_governance_hash: SHA256
    projection_hash: SHA256
    collection_digest: SHA256
    member_manifest_hash: SHA256
    profile_id: UUID
    profile_content_hash: SHA256
    profile_governance_hash: SHA256
    scope_token: SHA256
    item_token: SHA256
    quantity_unit_token: SHA256
    cost_unit_token: SHA256
    rule_id: Literal["inventory_declared_candidate_plans_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256

    @model_validator(mode="after")
    def original_identity(self):
        if self.source_id != f"inventory_scenario:{self.scenario_id}:{self.content_hash[:12]}":
            raise ValueError("Original inventory scenario identity differs")
        return self


def selection(values):
    if not isinstance(values, dict) or set(values) - {"inventory_scenario_id", "question"} or "inventory_scenario_id" not in values:
        raise HTTPException(422, "本地库存方案比较须明确引用一件受审完整场景，仅可另附院内问题；不能覆盖库存、数量、候选、费用或共同政策")
    if "question" in values and (not isinstance(values["question"], str) or len(values["question"]) > 12000):
        raise HTTPException(422, "补充问题须为最多12000字文本，仅留院内核对")
    try:
        return identity(values["inventory_scenario_id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "库存比较场景须为规范UUID") from exc


def inventory_evidence(binding):
    bound = InventoryContextBinding.model_validate(binding).model_dump(mode="json")
    return {"source_id": bound["source_id"], "kind": "operational_record", "title": "受审库存实盘、未来数量情景与完整采购候选集合", "content": canonical_json({"inventory_binding": bound})}


def _short_context(binding, snapshot_time):
    bound = InventoryContextBinding.model_validate(binding)
    return {
        "scope": "hospital_inventory",
        "source_domain": "declared_inventory_candidate_comparison",
        "department_ids": [],
        "selected_sources": {"inventory_scenario_id": bound.scenario_id},
        "inventory_binding": bound.model_dump(mode="json"),
        "scope_note": SCOPE_NOTE,
        "missing_data": list(MISSING_DATA),
        "truncated_sources": [],
        "snapshot_time": utc(snapshot_time),
    }


def inventory_context(db, user, values):
    from app.ai.context import ContextBundle
    from app.ai.inventory_scenarios import authorize_scenario, binding_for

    row, _, source = authorize_scenario(db, user, selection(values))
    bound = InventoryContextBinding(schema_version="inventory_context_binding_v1", **binding_for(row, source)).model_dump(mode="json")
    now = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return ContextBundle(data=_short_context(bound, now), evidence=[inventory_evidence(bound)], department_ids=set())


def public_payload(data):
    identifier = selection(data["input"])
    source = InventorySource.model_validate(data["context"]["inventory_source"]).model_dump(mode="json")
    bound = InventoryContextBinding.model_validate(data["context"]["inventory_binding"])
    keys = (
        "scenario_id",
        "item_kind",
        "source_id",
        "content_hash",
        "profile_id",
        "profile_content_hash",
        "profile_governance_hash",
        "scope_token",
        "item_token",
        "quantity_unit_token",
        "cost_unit_token",
        "rule_id",
        "recipe_digest",
        "input_policy_digest",
        "member_manifest_hash",
    )
    if (
        identifier != bound.scenario_id
        or any(source[key] != getattr(bound, key) for key in keys)
        or source["governance_hash"] != bound.scenario_governance_hash
        or hash_content(source) != bound.projection_hash
    ):
        raise ValueError("Complete public inventory source, original identities, units, candidate set or common policy differ")
    return {"context": {"inventory_source": source}}


def expand_context(db, context, *, user=None, current=False, execution=True):
    from app.ai.inventory_scenarios import authorize_scenario, binding_for, metadata, scenario_proof, scenario_row

    try:
        bound = InventoryContextBinding.model_validate(context["inventory_binding"])
        binding = bound.model_dump(mode="json")
        if canonical_json(context) != canonical_json(_short_context(binding, context["snapshot_time"])):
            raise ValueError("Original short inventory context contains a different scope or undisclosed fields")
        if current:
            row, snapshot, source = authorize_scenario(db, user, bound.scenario_id, binding=binding, execution=execution)
        else:
            row = scenario_row(db, bound.scenario_id)
            snapshot, source = scenario_proof(row)
        expected = InventoryContextBinding(schema_version="inventory_context_binding_v1", **binding_for(row, source)).model_dump(mode="json")
        if source is None or expected != binding:
            raise ValueError("Complete original inventory source or publication binding differs")
        return {
            **context,
            "inventory_source": source,
            "inventory_scenario": {
                **metadata(row, include_private_governance=True),
                "snapshot": snapshot,
                "public_source": source,
                "frozen_task_view": True,
                "can_record": False,
                "can_review": False,
                "can_revoke": False,
                "automatic_purchase": False,
            },
        }
    except HTTPException as exc:
        if exc.status_code == 403:
            raise
        raise HTTPException(409, "库存完整场景、公开投影或冻结任务绑定不符") from exc
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(409, "库存完整场景、公开投影或冻结任务绑定不符") from exc


def authorize_inventory_snapshot(db, user, context):
    from app.ai.inventory_scenarios import current_actor

    actor = current_actor(db, user)
    expand_context(db, context, user=actor, current=actor.user_role != "super_admin", execution=False)
