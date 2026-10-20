"""Explicit surgery scenario lifecycle; publication never books resources."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, defer

from app.ai import surgery_facts as facts
from app.ai import surgery_scenarios as scenarios
from app.ai.surgery_scenario_input import ScenarioCreate
from app.ai.surgery_scenario_models import AISurgeryScenario
from app.database import get_db
from app.dependencies import require_roles
from app.models import User
from app.routers.inpatient_support import QueryPositiveInteger

OPERATIONAL_ROLES = ("admin", "director", "super_admin")
router = APIRouter(tags=["AI完整手术排程场景"], default_response_class=JSONResponse)


def _write(db, user, operation):
    try:
        row = operation()
        data = scenarios.scenario_current(db, user, row.scenario_id, audit_only=user.user_role == "super_admin")
        db.commit()
        return {"code": 200, "data": data}
    except (IntegrityError, OperationalError) as exc:
        db.rollback()
        raise HTTPException(409, "场景身份、审核版本或数据库锁发生冲突，本次操作均未保存") from exc
    except Exception:
        db.rollback()
        raise


@router.get("/ai/surgery-scenarios")
def scenario_list(
    pool_id: str | None = None,
    status: facts.SourceStatus | None = None,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*OPERATIONAL_ROLES)),
):
    actor = facts.current_actor(db, user)
    if pool_id is not None:
        facts.pool_scope(db, actor, pool_id, require_published=False)
    elif actor.user_role != "super_admin":
        raise HTTPException(422, "请选择一个当前授权的实际资源池")
    query = db.query(AISurgeryScenario).options(defer(AISurgeryScenario.snapshot_json), defer(AISurgeryScenario.projection_json))
    if pool_id is not None:
        query = query.filter_by(pool_id=pool_id)
    if status is not None:
        query = query.filter_by(status=status)
    total = query.count()
    # This is a technical SQL directory. A selected detail must independently
    # prove full integrity, actual case care, current collection and eligibility.
    rows = query.order_by(AISurgeryScenario.created_at.desc(), AISurgeryScenario.scenario_id).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "code": 200,
        "data": {
            "items": [
                {
                    **{key: value for key, value in scenarios.metadata(row).items() if key not in {"review_basis_note", "revoke_reason"}},
                    "detail_required": True,
                    "candidate_only": True,
                    "automatic_booking": False,
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@router.post("/ai/surgery-scenarios")
def scenario_create(req: ScenarioCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*OPERATIONAL_ROLES))):
    return _write(db, user, lambda: scenarios.create_scenario(db, user, req))


@router.get("/ai/surgery-scenarios/{scenario_id}")
def scenario_detail(scenario_id: str, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles(*OPERATIONAL_ROLES))):
    return {"code": 200, "data": scenarios.scenario_current(db, user, scenario_id, audit_only=audit_only)}


@router.post("/ai/surgery-scenarios/{scenario_id}/review")
def scenario_review(scenario_id: str, req: facts.SourceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _write(db, user, lambda: scenarios.review_scenario(db, user, scenario_id, req))


@router.post("/ai/surgery-scenarios/{scenario_id}/revoke")
def scenario_revoke(scenario_id: str, req: facts.SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*OPERATIONAL_ROLES))):
    return _write(db, user, lambda: scenarios.revoke_scenario(db, user, scenario_id, req))
