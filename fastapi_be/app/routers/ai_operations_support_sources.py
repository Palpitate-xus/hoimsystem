"""Operations source management with independent full canonical JSON parts."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.ai import operations_support_cases as cases
from app.ai import operations_support_directories as directories
from app.ai import operations_support_registry as originals
from app.ai import operations_support_releases as releases
from app.ai.operations_support_contract import MAX_WHOLE_BYTES
from app.ai.operations_support_projection import _value
from app.ai.operations_support_registry_contract import CaseCreate, OriginalCreate, ReleaseCreate, ReleaseReview, SourceRevoke
from app.database import get_db
from app.dependencies import ADMIN_ROLES, User, require_roles
from app.routers.inpatient_support import QueryPositiveInteger


class BoundedOperationsRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request):
            if request.method in {"POST", "PUT", "PATCH"}:
                chunks, length = [], 0
                async for chunk in request.stream():
                    length += len(chunk)
                    if length > MAX_WHOLE_BYTES:
                        raise HTTPException(413, "完整运维请求超过8MiB，未截断解析")
                    chunks.append(chunk)
                body = b"".join(chunks)
                if body:
                    try:
                        _value(body)
                    except (ValueError, TypeError, UnicodeError) as exc:
                        raise HTTPException(422, "运维请求须为完整UTF8 JSON，不允许重复键、分数或非有限数") from exc
                request._body = body
            return await handler(request)

        return bounded


router = APIRouter(prefix="/ai/operations-support", tags=["Operations reviewed source management"], route_class=BoundedOperationsRoute)


def reply(value):
    return Response(content=originals.bounded_json({"code": 200, "msg": "success", "data": value}), media_type="application/json")


def commit_reply(db, operation):
    """Validate the actual response before committing source and receipt together."""
    try:
        response = reply(operation())
        db.commit()
        return response
    except BaseException:
        db.rollback()
        raise


def part(value):
    # No data/metadata wrapper consumes an otherwise legal full8MiB source.
    return Response(content=originals.bounded_json(value), media_type="application/json", headers={"X-AI-Parts-Wire": "canonical_json_body_no_envelope"})


Page = Annotated[QueryPositiveInteger, Query()]
Size = Annotated[QueryPositiveInteger, Query(le=50)]


@router.get("/originals")
def list_originals(page: Page = 1, size: Size = 20, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(directories.list_sources(db, user, "originals", page=page, size=size))


@router.post("/originals")
def register_original(body: OriginalCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return commit_reply(db, lambda: originals.register_original(db, user, body))


@router.get("/originals/{original_id}")
def original_metadata(original_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(originals.get_original(db, user, original_id))


@router.get("/originals/{original_id}/body")
def original_body(original_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return part(originals.get_original(db, user, original_id, include_body=True))


@router.post("/originals/{original_id}/revoke")
def revoke_original(original_id: str, body: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return commit_reply(db, lambda: originals.revoke_original(db, user, original_id, body))


@router.get("/releases")
def list_releases(page: Page = 1, size: Size = 20, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))):
    return reply(directories.list_sources(db, user, "releases", page=page, size=size))


@router.post("/releases")
def create_release(body: ReleaseCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return commit_reply(db, lambda: releases.create_release(db, user, body))


@router.get("/releases/{release_id}")
def release_metadata(release_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(releases.get_release(db, user, release_id))


@router.get("/releases/{release_id}/draft")
def release_draft(release_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return part(releases.get_release(db, user, release_id, include_body=True))


@router.get("/releases/{release_id}/source")
def preview_release(release_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))):
    return part(directories.preview_release(db, user, release_id))


@router.post("/releases/{release_id}/review")
def review_release(release_id: str, body: ReleaseReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return commit_reply(db, lambda: releases.review_release(db, user, release_id, body))


@router.post("/releases/{release_id}/revoke")
def revoke_release(release_id: str, body: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return commit_reply(db, lambda: releases.revoke_release(db, user, release_id, body))


@router.get("/cases")
def list_cases(page: Page = 1, size: Size = 20, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))):
    return reply(directories.list_sources(db, user, "cases", page=page, size=size))


@router.post("/cases")
def create_case(body: CaseCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))):
    return commit_reply(db, lambda: cases.create_case(db, user, body))


@router.get("/cases/{case_id}")
def case_metadata(case_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))):
    return reply(cases.describe_case(db, user, case_id))


@router.get("/cases/{case_id}/parts/{part_name}")
def read_case_part(case_id: str, part_name: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))):
    return part(cases.get_case_part(db, user, case_id, part_name))


@router.post("/cases/{case_id}/revoke")
def revoke_case(case_id: str, body: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return commit_reply(db, lambda: cases.revoke_case(db, user, case_id, body))
