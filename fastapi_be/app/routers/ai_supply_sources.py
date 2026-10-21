"""Explicit SKU original governance APIs. No stock, dispensing or purchasing writes."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.ai import supply_collection as collection
from app.ai import supply_sources as sources
from app.ai.supply_contract import TARGETS
from app.ai.supply_source_input import SOURCE_ROLES, ItemKind, SourceCreate, SourceReview, SourceRevoke, UnitCreate
from app.database import get_db
from app.dependencies import require_roles
from app.models import Consumable, Pharmaceutical, User
from app.routers.inpatient_support import QueryPositiveInteger

router = APIRouter(tags=["AI医院单SKU计数单位与原始数量"], default_response_class=JSONResponse)


def write(db, user, operation, kind):
    try:
        row = operation()
        rid = getattr(row, sources.MODELS[kind][1])
        actual = sources.current_actor(db, user, locking=True)
        data = sources.source_current(db, actual, kind, rid, audit_only=actual.user_role == "super_admin", locking=True)
        if not sources.verify_source_wrapper(data):
            raise HTTPException(409, "原件回执自身核对失败，本次未保存")
        db.commit()
        return {"code": 200, "data": data}
    except (IntegrityError, OperationalError) as exc:
        db.rollback()
        raise HTTPException(409, "原件、单位、版本或数据库锁已冲突，本次均未保存") from exc
    except Exception:
        db.rollback()
        raise


@router.get("/ai/supply-sources/options")
def options(
    item_kind: ItemKind | None = None,
    item_id: QueryPositiveInteger | None = Query(None, ge=1),
    keyword: str | None = Query(None, max_length=120),
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SOURCE_ROLES)),
):
    actor = sources.current_actor(db, user)
    if item_id is not None and item_kind is None:
        raise HTTPException(422, "明确品种标识必须同时提供真实品种类型")
    items = []
    total = 0
    if item_kind is not None:
        model, pk = (Pharmaceutical, Pharmaceutical.pharmaceutical_id) if item_kind == "pharmaceutical" else (Consumable, Consumable.consumable_id)
        query = db.query(model).filter(model.status == 0)
        if item_id is not None:
            query = query.filter(pk == item_id)
        if keyword:
            query = query.filter(or_(model.name.contains(keyword), model.barcode.contains(keyword))) if item_kind == "pharmaceutical" else query.filter(model.name.contains(keyword))
        total = query.count()
        for row in query.order_by(pk).offset((page - 1) * page_size).limit(page_size).all():
            rid = row.pharmaceutical_id if item_kind == "pharmaceutical" else row.consumable_id
            binding = sources.sku_binding(db, item_kind, rid)
            items.append({"item_kind": item_kind, "item_id": rid, "name": row.name, "status": row.status, "scope": "hospital_inventory", "identity_hash": sources.hash_content(binding)})
    return {
        "code": 200,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "scope": "hospital_inventory",
            "item_kinds": ["pharmaceutical", "consumable"],
            "source_kinds": ["unit_definition", "daily_quantity"],
            "targets": list(TARGETS),
            "can_record": True,
            "can_confirm_professional": actor.user_role == "pharmacist",
            "professional_signer_user_id": actor.user_id if actor.user_role == "pharmacist" else None,
            "can_review": actor.user_role == "super_admin",
            "provider_required": False,
            "scope_note": "当前平台明确授权的全院库存原件；不虚构科室、库房或执照权限。单SKU/单原计数单位，不自动换算，不把目录库存变化当实际历史。",
        },
    }


def listing(db, user, kind, item_kind, item_id, page, page_size):
    sources.current_actor(db, user)
    sources.sku_binding(db, item_kind, item_id)
    model, primary = sources.MODELS[kind]
    query = db.query(model).filter(model.item_kind == item_kind, model.item_id == item_id, model.scope == "hospital_inventory")
    total = query.count()
    rows = query.with_entities(getattr(model, primary)).order_by(model.recorded_at.desc(), getattr(model, primary)).offset((page - 1) * page_size).limit(page_size).all()
    items = [sources.source_metadata(sources.source_current(db, user, kind, row[0])) for row in rows]
    return {"code": 200, "data": {"items": items, "total": total, "page": page, "page_size": page_size, "detail_required": True}}


@router.get("/ai/supply-sources/units")
def unit_list(
    item_kind: ItemKind,
    item_id: QueryPositiveInteger = Query(..., ge=1),
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SOURCE_ROLES)),
):
    return listing(db, user, "unit", item_kind, item_id, page, page_size)


@router.post("/ai/supply-sources/units")
def unit_create(req: UnitCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return write(db, user, lambda: sources.create_unit(db, user, req), "unit")


@router.get("/ai/supply-sources/units/{record_id}")
def unit_detail(record_id: str, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return {"code": 200, "data": sources.source_current(db, user, "unit", record_id, audit_only=audit_only)}


@router.post("/ai/supply-sources/units/{record_id}/review")
def unit_review(record_id: str, req: SourceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return write(db, user, lambda: sources.review_source(db, user, "unit", record_id, req), "unit")


@router.post("/ai/supply-sources/units/{record_id}/revoke")
def unit_revoke(record_id: str, req: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return write(db, user, lambda: sources.review_source(db, user, "unit", record_id, req, revoke=True), "unit")


@router.get("/ai/supply-sources/daily")
def daily_list(
    item_kind: ItemKind,
    item_id: QueryPositiveInteger = Query(..., ge=1),
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SOURCE_ROLES)),
):
    return listing(db, user, "daily", item_kind, item_id, page, page_size)


@router.post("/ai/supply-sources/daily")
def daily_create(req: SourceCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return write(db, user, lambda: sources.create_source(db, user, req), "daily")


@router.get("/ai/supply-sources/daily/{record_id}")
def daily_detail(record_id: str, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return {"code": 200, "data": sources.source_current(db, user, "daily", record_id, audit_only=audit_only)}


@router.post("/ai/supply-sources/daily/{record_id}/review")
def daily_review(record_id: str, req: SourceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return write(db, user, lambda: sources.review_source(db, user, "daily", record_id, req), "daily")


@router.post("/ai/supply-sources/daily/{record_id}/revoke")
def daily_revoke(record_id: str, req: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return write(db, user, lambda: sources.review_source(db, user, "daily", record_id, req, revoke=True), "daily")


@router.post("/ai/supply-sources/preview")
def preview(req: collection.CapturePeriodRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return {"code": 200, "data": collection.capture_sources(db, user, req, locking=True)}


@router.get("/ai/admin/supply-sources")
def admin_list(
    record_kind: Literal["unit", "daily"],
    item_kind: ItemKind | None = None,
    item_id: QueryPositiveInteger | None = Query(None, ge=1),
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    sources.current_actor(db, user)
    model, primary = sources.MODELS[record_kind]
    query = db.query(model)
    if item_kind is not None:
        query = query.filter(model.item_kind == item_kind)
    if item_id is not None:
        if item_kind is None:
            raise HTTPException(422, "必须明确库存品种类型")
        query = query.filter(model.item_id == item_id)
    total = query.count()
    rows = query.with_entities(getattr(model, primary)).order_by(model.recorded_at.desc(), getattr(model, primary)).offset((page - 1) * page_size).limit(page_size).all()
    items = [sources.source_metadata(sources.source_current(db, user, record_kind, row[0], audit_only=True)) for row in rows]
    return {"code": 200, "data": {"items": items, "total": total, "page": page, "page_size": page_size, "detail_required": True}}


@router.get("/ai/admin/supply-sources/{record_id}")
def admin_detail(record_id: str, record_kind: Literal["unit", "daily"], db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return {"code": 200, "data": sources.source_current(db, user, record_kind, record_id, audit_only=True)}
