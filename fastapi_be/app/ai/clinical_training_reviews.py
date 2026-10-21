"""Actual independent lesson review; publication and model permission are separate."""

import uuid

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_references as refs
from app.ai import clinical_training_registry as r
from app.ai.clinical_training_models import AITrainingReview
from app.ai.clinical_training_registry_contract import TrainingLessonReview, TrainingReviewedLesson, TrainingSourceRevoke
from app.ai.clinical_training_write_guard import current_rows, lock_training_write

FLAGS = ("synthetic_material_checked", "answer_key_checked", "reference_applicability_checked", "model_processing_allowed")
ORIGIN_COLUMNS = ("review_id", "lesson_id", "lesson_private_hash", "lesson_public_hash", "lesson_references_hash", "review_hash", "reviewed_by", "reviewer_role", "reviewer_epoch", "reviewed_at", "review_decision", *FLAGS)


def review_header(db, review_id, *, require_current=True, require_published=False, execution=False):
    review_id = r.identifier(review_id)
    with db.no_autoflush:
        row = current_rows(db.query(*(getattr(AITrainingReview, key) for key in (*ORIGIN_COLUMNS, *r.STATE_COLUMNS))).filter_by(review_id=review_id), shared=True).one_or_none()
    if row is None:
        raise HTTPException(404, "明确课程独立复核版本不存在")
    h = dict(row._mapping)
    try:
        for key in ("lesson_private_hash", "lesson_public_hash", "lesson_references_hash", "review_hash"):
            TypeAdapter(c.Digest).validate_python(h[key], strict=True)
        if h["reviewer_role"] != "super_admin" or h["review_decision"] not in {"published", "rejected"} or any(type(h[key]) is not int or h[key] not in {0, 1} for key in FLAGS):
            raise ValueError("Explicit review fields differ")
        if h["review_decision"] == "published" and any(h[key] != 1 for key in FLAGS[:3]) or h["review_decision"] == "rejected" and h["model_processing_allowed"] != 0:
            raise ValueError("Publication assertions/model permission differ")
        r.verify_event(db, h["creation_event_id"], h["reviewed_by"], "training_lesson_review", review_id, r.detail(h, ORIGIN_COLUMNS), h["reviewed_at"])
        if h["status"] == h["review_decision"]:
            if h["revision"] != 1 or any(h[key] is not None for key in ("revoked_by", "revoked_at", "revocation_event_id")) or h["revoke_reason"] != "":
                raise ValueError("Unrevoked review carries revocation")
        elif h["status"] == "revoked":
            if h["revision"] != 2 or h["revoked_at"] is None or h["revoked_at"] < h["reviewed_at"] or type(h["revoked_by"]) is not int or not h["revoke_reason"] or h["revocation_event_id"] == h["creation_event_id"]:
                raise ValueError("Review revocation differs")
            r.verify_event(db, h["revocation_event_id"], h["revoked_by"], "training_review_revoke", review_id, r.revoke_detail(h, "review_id", "review_hash"), h["revoked_at"])
        else:
            raise ValueError("Unknown review state")
        lesson = r.lesson_header(db, h["lesson_id"], require_active=require_current, require_author=require_current)
        if any(h["lesson_" + key + "_hash"] != lesson[key + "_hash"] for key in ("private", "public", "references")) or h["reviewed_by"] == lesson["created_by"] or h["reviewed_at"] < lesson["created_at"] or h["creation_event_id"] == lesson["creation_event_id"]:
            raise ValueError("Review is not independent or does not bind the actual lesson")
    except (ValueError, TypeError, KeyError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "培训独立审核技术头、原课程或具体审计绑定损坏") from exc
    if require_current:
        if h["status"] == "revoked":
            raise HTTPException(403, "课程复核版本已经撤回")
        r.verify_actor(db, h["reviewed_by"], h["reviewer_role"], h["reviewer_epoch"])
    if require_published and (not require_current or h["status"] != "published"):
        raise HTTPException(403, "须选择当前有效且明确发布的课程复核版本")
    if execution and (not require_published or h["model_processing_allowed"] != 1):
        raise HTTPException(403, "当前课程复核未单独允许模型处理")
    return h, lesson


def metadata(header):
    """Super governance only; private fingerprints are not learner capabilities."""
    return r.detail(header, (*ORIGIN_COLUMNS, *r.STATE_COLUMNS))


