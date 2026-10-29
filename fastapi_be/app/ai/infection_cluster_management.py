"""Current local-model metadata; it grants no patient or execution authority."""

from fastapi import HTTPException

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_input as source_input
from app.ai import infection_cluster_profiles as profiles
from app.ai.infection_cluster_implementation import implementation_descriptor
from app.ai.infection_cluster_write_guard import current
from app.ai.models import AIFeatureConfig


def authorize_feature(db, user):
    from app.access_control import enforce_feature_permission

    actor = profiles._start(db, user, roles=source_input.SOURCE_ROLES)
    enforce_feature_permission(db, actor, profiles.KEY, fresh=True)
    config = current(db.query(AIFeatureConfig).filter_by(feature_key=profiles.KEY), shared=True).one_or_none()
    if config is not None and actor.user_role not in profiles._roles(config):
        raise HTTPException(403, "当前角色不在78固定角色与实际配置的交集中")
    return actor, config


def describe_configuration(db, spec, *, user=None, management=False):
    from app.ai.catalog import describe_feature
    from app.ai.governance import digest
    from app.ai.infection_cluster_task_contract import LOCAL_PROMPT_HASH

    state = None
    error = None
    if user is not None:
        # Current actor is checked before loading any selected Profile payload.
        profiles._start(db, user, roles=source_input.GOVERNANCE_ROLES if management else source_input.SOURCE_ROLES)
        try:
            state = profiles.configuration(db, user, management=management)
        except HTTPException as exc:
            error = dict(code="LOCAL_CONFIGURATION_INVALID", message="本地选择、完整配置或当前发布依据无法核对", status=exc.status_code)
    profile = state.get("profile") if state else None
    config = current(db.query(AIFeatureConfig).filter_by(feature_key=profiles.KEY), shared=True).one_or_none() if user is not None else None
    try:
        roles = profiles._roles(config) if config else sorted(source_input.SOURCE_ROLES)
    except HTTPException:
        roles = []
    result = {
        **describe_feature(spec),
        "input_mode": "infection_cluster_evidence",
        "execution": "local_exact_statistics",
        "enabled": bool(state and state["enabled"]),
        "allowed_roles": roles,
        "validation_status": state["validation_status"] if state else "unreviewed",
        "prompt_version": 0,
        "revision": config.revision if config else 0,
        "implementation_status": "local_fixed_recipe",
        "daily_limit": config.daily_limit if config else None,
        "provider_configured": False,
        "external_provider_required": False,
        "external_model_transfer": False,
        "local_profile_id": state["profile_id"] if state else None,
        "local_profile_current": bool(profile and profile["eligible"]) if management else None,
        "local_profile_validation_status": profile["payload"]["validation_status"] if profile else None,
        "local_configuration_verified": state is not None,
        "configuration_governor_current": bool(state and state["configuration_governor_current"]),
        "local_configuration_issue": error,
        "implementation_descriptor": implementation_descriptor(),
        "configuration_endpoint": "/api/ai/infection-cluster/local-configuration",
        "patient_processing_required_for_every_patient": True,
        "patient_purpose_not_verified_by_feature_metadata": True,
        "automatic_actions": False,
    }
    if management:
        result.update(
            provider_id=None,
            active_prompt_id=None,
            validation_note=state["validation_note"] if state else None,
            validated_by=config.validated_by if config else None,
            validated_at=config.validated_at.isoformat() if config and config.validated_at else None,
            system_prompt_hash=digest(""),
            local_recipe_prompt_hash=LOCAL_PROMPT_HASH,
            local_profile_content_hash=profile["content_hash"] if profile else None,
            local_profile_governance_hash=profile["governance_hash"] if profile else None,
            local_profile_current_issues=profile["current_issues"] if profile else [],
        )
    c.canonical(result)
    return result


def readiness(db, spec, *, user=None):
    value = describe_configuration(db, spec, user=user, management=user is not None)
    issues = []
    if not value["local_configuration_verified"]:
        issues.append(value["local_configuration_issue"] or dict(code="LOCAL_CONFIGURATION_REQUIRED", message="尚未由当前Super核对本地Profile与完整配置"))
    if not value["enabled"]:
        issues.append(dict(code="FEATURE_DISABLED", message="本地统计尚未显式启用"))
    if not value["local_profile_current"]:
        issues.append(dict(code="LOCAL_PROFILE_REQUIRED", message="尚无当前独立发布且与实际安装实现一致的已选择本地Profile"))
    if value["validation_status"] != "validated" or value["local_profile_validation_status"] != "validated":
        issues.append(dict(code="CLINICAL_VALIDATION_REQUIRED", message="功能与Profile适用范围均须独立记录本地验证；工程算例不证明实际临床有效"))
    if not value["configuration_governor_current"]:
        issues.append(dict(code="LOCAL_CONFIGURATION_GOVERNOR_REQUIRED", message="实际配置治理者的当前身份与原时段须有效"))
    return dict(
        ready=not issues,
        issues=issues,
        checked_at=profiles.r.utcnow(),
        scope_note="仅本地固定统计实现及治理依赖；未核对具体Source、逐患者处理用途、预先选族偏倚或真实临床效果；无需外部Provider",
    )
