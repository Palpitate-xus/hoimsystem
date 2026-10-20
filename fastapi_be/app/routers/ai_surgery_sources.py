"""Isolated surgery registry/source APIs; no reservation or legacy execution writes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.ai import surgery_collection as collection
from app.ai import surgery_facts as facts
from app.ai.surgery_contract import FactKind
from app.ai.surgery_models import AISurgeryPool, AISurgerySource
from app.database import get_db
from app.dependencies import require_roles
from app.models import Doctor, User
from app.routers.inpatient_support import QueryPositiveInteger

router = APIRouter(tags=["AI手术受控来源与全局物理身份"], default_response_class=JSONResponse)


def write(db, user, operation, view):
    try:
        row = operation()
        data = view(row)
        db.commit()
        return {"code": 200, "data": data}
    except (IntegrityError, OperationalError) as exc:
        db.rollback()
        raise HTTPException(409, "受控身份、来源、版本或数据库锁发生冲突，本次操作均未保存") from exc
    except Exception:
        db.rollback()
        raise


def source_view(db, user, row, *, summary=False):
    data = facts.source_current(db, user, row.source_kind, row.source_record_id, audit_only=user.user_role == "super_admin")
    if summary:
        for name in ("payload", "parent_binding", "review_basis_note", "revoke_reason"):
            data.pop(name, None)
    return data


def registry_view(db, user, kind, row, *, pool_id=None, summary=False):
    primary = facts.REGISTRY[kind][1]
    data = facts.registry_current(db, user, kind, getattr(row, primary), pool_id=pool_id, audit_only=user.user_role == "super_admin")
    if summary:
        data.pop("payload", None)
        data.pop("parent_binding", None)
        if data["governance"] is not None:
            data["governance"] = {key: value for key, value in data["governance"].items() if key not in {"review_basis_note", "revoke_reason"}}
    return data


@router.get("/ai/surgery-sources/options")
def options(db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    actor = facts.current_actor(db, user, clinical=True)
    rows = db.query(AISurgeryPool).filter_by(status="published").order_by(AISurgeryPool.pool_id).limit(2001).all()
    if len(rows) > 2000:
        raise HTTPException(422, "完整资源池目录超过安全容量，不能截断")
    pools = []
    for row in rows:
        try:
            facts.registry_proof("pool", row)
            facts._pool_scope(db, actor, row)
        except HTTPException as exc:
            if exc.status_code == 403:
                continue
            raise
        pools.append(
            {
                "pool_id": row.pool_id,
                "department_id": row.department_id,
                "name": facts.registry_proof("pool", row)["payload"]["name"],
                "content_hash": row.content_hash,
                "governance_hash": facts.hash_content(facts.governance_fields(row)),
            }
        )
    can_operate = actor.user_role != "doctor"
    if can_operate:
        try:
            facts.current_actor(db, actor)
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
            can_operate = False
    signers = db.query(Doctor).filter_by(user_id=actor.user_id).order_by(Doctor.doctor_id).limit(2001).all() if actor.user_role in {"doctor", "director", "super_admin"} else []
    if len(signers) > 2000:
        raise HTTPException(422, "当前账号完整医师别名集合超过安全容量，不得截断")
    return {
        "code": 200,
        "data": {
            "pools": pools,
            "source_kinds": list(facts.SOURCE_KINDS),
            "registry_kinds": list(facts.REGISTRY),
            "can_record_operational": can_operate,
            "has_actual_doctor": db.query(Doctor.doctor_id).filter_by(user_id=actor.user_id).first() is not None,
            "can_manage_registry": actor.user_role == "super_admin",
            "can_review": actor.user_role == "super_admin",
            "clinical_signers": [{"doctor_id": row.doctor_id, "name": row.name, "department_id": row.department_id} for row in signers],
            "provider_required": False,
        },
    }


@router.post("/ai/surgery-sources/preview")
def collection_preview(req: collection.CaptureRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    # Deliberately no mutation wrapper, commit or governance audit. Late roots
    # remain visible so preview never masquerades as a cutoff-valid capture.
    return {"code": 200, "data": collection.preview_input(db, user, req)}


@router.get("/ai/surgery-registry/{kind}")
def registry_list(
    kind: facts.RegistryKind,
    pool_id: str | None = None,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*facts.SOURCE_ROLES)),
):
    actor = facts.current_actor(db, user)
    if pool_id is not None:
        facts.pool_scope(db, actor, pool_id)
    elif actor.user_role != "super_admin" and kind != "pool":
        raise HTTPException(422, "普通身份必须选择一个真实授权资源池")
    cls, primary = facts.REGISTRY[kind]
    query = db.query(cls)
    if pool_id is not None and kind == "pool_membership":
        query = query.filter_by(pool_id=pool_id)
    rows = query.order_by(getattr(cls, primary)).limit(20001).all()
    if len(rows) > 20000:
        raise HTTPException(422, "完整受控登记集合超过安全容量，不能截断")
    items = []
    for row in rows:
        try:
            items.append(registry_view(db, actor, kind, row, pool_id=pool_id, summary=True))
        except HTTPException as exc:
            if exc.status_code == 403:
                continue
            raise
    return {"code": 200, "data": {"items": items[(page - 1) * page_size : page * page_size], "total": len(items), "page": page, "page_size": page_size}}


@router.post("/ai/surgery-registry/{kind}")
def registry_create(kind: facts.RegistryKind, req: facts.RegistryCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return write(db, user, lambda: facts.create_registry(db, user, kind, req), lambda row: registry_view(db, user, kind, row))


@router.get("/ai/surgery-registry/{kind}/{record_id}")
def registry_detail(kind: facts.RegistryKind, record_id: str, pool_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return {"code": 200, "data": registry_view(db, user, kind, facts.registry_row(db, kind, record_id), pool_id=pool_id)}


@router.post("/ai/surgery-registry/{kind}/{record_id}/review")
def registry_review(kind: facts.RegistryKind, record_id: str, req: facts.SourceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return write(db, user, lambda: facts.review_registry(db, user, kind, record_id, req), lambda row: registry_view(db, user, kind, row))


@router.post("/ai/surgery-registry/{kind}/{record_id}/revoke")
def registry_revoke(kind: facts.RegistryKind, record_id: str, req: facts.SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return write(db, user, lambda: facts.review_registry(db, user, kind, record_id, req, revoke=True), lambda row: registry_view(db, user, kind, row))


@router.get("/ai/surgery-sources/{kind}")
def source_list(
    kind: FactKind,
    pool_id: str,
    status: facts.SourceStatus | None = None,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*facts.SOURCE_ROLES)),
):
    actor, _ = facts.pool_scope(db, user, pool_id, clinical=kind in facts.CASE_KINDS, require_published=False)
    query = db.query(AISurgerySource).filter_by(pool_id=pool_id, source_kind=kind)
    if status is not None:
        query = query.filter_by(status=status)
    rows = query.order_by(AISurgerySource.recorded_at.desc(), AISurgerySource.source_record_id).limit(20001).all()
    if len(rows) > 20000:
        raise HTTPException(422, "完整授权来源集合超过安全容量，不能截断")
    items = []
    for row in rows:
        try:
            items.append(source_view(db, actor, row, summary=True))
        except HTTPException as exc:
            if exc.status_code == 403:
                continue
            raise
    return {"code": 200, "data": {"items": items[(page - 1) * page_size : page * page_size], "total": len(items), "page": page, "page_size": page_size}}


@router.post("/ai/surgery-protected-capsules")
def protected_capsule(req: facts.ProtectedCapsuleCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return write(db, user, lambda: facts.create_protected_capsule(db, user, req), lambda row: source_view(db, user, row))


@router.post("/ai/surgery-sources/{kind}")
def source_create(kind: FactKind, req: facts.SourceCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return write(db, user, lambda: facts.create_source(db, user, kind, req), lambda row: source_view(db, user, row))


@router.get("/ai/surgery-sources/{kind}/{record_id}")
def source_detail(kind: FactKind, record_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return {"code": 200, "data": source_view(db, user, facts.source_row(db, record_id, kind))}


@router.post("/ai/surgery-sources/{kind}/{record_id}/review")
def source_review(kind: FactKind, record_id: str, req: facts.SourceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return write(db, user, lambda: facts.review_source(db, user, kind, record_id, req), lambda row: source_view(db, user, row))


@router.post("/ai/surgery-sources/{kind}/{record_id}/revoke")
def source_revoke(kind: FactKind, record_id: str, req: facts.SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return write(db, user, lambda: facts.review_source(db, user, kind, record_id, req, revoke=True), lambda row: source_view(db, user, row))
