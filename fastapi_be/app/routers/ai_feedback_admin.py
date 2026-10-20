"""Super-administrator workflow for source inspection and reviewed feedback excerpts."""

import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import and_, case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.governance import audit
from app.ai.models import AIReviewExcerpt
from app.ai.operational_sources import operational_window
from app.ai.review_curation import create_excerpt, describe_excerpt, load_review_source, review_department, review_excerpt, source_state, verified_review_query
from app.ai.schemas import ReviewExcerptReview, ReviewExcerptWrite
from app.database import get_db
from app.dependencies import require_roles
from app.models import Department, Review, User

router = APIRouter(tags=["AI 反馈脱敏审核"], default_response_class=JSONResponse)


def _commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "版本或关联已变化，请刷新后重试") from exc


@router.get("/ai/admin/review-sources")
def list_sources(
    review_id: int | None = Query(None, ge=1),
    department_id: int | None = Query(None, ge=1),
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> dict:
    """Return source metadata; comment text is available only through audited detail."""
    query = verified_review_query(db, {department_id} if department_id else None)
    applied_window = None
    if review_id is not None:
        query = query.filter(Review.review_id == review_id)
    if review_id is None or date_from is not None or date_to is not None:
        start, end = operational_window({"date_from": str(date_from) if date_from else None, "date_to": str(date_to) if date_to else None})
        applied_window = [str(start), str(end)]
        query = query.filter(
            Review.review_time >= datetime.datetime.combine(start, datetime.time.min), Review.review_time < datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min)
        )
    total = query.count()
    has_text = case((and_(Review.comment.is_not(None), func.length(func.trim(Review.comment)) > 0), True), else_=False)
    rows = (
        query.with_entities(Review.review_id, Review.review_time, Review.score, review_department().label("department_id"), has_text.label("has_comment"))
        .order_by(Review.review_time.desc(), Review.review_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"code": 200, "msg": "success", "data": {"items": [dict(row._mapping) for row in rows], "total": total, "page": page, "page_size": page_size, "window": applied_window}}


@router.get("/ai/admin/review-sources/{review_id}")
def source_detail(review_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    source = load_review_source(db, review_id)
    result = {
        "review_id": review_id,
        "source_hash": source.fingerprint,
        "review_time": source.review.review_time,
        "recorded_score": source.review.score,
        "department_id": source.department_id,
        "department_name": db.get(Department, source.department_id).name,
        "department_source": "original_registration" if source.registration else "current_doctor",
        "raw_comment": source.review.comment,
        "suggested_redacted_text": source.redact(source.review.comment),
        "scope_note": "仅超级管理员可读取原文进行审核。自动建议只移除已知直接标识；第三方身份、间接线索与原意须逐条人工核查，保存草稿不会向模型发送原文",
    }
    audit(db, user.user_id, "review_source.read", str(review_id), {"source_hash": result["source_hash"]})
    _commit(db)
    return {"code": 200, "msg": "success", "data": result}


@router.get("/ai/admin/review-excerpts")
def list_excerpts(
    review_id: int | None = Query(None, ge=1),
    status: Literal["draft", "published", "rejected", "retired"] | None = None,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> dict:
    query = db.query(AIReviewExcerpt)
    if review_id is not None:
        query = query.filter_by(review_id=review_id)
    if status is not None:
        query = query.filter_by(status=status)
    total = query.count()
    rows = query.order_by(AIReviewExcerpt.create_time.desc(), AIReviewExcerpt.excerpt_id).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "code": 200,
        "msg": "success",
        "data": {"items": [{**describe_excerpt(item), "source_state": source_state(db, item)} for item in rows], "total": total, "page": page, "page_size": page_size},
    }


@router.get("/ai/admin/review-excerpts/{excerpt_id}")
def excerpt_detail(excerpt_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    item = db.get(AIReviewExcerpt, excerpt_id)
    if item is None:
        raise HTTPException(404, "脱敏稿版本不存在")
    result = {**describe_excerpt(item, include_text=True), "source_state": source_state(db, item)}
    audit(db, user.user_id, "review_excerpt.read", excerpt_id, {"version": item.version, "status": item.status})
    _commit(db)
    return {"code": 200, "msg": "success", "data": result}


@router.post("/ai/admin/review-excerpts")
def create_draft(req: ReviewExcerptWrite, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    item = create_excerpt(db, user, req)
    _commit(db)
    return {"code": 200, "msg": "success", "data": describe_excerpt(item, include_text=True)}


@router.post("/ai/admin/review-excerpts/{excerpt_id}/review")
def review_draft(excerpt_id: str, req: ReviewExcerptReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    item = review_excerpt(db, user, excerpt_id, req)
    _commit(db)
    return {"code": 200, "msg": "success", "data": describe_excerpt(item, include_text=True)}
