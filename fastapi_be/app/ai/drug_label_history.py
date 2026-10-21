"""Select complete leaflet tasks by their real Source/Artifact foreign keys."""

from fastapi import HTTPException

from app.ai import drug_label_sources as sources
from app.ai.drug_label_run_models import AIDrugLabelRunArtifact
from app.ai.drug_label_storage import FEATURE_KEY, authorize_task_reader
from app.ai.models import AIRun


def authorize_history(db, user):
    return authorize_task_reader(db, user, frozen_audit=user.user_role == "super_admin")


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
