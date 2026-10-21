"""Explicit finite comparison governance, not automatic signal activation."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_input as source_input
from app.ai import infection_cluster_scenario as scenarios
from app.ai import infection_cluster_scenario_input as i
from app.ai.infection_cluster_implementation import implementation_descriptor
from app.ai.infection_cluster_input import SOURCE_ROLES
from app.database import get_db
from app.dependencies import User, require_roles
from app.routers.ai_infection_cluster_sources import BoundedSourceRoute, response

router = APIRouter(prefix="/ai/infection-cluster", tags=["受审有限病例比较方案"], default_response_class=JSONResponse, route_class=BoundedSourceRoute)


@router.get("/local-implementation")
def local_implementation(user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    def read(db, user):
        scenarios.r._start(db, user, roles=SOURCE_ROLES)
        return implementation_descriptor()

    return response(db, read, user)


@router.get("/departments")
def departments(page: int = 1, size: int = 20, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, scenarios.department_directory, user, page=page, size=size)


@router.post("/scenarios")
def create(req: i.ScenarioCreate, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, scenarios.create_scenario, user, req.model_dump(mode="json"), write=True)


@router.get("/scenarios")
def directory(snapshot_id: c.UUID | None = None, page: int = 1, size: int = 20, user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    return response(db, scenarios.scenario_directory, user, snapshot_id=snapshot_id, page=page, size=size)


@router.get("/scenarios/{scenario_id}")
def detail(scenario_id: c.UUID, user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    return response(db, scenarios.scenario_current, user, scenario_id)


@router.post("/scenarios/{scenario_id}/review")
def review(scenario_id: c.UUID, req: i.ScenarioReview, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, scenarios.review_scenario, user, scenario_id, req.model_dump(mode="json"), write=True)


@router.post("/scenarios/{scenario_id}/revoke")
def revoke(scenario_id: c.UUID, req: source_input.CAS, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, scenarios.revoke_scenario, user, scenario_id, req.model_dump(mode="json"), write=True)
