"""Select complete leaflet tasks by their real Source/Artifact foreign keys."""

import json

from fastapi import HTTPException

from app.ai import drug_label_sources as sources
from app.ai.drug_label_run_models import AIDrugLabelRunArtifact
from app.ai.drug_label_storage import FEATURE_KEY
from app.ai.models import AIRun


def authorize_history(db, user):
    actor = sources.current_actor(db, user)
    if actor.user_role == "super_admin":
        return actor
    from app.ai.catalog import FEATURE_BY_KEY
    from app.ai.models import AIFeatureConfig

    config = db.get(AIFeatureConfig, FEATURE_KEY)
    try:
        roles = json.loads(config.allowed_roles_json) if config else list(FEATURE_BY_KEY[FEATURE_KEY].default_roles)
        if type(roles) is not list or any(type(role) is not str for role in roles):
            raise ValueError("A closed list of role names is required")
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "当前说明书功能权限配置无效") from exc
    if actor.user_role not in roles or actor.user_role not in FEATURE_BY_KEY[FEATURE_KEY].default_roles:
        raise HTTPException(403, "当前账户没有说明书任务历史权限")
    return actor


def filter_history(db, user, query, *, feature_key, binding_id, other_scope):
    if feature_key != FEATURE_KEY or any(value is not None for value in other_scope):
        raise HTTPException(422, "说明书历史须仅筛选同一明确完整来源，不接受其他患者或运营范围")
    try:
        identifier = sources._key(binding_id)
    except ValueError as exc:
        raise HTTPException(422, "说明书来源主键不规范") from exc
    actor = authorize_history(db, user)
    sources.source_current(db, actor, identifier, audit_only=actor.user_role == "super_admin", execution=actor.user_role != "super_admin")
    members = db.query(AIDrugLabelRunArtifact.run_id).filter(AIDrugLabelRunArtifact.source_binding_id == identifier)
    return query.filter(AIRun.run_id.in_(members))
