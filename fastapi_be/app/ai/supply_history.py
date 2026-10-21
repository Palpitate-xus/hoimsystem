"""Exact original SKU/series history filters with current-role checks."""

from fastapi import HTTPException
from sqlalchemy import JSON, type_coerce

from app.ai.models import AIRun
from app.ai.supply_contract import identity


def filter_history(db, user, query, *, supply_item_kind=None, supply_item_id=None, supply_series_id=None):
    from app.ai.supply_series import authorize_series, series_proof, series_row
    from app.ai.supply_sources import current_actor, sku_binding

    actor = current_actor(db, user)
    if (supply_item_kind is None) != (supply_item_id is None):
        raise HTTPException(422, "物资历史须同时提供明确品种类型与标识")
    if supply_item_kind is not None:
        if supply_item_kind not in {"pharmaceutical", "consumable"} or type(supply_item_id) is not int or not 1 <= supply_item_id <= 2147483647:
            raise HTTPException(422, "物资历史品种类型或标识无效")
        try:
            sku_binding(db, supply_item_kind, supply_item_id)
        except HTTPException as exc:
            if actor.user_role != "super_admin" or exc.status_code != 404:
                raise
    bound = type_coerce(AIRun.input_json, JSON)["payload"]["context"]["supply_binding"]
    if supply_series_id is not None:
        try:
            supply_series_id = identity(supply_series_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(422, "物资历史序列须为规范UUID") from exc
        row = series_row(db, supply_series_id)
        if actor.user_role == "super_admin":
            series_proof(row)
        else:
            authorize_series(db, actor, row.series_id, 7, execution=False)
        if supply_item_kind is not None and (row.item_kind, row.item_id) != (supply_item_kind, supply_item_id):
            raise HTTPException(422, "所选原序列与物资历史品种范围不同")
        query = query.filter(bound["series_id"].as_string() == supply_series_id)
    if supply_item_kind is not None:
        query = query.filter(bound["item_kind"].as_string() == supply_item_kind, bound["item_id"].as_integer() == supply_item_id, bound["scope"].as_string() == "hospital_inventory")
    return query
