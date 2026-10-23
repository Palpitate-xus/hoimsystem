"""Native local statistics: finite explicit Scenario, durable Task, split reads."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_input as source_input
from app.ai import infection_cluster_task_context as context
from app.ai import infection_cluster_task_contract as i
from app.ai import infection_cluster_task_runtime as runtime
from app.ai import infection_cluster_task_views as views
from app.database import get_db
from app.dependencies import User, get_current_user, require_roles
from app.routers.ai_infection_cluster_sources import BoundedSourceRoute, response

router = APIRouter(prefix="/ai/infection-cluster", tags=["明确病例集内本地关联统计任务"], default_response_class=JSONResponse, route_class=BoundedSourceRoute)


@router.post("/context")
def preview(req: i.TaskCreate, user: User = Depends(require_roles(*source_input.SOURCE_ROLES)), db: Session = Depends(get_db)):
    def inspect(db, user):
        actor, scenario, source, profile, config, selection = context.prepare(db, user, req.infection_cluster_scenario_id, preview=req.preview)
        return dict(
            schema_version="infection_local_context_v1",
            source=source.model_dump(mode="json"),
            scenario_content_hash=scenario.content_hash,
            scenario_governance_hash=scenario.governance_hash,
            profile_id=profile.profile_id,
            profile_content_hash=profile.content_hash,
            profile_governance_hash=profile.governance_hash,
            configuration_hash=selection.config_hash,
            source_hash=c.digest(source),
            engine="prediction",
            external_model_transfer=False,
            automatic_actions=False,
        )

    return response(db, inspect, user)


@router.post("/tasks")
def create(req: i.TaskCreate, user: User = Depends(require_roles(*source_input.SOURCE_ROLES)), db: Session = Depends(get_db)):
    return response(db, runtime.create_run, user, req.model_dump(mode="json"), write=True)


@router.get("/tasks")
def directory(scenario_id: c.UUID | None = None, page: int = 1, size: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return response(db, views.directory, user, scenario_id=scenario_id, page=page, size=size)


@router.get("/tasks/{run_id}")
def metadata(run_id: c.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return response(db, views.metadata, user, run_id)


@router.get("/tasks/{run_id}/parts/{part}")
def part(run_id: c.UUID, part: str, user: User = Depends(require_roles(*source_input.SOURCE_ROLES)), db: Session = Depends(get_db)):
    return response(db, views.part, user, run_id, part)


@router.post("/tasks/{run_id}/cancel")
def cancel(run_id: c.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return response(db, runtime.cancel, user, run_id, write=True)
