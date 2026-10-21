"""Governed finite inventory plan comparisons; never writes stock or purchase orders."""

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic_core import core_schema
from sqlalchemy.orm import Session, defer

from app.ai import inventory_scenarios as scenarios
from app.ai.inventory_native_source_input import SOURCE_ROLES, ItemKind
from app.ai.inventory_scenario_input import ScenarioPeriodRequest, preview_input
from app.ai.inventory_scenario_models import AIInventoryScenario
from app.database import get_db
from app.dependencies import require_roles
from app.models import User

router = APIRouter(tags=["AI受审完整库存候选场景"], default_response_class=JSONResponse)
Status = Literal["draft", "published", "rejected", "revoked"]


class QueryPositiveInteger(int):
    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        def validate(value):
            if isinstance(value, str):
                if not re.fullmatch(r"[1-9][0-9]*", value):
                    raise ValueError("Canonical positive integer required")
                value = int(value)
            if type(value) is not int or not 1 <= value <= 2147483647:
                raise ValueError("Positive integer required")
            return value

        return core_schema.no_info_plain_validator_function(validate, json_schema_input_schema=core_schema.int_schema(gt=0, le=2147483647))


def write(db, user, operation):
    try:
        row = operation()
        data = scenarios.scenario_current(db, user, row.scenario_id, audit_only=scenarios.current_actor(db, user).user_role == "super_admin")
        db.commit()
        return {"code": 200, "data": data}
    except Exception:
        db.rollback()
        raise


def listing(db, user, item_kind, item_id, status, page, page_size):
    actor = scenarios.current_actor(db, user)
    if (item_kind is None) != (item_id is None):
        raise HTTPException(422, "须同时明确SKU类型与实际标识")
    if page_size > 100:
        raise HTTPException(422, "每页最多100条")
    query = db.query(AIInventoryScenario).options(defer(AIInventoryScenario.snapshot_json), defer(AIInventoryScenario.projection_json))
    if item_kind is not None:
        if actor.user_role != "super_admin":
            scenarios.require_sku(db, item_kind, item_id)
        query = query.filter_by(item_kind=item_kind, item_id=item_id)
    if status is not None:
        query = query.filter_by(status=status)
    total = query.with_entities(AIInventoryScenario.scenario_id).count()
    rows = query.order_by(AIInventoryScenario.created_at.desc(), AIInventoryScenario.scenario_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [scenarios.metadata(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/ai/inventory-scenarios/preview")
def preview(req: ScenarioPeriodRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return {"code": 200, "data": preview_input(db, user, req)}


@router.get("/ai/inventory-scenarios")
def scenario_list(
    item_kind: ItemKind | None = None,
    item_id: QueryPositiveInteger | None = None,
    status: Status | None = None,
    page: QueryPositiveInteger = Query(1),
    page_size: QueryPositiveInteger = Query(20),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SOURCE_ROLES)),
):
    return {"code": 200, "data": listing(db, user, item_kind, item_id, status, page, page_size)}


@router.post("/ai/inventory-scenarios")
def create(req: scenarios.ScenarioCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return write(db, user, lambda: scenarios.create_scenario(db, user, req))


@router.get("/ai/inventory-scenarios/{scenario_id}")
def detail(scenario_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return {"code": 200, "data": scenarios.scenario_current(db, user, scenario_id)}


@router.post("/ai/inventory-scenarios/{scenario_id}/review")
def review(scenario_id: str, req: scenarios.ScenarioReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return write(db, user, lambda: scenarios.review_scenario(db, user, scenario_id, req))


@router.post("/ai/inventory-scenarios/{scenario_id}/revoke")
def revoke(scenario_id: str, req: scenarios.ScenarioRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return write(db, user, lambda: scenarios.revoke_scenario(db, user, scenario_id, req))


@router.get("/ai/admin/inventory-scenarios")
def admin_list(
    item_kind: ItemKind | None = None,
    item_id: QueryPositiveInteger | None = None,
    status: Status | None = None,
    page: QueryPositiveInteger = Query(1),
    page_size: QueryPositiveInteger = Query(20),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    if scenarios.current_actor(db, user).user_role != "super_admin":
        raise HTTPException(403, "当前账户不是超级管理员")
    return {"code": 200, "data": listing(db, user, item_kind, item_id, status, page, page_size)}


@router.get("/ai/admin/inventory-scenarios/{scenario_id}")
def admin_detail(scenario_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return {"code": 200, "data": scenarios.scenario_current(db, user, scenario_id, audit_only=True)}
