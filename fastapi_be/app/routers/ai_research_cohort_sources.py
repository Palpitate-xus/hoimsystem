"""Bounded project registry only; no cohort execution or export endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import research_cohort_cases as cases
from app.ai import research_cohort_directories as directories
from app.ai import research_cohort_registry as registry
from app.ai import research_cohort_sources as sources
from app.ai.research_cohort_contract import UUID, AuthorizationReview, CaptureRequest, CaseCreate, PatientAuthorizationCreate, ProjectACLCreate, ScopeCreate, SourceReview, SourceRevoke
from app.database import get_db
from app.dependencies import User, get_current_user
from app.routers.inpatient_support import QueryPositiveInteger

router = APIRouter(prefix="/ai/research-cohort", tags=["Research cohort source registry"])


def reply(value):
    # Exact Source UTC6 strings and literal original text never pass through a
    # response model which could rewrite their original serialized bytes.
    response = JSONResponse({"code": 200, "msg": "success", "data": value})
    if len(response.body) > 32 * 1024 * 1024:
        raise HTTPException(413, "组合科研来源回执超过32MiB；单件原件和公开投影仍各限8MiB")
    return response


@router.post("/scopes")
def create_scope(body: ScopeCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(sources.create_scope(db, user, body))


@router.get("/scopes/{scope_id}")
def get_scope(scope_id: UUID, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(sources.scope_current(db, user, scope_id, audit_only=audit_only))


@router.post("/scopes/{scope_id}/authorization-review")
def review_authorization(scope_id: UUID, body: AuthorizationReview, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(sources.review_scope_authorization(db, user, scope_id, body))


@router.post("/scopes/{scope_id}/review")
def review_scope(scope_id: UUID, body: SourceReview, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(sources.review_scope(db, user, scope_id, body))


@router.post("/scopes/{scope_id}/revoke")
def revoke_scope(scope_id: UUID, body: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(sources.review_scope(db, user, scope_id, body, revoke=True))


@router.post("/project-acls")
def create_acl(body: ProjectACLCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(registry.create_registry_original(db, user, "acl", body))


@router.get("/project-acls/{record_id}")
def get_acl(record_id: UUID, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(registry.registry_current(db, user, "acl", record_id, audit_only=audit_only))


@router.post("/project-acls/{record_id}/review")
def review_acl(record_id: UUID, body: SourceReview, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(registry.review_registry_original(db, user, "acl", record_id, body))


@router.post("/project-acls/{record_id}/revoke")
def revoke_acl(record_id: UUID, body: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(registry.review_registry_original(db, user, "acl", record_id, body, revoke=True))


@router.post("/patient-authorizations")
def create_patient_authorization(body: PatientAuthorizationCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(registry.create_registry_original(db, user, "authorization", body))


@router.get("/patient-authorizations/{record_id}")
def get_patient_authorization(record_id: UUID, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(registry.registry_current(db, user, "authorization", record_id, audit_only=audit_only))


@router.post("/patient-authorizations/{record_id}/authorization-review")
def sign_patient_authorization(record_id: UUID, body: AuthorizationReview, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(registry.review_registry_original(db, user, "authorization", record_id, body, manual=True))


@router.post("/patient-authorizations/{record_id}/review")
def review_patient_authorization(record_id: UUID, body: SourceReview, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(registry.review_registry_original(db, user, "authorization", record_id, body))


@router.post("/patient-authorizations/{record_id}/revoke")
def revoke_patient_authorization(record_id: UUID, body: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(registry.review_registry_original(db, user, "authorization", record_id, body, revoke=True))


@router.post("/cases/preview")
def preview_case(body: CaptureRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(cases.preview_input(db, user, body))


@router.post("/cases")
def create_case(body: CaseCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(cases.create_case(db, user, body))


@router.get("/cases")
def list_cases(
    scope_id: UUID,
    page: Annotated[QueryPositiveInteger, Query(ge=1, le=100000)] = 1,
    size: Annotated[QueryPositiveInteger, Query(ge=1, le=100)] = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return reply(cases.list_cases(db, user, scope_id, page=page, size=size))


@router.get("/cases/{case_id}")
def get_case(case_id: UUID, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(cases.case_current(db, user, case_id, audit_only=audit_only))


@router.post("/cases/{case_id}/review")
def review_case(case_id: UUID, body: SourceReview, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(cases.review_case(db, user, case_id, body))


@router.post("/cases/{case_id}/revoke")
def revoke_case(case_id: UUID, body: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reply(cases.review_case(db, user, case_id, body, revoke=True))


@router.get("/scopes")
def list_scopes(
    page: Annotated[QueryPositiveInteger, Query(ge=1, le=100000)] = 1,
    size: Annotated[QueryPositiveInteger, Query(ge=1, le=100)] = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return reply(directories.list_registry(db, user, "scope", page=page, size=size))


@router.get("/project-acls")
def list_project_acls(
    scope_id: UUID,
    page: Annotated[QueryPositiveInteger, Query(ge=1, le=100000)] = 1,
    size: Annotated[QueryPositiveInteger, Query(ge=1, le=100)] = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return reply(directories.list_registry(db, user, "acl", scope_id=scope_id, page=page, size=size))


@router.get("/patient-authorizations")
def list_patient_authorizations(
    scope_id: UUID,
    page: Annotated[QueryPositiveInteger, Query(ge=1, le=100000)] = 1,
    size: Annotated[QueryPositiveInteger, Query(ge=1, le=100)] = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return reply(directories.list_registry(db, user, "authorization", scope_id=scope_id, page=page, size=size))
