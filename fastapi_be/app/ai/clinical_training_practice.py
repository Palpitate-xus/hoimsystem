"""Actual server-scored immutable practice; AI can only later explain the grade."""

import uuid

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_learner as learner
from app.ai import clinical_training_registry as r
from app.ai import clinical_training_reviews as reviews
from app.ai import clinical_training_scoring as scoring
from app.ai.clinical_training_practice_models import AITrainingSubmission
from app.ai.clinical_training_write_guard import TRAINING_STAFF_ROLES, current_rows
from app.models import User

ORIGIN_COLUMNS = ("submission_id", "schema_version", "review_id", "lesson_id", "review_hash", "lesson_private_hash", "lesson_public_hash", "lesson_references_hash", "actor_id", "actor_role", "actor_epoch", "submitted_at", "submission_hash", "submission_bytes", "feedback_hash", "feedback_bytes", "scoring_method", "question_count", "matching_count", "differing_count", "unanswered_count")


class PracticeCreate(c.StrictModel):
    review_id: c.Identifier
    submission: scoring.LessonSubmission


def _validate_public_answers(public, submission):
    if submission.lesson_id != public.lesson_id or submission.public_source_sha256 != c.content_hash(public):
        raise HTTPException(409, "答题必须绑定当前完整公开题面")
    answers = {answer.question_id: answer for answer in submission.answers}
    if set(answers) != {question.question_id for question in public.questions}:
        raise HTTPException(422, "每道实际题目须有明确提交；空选表示未作答，不可省略题目")
    for question in public.questions:
        selected = answers[question.question_id].selected_option_ids
        if not set(selected).issubset({option.option_id for option in question.options}) or question.selection == "single" and len(selected) > 1:
            raise HTTPException(422, "存在其他题目的选项或不符合题型的选择数")


def submission_header(db, actor, submission_id, *, require_owner=True):
    submission_id = r.identifier(submission_id)
    with db.no_autoflush:
        row = current_rows(db.query(*(getattr(AITrainingSubmission, key) for key in (*ORIGIN_COLUMNS, "creation_event_id"))).filter_by(submission_id=submission_id), shared=True).one_or_none()
    if row is None:
        raise HTTPException(404, "实际培训提交不存在")
    h = dict(row._mapping)
    if require_owner and actor.user_id != h["actor_id"]:
        raise HTTPException(403, "仅当前提交人可读取其完整作答和反馈，管理目录不恢复此权限")
    try:
        if h["schema_version"] != "clinical_training_submission_record_v1" or h["scoring_method"] != "all_selected_options_exact_set_match_v1" or h["actor_role"] not in TRAINING_STAFF_ROLES:
            raise ValueError("Practice record identity/recipe differs")
        for key in ("review_hash", "lesson_private_hash", "lesson_public_hash", "lesson_references_hash", "submission_hash", "feedback_hash"):
            TypeAdapter(c.Digest).validate_python(h[key], strict=True)
        if any(type(h[key]) is not int or h[key] < 0 for key in ("question_count", "matching_count", "differing_count", "unanswered_count")) or not 1 <= h["question_count"] <= 64 or h["matching_count"] + h["differing_count"] + h["unanswered_count"] != h["question_count"]:
            raise ValueError("Practice counts differ")
        if type(h["submission_bytes"]) is not int or not 1 <= h["submission_bytes"] <= 131072 or type(h["feedback_bytes"]) is not int or not 1 <= h["feedback_bytes"] <= c.WHOLE_BYTES:
            raise ValueError("Whole submitted/feedback byte counts differ")
        r.verify_event(db, h["creation_event_id"], h["actor_id"], "training_practice_submit", submission_id, r.detail(h, ORIGIN_COLUMNS), h["submitted_at"])
    except (ValueError, TypeError, KeyError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "实际培训提交技术头、练习计算或具体审计绑定损坏") from exc
    return h


def _current_source(db, actor, header):
    with db.no_autoflush:
        owner = current_rows(db.query(User.user_id, User.user_role, User.token_invalid_before).filter_by(user_id=header["actor_id"]), shared=True).one_or_none()
    if owner is None or owner.user_role != header["actor_role"] or owner.token_invalid_before != header["actor_epoch"]:
        raise HTTPException(403, "原提交人的当前角色或授权时刻已经变化")
    review, lesson = reviews.review_header(db, header["review_id"], require_published=True)
    if review["lesson_id"] != header["lesson_id"] or review["review_hash"] != header["review_hash"] or any(review["lesson_" + key + "_hash"] != header["lesson_" + key + "_hash"] for key in ("private", "public", "references")):
        raise HTTPException(409, "实际答题所绑定的完整课程与独立复核版本损坏")
    return review, lesson


