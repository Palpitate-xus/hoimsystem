"""Filter native evaluation history through the actual immutable Case FK."""

import json

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.models import AIFeatureConfig, AIRun
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_contract import UUID
from app.ai.satisfaction_runtime import current_actor
from app.ai.satisfaction_sources import authorize_case, case_current


def authorize_history(db, user):
    """Current ordinary feature roles, or independent current Super audit."""
    actor = current_actor(db, user)
    if actor.user_role == "super_admin":
        return actor
    config = db.query(AIFeatureConfig).filter_by(feature_key="feedback_analysis").populate_existing().with_for_update(read=True).one_or_none()
    baseline = FEATURE_BY_KEY["feedback_analysis"].default_roles
    try:
        roles = json.loads(config.allowed_roles_json) if config is not None else list(baseline)
        if not isinstance(roles, list) or any(type(role) is not str for role in roles):
            raise ValueError("Malformed current feature roles")
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "评价任务当前适用角色配置无法核对") from exc
    if actor.user_role not in roles or actor.user_role not in baseline:
        raise HTTPException(403, "当前账户已无评价任务的适用权限")
    return actor


def filter_history(db, user, query, *, feature_key, case_id=None, native_only=False, other_scope=()):
    if feature_key != "feedback_analysis" or any(value is not None for value in other_scope):
        raise HTTPException(422, "完整评价历史只筛选本功能原件，不能混入患者、科室或其他来源范围")
    actor = current_actor(db, user)
    members = db.query(AISatisfactionRunArtifact.run_id)
    if case_id is not None:
        try:
            identifier = TypeAdapter(UUID).validate_python(case_id, strict=True)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, "评价历史来源须为规范UUID") from exc
        if actor.user_role == "super_admin":
            case_current(db, actor, identifier, audit_only=True)
        else:
            authorize_case(db, actor, identifier, execution=False, locking=True)
        members = members.filter_by(case_id=identifier)
    if native_only or case_id is not None:
        query = query.filter(AIRun.run_id.in_(members))
    return query
