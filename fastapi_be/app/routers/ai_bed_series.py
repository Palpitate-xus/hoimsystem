"""Reviewed physical-bed series and hospital-wide Super audit, without live writes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import bed_facts as facts
from app.ai import bed_series as series
from app.ai.bed_series_input import SeriesPeriodRequest, preview_input
from app.ai.bed_series_models import AIBedSeries
from app.database import get_db
from app.dependencies import require_roles
from app.models import User, Ward
from app.routers.ai_bed_sources import commit
from app.routers.inpatient_support import QueryPositiveInteger

router = APIRouter(tags=["AI受审床位序列"], default_response_class=JSONResponse)


def detail(db, user, series_id, *, summary=False):
    actor = facts.current_actor(db, user)
    data = series.series_current(db, actor, series_id, audit_only=actor.user_role == "super_admin")
    if summary:
        for key in ("snapshot", "public_source", "review_basis_note", "revoke_reason"):
            data.pop(key, None)
    return data


def write(db, user, operation):
    try:
        row = operation()
        data = detail(db, user, row.series_id)
        commit(db)
        return {"code": 200, "data": data}
    except Exception:
        db.rollback()
        raise


def listing(db, user, department_id, ward_id, status, page, page_size):
    actor = facts.current_actor(db, user)
    permitted = facts.authorized_departments(db, actor)
    query = db.query(AIBedSeries)
    if permitted is not None:
        query = query.filter(AIBedSeries.department_id.in_(permitted))
    if department_id is not None:
        facts.bed_scope(db, actor, department_id, allow_missing=actor.user_role in {"admin", "super_admin"})
        query = query.filter_by(department_id=department_id)
    if ward_id is not None:
        if actor.user_role != "super_admin":
            ward = facts.current_query(db.query(Ward).filter_by(ward_id=ward_id)).one_or_none()
            if ward is None or ward.department_id is None:
                raise HTTPException(422, "病区不存在或当前科室归属未知")
            facts.bed_scope(db, actor, ward.department_id)
        query = query.filter_by(ward_id=ward_id)
    if status is not None:
        query = query.filter_by(status=status)
    total = query.count()
    rows = query.order_by(AIBedSeries.created_at.desc(), AIBedSeries.series_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [detail(db, actor, row.series_id, summary=True) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/ai/bed-series/preview")
def preview(req: SeriesPeriodRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return {"code": 200, "data": preview_input(db, user, req)}


@router.get("/ai/bed-series")
def series_list(
    ward_id: QueryPositiveInteger = Query(ge=1, le=2147483647),
    status: facts.SourceStatus | None = None,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*facts.SOURCE_ROLES)),
):
    return {"code": 200, "data": listing(db, user, None, ward_id, status, page, page_size)}


@router.post("/ai/bed-series")
def create(req: series.SeriesCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return write(db, user, lambda: series.create_series(db, user, req))


@router.get("/ai/bed-series/{series_id}")
def series_detail(series_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return {"code": 200, "data": detail(db, user, series_id)}


@router.post("/ai/bed-series/{series_id}/review")
def review(series_id: str, req: series.SeriesReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return write(db, user, lambda: series.review_series(db, user, series_id, req))


@router.post("/ai/bed-series/{series_id}/revoke")
def revoke(series_id: str, req: series.SeriesRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return write(db, user, lambda: series.revoke_series(db, user, series_id, req))


@router.get("/ai/admin/bed-series")
def admin_series(
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
    return {"code": 200, "data": listing(db, actor, department_id, ward_id, status, page, page_size)}


@router.get("/ai/admin/bed-series/{series_id}")
def admin_series_detail(series_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    actor = facts.current_actor(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "当前身份已不再是超级管理员")
    return {"code": 200, "data": detail(db, actor, series_id)}
