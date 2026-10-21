"""Independent local-model governance and coupled activation, without a Provider."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_input as source_input
from app.ai import infection_cluster_profile_input as i
from app.ai import infection_cluster_profiles as profiles
from app.ai import infection_cluster_scenario_input as scenario_input
from app.database import get_db
from app.dependencies import User, require_roles
from app.routers.ai_infection_cluster_sources import BoundedSourceRoute, response

router = APIRouter(prefix="/ai/infection-cluster", tags=["本地病例关联统计版本与启用治理"], default_response_class=JSONResponse, route_class=BoundedSourceRoute)


@router.post("/local-profiles")
def create(req: i.ProfileCreate, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, profiles.create_profile, user, req.model_dump(mode="json"), write=True)


@router.get("/local-profiles")
def directory(page: int = 1, size: int = 20, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, profiles.directory, user, page=page, size=size)


@router.get("/local-profiles/{profile_id}")
def detail(profile_id: c.UUID, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, profiles.detail, user, profile_id)


@router.post("/local-profiles/{profile_id}/review")
def review(profile_id: c.UUID, req: scenario_input.ScenarioReview, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, profiles.review_profile, user, profile_id, req.model_dump(mode="json"), write=True)


@router.post("/local-profiles/{profile_id}/revoke")
def revoke(profile_id: c.UUID, req: source_input.CAS, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, profiles.revoke_profile, user, profile_id, req.model_dump(mode="json"), write=True)


@router.get("/local-configuration")
def configuration(management: bool = False, user: User = Depends(require_roles(*source_input.SOURCE_ROLES)), db: Session = Depends(get_db)):
    return response(db, profiles.configuration, user, management=management)


@router.put("/local-configuration")
def configure(req: i.LocalConfigWrite, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, profiles.configure, user, req.model_dump(mode="json"), write=True)
