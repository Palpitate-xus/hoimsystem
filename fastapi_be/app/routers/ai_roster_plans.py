"""Business roster declarations and hospital-wide Super review, without live writes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import roster_facts as facts
from app.ai import roster_plans as plans
from app.ai.roster_plan_input import PlanRequest, preview_input
from app.ai.roster_plan_models import AIRosterPlan
from app.database import get_db
from app.dependencies import require_roles
from app.models import User
from app.routers.ai_roster_sources import commit
from app.routers.inpatient_support import QueryPositiveInteger

router = APIRouter(tags=["AI受审排班计划"], default_response_class=JSONResponse)


def detail(db, user, plan_id, *, summary=False):
    actor = facts.current_actor(db, user)
    data = plans.plan_current(db, actor, plan_id, audit_only=actor.user_role == "super_admin")
    if summary:
        for key in ("snapshot", "public_source", "review_basis_note", "revoke_reason"):
            data.pop(key, None)
    return data


def write(db, user, operation):
    try:
        row = operation()
        data = detail(db, user, row.plan_id)
        commit(db)
        return {"code": 200, "data": data}
    except Exception:
        db.rollback()
        raise


def listing(db, user, department_id, status, page, page_size):
    actor = facts.current_actor(db, user)
    permitted = facts.authorized_departments(db, actor)
    query = db.query(AIRosterPlan)
    if permitted is not None:
        query = query.filter(AIRosterPlan.department_id.in_(permitted))
    if department_id is not None:
        facts.roster_scope(db, actor, department_id, allow_missing=actor.user_role in {"admin", "super_admin"})
        query = query.filter_by(department_id=department_id)
    if status is not None:
        query = query.filter_by(status=status)
    total = query.count()
    rows = query.order_by(AIRosterPlan.created_at.desc(), AIRosterPlan.plan_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [detail(db, actor, row.plan_id, summary=True) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/ai/roster-plans/preview")
def preview(req: PlanRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return {"code": 200, "data": preview_input(db, user, req)}


@router.get("/ai/roster-plans")
def plan_list(
    department_id: QueryPositiveInteger = Query(ge=1, le=2147483647),
    status: facts.SourceStatus | None = None,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*facts.SOURCE_ROLES)),
):
    return {"code": 200, "data": listing(db, user, department_id, status, page, page_size)}


@router.post("/ai/roster-plans")
def create(req: plans.PlanCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return write(db, user, lambda: plans.create_plan(db, user, req))


@router.get("/ai/roster-plans/{plan_id}")
def plan(plan_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return {"code": 200, "data": detail(db, user, plan_id)}


@router.post("/ai/roster-plans/{plan_id}/review")
def review(plan_id: str, req: plans.PlanReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return write(db, user, lambda: plans.review_plan(db, user, plan_id, req))


@router.post("/ai/roster-plans/{plan_id}/revoke")
def revoke(plan_id: str, req: plans.PlanRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*facts.SOURCE_ROLES))):
    return write(db, user, lambda: plans.revoke_plan(db, user, plan_id, req))


@router.get("/ai/admin/roster-plans")
def admin_plans(
    department_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    status: facts.SourceStatus | None = None,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    actor = facts.current_actor(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "当前身份已不再是超级管理员")
    return {"code": 200, "data": listing(db, actor, department_id, status, page, page_size)}


@router.get("/ai/admin/roster-plans/{plan_id}")
def admin_plan(plan_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    actor = facts.current_actor(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "当前身份已不再是超级管理员")
    return {"code": 200, "data": detail(db, actor, plan_id)}
