"""Exact original SKU/scenario task filters with current actor and complete frozen proofs."""

from fastapi import HTTPException
from sqlalchemy import JSON, type_coerce

from app.ai.inventory_contract import identity
from app.ai.models import AIRun


def filter_history(db, user, query, *, inventory_item_kind=None, inventory_item_id=None, inventory_scenario_id=None):
    from app.ai.inventory_scenarios import authorize_scenario, current_actor, require_sku, scenario_proof, scenario_row

    actor = current_actor(db, user)
    if (inventory_item_kind is None) != (inventory_item_id is None):
        raise HTTPException(422, "库存比较历史须同时提供明确品种类型与标识")
    if inventory_item_kind is not None:
        if inventory_item_kind not in {"pharmaceutical", "consumable"} or type(inventory_item_id) is not int or not 1 <= inventory_item_id <= 2147483647:
            raise HTTPException(422, "库存比较历史品种类型或标识无效")
        try:
            require_sku(db, inventory_item_kind, inventory_item_id)
        except HTTPException as exc:
            if actor.user_role != "super_admin" or exc.status_code != 409:
                raise
    bound = type_coerce(AIRun.input_json, JSON)["payload"]["context"]["inventory_binding"]
    if inventory_scenario_id is not None:
        try:
            inventory_scenario_id = identity(inventory_scenario_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(422, "库存比较历史场景须为规范UUID") from exc
        row = scenario_row(db, inventory_scenario_id)
        if actor.user_role == "super_admin":
            scenario_proof(row)
        else:
            authorize_scenario(db, actor, row.scenario_id, execution=False)
        if inventory_item_kind is not None and (row.item_kind, row.item_id) != (inventory_item_kind, inventory_item_id):
            raise HTTPException(422, "所选原场景与库存历史品种范围不同")
        query = query.filter(bound["scenario_id"].as_string() == inventory_scenario_id)
    if inventory_item_kind is not None:
        query = query.filter(bound["item_kind"].as_string() == inventory_item_kind, bound["item_id"].as_integer() == inventory_item_id, bound["scope"].as_string() == "hospital_inventory")
    return query
