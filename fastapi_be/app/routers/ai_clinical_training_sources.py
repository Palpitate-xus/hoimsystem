"""Reviewed synthetic teaching and actual local practice, with bounded bare parts."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_directories as directories
from app.ai import clinical_training_learner as learner
from app.ai import clinical_training_practice as practice
from app.ai import clinical_training_reference_contract as refs
from app.ai import clinical_training_registry as registry
from app.ai import clinical_training_reviews as reviews
from app.ai.clinical_training_registry_contract import TrainingLessonCreate, TrainingLessonReview, TrainingSourceRevoke
from app.ai.clinical_training_write_guard import TRAINING_STAFF_ROLES
from app.database import get_db
from app.dependencies import User, require_roles
from app.routers.inpatient_support import QueryPositiveInteger


class BoundedTrainingRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request):
            if request.method in {"POST", "PUT", "PATCH"}:
                chunks, length = [], 0
                async for chunk in request.stream():
                    length += len(chunk)
                    if length > c.WHOLE_BYTES:
                        raise HTTPException(413, "完整培训请求超过8MiB，未截断处理")
                    chunks.append(chunk)
                body = b"".join(chunks)
                if body:
                    try:
                        c.parse_packet(body)
                    except (ValueError, TypeError, UnicodeError) as exc:
                        raise HTTPException(422, "须提供完整UTF8 JSON，不允许重复键、分数或非有限数") from exc
                request._body = body
            return await handler(request)

        return bounded


router = APIRouter(prefix="/ai/clinical-training", tags=["Reviewed synthetic clinical training"], route_class=BoundedTrainingRoute)
Page = Annotated[QueryPositiveInteger, Query(le=100000)]
Size = Annotated[QueryPositiveInteger, Query(le=50)]


def reply(value):
    return Response(content=c.whole(dict(code=200, msg="success", data=value)), media_type="application/json")


def part(value):
    return Response(content=c.whole(value), media_type="application/json", headers={"X-AI-Parts-Wire": "canonical_json_body_no_envelope"})


def commit_reply(db, operation):
    try:
        response = reply(operation())
        db.commit()
        return response
    except BaseException:
        db.rollback()
        raise


def query_fields(request, allowed):
    keys = [key for key, _ in request.query_params.multi_items()]
    if len(keys) != len(set(keys)) or set(keys) - set(allowed):
        raise HTTPException(422, "培训请求只接受明确单值参数，不接受患者、其他来源或未知范围")


@router.get("/lessons")
def list_lessons(request: Request, page: Page = 1, size: Size = 20, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    query_fields(request, {"page", "size"})
    return reply(directories.list_records(db, user, "lessons", page=page, size=size))


@router.post("/lessons")
def create_lesson(body: TrainingLessonCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return commit_reply(db, lambda: registry.register_lesson(db, user, body))


@router.get("/lessons/{lesson_id}")
def lesson_metadata(lesson_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(registry.get_lesson(db, user, lesson_id))


@router.get("/lessons/{lesson_id}/parts/{part_name}")
def lesson_part(lesson_id: str, part_name: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    if part_name not in {"private", "public", "references"}:
        raise HTTPException(404, "明确课程分件不存在")
    return part(registry.get_lesson(db, user, lesson_id, include_body=True)[part_name])


@router.post("/lessons/{lesson_id}/reviews")
def review_lesson(lesson_id: str, body: TrainingLessonReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return commit_reply(db, lambda: reviews.review_lesson(db, user, lesson_id, body))


@router.post("/lessons/{lesson_id}/revoke")
def revoke_lesson(lesson_id: str, body: TrainingSourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return commit_reply(db, lambda: registry.revoke_lesson(db, user, lesson_id, body))


@router.get("/reviews")
def list_reviews(request: Request, page: Page = 1, size: Size = 20, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    query_fields(request, {"page", "size"})
    return reply(directories.list_records(db, user, "reviews", page=page, size=size))


@router.get("/reviews/{review_id}")
def review_metadata(review_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(reviews.get_review(db, user, review_id))


@router.get("/reviews/{review_id}/body")
def review_body(review_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return part(reviews.get_review(db, user, review_id, include_body=True))


@router.post("/reviews/{review_id}/revoke")
def revoke_review(review_id: str, body: TrainingSourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return commit_reply(db, lambda: reviews.revoke_review(db, user, review_id, body))


@router.get("/published-lessons")
def published_lessons(request: Request, page: Page = 1, size: Size = 20, db: Session = Depends(get_db), user: User = Depends(require_roles(*TRAINING_STAFF_ROLES))):
    query_fields(request, {"page", "size"})
    return reply(directories.list_records(db, user, "published", page=page, size=size))


@router.get("/published-lessons/{review_id}")
def public_lesson(review_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*TRAINING_STAFF_ROLES))):
    # Public core is a complete bounded packet; metadata is read separately.
    value = learner.get_public_lesson(db, user, review_id)
    response = part(value["lesson"])
    response.headers["X-AI-Public-Source-SHA256"] = value["public_source_sha256"]
    response.headers["X-AI-Training-Review-ID"] = value["review_id"]
    return response


@router.post("/submissions")
def submit_practice(body: practice.PracticeCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*TRAINING_STAFF_ROLES))):
    return commit_reply(db, lambda: practice.submit_practice(db, user, body))


@router.get("/submissions")
def own_submissions(request: Request, page: Page = 1, size: Size = 20, db: Session = Depends(get_db), user: User = Depends(require_roles(*TRAINING_STAFF_ROLES))):
    query_fields(request, {"page", "size"})
    return reply(directories.list_records(db, user, "own_submissions", page=page, size=size))


@router.get("/submission-management")
def managed_submissions(request: Request, page: Page = 1, size: Size = 20, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    query_fields(request, {"page", "size"})
    return reply(directories.list_records(db, user, "submissions", page=page, size=size))


@router.get("/submissions/{submission_id}")
def submission_metadata(submission_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*TRAINING_STAFF_ROLES))):
    return reply(practice.get_practice(db, user, submission_id))


@router.get("/submissions/{submission_id}/parts/{part_name}")
def submission_part(submission_id: str, part_name: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*TRAINING_STAFF_ROLES))):
    if part_name not in {"submission", "feedback", "references"}:
        raise HTTPException(404, "明确练习分件不存在")
    actor = learner.current_learner(db, user)
    header = practice.submission_header(db, actor, submission_id)
    submitted, feedback, private, public, frozen = practice._read_current(db, actor, header)
    return part({"submission": submitted, "feedback": feedback, "references": refs.model_projection(frozen)}[part_name])
