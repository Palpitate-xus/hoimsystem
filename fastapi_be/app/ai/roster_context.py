"""Short task bindings to complete local roster declarations, with current scope checks."""

from typing import Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from app.ai import roster_facts as facts
from app.ai.roster_contract import SHA256, StrictModel, hash_content


class RosterContextBinding(StrictModel):
    schema_version: Literal["roster_context_binding_v1"]
    plan_id: str
    department_id: int = Field(ge=1, le=2147483647)
    revision: Literal[2]
    source_id: str
    content_hash: SHA256
    problem_governance_hash: SHA256
    projection_hash: SHA256
    scope_binding_hash: SHA256
    manifest_digest: SHA256
    collection_digest: SHA256
    rule_id: Literal["roster_declared_constraints_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    _id = field_validator("plan_id")(facts.canonical_id)


def selection(values):
    if not isinstance(values, dict) or set(values) - {"roster_plan_id", "question"} or "roster_plan_id" not in values:
        raise HTTPException(422, "本地排班仅接受一件受审计划引用及可选本地问题，不接受其他来源、约束或原量覆盖")
    if "question" in values and (not isinstance(values["question"], str) or len(values["question"]) > 12000):
        raise HTTPException(422, "排班问题最多12000字。")
    try:
        return facts.canonical_id(values["roster_plan_id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "排班计划须为规范UUID") from exc


def roster_context(db, user, values):
    from app.ai.context import ContextBundle
    from app.ai.roster_plans import authorize_plan, binding_for

    row, _, source = authorize_plan(db, user, selection(values))
    bound = RosterContextBinding(schema_version="roster_context_binding_v1", **binding_for(row, source)).model_dump(mode="json")
    note = "仅明确审核的场景净容量与约束，不是实时可预约余号；来源审核与合成算例不构成实际运营效果验证，不自动发布排班或修改库存"
    return ContextBundle(
        data={
            "scope": "department",
            "source_domain": "roster_declared_scenario",
            "department_ids": [row.department_id],
            "selected_sources": {"roster_plan_id": row.plan_id},
            "roster_binding": bound,
            "scope_note": note,
            "missing_data": [note, "人员按整班分配不等于每个时刻均有人提供服务；未实现连续在岗人数和连续本地工作日限制"],
            "truncated_sources": [],
            "snapshot_time": facts.utc_text(facts.utcnow()),
        },
        evidence=[{"source_id": source["source_id"], "kind": "operational_record", "title": "受审完整排班场景与约束原声明", "content": facts.canonical_json({"roster_binding": bound})}],
        department_ids={row.department_id},
    )


def expand_context(db, context, *, user=None, current=False, execution=True):
    from app.ai.roster_plans import authorize_plan, binding_for, metadata, plan_proof, plan_row

    try:
        bound = RosterContextBinding.model_validate(context["roster_binding"])
        if current:
            row, snapshot, source = authorize_plan(db, user, bound.plan_id, execution=execution, binding=bound.model_dump(mode="json"))
        else:
            row = plan_row(db, bound.plan_id)
            snapshot, source = plan_proof(row)
        expected = RosterContextBinding(schema_version="roster_context_binding_v1", **binding_for(row, source)).model_dump(mode="json")
        if expected != bound.model_dump(mode="json") or source is None or hash_content(source) != bound.projection_hash:
            raise ValueError("Original published plan binding differs")
        return {
            **context,
            "roster_source": source,
            "roster_plan": {
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
        raise HTTPException(409, "排班原计划、完整来源或公开投影与冻结引用不符") from exc
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(409, "排班原计划、完整来源或公开投影与冻结引用不符") from exc


def authorize_roster_snapshot(db, user, context):
    actor = facts.current_actor(db, user)
    expand_context(db, context, user=actor, current=actor.user_role != "super_admin", execution=False)
