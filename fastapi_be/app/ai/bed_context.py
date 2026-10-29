"""Short Ward/series/horizon bindings; complete originals stay in bounded local SQL."""

from typing import Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from app.ai import bed_facts as facts
from app.ai.bed_contract import RULE_ID, SHA256, UUID, StrictModel, canonical_json, hash_content


class BedContextBinding(StrictModel):
    schema_version: Literal["bed_context_binding_v1"]
    series_id: UUID
    department_id: int = Field(ge=1, le=2147483647)
    ward_id: int = Field(ge=1, le=2147483647)
    revision: Literal[2]
    source_id: str = Field(min_length=1, max_length=110)
    content_hash: SHA256
    series_governance_hash: SHA256
    projection_hash: SHA256
    scope_token: SHA256
    member_manifest_hash: SHA256
    collection_digest: SHA256
    historical_collection_digest: SHA256
    current_membership_digest: SHA256
    future_scenario_collection_digest: SHA256
    rule_id: Literal["bed_physical_daily_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    horizon_days: Literal[7, 14]

    @field_validator("source_id")
    @classmethod
    def original_series_identity(cls, value, info):
        if not value.startswith("bed_series:" + info.data["series_id"] + ":"):
            raise ValueError("Original bed series identity differs")
        return value


def selection(values):
    if not isinstance(values, dict) or set(values) - {"bed_series_id", "horizon_days", "question"} or not {"bed_series_id", "horizon_days"} <= set(values):
        raise HTTPException(422, "本地床位预测须选择一件受审序列和明确的7或14日预测期，仅可另附本地问题；不接受原量或容量覆盖")
    if type(values["horizon_days"]) is not int or values["horizon_days"] not in {7, 14}:
        raise HTTPException(422, "床位预测期须为实际整数7或14个完整业务日")
    if "question" in values and (not isinstance(values["question"], str) or len(values["question"]) > 12000):
        raise HTTPException(422, "床位预测问题最多12000字。")
    try:
        return facts.canonical_id(values["bed_series_id"]), values["horizon_days"]
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "床位序列须为规范UUID") from exc


def bed_evidence(binding):
    """Reconstruct the sole local citation from the typed immutable task binding."""
    return {"source_id": binding["source_id"], "kind": "operational_record", "title": "受审病区实占床位与实际流转事件序列", "content": canonical_json({"bed_binding": binding})}


def bed_context(db, user, values):
    from app.ai.bed_series import authorize_series, binding_for
    from app.ai.context import ContextBundle

    series_id, horizon = selection(values)
    row, _, source = authorize_series(db, user, series_id)
    bound = BedContextBinding(schema_version="bed_context_binding_v1", horizon_days=horizon, **binding_for(row, source)).model_dump(mode="json")
    note = "预测对象为原业务日边界实占床位数及四类实际流转事件；未来总运行床位仅为明确审核情景，不能解释为即时可收治床位或未满足需求"
    return ContextBundle(
        data={
            "scope": "department",
            "source_domain": "bed_observed_physical_series",
            "department_ids": [row.department_id],
            "ward_ids": [row.ward_id],
            "selected_sources": {"bed_series_id": row.series_id},
            "bed_binding": bound,
            "scope_note": note,
            "missing_data": [note, "各目标独立检查来源完整性；缺项保留未知，流转事件预测不能替代实占床位预测。回测基于本次冻结原件，不构成历史可得性重放或实际运营验证"],
            "truncated_sources": [],
            "snapshot_time": facts.utc_text(facts.utcnow()),
        },
        evidence=[bed_evidence(bound)],
        department_ids={row.department_id},
    )


def expand_context(db, context, *, user=None, current=False, execution=True):
    from app.ai.bed_series import authorize_series, binding_for, metadata, series_proof, series_row

    try:
        bound = BedContextBinding.model_validate(context["bed_binding"])
        if current:
            row, snapshot, source = authorize_series(db, user, bound.series_id, execution=execution, binding=bound.model_dump(mode="json"))
        else:
            row = series_row(db, bound.series_id)
            snapshot, source = series_proof(row)
        expected = BedContextBinding(schema_version="bed_context_binding_v1", horizon_days=bound.horizon_days, **binding_for(row, source)).model_dump(mode="json")
        if expected != bound.model_dump(mode="json") or source is None or hash_content(source) != bound.projection_hash or source["rule_id"] != RULE_ID:
            raise ValueError("Original published bed series binding differs")
        return {
            **context,
            "bed_source": source,
            "bed_series": {
                **metadata(row),
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
        raise HTTPException(409, "床位原序列、完整原件或公开投影与冻结任务引用不符") from exc
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(409, "床位原序列、完整原件或公开投影与冻结任务引用不符") from exc


def authorize_bed_snapshot(db, user, context):
    actor = facts.current_actor(db, user)
    expand_context(db, context, user=actor, current=actor.user_role != "super_admin", execution=False)
