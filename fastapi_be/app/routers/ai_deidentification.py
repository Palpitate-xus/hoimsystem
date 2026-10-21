"""Explicit75 selected-field review/release APIs; no generic research export."""

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai import deidentification_exports as exports
from app.ai import deidentification_reviews as reviews
from app.ai import deidentification_sources as sources
from app.ai.deidentification_contract import (
    SOURCE_ROLES,
    UUID,
    CaptureRequest,
    CaseCreate,
    GovernanceReview,
    GovernanceRevoke,
    PatientScopeRequest,
    ReleaseAuthorityReview,
    ReleaseCreate,
    ResidualReview,
    ReviewCreate,
)
from app.ai.deidentification_directory import case_directory
from app.ai.deidentification_http import BoundedDeidentificationResponse, BoundedDeidentificationRoute, response_bytes
from app.database import get_db
from app.dependencies import User, require_roles

router = APIRouter(
    prefix="/ai/deidentification", tags=["Explicit selected-field deidentification review"], route_class=BoundedDeidentificationRoute, default_response_class=BoundedDeidentificationResponse
)


def reply(db, operation):
    from fastapi import HTTPException

    try:
        data = operation()
        raw = response_bytes(data)
        return Response(content=raw, media_type="application/json", headers={"Cache-Control": "no-store"})
    except Exception as exc:
        db.rollback()
        if isinstance(exc, HTTPException):
            raise
        if isinstance(exc, SQLAlchemyError):
            raise HTTPException(409, "75事务冲突，未接受部分原件或下载") from exc
        raise


@router.post("/fields")
def fields(body: PatientScopeRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: sources.choices(db, user, body))


@router.post("/cases/directory")
def directory(body: PatientScopeRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: case_directory(db, user, body))


@router.post("/cases/preview")
def preview(body: CaptureRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: sources.preview_input(db, user, body))


@router.post("/cases")
def create_case(body: CaseCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: sources.create_case(db, user, body))


@router.get("/cases/{case_id}")
def get_case(case_id: UUID, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: sources.source_current(db, user, case_id, audit_only=audit_only))


@router.post("/cases/{case_id}/review")
def review_case(case_id: UUID, body: GovernanceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(db, lambda: sources.review_case(db, user, case_id, body))


@router.post("/cases/{case_id}/revoke")
def revoke_case(case_id: UUID, body: GovernanceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: sources.review_case(db, user, case_id, body, revoke=True))


@router.post("/reviews")
def create_review(body: ReviewCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: reviews.create_review(db, user, body))


@router.get("/reviews/{review_id}")
def get_review(review_id: UUID, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: reviews.get_review(db, user, review_id, audit_only=audit_only))


@router.post("/reviews/{review_id}/residual-review")
def residual_review(review_id: UUID, body: ResidualReview, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: reviews.review_original(db, user, review_id, body, manual=True))


@router.post("/reviews/{review_id}/review")
def publish_review(review_id: UUID, body: GovernanceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(db, lambda: reviews.review_original(db, user, review_id, body))


@router.post("/reviews/{review_id}/revoke")
def revoke_review(review_id: UUID, body: GovernanceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: reviews.review_original(db, user, review_id, body, revoke=True))


@router.post("/releases")
def create_release(body: ReleaseCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: exports.create_release(db, user, body))


@router.get("/releases/{release_id}")
def get_release(release_id: UUID, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: exports.get_release(db, user, release_id, audit_only=audit_only))


@router.post("/releases/{release_id}/authority-review")
def authority_review(release_id: UUID, body: ReleaseAuthorityReview, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: exports.review_release(db, user, release_id, body, manual=True))


@router.post("/releases/{release_id}/review")
def publish_release(release_id: UUID, body: GovernanceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(db, lambda: exports.review_release(db, user, release_id, body))


@router.post("/releases/{release_id}/revoke")
def revoke_release(release_id: UUID, body: GovernanceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    return reply(db, lambda: exports.review_release(db, user, release_id, body, revoke=True))


@router.post("/releases/{release_id}/download")
def download(release_id: UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(*SOURCE_ROLES))):
    result = exports.download_release(db, user, release_id)
    return Response(
        content=result["body"],
        media_type=result["content_type"],
        headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="' + result["filename"] + '"', "X-Artifact-SHA256": result["sha256"]},
    )
