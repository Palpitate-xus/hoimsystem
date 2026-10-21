"""Current recorded practice, model permission and immutable configuration stage.

Returned contexts belong to the caller's current transaction; they are never
bearer permissions and perform no model request, Task write, commit or replay.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_learner as learner
from app.ai import clinical_training_practice as practice
from app.ai import clinical_training_reference_contract as references
from app.ai import clinical_training_references as current_references
from app.ai import clinical_training_registry as registry
from app.ai.clinical_training_protocol import instructions_for
from app.ai.clinical_training_task_contract import TrainingFeedbackSource, TrainingTaskSelection
from app.ai.clinical_training_task_prompt import PROMPT_VERSION, SYSTEM_PROMPT, TASK_PROMPT
from app.ai.clinical_training_write_guard import current_rows

FEATURE = "clinical_training"
FRAME_BYTES = 262144


def bounded_frame(value):
    raw = c.canonical_json(value)
    if len(raw.encode()) > FRAME_BYTES:
        raise HTTPException(422, "完整培训Prompt/执行快照超过256KiB，未裁剪保存")
    return raw


def configuration(db, actor, *, preview, exclusive=False):
    from app.ai.catalog import CATALOG_VERSION, FEATURE_BY_KEY
    from app.ai.governance import provider_feature_issues, validate_endpoint
    from app.ai.models import AIFeatureConfig, AIPromptVersion, AIProvider
    from app.config import settings
    from app.dependencies import VALID_USER_ROLES
    from app.models import User

    if type(preview) is not bool or type(exclusive) is not bool:
        raise HTTPException(422, "培训预览与配置锁标记须为明确布尔值")
    if preview and actor.user_role != "super_admin":
        raise HTTPException(403, "仅当前超级管理员可预览未启用的培训AI配置")
    with db.no_autoflush:
        config = current_rows(db.query(AIFeatureConfig).filter_by(feature_key=FEATURE), shared=not exclusive).one_or_none()
    if config is None:
        raise HTTPException(409, "培训AI功能尚未配置")
    try:
        roles = c.parse_packet(config.allowed_roles_json)
        if type(roles) is not list or len(config.allowed_roles_json.encode()) > 65535 or any(type(role) is not str or role not in VALID_USER_ROLES for role in roles) or len(set(roles)) != len(roles):
            raise ValueError("Current configured roles must be exact distinct platform roles")
        if type(config.revision) is not int or config.revision < 1 or type(config.daily_limit) is not int or not 1 <= config.daily_limit <= 1000000:
            raise ValueError("Explicit revision and quota required")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "培训AI当前角色、修订或额度配置损坏") from exc
    if actor.user_role not in roles:
        raise HTTPException(403, "当前角色不在培训AI已配置范围，预览也不恢复业务来源权限")
    if not preview and (config.enabled != 1 or config.validation_status != "validated" or config.validated_at is None or not config.validation_note):
        raise HTTPException(409, "培训AI尚未启用或缺少当前范围的独立启用记录")
    validator_state = None
    if not preview:
        with db.no_autoflush:
            validator = current_rows(db.query(User.user_id, User.user_role, User.token_invalid_before).filter_by(user_id=config.validated_by), shared=True).one_or_none()
        if validator is None or validator.user_role != "super_admin" or validator.token_invalid_before is not None and config.validated_at < validator.token_invalid_before:
            raise HTTPException(403, "培训AI启用审核人的当前角色或授权时刻已变化")
        validator_state = current_references.actor_packet(validator)
    with db.no_autoflush:
        provider = current_rows(db.query(AIProvider).filter_by(provider_id=config.provider_id), shared=True).one_or_none()
    if provider is None or provider.enabled != 1 or provider.kind not in {"chat", "responses"} or type(provider.revision) is not int or provider.revision < 1:
        raise HTTPException(409, "当前培训文本模型服务未正确启用")
    try:
        temperature = Decimal(str(provider.temperature))
        if type(provider.model) is not str or not provider.model.strip() or type(provider.timeout_seconds) is not int or not 1 <= provider.timeout_seconds <= 300 or type(provider.max_output_tokens) is not int or not 1 <= provider.max_output_tokens <= 1000000 or not temperature.is_finite() or not Decimal("0") <= temperature <= Decimal("2") or type(settings.AI_MAX_OUTPUT_TOKENS) is not int or settings.AI_MAX_OUTPUT_TOKENS < 1:
            raise ValueError("Actual complete model parameters are required")
        if validate_endpoint(provider.api_base) != provider.api_base or provider_feature_issues(FEATURE_BY_KEY[FEATURE], provider):
            raise ValueError("Provider scope or exact configured endpoint differs")
    except (ValueError, TypeError, InvalidOperation, AttributeError, HTTPException) as exc:
        raise HTTPException(409, "当前培训模型协议、地址或参数不满足明确范围") from exc
    with db.no_autoflush:
        prompt = current_rows(db.query(AIPromptVersion).filter_by(prompt_id=config.active_prompt_id), shared=True).one_or_none() if config.active_prompt_id is not None else None
    try:
        if config.active_prompt_id is not None:
            TypeAdapter(c.Identifier).validate_python(config.active_prompt_id, strict=True)
            if prompt is None or prompt.feature_key != FEATURE or type(prompt.version) is not int or prompt.version < 1:
                raise ValueError("Actual immutable Prompt UUID/feature/version differs")
        task = TASK_PROMPT if prompt is None else prompt.task_prompt
        instructions = instructions_for(task)
    except (ValueError, TypeError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "培训AI不可变Prompt实际归属、UUID或完整文本损坏") from exc
    frozen_prompt = dict(schema_version="clinical_training_prompt_snapshot_v1", prompt_id=None if prompt is None else prompt.prompt_id, prompt_version=0 if prompt is None else prompt.version, origin="packaged_task" if prompt is None else "database_version", catalog_version=CATALOG_VERSION, native_task_version=PROMPT_VERSION, system_prompt=SYSTEM_PROMPT, task_prompt=task, instructions_digest=hashlib.sha256(instructions.encode()).hexdigest())
    provider_snapshot = {name: getattr(provider, name) for name in ("provider_id", "revision", "name", "kind", "api_base", "model", "timeout_seconds", "max_output_tokens", "validation_report")}
    provider_snapshot.update(temperature_decimal=str(temperature), allows_patient_data=bool(provider.allows_patient_data), effective_output_limit=min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS))
    execution = dict(schema_version="clinical_training_execution_snapshot_v1", feature_key=FEATURE, preview=preview, requester_epoch=dict(user_id=actor.user_id, user_role=actor.user_role, token_invalid_before=current_references.utc_text(actor.token_invalid_before) if actor.token_invalid_before is not None else None), configuration=dict(revision=config.revision, enabled=config.enabled, allowed_roles=sorted(roles), daily_limit=config.daily_limit, active_prompt_id=config.active_prompt_id), provider_snapshot=provider_snapshot, feature_validation=dict(status=config.validation_status, note=config.validation_note, validated_by=config.validated_by, validated_at=current_references.utc_text(config.validated_at) if config.validated_at is not None else None, current_validator=validator_state))
    bounded_frame(frozen_prompt)
    bounded_frame(execution)
    return config, provider, frozen_prompt, execution


@dataclass(frozen=True)
class TrainingContext:
    actor: object
    selection: TrainingTaskSelection
    submission: dict
    review: dict
    lesson: dict
    source: TrainingFeedbackSource
    config: object
    provider: object
    prompt: dict
    execution: dict

    def binding(self):
        return source_binding(self.submission, self.review, self.lesson, self.selection.objective)


def source_binding(submitted, review, lesson, objective):
    return dict(schema_version="clinical_training_source_binding_v1", submission_id=submitted["submission_id"], submission_creation_event_id=submitted["creation_event_id"], submitted_at=current_references.utc_text(submitted["submitted_at"]), requested_by=submitted["actor_id"], submission_actor_role=submitted["actor_role"], submission_actor_epoch=current_references.utc_text(submitted["actor_epoch"]) if submitted["actor_epoch"] is not None else None, submission_hash=submitted["submission_hash"], feedback_hash=submitted["feedback_hash"], review_id=review["review_id"], review_hash=review["review_hash"], review_creation_event_id=review["creation_event_id"], lesson_id=lesson["lesson_id"], lesson_private_hash=lesson["private_hash"], lesson_public_hash=lesson["public_hash"], lesson_references_hash=lesson["references_hash"], lesson_creation_event_id=lesson["creation_event_id"], reference_state_hash=lesson["reference_state_hash"], objective=objective)


def read_source(db, actor, submitted):
    selected, feedback, private, public, frozen = practice._read_current(db, actor, submitted)
    try:
        source = TrainingFeedbackSource(schema_version="clinical_training_feedback_source_v1", source_id=submitted["submission_id"], lesson=public, submission=selected, feedback=feedback, references=references.model_projection(frozen), intended_use="explain_actual_recorded_practice_not_patient_treatment_or_credentialing")
        c.whole(source)
    except (ValueError, TypeError, UnicodeError, ValidationError) as exc:
        raise HTTPException(422, "完整课程、作答、反馈与参考合计超过AI请求范围；本地完整练习仍可用，未截断送模") from exc
    return source


def prepare_context(db, user, value, *, preview=False, exclusive_config=False):
    selection = registry.typed(TrainingTaskSelection, value)
    actor = learner.current_learner(db, user)
    submitted = practice.submission_header(db, actor, selection.clinical_training_submission_id)
    review, lesson = practice._current_source(db, actor, submitted)
    if review["model_processing_allowed"] != 1:
        raise HTTPException(403, "该实际提交所绑定的课程复核未单独允许模型处理")
    current_references._capture_current(db, actor.user_id, lesson["lesson_id"], c.parse_packet(lesson["reference_ids_json"]), expected_state_hash=lesson["reference_state_hash"], metadata_only=True)
    config, provider, prompt, execution = configuration(db, actor, preview=preview, exclusive=exclusive_config)
    source = read_source(db, actor, submitted)
    return TrainingContext(actor, selection, submitted, review, lesson, source, config, provider, prompt, execution)
