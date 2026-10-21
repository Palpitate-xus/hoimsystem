"""Dedicated finite research tasks; independent Source/Scope/Result reads.

These endpoints do not enroll patients, execute SQL, export clinical data or
grant project/patient rights. Technical Super access never restores those rights.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import research_cohort_runtime as runtime
from app.ai.research_cohort_contract import UUID
from app.ai.research_cohort_execution import cancel_research_run
from app.database import get_db
from app.dependencies import User, get_current_user
from app.routers.inpatient_support import QueryPositiveInteger

router = APIRouter(prefix="/ai/research-cohort/tasks", tags=["Research cohort dedicated tasks"])


def reply(value, *, limit=8 * 1024 * 1024):
    # Preserve original raw TEXT strings and UTC6 lexemes. Each whole part has
    # its own limit; no duplicate combined Source/Scope/Result wrapper is emitted.
    response = JSONResponse({"code": 200, "msg": "success", "data": value})
    if len(response.body) > limit + 128:
        raise HTTPException(413, "完整科研任务独立回执超过明确容量，未截断")
    return response


@router.post("")
def create_task(body: runtime.ResearchRunInput, preview: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    identifier = runtime.create_research_run(db, user, body.model_dump(), preview=preview)
    return reply(runtime.describe_research_run(db, user, identifier))


@router.get("")
def list_tasks(
    case_id: UUID | None = None,
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = None,
    page: Annotated[QueryPositiveInteger, Query(ge=1, le=100000)] = 1,
    size: Annotated[QueryPositiveInteger, Query(ge=1, le=100)] = 20,
    audit_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return reply(runtime.list_research_runs(db, user, case_id=case_id, status=status, page=page, size=size, audit_only=audit_only))


@router.get("/{run_id}")
def get_task(run_id: UUID, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(runtime.describe_research_run(db, user, run_id, audit_only=audit_only))


@router.post("/{run_id}/cancel")
def cancel_task(run_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cancel_research_run(db, user, run_id)
    return reply(runtime.describe_research_run(db, user, run_id))


@router.get("/{run_id}/parts/{part}")
def get_part(
    run_id: UUID,
    part: Literal["source", "scope", "result", "task"],
    audit_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return reply(runtime.read_research_part(db, user, run_id, part, audit_only=audit_only))
