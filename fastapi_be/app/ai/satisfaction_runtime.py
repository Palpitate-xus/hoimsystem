"""Dedicated current authorized creation and reading of satisfaction tasks."""

import datetime
import hashlib
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.orm import defer

from app.ai.catalog import CATALOG_VERSION, FEATURE_BY_KEY
from app.ai.context import context_metadata
from app.ai.gateway import AIExecutionError
from app.ai.governance import active_prompt
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_context import FEATURE_KEY, expand_context, satisfaction_context, selection
from app.ai.satisfaction_contract import SOURCE_ROLES
from app.ai.satisfaction_draft import canonical_json, source_hash
from app.ai.satisfaction_prompt import SATISFACTION_SYSTEM_PROMPT
from app.ai.satisfaction_receipts import ARTIFACT_FIELDS, WRITE_FIELDS, load_terminal, readback
from app.ai.satisfaction_sources import utcnow
from app.ai.satisfaction_storage import _run_identifier, authorize_run_scope, load_snapshot, stage_anchor
from app.ai.satisfaction_write_guard import lock_satisfaction_write
from app.config import settings
from app.sql_counts import locked_row_count


def actor_epoch(actor):
    return actor.user_role, actor.token_invalid_before


def current_actor(db, user, *, expected=None):
    actor = lock_satisfaction_write(db, user, allowed_roles=SOURCE_ROLES)
    if expected is not None and actor_epoch(actor) != expected:
        raise HTTPException(403, "评价任务原角色或登录授权已变化")
    return actor


def configuration(db, actor, preview, *, writing=False):
    from app.ai.runtime import check_configuration

    config = db.query(AIFeatureConfig).filter_by(feature_key=FEATURE_KEY).populate_existing().with_for_update(read=not writing).one_or_none()
    spec = FEATURE_BY_KEY[FEATURE_KEY]
    if config is None or config.provider_id is None:
        raise HTTPException(409, "评价功能尚未配置完整模型服务")
    try:
        import json

        roles = json.loads(config.allowed_roles_json)
        if not isinstance(roles, list) or not roles or any(type(role) is not str for role in roles):
            raise ValueError("Malformed current feature roles")
        if actor.user_role != "super_admin" and (actor.user_role not in roles or actor.user_role not in spec.default_roles):
            raise HTTPException(403, "当前账户没有使用该评价功能的权限")
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "评价功能当前适用角色配置无效") from exc
    provider = db.query(AIProvider).filter_by(provider_id=config.provider_id).populate_existing().with_for_update(read=True).one_or_none()
    if provider is None:
        raise HTTPException(409, "评价功能当前模型服务不存在")
    if config.active_prompt_id is not None:
        prompt_row = db.query(AIPromptVersion).filter_by(prompt_id=config.active_prompt_id).populate_existing().with_for_update(read=True).one_or_none()
        if prompt_row is None or prompt_row.feature_key != FEATURE_KEY:
            raise HTTPException(409, "评价功能当前Prompt版本不存在或范围错误")
    if check_configuration(db, actor, spec, config, bool(preview)) is not provider or provider.kind not in {"chat", "responses"}:
        raise HTTPException(409, "评价证据只能使用已配置的文本模型")
    prompt, version = active_prompt(db, spec, config)
    if type(prompt) is not str or not prompt.strip() or len(prompt.encode("utf-8", errors="strict")) > 65535 or type(version) is not int or version < 0:
        raise HTTPException(409, "评价Task须为完整有效的当前不可变版本")
    return spec, config, provider, prompt, version


def validation(config):
    return {
        "status": config.validation_status,
        "note": config.validation_note,
        "validated_by": config.validated_by,
        "validated_at": None if config.validated_at is None else str(config.validated_at),
        "feature_revision": config.revision,
    }


def recheck(db, run, *, expected_epoch=None):
    from app.ai.runtime import provider_snapshot

    actor = current_actor(db, SimpleNamespace(user_id=run.requested_by), expected=expected_epoch)
    if actor.token_invalid_before is not None and actor.token_invalid_before >= run.create_time:
        raise HTTPException(403, "任务创建后的登录授权已失效，请重新核对评价来源")
    if utcnow() - run.create_time > datetime.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS):
        raise AIExecutionError("TASK_EXPIRED", "任务等待时间过长，请重新核对完整评价来源后提交")
    snapshot, _, _, _ = load_snapshot(db, run, execution=True)
    spec, config, provider, prompt, version = configuration(db, actor, bool(run.preview))
    if (
        snapshot["catalog_version"] != CATALOG_VERSION
        or snapshot["system_prompt"] != SATISFACTION_SYSTEM_PROMPT
        or snapshot["provider_snapshot"] != provider_snapshot(provider)
        or snapshot["feature_validation"] != validation(config)
    ):
        raise HTTPException(409, "评价任务目录、固定System或完整模型及验证配置已改变")
    if run.prompt_version != version or snapshot["task_prompt"] != prompt:
        raise HTTPException(409, "评价任务当前Prompt版本已改变，须重新创建任务")
    expanded = expand_context(db, snapshot["payload"]["context"], user=actor, current=True, locking=True)
    return spec, provider, {**snapshot, "payload": {**snapshot["payload"], "context": expanded}}, actor_epoch(actor)


