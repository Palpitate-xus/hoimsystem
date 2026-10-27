"""Explicit governed inventory originals; never changes stock or orders."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.ai import inventory_native_collection as collection
from app.ai import inventory_native_sources as sources
from app.ai import supply_sources as units
from app.ai.inventory_native_source_input import SOURCE_ROLES, CapturePeriod, ItemKind, LegacyCaptureRequest, SourceCreate, SourceKind, SourceReview, SourceRevoke
from app.ai.inventory_native_source_models import AIInventoryNativeSource as Model
from app.ai.inventory_write_guard import current_inventory_rows, lock_inventory_write
from app.database import get_db
from app.dependencies import require_roles
from app.models import Consumable, Pharmaceutical, User
from app.routers.inpatient_support import QueryPositiveInteger
from app.sql_counts import locked_row_count

router = APIRouter(tags=["AI库存完整原件与有限采购候选治理"], default_response_class=JSONResponse)


def write(db, user, operation):
    try:
        row = operation()
        actor = sources.current_actor(db, user)
        result = sources.source_current(db, actor, row.source_record_id, audit_only=actor.user_role == "super_admin", locking=True)
        if not sources.verify_source_wrapper(result):
            raise HTTPException(409, "库存原件回执无法核对，本次未保存")
        db.commit()
        return {"code": 200, "data": result}
    except (IntegrityError, OperationalError) as exc:
        db.rollback()
        raise HTTPException(409, "库存原件、版本、单位或数据库锁冲突，本次均未保存") from exc
    except Exception:
        db.rollback()
        raise


@router.get("/ai/inventory-native-sources/options")
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
        raise HTTPException(422, "明确SKU标识必须同时提供实际SKU类型")
    result = []
    total = 0
    if item_kind is not None:
        model, pk = (Pharmaceutical, Pharmaceutical.pharmaceutical_id) if item_kind == "pharmaceutical" else (Consumable, Consumable.consumable_id)
        query = db.query(model).filter(model.status == 0)
        if item_id is not None:
            query = query.filter(pk == item_id)
        if keyword:
            query = query.filter(or_(model.name.contains(keyword), model.barcode.contains(keyword))) if item_kind == "pharmaceutical" else query.filter(model.name.contains(keyword))
        total = locked_row_count(current_inventory_rows(query, shared=True), pk)
        identifiers = current_inventory_rows(query.with_entities(pk).order_by(pk).offset((page - 1) * page_size).limit(page_size), shared=True).all()
        for (identifier,) in identifiers:
            sku = units.sku_binding(db, item_kind, identifier, locking=True, require_active=True)
            result.append(
                {
                    "item_kind": item_kind,
                    "item_id": identifier,
                    "name": sku["identity"]["name"],
                    "status": sku["identity"]["status"],
                    "scope": "hospital_inventory",
                    "identity_hash": sources.hash_content(sku),
                }
            )
    return {
        "code": 200,
        "data": {
            "items": result,
            "total": total,
            "page": page,
            "page_size": page_size,
            "item_kinds": ["pharmaceutical", "consumable"],
            "source_kinds": ["inventory_observation", "future_quantity_scenario", "purchase_candidate_plan"],
            "scope": "hospital_inventory",
            "can_record": True,
            "can_confirm_professional": actor.user_role == "pharmacist",
            "professional_signer_user_id": actor.user_id if actor.user_role == "pharmacist" else None,
            "can_review": actor.user_role == "super_admin",
            "provider_required": False,
            "unit_sources_path": "/ai/supply-sources/units",
            "scope_note": "单实际SKU、受审原计数单位和完整有限候选；不自动换算、采购或改库存。技术采集不是独立实盘，耗材没有真实批次表时不捏造批次；技术审核不能代替药师本人明确确认。",
        },
    }


@router.post("/ai/inventory-native-sources/legacy-capture")
def legacy_capture(req: LegacyCaptureRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    lock_inventory_write(db, user, allowed_roles=SOURCE_ROLES, skus=[(req.item_kind, req.item_id)], require_active=True)
    return {"code": 200, "data": collection.capture_legacy_inventory(db, req.item_kind, req.item_id)}


@router.post("/ai/inventory-native-sources/preview")
def preview(req: CapturePeriod, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return {"code": 200, "data": collection.capture_sources(db, user, req, locking=True)}


def listing(db, user, kind, item_kind, item_id, page, page_size, *, admin=False):
    actor = sources.current_actor(db, user)
    if admin and actor.user_role != "super_admin":
        raise HTTPException(403, "当前身份已无全院库存原件审计权限")
    if item_id is not None and item_kind is None:
        raise HTTPException(422, "明确SKU标识须同时给出真实SKU类型")
    query = db.query(Model)
    if kind is not None:
        query = query.filter(Model.source_kind == kind)
    if item_kind is not None:
        query = query.filter(Model.item_kind == item_kind)
    if item_id is not None:
        query = query.filter(Model.item_id == item_id)
    primary = Model.source_record_id
    total = locked_row_count(current_inventory_rows(query, shared=True), primary)
    ids = current_inventory_rows(query.with_entities(primary).order_by(Model.recorded_at.desc(), primary).offset((page - 1) * page_size).limit(page_size), shared=True).all()
    # PK page, followed only by immutable/governance scalar columns; neither
    # payload_json nor parent_binding_json is fetched or falsely certified.
    names = (*sources.IDENTITY_FIELDS, *sources.GOVERNANCE_FIELDS, "content_hash")
    columns = [getattr(Model, key) for key in names]
    items = []
    for (identifier,) in ids:
        row = current_inventory_rows(db.query(*columns).filter(primary == identifier), shared=True).one()
        items.append(sources.row_metadata(row))
    return {"code": 200, "data": {"items": items, "total": total, "page": page, "page_size": page_size, "detail_required": True}}


@router.get("/ai/admin/inventory-native-sources")
def admin_list(
    source_kind: SourceKind | None = None,
    item_kind: ItemKind | None = None,
    item_id: QueryPositiveInteger | None = Query(None, ge=1),
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    return listing(db, user, source_kind, item_kind, item_id, page, page_size, admin=True)


@router.get("/ai/admin/inventory-native-sources/{record_id}")
def admin_detail(record_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    actor = sources.current_actor(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "当前身份已无完整冻结库存原件审计权限")
    return {"code": 200, "data": sources.source_current(db, actor, record_id, audit_only=True)}


@router.get("/ai/inventory-native-sources/{kind}")
def source_list(
    kind: SourceKind,
    item_kind: ItemKind,
    item_id: QueryPositiveInteger = Query(..., ge=1),
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SOURCE_ROLES)),
):
    return listing(db, user, kind, item_kind, item_id, page, page_size)


@router.post("/ai/inventory-native-sources/{kind}")
def source_create(kind: SourceKind, req: SourceCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    if req.payload.kind != kind:
        raise HTTPException(422, "URL来源种类必须与完整原件种类一致")
    return write(db, user, lambda: sources.create_source(db, user, req))


def typed_record(db, user, kind, record_id, audit_only=False):
    result = sources.source_current(db, user, record_id, audit_only=audit_only)
    if result["source_kind"] != kind:
        raise HTTPException(404, "该种类下原库存资料不存在")
    return result


@router.get("/ai/inventory-native-sources/{kind}/{record_id}")
def source_detail(kind: SourceKind, record_id: str, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return {"code": 200, "data": typed_record(db, user, kind, record_id, audit_only)}


@router.post("/ai/inventory-native-sources/{kind}/{record_id}/review")
def source_review(kind: SourceKind, record_id: str, req: SourceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    typed_record(db, user, kind, record_id)
    return write(db, user, lambda: sources.review_source(db, user, record_id, req))


@router.post("/ai/inventory-native-sources/{kind}/{record_id}/revoke")
def source_revoke(kind: SourceKind, record_id: str, req: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    typed_record(db, user, kind, record_id)
    return write(db, user, lambda: sources.review_source(db, user, record_id, req, revoke=True))
