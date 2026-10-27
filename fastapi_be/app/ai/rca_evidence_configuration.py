"""Current Source -> configuration -> Task order for the dedicated RCA worker."""

import datetime as dt
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select

from app.ai import rca_evidence_context as context
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_storage as storage
from app.ai import rca_evidence_storage_contract as types
from app.ai import rca_evidence_task_contract as task_types
from app.ai.catalog import CATALOG_VERSION, FEATURE_BY_KEY
from app.ai.models import AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.ai.rca_evidence_task_prompt import SYSTEM_PROMPT
from app.ai.rca_evidence_task_views import RcaFrozenProvider, RcaFrozenValidation
from app.ai.rca_evidence_write_guard import current_rows
from app.config import settings
from app.sql_counts import locked_row_count


@dataclass(frozen=True)
class RcaConfiguration:
    config: AIFeatureConfig
    provider: AIProvider
    task_prompt: str
    prompt_version: int
    frozen_provider: RcaFrozenProvider
    frozen_validation: RcaFrozenValidation


def _current_configuration(db, actor, preview, *, writing=False):
    """Internal: caller already holds actual Source parents and original grants."""
    from app.ai.runtime import check_configuration, provider_snapshot

    if type(preview) is not bool:
        raise HTTPException(422, "预览必须为显式布尔值")
    actor = grants.current_actor(db, actor, grants.SOURCE_ROLES)
    config = current_rows(db.query(AIFeatureConfig).filter_by(feature_key=task_types.FEATURE_KEY), shared=not writing).one_or_none()
    if config is None or config.provider_id is None:
        raise HTTPException(409, "事件调查功能尚未明确配置文字模型")
    provider = current_rows(db.query(AIProvider).filter_by(provider_id=config.provider_id), shared=True).one_or_none()
    if provider is None:
        raise HTTPException(409, "原事件调查文字模型已不存在")
    try:
        from app.dependencies import VALID_USER_ROLES

        roles = c._strict_reply(config.allowed_roles_json)
        if type(roles) is not list or any(type(role) is not str or role not in VALID_USER_ROLES for role in roles) or len(roles) != len(set(roles)):
            raise ValueError("Actual configured roles must remain a strict closed role list")
        if type(config.enabled) is not int or config.enabled not in {0, 1} or type(provider.enabled) is not int or provider.enabled not in {0, 1}:
            raise ValueError("Actual activation flags are explicit SQL0/1")
        if type(config.daily_limit) is not int or not 1 <= config.daily_limit <= 10000:
            raise ValueError("The actual daily task limit must be explicit and bounded")
        if type(provider.allows_patient_data) is not int or provider.allows_patient_data != 1 or provider.kind not in {"chat", "responses"}:
            raise ValueError("Only explicitly authorized sensitive text protocols are suitable")
        spec = FEATURE_BY_KEY[task_types.FEATURE_KEY]
        if spec.default_roles != ("super_admin",) or spec.scope != "input" or not spec.requires_patient_data_permission or spec.requires_knowledge:
            raise ValueError("The actual packaged native RCA capability differs")
        if check_configuration(db, actor, spec, config, preview) is not provider:
            raise ValueError("The current provider differs from its locked configuration")
        if config.active_prompt_id is not None:
            prompt = current_rows(db.query(AIPromptVersion).filter_by(prompt_id=config.active_prompt_id), shared=True).one_or_none()
            if prompt is None or prompt.feature_key != spec.key or type(prompt.version) is not int or prompt.version < 1:
                raise ValueError("An active immutable Prompt must belong to this exact feature")
            task_prompt, version = prompt.task_prompt, prompt.version
        else:
            task_prompt, version = spec.task_prompt, 0
        c.plain(task_prompt, task_types.MAX_RUN_TEXT_BYTES)
        frozen_provider = RcaFrozenProvider.model_validate(provider_snapshot(provider))
        frozen_validation = RcaFrozenValidation(
            status=config.validation_status,
            note=config.validation_note,
            validated_by=config.validated_by,
            validated_at=str(config.validated_at) if config.validated_at is not None else None,
            feature_revision=config.revision,
        )
        return RcaConfiguration(config, provider, task_prompt, version, frozen_provider, frozen_validation)
    except (ValueError, TypeError, UnicodeError, KeyError) as exc:
        raise HTTPException(409, "当前功能角色、文字模型授权、完整Prompt或实际验证配置无法核对") from exc


