"""Exact SKU/series/horizon references; only typed opaque quantities leave the hospital."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from app.ai.supply_contract import SHA256, UUID, StrictModel, SupplySource, canonical_json, hash_content, identity, utc

SCOPE_NOTE = "仅预测单一物资、明确库存范围和审核计量单位下的原申请量、实际发出量及确认消耗量；三目标独立核对，不能解释为潜在需求或采购指令"
MISSING_DATA = (
    SCOPE_NOTE,
    "零、未知、单位不符及原件冲突分别保留；滚动回测基于本次冻结原件，不代表历史可得性重放、未来区间或真实运营效果验证。",
)


class SupplyContextBinding(StrictModel):
    schema_version: Literal["supply_context_binding_v1"]
    series_id: UUID
    item_kind: Literal["pharmaceutical", "consumable"]
    item_id: int = Field(ge=1, le=2147483647)
    scope: Literal["hospital_inventory"]
    unit_definition_id: UUID
    revision: Literal[2]
    source_id: str = Field(min_length=1, max_length=110)
    content_hash: SHA256
    series_governance_hash: SHA256
    projection_hash: SHA256
    collection_digest: SHA256
    historical_collection_digest: SHA256
    current_membership_digest: SHA256
    member_manifest_hash: SHA256
    profile_id: UUID
    profile_content_hash: SHA256
    profile_governance_hash: SHA256
    scope_token: SHA256
    item_token: SHA256
    unit_token: SHA256
    rule_id: Literal["supply_recorded_quantity_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    horizon_days: Literal[7, 14]

    @model_validator(mode="after")
    def original_identity(self):
        if self.source_id != f"supply_series:{self.series_id}:{self.content_hash[:12]}":
            raise ValueError("Original supply series identity differs")
        return self


def selection(values):
    if not isinstance(values, dict) or set(values) - {"supply_series_id", "horizon_days", "question"} or not {"supply_series_id", "horizon_days"} <= set(values):
        raise HTTPException(422, "本地物资预测须明确引用一件受审完整序列和7或14日预测期，仅可另附院内问题；不能覆盖原量、单位或参数")
    if type(values["horizon_days"]) is not int or values["horizon_days"] not in {7, 14}:
        raise HTTPException(422, "物资预测期须为实际整数7或14个完整业务日")
    if "question" in values and (not isinstance(values["question"], str) or len(values["question"]) > 12000):
        raise HTTPException(422, "补充问题须为最多12000字文本，仅留院内核对")
    try:
        return identity(values["supply_series_id"]), values["horizon_days"]
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "物资预测序列须为规范UUID") from exc


def supply_evidence(binding):
    bound = SupplyContextBinding.model_validate(binding).model_dump(mode="json")
    return {"source_id": bound["source_id"], "kind": "operational_record", "title": "受审物资申请、实际发出与确认消耗完整原量序列", "content": canonical_json({"supply_binding": bound})}


def _short_context(binding, snapshot_time):
    bound = SupplyContextBinding.model_validate(binding)
    return {
        "scope": "hospital_inventory",
        "source_domain": "recorded_supply_quantity_series",
        "department_ids": [],
        "selected_sources": {"supply_series_id": bound.series_id},
        "supply_binding": bound.model_dump(mode="json"),
        "scope_note": SCOPE_NOTE,
        "missing_data": list(MISSING_DATA),
        "truncated_sources": [],
        "snapshot_time": utc(snapshot_time),
    }


def supply_context(db, user, values):
    from app.ai.context import ContextBundle
    from app.ai.supply_series import authorize_series, binding_for

    series_id, horizon = selection(values)
    row, _, source = authorize_series(db, user, series_id, horizon)
    bound = SupplyContextBinding(schema_version="supply_context_binding_v1", horizon_days=horizon, **binding_for(row, source)).model_dump(mode="json")
    now = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return ContextBundle(data=_short_context(bound, now), evidence=[supply_evidence(bound)], department_ids=set())


def public_payload(data):
    series_id, horizon = selection(data["input"])
    source = SupplySource.model_validate(data["context"]["supply_source"]).model_dump(mode="json")
    bound = SupplyContextBinding.model_validate(data["context"]["supply_binding"])
    keys = (
        "series_id",
        "item_kind",
        "source_id",
        "content_hash",
        "profile_id",
        "profile_content_hash",
        "profile_governance_hash",
        "scope_token",
        "item_token",
        "unit_token",
        "rule_id",
        "recipe_digest",
        "input_policy_digest",
        "historical_collection_digest",
        "current_membership_digest",
        "member_manifest_hash",
    )
    if (
        series_id != bound.series_id
        or horizon != bound.horizon_days
        or any(source[key] != getattr(bound, key) for key in keys)
        or source["governance_hash"] != bound.series_governance_hash
        or hash_content(source) != bound.projection_hash
    ):
        raise ValueError("Complete public supply source, original identities, policy or horizon differ")
    return {"context": {"supply_source": source}, "horizon_days": horizon}


def expand_context(db, context, *, user=None, current=False, execution=True):
    from app.ai.supply_series import authorize_series, binding_for, metadata, series_proof, series_row

    try:
        bound = SupplyContextBinding.model_validate(context["supply_binding"])
        binding = bound.model_dump(mode="json")
        if canonical_json(context) != canonical_json(_short_context(binding, context["snapshot_time"])):
            raise ValueError("Original short supply context contains a different scope or undisclosed fields")
        if current:
            row, snapshot, source = authorize_series(db, user, bound.series_id, bound.horizon_days, binding=binding, execution=execution)
        else:
            row = series_row(db, bound.series_id)
            snapshot, source = series_proof(row)
        expected = SupplyContextBinding(schema_version="supply_context_binding_v1", horizon_days=bound.horizon_days, **binding_for(row, source)).model_dump(mode="json")
        if source is None or expected != binding:
            raise ValueError("Complete original supply source or publication binding differs")
        return {
            **context,
            "supply_source": source,
            "supply_series": {
                **metadata(row, include_private_governance=True),
                "snapshot": snapshot,
                "public_source": source,
                "frozen_task_view": True,
                "can_record": False,
                "can_review": False,
                "can_revoke": False,
            },
        }
    except HTTPException as exc:
        if exc.status_code == 403:
            raise
        raise HTTPException(409, "物资完整原序列、公开投影或冻结任务绑定不符") from exc
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(409, "物资完整原序列、公开投影或冻结任务绑定不符") from exc


def authorize_supply_snapshot(db, user, context):
    from app.ai.supply_sources import current_actor

    actor = current_actor(db, user)
    expand_context(db, context, user=actor, current=actor.user_role != "super_admin", execution=False)
