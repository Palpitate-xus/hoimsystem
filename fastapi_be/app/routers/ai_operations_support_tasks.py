"""Explicit reviewed operations tasks and independently authorized bare parts."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.ai import operations_support_contract as c
from app.ai import operations_support_runtime as runtime
from app.ai import operations_support_storage as storage
from app.ai import operations_support_task_directory as directory
from app.ai import operations_support_views as views
from app.ai.operations_support_task_contract import OperationsTaskSelection
from app.ai.operations_support_task_prompt import OBJECTIVES, PROMPT_VERSION
from app.ai.operations_support_write_guard import lock_operations_write
from app.database import get_db
from app.dependencies import ADMIN_ROLES, User, require_roles
from app.routers.ai_operations_support_sources import BoundedOperationsRoute, Page, Size, commit_reply, part, reply


class OperationsTaskCreate(OperationsTaskSelection):
    preview: bool = False


router = APIRouter(prefix="/ai/operations-support", tags=["Operations reviewed tasks"], route_class=BoundedOperationsRoute)


@router.get("/task-descriptor")
def task_descriptor(db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))):
    lock_operations_write(db, user)
    return reply({"feature_key": "operations_support", "native_task_version": PROMPT_VERSION, "objectives": OBJECTIVES, "parts": list(views.PARTS), "parts_wire": "canonical_json_body_no_envelope", "max_part_utf8_bytes": c.MAX_WHOLE_BYTES})


@router.post("/tasks")
def create_task(body: OperationsTaskCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))):
    def stage():
        identifier = storage.stage_run(db, user, {"operations_case_id": body.operations_case_id, "objective": body.objective}, preview=body.preview)
        return views.describe_task(db, user, identifier).model_dump(mode="json")

    return commit_reply(db, stage)


@router.get("/tasks")
def list_tasks(request: Request, case_id: str | None = None, page: Page = 1, size: Size = 20, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))):
    keys = [key for key, _ in request.query_params.multi_items()]
    if len(keys) != len(set(keys)) or set(keys) - {"case_id", "page", "size"}:
        raise HTTPException(422, "运维任务目录只接受明确Case与单值分页，不接受患者、其它来源或未知范围")
    return reply(directory.list_tasks(db, user, case_id=case_id, page=page, size=size))


@router.get("/tasks/{run_id}")
def task_metadata(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))):
    return reply(views.describe_task(db, user, run_id).model_dump(mode="json"))


@router.get("/tasks/{run_id}/parts/{part_name}")
def task_part(run_id: str, part_name: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))):
    return part(views.read_part(db, user, run_id, part_name))


@router.post("/tasks/{run_id}/cancel")
def cancel_task(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(runtime.cancel_operations_run(db, user, run_id).model_dump(mode="json"))


@router.get("/tasks/{run_id}/trace")
def task_trace(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(views.split_trace(db, user, run_id))