def for_context(db, user, prepared, preview, *, writing=False):
    auth, _immutable = context.authorize_binding(db, user, prepared.binding)
    return _current_configuration(db, auth.actor, preview, writing=writing)


def snapshot_for_context(prepared, configured):
    actor = prepared.authorized.actor
    return types.RcaTaskSnapshot(
        schema_version="rca_evidence_task_snapshot_v1",
        catalog_version=CATALOG_VERSION,
        system_prompt=SYSTEM_PROMPT,
        task_prompt=configured.task_prompt,
        payload={"input": prepared.selection, "context": prepared.data, "tools": {}, "evidence": prepared.evidence},
        provider_snapshot=configured.frozen_provider,
        feature_validation=configured.frozen_validation,
        source_case_governance=prepared.record.governance,
        actor_epoch={"user_role": actor.user_role, "token_invalid_before": i.utc_text(actor.token_invalid_before) if actor.token_invalid_before is not None else None},
        run_clock_basis="legacy_utc_second_storage",
    )


def assert_frozen_configuration(stored, configured):
    if (
        stored.snapshot.catalog_version != CATALOG_VERSION
        or stored.snapshot.system_prompt != SYSTEM_PROMPT
        or stored.snapshot.task_prompt != configured.task_prompt
        or stored.run.prompt_version != configured.prompt_version
        or stored.snapshot.provider_snapshot != configured.frozen_provider
        or stored.snapshot.feature_validation != configured.frozen_validation
    ):
        raise HTTPException(409, "原任务完整模型、Prompt、验证或目录版本已改变，未启动或接受新正文")


def for_execution(db, user, identifier, *, exclusive=True):
    # Even configuration/quota locks precede Run locks. No Run/Artifact body is
    # used as an authorization locator, and an old RR snapshot cannot hide a
    # newly committed opaque Artifact from the technical current lookup.
    identity = storage.locate_artifact(db, identifier)
    auth, _immutable, _grant_ids = storage._source_before_task(db, user, identity)
    # The preview flag is a short immutable Run header column. It is read only
    # after Source authority and without taking a Run lock before Config.
    preview_row = storage._narrow_current(db, select(AIRun.run_id, AIRun.preview).where(AIRun.run_id == identity[0]))
    preview = preview_row[1] if preview_row is not None else None
    if type(preview) is not int or preview not in {0, 1}:
        raise HTTPException(409, "原任务显式预览标志缺失或无效")
    configured = _current_configuration(db, auth.actor, bool(preview))
    stored = storage.load_task(db, auth.actor, identifier, exclusive=exclusive)
    assert_frozen_configuration(stored, configured)
    if type(settings.AI_MAX_QUEUE_AGE_SECONDS) is not int or settings.AI_MAX_QUEUE_AGE_SECONDS < 1:
        raise HTTPException(409, "明确任务最长等待政策无效")
    elapsed = grants.utcnow() - stored.artifact.recorded_at
    if elapsed < dt.timedelta(0) or elapsed > dt.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS):
        raise HTTPException(409, "原任务实际时钟或等待期限已不适用，请明确重读当前Case后提交新任务")
    return stored, configured


def current_daily_count(db, owner, when):
    """Caller holds Source then this feature's Config X throughout creation.

    Current FOR SHARE plus the actual feature/time index keeps a retained RR
    view honest without taking an unrelated feature's Run lock. Runtime
    execution takes Config before its Run lock, preserving this order.
    """
    start = dt.datetime.combine(when.date(), dt.time.min)
    query = (
        db.query(AIRun)
        .with_hint(AIRun, "FORCE INDEX (idx_ai_run_feature_time)", dialect_name="mysql")
        .filter(AIRun.feature_key == task_types.FEATURE_KEY, AIRun.requested_by == owner, AIRun.create_time >= start, AIRun.create_time < start + dt.timedelta(days=1))
        .with_for_update(read=True)
    )
    return locked_row_count(query, AIRun.run_id, aggregate=True)
