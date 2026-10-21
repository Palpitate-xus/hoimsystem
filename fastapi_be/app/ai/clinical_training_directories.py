"""Bounded current candidate directories; no stale aggregate or answer bodies."""

from fastapi import HTTPException

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_learner as learner
from app.ai import clinical_training_practice as practice
from app.ai import clinical_training_references as refs
from app.ai import clinical_training_registry as r
from app.ai import clinical_training_reviews as reviews
from app.ai.clinical_training_models import AITrainingLesson, AITrainingReview
from app.ai.clinical_training_practice_models import AITrainingSubmission
from app.ai.clinical_training_write_guard import current_rows, lock_training_write


def list_records(db, user, kind, *, page=1, size=20):
    if type(page) is not int or not 1 <= page <= 100000 or type(size) is not int or not 1 <= size <= 50 or kind not in {"lessons", "reviews", "submissions", "published", "own_submissions"}:
        raise HTTPException(422, "培训目录仅接受明确类型和有界单值分页")
    actor = learner.current_learner(db, user) if kind in {"published", "own_submissions"} else lock_training_write(db, user, governance=True)
    model, key, clock = {"lessons": (AITrainingLesson, "lesson_id", "created_at"), "reviews": (AITrainingReview, "review_id", "reviewed_at"), "published": (AITrainingReview, "review_id", "reviewed_at"), "submissions": (AITrainingSubmission, "submission_id", "submitted_at"), "own_submissions": (AITrainingSubmission, "submission_id", "submitted_at")}[kind]
    query = db.query(getattr(model, key))
    if kind == "published":
        query = query.filter(AITrainingReview.status == "published")
    elif kind == "own_submissions":
        query = query.filter(AITrainingSubmission.actor_id == actor.user_id)
    with db.no_autoflush:
        rows = current_rows(query.order_by(getattr(model, clock).desc(), getattr(model, key).desc()).offset((page - 1) * size).limit(size + 1), shared=True).all()
    items = []
    for row in rows[:size]:
        if kind == "lessons":
            items.append(r.metadata(r.lesson_header(db, row[0], require_active=False, require_author=False)))
        elif kind == "reviews":
            items.append(reviews.metadata(reviews.review_header(db, row[0], require_current=False)[0]))
        elif kind in {"submissions", "own_submissions"}:
            header = practice.submission_header(db, actor, row[0], require_owner=kind == "own_submissions")
            items.append(dict(**practice.metadata(header), requested_by=header["actor_id"]))
        else:
            try:
                header, lesson = reviews.review_header(db, row[0], require_published=True)
                refs._capture_current(db, actor.user_id, lesson["lesson_id"], c.parse_packet(lesson["reference_ids_json"]), expected_state_hash=lesson["reference_state_hash"], metadata_only=True)
            except HTTPException as exc:
                if exc.status_code not in {403, 404, 409}:
                    raise
                continue
            items.append(dict(review_id=header["review_id"], lesson_id=lesson["lesson_id"], title=lesson["title"], version_label=lesson["version_label"], public_source_sha256=lesson["public_hash"], model_processing_allowed=bool(header["model_processing_allowed"])))
    result = dict(items=items, page=page, size=size, has_more=len(rows) > size, next_page=page + 1 if len(rows) > size else None, pagination_basis="current_opaque_candidates_not_inferred_total")
    if len(c.whole(result).encode()) > 1048576:
        raise HTTPException(422, "完整培训目录超过1MiB，请缩小本次分页")
    return result
