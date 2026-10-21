"""Current local practice access and answer-free lesson projection.

AI activation/provider settings do not turn fixed local practice into a model
call. Current configured feature roles still restrict every learner, including
Super. Governance authoring remains a separate current-Super capability.
"""

from fastapi import HTTPException
from pydantic import ValidationError

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_references as refs
from app.ai import clinical_training_registry as r
from app.ai import clinical_training_reviews as reviews
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.clinical_training_write_guard import TRAINING_STAFF_ROLES, current_rows, lock_training_write
from app.ai.models import AIFeatureConfig
from app.dependencies import VALID_USER_ROLES


def current_learner(db, user):
    actor = lock_training_write(db, user)
    with db.no_autoflush:
        config = current_rows(db.query(AIFeatureConfig.allowed_roles_json, AIFeatureConfig.revision).filter_by(feature_key="clinical_training"), shared=True).one_or_none()
    try:
        roles = list(FEATURE_BY_KEY["clinical_training"].default_roles) if config is None else c.parse_packet(config.allowed_roles_json)
        if type(roles) is not list or any(type(role) is not str or role not in VALID_USER_ROLES for role in roles) or len(set(roles)) != len(roles) or config is not None and (type(config.revision) is not int or config.revision < 1):
            raise ValueError("Current feature roles/revision are not explicit")
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "当前培训角色配置损坏，未回退到更宽范围") from exc
    if actor.user_role not in TRAINING_STAFF_ROLES or actor.user_role not in roles:
        raise HTTPException(403, "当前账户不在培训练习的已配置角色范围，超级管理员也须满足此范围")
    return actor


def _public_current(db, lesson, actor_id):
    # No frozen reference/answer packet is needed to check current publication.
    refs._capture_current(db, actor_id, lesson["lesson_id"], c.parse_packet(lesson["reference_ids_json"]), expected_state_hash=lesson["reference_state_hash"], metadata_only=True)
    with db.no_autoflush:
        row = current_rows(db.query(r.AITrainingLesson.public_json).filter_by(lesson_id=lesson["lesson_id"]), shared=True).one_or_none()
    try:
        if row is None or len(row.public_json.encode()) != lesson["public_bytes"] or r.raw_sha(row.public_json) != lesson["public_hash"]:
            raise ValueError("The whole immutable public lesson differs")
        public = c.PublicTrainingLesson.model_validate(c.parse_packet(row.public_json), strict=True)
        if c.whole(public) != row.public_json or any(getattr(public, key) != lesson[key] for key in ("lesson_id", "title", "version_label")):
            raise ValueError("The public projection identity differs")
        return public
    except (ValueError, TypeError, KeyError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "完整公开题面或实际发布绑定已损坏") from exc


def get_public_lesson(db, user, review_id):
    actor = current_learner(db, user)
    header, lesson = reviews.review_header(db, review_id, require_published=True)
    public = _public_current(db, lesson, actor.user_id)
    return dict(review_id=header["review_id"], public_source_sha256=lesson["public_hash"], lesson=public.model_dump(mode="json"), access_policy="current_training_roles_and_reviewed_synthetic_lesson_v1", model_processing_allowed=bool(header["model_processing_allowed"]))