def metadata(header):
    return dict(submission_id=header["submission_id"], review_id=header["review_id"], lesson_id=header["lesson_id"], submitted_at=r.references.utc_text(header["submitted_at"]), creation_event_id=header["creation_event_id"], record_kind="server_recorded_deterministic_practice", model_attempted=False, assessment_claim="practice_record_only_not_clinical_competence_or_credential")


def _read_current(db, actor, header):
    review, lesson = _current_source(db, actor, header)
    private, public, frozen = r._read_current(db, lesson, actor.user_id)
    with db.no_autoflush:
        row = current_rows(db.query(AITrainingSubmission.submission_json, AITrainingSubmission.feedback_json).filter_by(submission_id=header["submission_id"]), shared=True).one_or_none()
    try:
        if row is None:
            raise ValueError("Actual locked practice record disappeared")
        for prefix in ("submission", "feedback"):
            raw = getattr(row, prefix + "_json")
            if len(raw.encode()) != header[prefix + "_bytes"] or r.raw_sha(raw) != header[prefix + "_hash"]:
                raise ValueError("Whole actual submitted/feedback bytes differ")
        submission = scoring.LessonSubmission.model_validate(c.parse_packet(row.submission_json), strict=True)
        feedback = scoring.verify_feedback(row.feedback_json, private, submission)
        if c.whole(submission) != row.submission_json or c.whole(feedback) != row.feedback_json or submission.lesson_id != header["lesson_id"] or submission.public_source_sha256 != header["lesson_public_hash"] or feedback.scoring_method != header["scoring_method"] or any(getattr(feedback, key) != header[key] for key in ("question_count", "matching_count", "differing_count", "unanswered_count")):
            raise ValueError("The complete deterministic practice record differs")
        return submission, feedback, private, public, frozen
    except (ValueError, TypeError, KeyError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "完整培训提交或反馈与原受审答案的确定性复算不一致") from exc


def submit_practice(db, user, value):
    try:
        actor = learner.current_learner(db, user)
        request = r.typed(PracticeCreate, value)
        review, lesson = reviews.review_header(db, request.review_id, require_published=True)
        public = learner._public_current(db, lesson, actor.user_id)
        _validate_public_answers(public, request.submission)
        # Only a structurally complete answer selection reaches the private key.
        private, stored_public, frozen = r._read_current(db, lesson, actor.user_id)
        feedback = scoring.score_submission(private, request.submission)
        submitted_raw, feedback_raw = c.whole(request.submission), c.whole(feedback)
        if len(submitted_raw.encode()) > 131072:
            raise HTTPException(422, "完整结构化作答超出实际容量，未截断保存")
        clock = r.utcnow()
        if clock < review["reviewed_at"]:
            raise HTTPException(409, "实际提交时刻早于课程独立复核")
        h = dict(submission_id=str(uuid.uuid4()), schema_version="clinical_training_submission_record_v1", review_id=review["review_id"], lesson_id=lesson["lesson_id"], review_hash=review["review_hash"], lesson_private_hash=lesson["private_hash"], lesson_public_hash=lesson["public_hash"], lesson_references_hash=lesson["references_hash"], actor_id=actor.user_id, actor_role=actor.user_role, actor_epoch=actor.token_invalid_before, submitted_at=clock, submission_hash=r.raw_sha(submitted_raw), submission_bytes=len(submitted_raw.encode()), feedback_hash=r.raw_sha(feedback_raw), feedback_bytes=len(feedback_raw.encode()), scoring_method=feedback.scoring_method, **{key: getattr(feedback, key) for key in ("question_count", "matching_count", "differing_count", "unanswered_count")})
        event_id = r.audit_event(db, actor.user_id, "training_practice_submit", h["submission_id"], r.detail(h, ORIGIN_COLUMNS), clock)
        db.add(AITrainingSubmission(**h, submission_json=submitted_raw, feedback_json=feedback_raw, creation_event_id=event_id))
        db.flush()
        stored = submission_header(db, actor, h["submission_id"])
        if _read_current(db, actor, stored)[:2] != (request.submission, feedback):
            raise HTTPException(409, "实际培训提交及反馈完整写入读回不一致")
        # The creation ACK carries no key/rationale. The HTTP layer must commit
        # this actual receipt before a subsequent current-owner feedback GET.
        return metadata(stored)
    except Exception:
        db.rollback()
        raise


def get_practice(db, user, submission_id, *, include_feedback=False):
    actor = learner.current_learner(db, user)
    header = submission_header(db, actor, submission_id)
    if not include_feedback:
        return metadata(header)
    submission, feedback, private, public, frozen = _read_current(db, actor, header)
    return dict(**metadata(header), submission=submission.model_dump(mode="json"), feedback=feedback.model_dump(mode="json"))
