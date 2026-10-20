"""Scoped physical bed originals and Super review; no live bed or admission writes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai import bed_facts as facts
from app.ai.bed_models import AIBedSource
from app.database import get_db
from app.dependencies import require_roles
from app.models import Department, User
from app.routers.inpatient_support import QueryPositiveInteger

router = APIRouter(tags=["AI病区床位受控原来源"], default_response_class=JSONResponse)


def detail(db, actor, row, *, summary=False):
    data = facts.source_current(db, actor, row.source_kind, row.source_record_id, audit_only=actor.user_role == "super_admin")
    if summary:
        data.pop("payload", None)
        data.pop("parent_binding", None)
        # Lists are metadata, not private external-register or reviewer narratives.
        data.pop("review_basis_note", None)
        data.pop("revoke_reason", None)
    return data


def commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "原来源与审计发生数据或版本竞争，本次变更均未保存") from exc


def write(db, user, operation):
    try:
        row = operation()
        actor = facts.current_actor(db, user)
        data = detail(db, actor, row)
        commit(db)
        return {"code": 200, "data": data}
    except Exception:
        db.rollback()
        raise


def listing(db, actor, kind, department_id, ward_id, status, page, page_size):
    permitted = facts.authorized_departments(db, actor)
    query = db.query(AIBedSource)
    if permitted is not None:
        query = query.filter(AIBedSource.department_id.in_(permitted))
    if department_id is not None:
        facts.bed_scope(db, actor, department_id, allow_missing=actor.user_role in {"admin", "super_admin"})
        query = query.filter_by(department_id=department_id)
    if kind is not None:
        query = query.filter_by(source_kind=kind)
    if ward_id is not None:
        query = query.filter_by(ward_id=ward_id)
    if status is not None:
        query = query.filter_by(status=status)
    total = query.count()
    rows = query.order_by(AIBedSource.recorded_at.desc(), AIBedSource.source_record_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [detail(db, actor, row, summary=True) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/ai/bed-sources/options")
def options(
    department_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*facts.SOURCE_ROLES)),
):
    actor = facts.current_actor(db, user)
    if department_id is not None:
        return {"code": 200, "data": facts.options(db, actor, department_id)}
    permitted = facts.authorized_departments(db, actor)
    query = db.query(Department)
    if permitted is not None:
        query = query.filter(Department.department_id.in_(permitted))
    rows = query.order_by(Department.department_id).limit(2001).all()
    if len(rows) > 2000:
        raise HTTPException(422, "完整科室目录超过界面安全容量，不能截断展示")
    return {
        "code": 200,
        "data": {
            "departments": [{"department_id": row.department_id, "name": row.name} for row in rows],
            "source_kinds": list(facts.KINDS),
            "can_record": True,
            "can_review": actor.user_role == "super_admin",
            "provider_required": False,
        },
    }


@router.get("/ai/bed-sources/{kind}")
def sources(
    kind: facts.SourceKind,
    department_id: QueryPositiveInteger = Query(ge=1, le=2147483647),
    ward_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    status: facts.SourceStatus | None = None,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*facts.SOURCE_ROLES)),
):
    actor = facts.bed_scope(db, user, department_id, allow_missing=user.user_role in {"admin", "super_admin"})
    return {"code": 200, "data": listing(db, actor, kind, department_id, ward_id, status, page, page_size)}


@router.post("/ai/bed-sources/{kind}")
def create(kind: facts.SourceKind, req: facts.SourceCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return write(db, user, lambda: facts.create_source(db, user, kind, req))


@router.get("/ai/bed-sources/{kind}/{source_record_id}")
def source(kind: facts.SourceKind, source_record_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    actor = facts.current_actor(db, user)
    return {"code": 200, "data": detail(db, actor, facts.source_row(db, source_record_id, kind))}


@router.post("/ai/bed-sources/{kind}/{source_record_id}/review")
def review(kind: facts.SourceKind, source_record_id: str, req: facts.SourceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return write(db, user, lambda: facts.review_source(db, user, kind, source_record_id, req))


@router.post("/ai/bed-sources/{kind}/{source_record_id}/revoke")
def revoke(kind: facts.SourceKind, source_record_id: str, req: facts.SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return write(db, user, lambda: facts.revoke_source(db, user, kind, source_record_id, req))


@router.get("/ai/admin/bed-sources")
def admin_sources(
    kind: facts.SourceKind | None = None,
    department_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    ward_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    status: facts.SourceStatus | None = None,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    actor = facts.current_actor(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "当前身份已不再是超级管理员")
    return {"code": 200, "data": listing(db, actor, kind, department_id, ward_id, status, page, page_size)}


@router.get("/ai/admin/bed-sources/{source_record_id}")
def admin_source(source_record_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    actor = facts.current_actor(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "当前身份已不再是超级管理员")
    return {"code": 200, "data": detail(db, actor, facts.source_row(db, source_record_id))}
