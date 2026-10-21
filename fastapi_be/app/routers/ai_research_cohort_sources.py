"""Bounded project registry only; no cohort execution or export endpoint."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import research_cohort_sources as sources
from app.ai.research_cohort_contract import AuthorizationReview, ScopeCreate, SourceReview, SourceRevoke
from app.database import get_db
from app.dependencies import User, get_current_user

router = APIRouter(prefix="/ai/research-cohort", tags=["Research cohort source registry"])


def reply(value):
    # Exact Source UTC6 strings and literal original text never pass through a
    # response model which could rewrite their original serialized bytes.
    return JSONResponse({"code": 200, "msg": "success", "data": value})


@router.post("/scopes")
def create_scope(body: ScopeCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(sources.create_scope(db, user, body))


@router.get("/scopes/{scope_id}")
def get_scope(scope_id: str, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(sources.scope_current(db, user, scope_id, audit_only=audit_only))


@router.post("/scopes/{scope_id}/authorization-review")
def review_authorization(scope_id: str, body: AuthorizationReview, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(sources.review_scope_authorization(db, user, scope_id, body))


@router.post("/scopes/{scope_id}/review")
def review_scope(scope_id: str, body: SourceReview, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(sources.review_scope(db, user, scope_id, body))


@router.post("/scopes/{scope_id}/revoke")
def revoke_scope(scope_id: str, body: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(sources.review_scope(db, user, scope_id, body, revoke=True))
