"""Current76 configuration; Source callers keep their authority transaction.

The Source permission gate is independent. This helper never reads clinical or
Task bodies and never enables a feature, validates a model or alters a Prompt.
"""

from dataclasses import dataclass

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import provider_credential, provider_feature_issues, validate_endpoint
from app.ai.models import AIFeatureConfig, AIPromptVersion, AIProvider
from app.ai.research_cohort_contract import UUID
from app.ai.research_cohort_write_guard import current_research_rows, lock_research_write
from app.ai.research_variables_fields import VARIABLE_SOURCE_ROLES
from app.ai.research_variables_prompt import SYSTEM_PROMPT
from app.ai.research_variables_storage_contract import VariableFrozenProvider, VariableFrozenValidation, VariablePromptOrigin
from app.ai.research_variables_task_contract import FEATURE_KEY, strict_json
from app.config import settings
from app.dependencies import VALID_USER_ROLES


@dataclass(frozen=True)
class VariableConfiguration:
    actor: object
    config: object
    provider: object
    system_prompt: str
    task_prompt: str
    prompt_origin: VariablePromptOrigin
    provider_snapshot: VariableFrozenProvider
    validation_snapshot: VariableFrozenValidation


def current_configuration(db, user, *, preview, require_credentials=False):
    """Gate/current Actor -> Feature/Provider/Prompt before Task row locks.

    Runtime must obtain current project/all-patient/model purposes before this
    operation and still before any private Task TEXT. A valid config grants no
    such purposes. Config roles intersect the fixed catalog and Source roles.
    """
    if type(preview) is not bool or type(require_credentials) is not bool:
        raise HTTPException(422, "预览与实际凭据检查须明确布尔值")
    actor = lock_research_write(db, user, allowed_roles=VARIABLE_SOURCE_ROLES)
    spec = FEATURE_BY_KEY[FEATURE_KEY]
    config = current_research_rows(db.query(AIFeatureConfig).filter_by(feature_key=FEATURE_KEY)).one_or_none()
    if config is None or config.provider_id is None:
        raise HTTPException(409, "变量抽取尚未配置模型服务")
    try:
        roles = strict_json(config.allowed_roles_json, 65535)
        if type(roles) is not list or any(type(role) is not str or role not in VALID_USER_ROLES for role in roles) or len(roles) != len(set(roles)):
            raise ValueError("A complete explicit platform role set is required")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "变量抽取功能角色闭集无法核对") from exc
    if actor.user_role != "super_admin" and (actor.user_role not in roles or actor.user_role not in spec.default_roles):
        raise HTTPException(403, "当前账户不在本功能及来源允许角色交集中")
    if preview and actor.user_role != "super_admin":
        raise HTTPException(403, "未启用功能的显式预览仅限当前超级管理员；预览不授科研权限")
    if not preview and config.enabled != 1:
        raise HTTPException(409, "变量抽取功能尚未明确启用")
    if not preview and (spec.clinical or spec.requires_operational_validation) and config.validation_status != "validated":
        raise HTTPException(409, "该功能尚未完成其实际范围所需的独立验证")
    provider = current_research_rows(db.query(AIProvider).filter_by(provider_id=config.provider_id)).one_or_none()
    if provider is None or provider.enabled != 1 or provider.allows_patient_data != 1 or provider.kind not in {"chat", "responses"}:
        raise HTTPException(409, "变量原文仅能发给当前明确允许患者数据的文本模型服务")
    issues = provider_feature_issues(spec, provider)
    if issues:
        raise HTTPException(409, issues[0]["message"])
    try:
        validate_endpoint(provider.api_base)
    except HTTPException as exc:
        raise HTTPException(409, "当前模型地址未通过独立服务器出口策略，未冻结凭据URL或发送原文") from exc
    origin = VariablePromptOrigin(prompt_id=None, prompt_version=0)
    task_prompt = spec.task_prompt
    if config.active_prompt_id is not None:
        try:
            TypeAdapter(UUID).validate_python(config.active_prompt_id, strict=True)
        except (ValueError, TypeError) as exc:
            raise HTTPException(409, "自定义Prompt标识须为其真实UUID，未按整数查找或采用默认版本") from exc
        prompt = current_research_rows(db.query(AIPromptVersion).filter_by(prompt_id=config.active_prompt_id), shared=True).one_or_none()
        if prompt is None or prompt.feature_key != FEATURE_KEY:
            raise HTTPException(409, "当前Prompt UUID不属于本功能或原版本不存在")
        try:
            origin = VariablePromptOrigin(prompt_id=prompt.prompt_id, prompt_version=prompt.version)
        except (ValueError, TypeError) as exc:
            raise HTTPException(409, "当前自定义Prompt实际版本无法核对") from exc
        task_prompt = prompt.task_prompt
    try:
        frozen_provider = VariableFrozenProvider(
            **{name: getattr(provider, name) for name in ("provider_id", "revision", "name", "kind", "api_base", "model", "timeout_seconds", "max_output_tokens", "validation_report")},
            temperature=float(provider.temperature),
            allows_patient_data=bool(provider.allows_patient_data),
            effective_output_limit=min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS),
        )
        validation = VariableFrozenValidation(
            status=config.validation_status,
            note=config.validation_note,
            validated_by=config.validated_by,
            validated_at=str(config.validated_at) if config.validated_at is not None else None,
            feature_revision=config.revision,
        )
        task_prompt.encode("utf-8", errors="strict")
        if not task_prompt or len(task_prompt.encode("utf-8")) > 65535:
            raise ValueError("Complete actual Prompt exceeds its declared storage limit")
    except (ValueError, TypeError, UnicodeError, AttributeError) as exc:
        raise HTTPException(409, "完整当前模型、独立验证或Prompt原量无法冻结，未截断") from exc
    if require_credentials:
        provider_credential(provider)
    return VariableConfiguration(actor, config, provider, SYSTEM_PROMPT, task_prompt, origin, frozen_provider, validation)
