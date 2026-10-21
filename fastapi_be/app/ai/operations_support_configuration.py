"""Current operations source and configuration stage; no queue, HTTP or commit.

Returned values are inputs to one caller-owned SQL transaction, never a reusable
permission token. Creation must lock the configuration exclusively before its
current daily count; readers use SHARE before any Run lock.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from app.ai import operations_support_cases as cases
from app.ai import operations_support_projection as projection
from app.ai import operations_support_registry as registry
from app.ai.operations_support_protocol import instructions_for as protocol_instructions
from app.ai.operations_support_run_models import FRAME_BYTES
from app.ai.operations_support_task_contract import OperationsTaskSelection
from app.ai.operations_support_task_prompt import PROMPT_VERSION, SYSTEM_PROMPT, TASK_PROMPT
from app.ai.operations_support_write_guard import OPERATIONS_SOURCE_ROLES, current_rows, lock_operations_write

FEATURE = "operations_support"


def instructions_for(task):
    try:
        return protocol_instructions(task)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "运维任务Prompt须为完整且不超过65535字节的非空原文") from exc


def roles_for(raw):
    from app.dependencies import VALID_USER_ROLES

    try:
        if type(raw) is not str or len(raw.encode("utf-8")) > 65535:
            raise ValueError("Complete role JSON required")
        values = projection._value(raw)
        if type(values) is not list or any(type(value) is not str or value not in VALID_USER_ROLES for value in values) or len(values) != len(set(values)):
            raise ValueError("Explicit distinct platform roles required")
        return sorted(values)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "运维功能当前角色配置损坏") from exc


def configuration(db, actor, *, preview, exclusive=False):
    """Current Config -> Provider -> immutable Prompt; never credentials or Source."""
    from app.ai.catalog import CATALOG_VERSION, FEATURE_BY_KEY
    from app.ai.governance import provider_feature_issues, validate_endpoint
    from app.ai.models import AIFeatureConfig, AIPromptVersion, AIProvider
    from app.config import settings

    if type(preview) is not bool or type(exclusive) is not bool:
        raise HTTPException(422, "运维预览和配置锁标记须为实际布尔值")
    if actor.user_role not in OPERATIONS_SOURCE_ROLES:
        raise HTTPException(403, "当前身份不具备运维任务业务权限")
    if preview and actor.user_role != "super_admin":
        raise HTTPException(403, "仅当前超级管理员可预览尚未启用的运维配置")
    config = current_rows(db.query(AIFeatureConfig).filter_by(feature_key=FEATURE), shared=not exclusive).one_or_none()
    if config is None:
        raise HTTPException(409, "运维功能尚未配置")
    roles = roles_for(config.allowed_roles_json)
    if actor.user_role != "super_admin" and actor.user_role not in roles:
        raise HTTPException(403, "当前身份未获配置中的运维任务使用权限")
    if not preview and (config.enabled != 1 or config.validation_status != "validated"):
        raise HTTPException(409, "运维功能未启用或尚未记录当前范围验证")
    if type(config.revision) is not int or config.revision < 1 or type(config.daily_limit) is not int or not 1 <= config.daily_limit <= 1000000:
        raise HTTPException(409, "运维功能修订或每日额度不是有效闭集")
    provider = current_rows(db.query(AIProvider).filter_by(provider_id=config.provider_id), shared=True).one_or_none()
    if provider is None or provider.enabled != 1 or provider.kind not in {"chat", "responses"} or type(provider.revision) is not int or provider.revision < 1:
        raise HTTPException(409, "当前运维文本模型服务未正确启用")
    try:
        temperature = Decimal(str(provider.temperature))
        if (
            type(provider.model) is not str
            or not provider.model.strip()
            or type(provider.timeout_seconds) is not int
            or not 1 <= provider.timeout_seconds <= 300
            or type(provider.max_output_tokens) is not int
            or not 1 <= provider.max_output_tokens <= 1000000
            or not temperature.is_finite()
            or not Decimal("0") <= temperature <= Decimal("2")
            or type(settings.AI_MAX_OUTPUT_TOKENS) is not int
            or settings.AI_MAX_OUTPUT_TOKENS < 1
        ):
            raise ValueError("Complete explicit provider parameters required")
        validate_endpoint(provider.api_base)
        issues = provider_feature_issues(FEATURE_BY_KEY[FEATURE], provider)
        if issues:
            raise ValueError("Configured provider is outside this feature scope")
    except (ValueError, TypeError, InvalidOperation, AttributeError, HTTPException) as exc:
        raise HTTPException(409, "当前运维模型协议、地址或参数不可用") from exc
    prompt = current_rows(db.query(AIPromptVersion).filter_by(prompt_id=config.active_prompt_id), shared=True).one_or_none() if config.active_prompt_id is not None else None
    if config.active_prompt_id is not None and (prompt is None or prompt.feature_key != FEATURE or type(prompt.version) is not int or prompt.version < 1):
        raise HTTPException(409, "运维当前不可变Prompt版本归属或版本号不一致")
    task = TASK_PROMPT if prompt is None else prompt.task_prompt
    instructions = instructions_for(task)
    prompt_snapshot = {
        "schema_version": "operations_prompt_snapshot_v1",
        "prompt_id": None if prompt is None else prompt.prompt_id,
        "prompt_version": 0 if prompt is None else prompt.version,
        "origin": "packaged_task" if prompt is None else "database_version",
        "catalog_version": CATALOG_VERSION,
        "native_task_version": PROMPT_VERSION,
        "system_prompt": SYSTEM_PROMPT,
        "task_prompt": task,
        "instructions_digest": hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
    }
    provider_snapshot = {name: getattr(provider, name) for name in ("provider_id", "revision", "name", "kind", "api_base", "model", "timeout_seconds", "max_output_tokens", "validation_report")}
    provider_snapshot.update(
        temperature_decimal=str(temperature), allows_patient_data=bool(provider.allows_patient_data), effective_output_limit=min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS)
    )
    execution = {
        "schema_version": "operations_execution_snapshot_v1",
        "feature_key": FEATURE,
        "preview": preview,
        "requester_epoch": {
            "user_id": actor.user_id,
            "user_role": actor.user_role,
            "token_invalid_before": registry.utc_text(actor.token_invalid_before) if actor.token_invalid_before is not None else None,
        },
        "configuration": {"revision": config.revision, "enabled": config.enabled, "allowed_roles": roles, "daily_limit": config.daily_limit, "active_prompt_id": config.active_prompt_id},
        "provider_snapshot": provider_snapshot,
        "feature_validation": {
            "status": config.validation_status,
            "note": config.validation_note,
            "validated_by": config.validated_by,
            "validated_at": registry.utc_text(config.validated_at) if config.validated_at is not None else None,
        },
    }
    # Complete frame sizes are checked before private original/review/Case reads.
    registry.bounded_json(prompt_snapshot, FRAME_BYTES)
    registry.bounded_json(execution, FRAME_BYTES)
    return config, provider, prompt_snapshot, execution


@dataclass(frozen=True)
class OperationsContext:
    actor: object
    selection: OperationsTaskSelection
    header: dict
    membership: cases.Membership
    source: projection.OperationsSupportSource
    private: projection.PrivateOperationsCollection
    config: object
    provider: object
    prompt: dict
    execution: dict

    def binding(self):
        return {
            "schema_version": "operations_source_binding_v1",
            "case_id": self.header["case_id"],
            "case_requested_by": self.header["requested_by"],
            "case_private_hash": self.header["private_hash"],
            "case_public_hash": self.header["public_hash"],
            "case_membership_hash": self.header["member_bindings_hash"],
            "case_creation_event_id": self.header["creation_event_id"],
            "case_assembled_at": registry.utc_text(self.header["assembled_at"]),
            "objective": self.selection.objective,
        }


def prepare_context(db, user, value, *, preview=False, exclusive_config=False):
    """Gate -> current Actor -> every source header -> Config -> complete bodies."""
    if type(preview) is not bool or type(exclusive_config) is not bool:
        raise HTTPException(422, "运维预览和配置锁标记须为实际布尔值")
    selection = registry.typed(OperationsTaskSelection, value)
    actor = lock_operations_write(db, user)
    header = cases.case_header(db, actor, selection.operations_case_id)
    membership, source_headers = cases.current_members(db, header, execution=True)
    config, provider, prompt, execution = configuration(db, actor, preview=preview, exclusive=exclusive_config)
    private, source = cases.read_case_bodies(db, header, membership, source_headers)
    return OperationsContext(actor, selection, header, membership, source, private, config, provider, prompt, execution)
