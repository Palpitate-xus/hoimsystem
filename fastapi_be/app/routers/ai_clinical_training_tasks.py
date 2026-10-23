"""Explicit submitted-practice tasks and independently authorized whole parts."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_feedback as feedback
from app.ai import clinical_training_learner as learner
from app.ai import clinical_training_runtime as runtime
from app.ai import clinical_training_storage as storage
from app.ai import clinical_training_task_directory as directory
from app.ai import clinical_training_views as views
from app.ai.clinical_training_task_contract import OBJECTIVES, TrainingTaskSelection
from app.ai.clinical_training_task_prompt import PROMPT_VERSION
from app.ai.clinical_training_write_guard import TRAINING_STAFF_ROLES
from app.ai.schemas import FeedbackWrite
from app.database import get_db
from app.dependencies import User, require_roles
from app.routers.ai_clinical_training_sources import BoundedTrainingRoute, Page, Size, commit_reply, part, query_fields, reply


class TrainingTaskCreate(TrainingTaskSelection):
    preview: bool = False


router = APIRouter(prefix="/ai/clinical-training", tags=["Submitted clinical practice feedback"], route_class=BoundedTrainingRoute)


@router.get("/task-descriptor")
def task_descriptor(db: Session = Depends(get_db), user: User = Depends(require_roles(*TRAINING_STAFF_ROLES))):
    learner.current_learner(db, user)
    return reply(dict(feature_key="clinical_training", native_task_version=PROMPT_VERSION, objectives=OBJECTIVES, parts=list(views.PARTS), parts_wire="canonical_json_body_no_envelope", max_part_utf8_bytes=c.WHOLE_BYTES, grade_policy="server_score_unchanged"))


@router.post("/tasks")
def create_task(body: TrainingTaskCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*TRAINING_STAFF_ROLES))):
    def stage():
        identifier = storage.stage_run(db, user, {"clinical_training_submission_id": body.clinical_training_submission_id, "objective": body.objective}, preview=body.preview)
        return views.describe_task(db, user, identifier).model_dump(mode="json")

    return commit_reply(db, stage)


@router.get("/tasks")
def list_tasks(request: Request, submission_id: str | None = None, page: Page = 1, size: Size = 20, db: Session = Depends(get_db), user: User = Depends(require_roles(*TRAINING_STAFF_ROLES))):
    query_fields(request, {"submission_id", "page", "size"})
    return reply(directory.list_tasks(db, user, submission_id=submission_id, page=page, size=size))


@router.get("/tasks/{run_id}")
def task_metadata(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*TRAINING_STAFF_ROLES))):
    return reply(views.describe_task(db, user, run_id).model_dump(mode="json"))


@router.get("/tasks/{run_id}/parts/{part_name}")
def task_part(run_id: str, part_name: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*TRAINING_STAFF_ROLES))):
    return part(views.read_part(db, user, run_id, part_name))


@router.post("/tasks/{run_id}/cancel")
def cancel_task(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(runtime.cancel_training_run(db, user, run_id).model_dump(mode="json"))


@router.post("/tasks/{run_id}/feedback")
def review_task(run_id: str, body: FeedbackWrite, db: Session = Depends(get_db), user: User = Depends(require_roles(*TRAINING_STAFF_ROLES))):
    return commit_reply(db, lambda: feedback.stage_feedback(db, user, run_id, body))


@router.get("/tasks/{run_id}/trace")
def task_trace(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(views.split_trace(db, user, run_id))