def _stage_create_audit(db, run, actor):
    event = AIAuditEvent(actor_id=actor.user_id, action="run.satisfaction.create", target=run.run_id, detail_json=canonical_json({"feature_key": FEATURE_KEY, "preview": bool(run.preview)}))
    expected = {"run": {key: getattr(run, key) for key in WRITE_FIELDS}, "audit": {key: getattr(event, key) for key in ("actor_id", "action", "target", "detail_json")}, "event": event}
    row = db.get(AISatisfactionRunArtifact, run.run_id)
    expected["artifact"] = {key: getattr(row, key) for key in ARTIFACT_FIELDS}
    db.add(event)
    db.flush()
    readback(db, run, expected)
    return expected


def create_satisfaction_run(db, user, req):
    from app.ai.runtime import _check_run_storage_json, provider_snapshot
    from app.ai.schemas import RunRequest

    try:
        req = req if isinstance(req, RunRequest) else RunRequest.model_validate(req)
        if req.feature_key != FEATURE_KEY or req.patient_id is not None or req.encounter_ref is not None:
            raise HTTPException(422, "评价证据任务不接收患者或就诊范围，也不能混入其他功能")
        selection(req.input)
        actor = current_actor(db, user)
        epoch = actor_epoch(actor)
        _, config, provider, prompt, version = configuration(db, actor, req.preview, writing=True)
        bundle = satisfaction_context(db, actor, req.input)
        clock = utcnow()
        start = datetime.datetime.combine(clock.date(), datetime.time.min)
        used = locked_row_count(db.query(AIRun).filter(AIRun.feature_key == FEATURE_KEY, AIRun.requested_by == actor.user_id, AIRun.create_time >= start).with_for_update(read=True), AIRun.run_id, aggregate=True)
        if type(config.daily_limit) is not int or config.daily_limit < 1:
            raise HTTPException(409, "评价功能当前每日额度配置无效")
        if used >= config.daily_limit:
            raise HTTPException(429, "该功能今日调用额度已用完")
        metadata = {
            **context_metadata(bundle),
            "feature_revision": config.revision,
            "validation_status": config.validation_status,
            "tool_fingerprint": source_hash({}),
            "instructions_digest": hashlib.sha256((SATISFACTION_SYSTEM_PROMPT + "\n\n" + prompt).encode("utf-8")).hexdigest(),
            "model_version": provider.model,
        }
        snapshot = {
            "catalog_version": CATALOG_VERSION,
            "system_prompt": SATISFACTION_SYSTEM_PROMPT,
            "task_prompt": prompt,
            "payload": {"input": req.input, "context": bundle.data, "tools": {}, "evidence": bundle.evidence},
            "provider_snapshot": provider_snapshot(provider),
            "feature_validation": validation(config),
        }
        serialized = {"input_json": canonical_json(snapshot), "evidence_json": canonical_json(bundle.evidence), "context_metadata_json": canonical_json(metadata)}
        _check_run_storage_json(serialized)
        run = AIRun(
            feature_key=FEATURE_KEY,
            provider_id=provider.provider_id,
            provider_revision=provider.revision,
            prompt_version=version,
            prompt_hash=source_hash([SATISFACTION_SYSTEM_PROMPT, prompt]),
            context_digest=source_hash(bundle.data),
            requested_by=actor.user_id,
            preview=int(req.preview),
            status="queued",
            create_time=clock,
            **serialized,
        )
        db.add(run)
        db.flush()
        stage_anchor(db, run)
        expected = _stage_create_audit(db, run, actor)
        recheck(db, run, expected_epoch=epoch)
        readback(db, run, expected)
        db.commit()
        return run
    except Exception:
        db.rollback()
        raise


def run_row(db, run_id, *, locking=False):
    from pydantic import TypeAdapter

    from app.ai.satisfaction_contract import UUID

    try:
        TypeAdapter(UUID).validate_python(run_id, strict=True)
    except ValueError as exc:
        raise HTTPException(422, "评价任务标识须为规范UUID") from exc
    query = db.query(AIRun).filter_by(run_id=run_id).options(*(defer(getattr(AIRun, key)) for key in ("input_json", "evidence_json", "context_metadata_json", "result_json")))
    if locking:
        query = query.populate_existing().with_for_update()
    value = query.one_or_none()
    if value is None:
        raise HTTPException(404, "评价任务不存在")
    return value


def authorize_satisfaction_run(db, user, run, *, execution=False, audit_only=False):
    identifier = _run_identifier(run)
    _, expanded = authorize_run_scope(db, user, identifier, execution=execution, audit_only=audit_only)
    # Original JSON is read only after current role/ownership/whole Source scope.
    run = db.query(AIRun).filter_by(run_id=identifier).populate_existing().with_for_update(read=True).one()
    snapshot, binding, metadata, evidence = load_snapshot(db, run, execution=execution)
    return run, snapshot, binding, metadata, evidence, expanded


def describe_satisfaction_run(db, user, run, *, include_result=True, audit_only=False):
    run, _, binding, metadata, evidence, expanded = authorize_satisfaction_run(db, user, run, audit_only=audit_only)
    result, receipt = load_terminal(db, run)
    fields = (
        "run_id",
        "feature_key",
        "status",
        "preview",
        "prompt_version",
        "provider_revision",
        "context_digest",
        "patient_id",
        "encounter_ref",
        "error_code",
        "error_message",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "create_time",
        "start_time",
        "finish_time",
    )
    value = {key: getattr(run, key) for key in fields}
    value.update(feature_name=FEATURE_BY_KEY[FEATURE_KEY].name, requires_human_review=True, context_metadata=metadata, usage=receipt)
    if include_result:
        value.update(
            result=result or {},
            evidence=evidence,
            satisfaction_findings={"satisfaction_source": expanded["satisfaction_source"], "satisfaction_case": expanded["satisfaction_case"], "satisfaction_binding": binding},
        )
    return value
