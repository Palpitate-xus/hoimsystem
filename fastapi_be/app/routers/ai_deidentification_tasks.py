"""Dedicated75 task API. Root registers it in shared Main in a later phase."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai import deidentification_runtime as runtime
from app.ai import deidentification_storage as storage
from app.ai.deidentification_contract import SOURCE_ROLES, UUID, StrictModel
from app.ai.deidentification_http import BoundedDeidentificationResponse, BoundedDeidentificationRoute
from app.ai.deidentification_task_access import authorize_locator
from app.ai.deidentification_task_contract import TaskInput
from app.database import get_db
from app.dependencies import User, require_roles
from app.routers.ai_deidentification import reply

router = APIRouter(prefix="/ai/deidentification/tasks", tags=["Controlled75 literal candidate tasks"], route_class=BoundedDeidentificationRoute, default_response_class=BoundedDeidentificationResponse)


class TaskCreate(StrictModel):
    input: TaskInput
    preview: bool = False


@router.post("/context")
def preview(body: TaskCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    def operation():
        _, _, _, source, task, evidence, metadata, _ = storage.prepare(db, user, body.input.model_dump(exclude_unset=True), preview=body.preview)
        return {
            "context": task["context"],
            "source": source["public_source"],
            "source_snapshot": source["source_snapshot"],
            "publication": source["publication"],
            "metadata": metadata,
            "evidence": evidence,
            "can_execute": False,
            "can_review": False,
            "can_export": False,
        }

    return reply(db, operation)


@router.post("")
def create(body: TaskCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    def operation():
        run = runtime.create_deidentification_run(db, user, body.input.model_dump(exclude_unset=True), preview=body.preview)
        return {"run_id": run.run_id, "feature_key": runtime.FEATURE_KEY, "status": run.status, "input_tokens": None, "output_tokens": None, "model_call_attempted": None, "detail_required": True}

    return reply(db, operation)


@router.get("/{run_id}")
def detail(run_id: UUID, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: runtime.describe_deidentification_run(db, user, run_id, audit_only=audit_only))


@router.get("/{run_id}/technical")
def technical(run_id: UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: runtime.technical_deidentification_status(db, user, run_id))


@router.get("/{run_id}/source")
def source_part(run_id: UUID, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    def operation():
        loaded = storage.load_snapshot(db, user, run_id, audit_only=audit_only)
        return {"run_id": run_id, "source_artifact": loaded[3], "source_hash": loaded[2].source_hash, "proof_scope": "currently_authorized_complete_frozen_source_not_anonymity"}

    return reply(db, operation)


@router.get("/{run_id}/result")
def result_part(run_id: UUID, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    def operation():
        loaded, result = storage.load_result(db, user, run_id, audit_only=audit_only)
        return {"run_id": run_id, "result": result, "source_binding": loaded[4]["context"], "usage_receipt": runtime.usage_receipt(db, loaded[1]), "can_review": False, "can_export": False}

    return reply(db, operation)


@router.get("/{run_id}/trace")
def trace(run_id: UUID, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    def operation():
        loaded, result = storage.load_result(db, user, run_id, audit_only=True)
        run = loaded[1]
        return {
            "run_id": run_id,
            "source_artifact": loaded[3],
            "result": result,
            "raw_frozen_json": {key: getattr(run, key) for key in storage.TEXT_FIELDS},
            "usage_receipt": runtime.usage_receipt(db, run),
            "audit_only": True,
            "can_execute": False,
            "can_review": False,
            "can_export": False,
        }

    return reply(db, operation)


@router.post("/{run_id}/cancel")
def cancel(run_id: UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    def operation():
        authorize_locator(db, user, run_id)
        runtime.cancel_deidentification_run(db, user, run_id)
        return runtime.technical_deidentification_status(db, user, run_id)

    return reply(db, operation)
