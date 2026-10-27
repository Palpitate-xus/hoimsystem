"""Current config snapshots; roles never replace project/patient permissions."""

from fastapi import HTTPException

from app.ai.deidentification_frozen import freeze_prompt
from app.ai.deidentification_task_access import role_configuration
from app.ai.deidentification_task_contract import FEATURE_KEY, FrozenProvider, FrozenValidation, RequesterEpoch
from app.ai.governance import active_prompt, get_spec, provider_credential, validate_endpoint
from app.ai.models import AIPromptVersion, AIProvider
from app.ai.research_cohort_write_guard import current_research_rows
from app.ai.retry_policy import configured_attempts
from app.config import settings


def epoch(actor):
    return RequesterEpoch.model_validate(
        {"user_id": actor.user_id, "user_role": actor.user_role, "token_invalid_before": str(actor.token_invalid_before) if actor.token_invalid_before is not None else None}
    ).model_dump()


def configuration(db, actor, preview=False):
    config, roles = role_configuration(db, actor)
    if type(config.daily_limit) is not int or not 1 <= config.daily_limit <= 10000:
        raise HTTPException(409, "完整当前日额度配置无效")
    if type(preview) is not bool or preview and actor.user_role != "super_admin":
        raise HTTPException(403, "只有当前Super可明确预览，且仍须研究权限")
    if not preview and config.enabled != 1 or config.validation_status == "suspended":
        raise HTTPException(409, "75功能未启用或已暂停")
    provider = current_research_rows(db.query(AIProvider).filter_by(provider_id=config.provider_id), shared=True).one_or_none()
    if provider is None or provider.enabled != 1 or provider.allows_patient_data != 1 or provider.kind not in {"chat", "responses"}:
        raise HTTPException(409, "须明确允许原临床正文的有效文字模型配置")
    import json

    try:
        supported = json.loads(provider.supported_features_json)
        if type(supported) is not list or any(type(item) is not str for item in supported):
            raise ValueError("Original provider feature declaration must retain its type")
        public = FrozenProvider.model_validate(
            {
                **{key: getattr(provider, key) for key in ("provider_id", "revision", "name", "kind", "api_base", "model", "timeout_seconds", "max_output_tokens", "validation_report")},
                "max_attempts": configured_attempts(provider),
                "temperature": float(provider.temperature),
                "allows_patient_data": True,
                "effective_output_limit": min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS),
            }
        ).model_dump()
        validation = FrozenValidation.model_validate(
            {
                "status": config.validation_status,
                "note": config.validation_note,
                "validated_by": config.validated_by,
                "validated_at": str(config.validated_at) if config.validated_at is not None else None,
                "feature_revision": config.revision,
            }
        ).model_dump()
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "75完整模型或功能验证配置无法核对") from exc
    validate_endpoint(provider.api_base)
    provider_credential(provider)
    spec = get_spec(FEATURE_KEY)
    # Explicit current read before active_prompt's identity-map lookup.
    original = None
    if config.active_prompt_id is not None:
        row = current_research_rows(db.query(AIPromptVersion).filter_by(prompt_id=config.active_prompt_id), shared=True).one_or_none()
        if row is None:
            raise HTTPException(409, "实际Prompt版本不存在")
        original = {key: getattr(row, key) for key in ("prompt_id", "feature_key", "version", "task_prompt", "change_note", "created_by")}
        original["create_time"] = str(row.create_time)
    task, version = active_prompt(db, spec, config)
    from app.ai.catalog import CATALOG_VERSION

    prompt = freeze_prompt(task, catalog_version=CATALOG_VERSION, database_snapshot=original)
    if prompt["version"] != version:
        raise HTTPException(409, "实际Prompt版本不一致")
    return config, provider, public, validation, prompt, roles