def _read_current(db, header, lesson, actor_id):
    private, public, frozen = r._read_current(db, lesson, actor_id)
    with db.no_autoflush:
        row = current_rows(db.query(AITrainingReview.review_json).filter_by(review_id=header["review_id"]), shared=True).one_or_none()
    try:
        if row is None or len(row.review_json.encode()) > 65535 or r.raw_sha(row.review_json) != header["review_hash"]:
            raise ValueError("The complete review packet differs")
        review = TrainingReviewedLesson.model_validate(c.parse_packet(row.review_json), strict=True)
        proposal = review.proposal
        if c.whole(review) != row.review_json or review.review_id != header["review_id"] or review.lesson_id != header["lesson_id"] or review.reviewed_by != header["reviewed_by"] or review.reviewed_at != refs.utc_text(header["reviewed_at"]):
            raise ValueError("Server review identity differs")
        if proposal.expected_lesson_revision != 1 or any(getattr(proposal, "expected_" + key + "_sha256") != header["lesson_" + key + "_hash"] for key in ("private", "public", "references")):
            raise ValueError("Review proposal does not bind the complete source")
        if ("published" if proposal.decision == "publish" else "rejected") != header["review_decision"] or any(int(getattr(proposal, key)) != header[key] for key in FLAGS):
            raise ValueError("The original explicit decision/flags differ")
        return review, private, public, frozen
    except (ValueError, TypeError, KeyError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "完整培训复核原文、决定或课程绑定已损坏") from exc


def review_lesson(db, user, lesson_id, value):
    try:
        actor = lock_training_write(db, user, governance=True)
        request = r.typed(TrainingLessonReview, value)
        lesson = r.lesson_header(db, lesson_id)
        if actor.user_id == lesson["created_by"]:
            raise HTTPException(403, "课程须由与作者不同的当前超级管理员独立复核")
        if request.expected_lesson_revision != lesson["revision"] or any(getattr(request, "expected_" + key + "_sha256") != lesson[key + "_hash"] for key in ("private", "public", "references")):
            raise HTTPException(409, "待复核课程的具体完整版本已变化")
        r._read_current(db, lesson, actor.user_id)
        clock = r.utcnow()
        if clock < lesson["created_at"]:
            raise HTTPException(409, "复核时刻早于实际登记，未改写时钟")
        packet = TrainingReviewedLesson(schema_version="clinical_training_independent_review_v1", review_id=str(uuid.uuid4()), lesson_id=lesson["lesson_id"], reviewed_by=actor.user_id, reviewed_at=refs.utc_text(clock), proposal=request)
        raw = c.whole(packet)
        if len(raw.encode()) > 65535:
            raise HTTPException(422, "完整培训复核超过实际TEXT容量")
        decision = "published" if request.decision == "publish" else "rejected"
        h = dict(review_id=packet.review_id, lesson_id=lesson["lesson_id"], lesson_private_hash=lesson["private_hash"], lesson_public_hash=lesson["public_hash"], lesson_references_hash=lesson["references_hash"], review_hash=r.raw_sha(raw), reviewed_by=actor.user_id, reviewer_role=actor.user_role, reviewer_epoch=actor.token_invalid_before, reviewed_at=clock, review_decision=decision, **{key: int(getattr(request, key)) for key in FLAGS})
        event_id = r.audit_event(db, actor.user_id, "training_lesson_review", packet.review_id, r.detail(h, ORIGIN_COLUMNS), clock)
        db.add(AITrainingReview(**h, review_json=raw, creation_event_id=event_id, status=decision, revision=1, revoke_reason=""))
        db.flush()
        stored, current_lesson = review_header(db, packet.review_id)
        if _read_current(db, stored, current_lesson, actor.user_id)[0] != packet:
            raise HTTPException(409, "培训复核实际完整写入读回不一致")
        return metadata(stored)
    except Exception:
        db.rollback()
        raise


def get_review(db, user, review_id, *, include_body=False):
    actor = lock_training_write(db, user, governance=True)
    header, lesson = review_header(db, review_id, require_current=include_body)
    if not include_body:
        return metadata(header)
    return _read_current(db, header, lesson, actor.user_id)[0].model_dump(mode="json")


def revoke_review(db, user, review_id, value):
    try:
        actor = lock_training_write(db, user, governance=True)
        request = r.typed(TrainingSourceRevoke, value)
        h, lesson = review_header(db, review_id, require_current=False)
        if h["status"] not in {"published", "rejected"} or h["revision"] != request.revision:
            raise HTTPException(409, "课程复核状态已经变化，请刷新后重试")
        clock = r.utcnow()
        if clock < h["reviewed_at"]:
            raise HTTPException(409, "复核撤回时刻早于实际复核")
        values = dict(status="revoked", revision=2, revoked_by=actor.user_id, revoked_at=clock, revoke_reason=request.reason)
        event_id = r.audit_event(db, actor.user_id, "training_review_revoke", h["review_id"], r.revoke_detail({**h, **values}, "review_id", "review_hash"), clock)
        with db.no_autoflush:
            count = db.query(AITrainingReview).filter_by(review_id=h["review_id"], status=h["status"], revision=request.revision).update({**values, "revocation_event_id": event_id}, synchronize_session=False)
        if count != 1:
            raise HTTPException(409, "课程复核当前版本已经变化")
        db.flush()
        stored, lesson = review_header(db, h["review_id"], require_current=False)
        if any(stored[key] != value for key, value in {**values, "revocation_event_id": event_id}.items()):
            raise HTTPException(409, "课程复核撤回实际读回与具体审计不一致")
        return metadata(stored)
    except Exception:
        db.rollback()
        raise
