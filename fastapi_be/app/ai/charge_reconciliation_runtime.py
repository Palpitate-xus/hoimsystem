"""Current authorized task creation and execution for one full recorded ledger."""

import datetime
import hashlib

from fastapi import HTTPException
from sqlalchemy import func

from app.ai import charge_reconciliation_contract as c
from app.ai import charge_reconciliation_sources as sources
from app.ai.catalog import CATALOG_VERSION
from app.ai.charge_reconciliation_context import charge_context, expand_context, selection
from app.ai.charge_reconciliation_prompt import CHARGE_RECONCILIATION_SYSTEM_PROMPT
from app.ai.charge_reconciliation_receipts import ARTIFACT_FIELDS, WRITE_FIELDS, _verify_write
from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.charge_reconciliation_storage import FEATURE_KEY, load_snapshot, stage_anchor
from app.ai.context import context_metadata
from app.ai.gateway import AIExecutionError
from app.ai.governance import active_prompt, audit, digest
from app.ai.models import AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.ai.native_acceptance import acceptance_state
from app.config import settings
from app.models import User


def actor_epoch(actor):
    return actor.user_role, actor.token_invalid_before


def current_actor(db, user, *, expected=None):
    actor = sources.current_actor(db, user)
    if expected is not None and actor_epoch(actor) != expected:
        raise HTTPException(403, "本次账目任务的原角色或登录授权已改变")
    return actor


def _configuration(db, actor, preview, *, writing=False):
    from app.ai.runtime import authorized_feature, check_configuration

    config = db.query(AIFeatureConfig).filter_by(feature_key=FEATURE_KEY).populate_existing().with_for_update(read=not writing).one_or_none()
    if config is None or config.provider_id is None:
        raise HTTPException(409, "完整账目功能的当前模型配置不可用")
    current_provider = db.query(AIProvider).filter_by(provider_id=config.provider_id).populate_existing().with_for_update(read=True).one_or_none()
    if current_provider is None:
        raise HTTPException(409, "完整账目功能的当前模型服务不存在")
    if config.active_prompt_id is not None:
        current_prompt = db.query(AIPromptVersion).filter_by(prompt_id=config.active_prompt_id).populate_existing().with_for_update(read=True).one_or_none()
        if current_prompt is None or current_prompt.feature_key != FEATURE_KEY:
            raise HTTPException(409, "完整账目功能的当前Prompt不存在或不属于本功能")
    spec, config = authorized_feature(db, actor, FEATURE_KEY)
    provider = check_configuration(db, actor, spec, config, preview)
    if provider.kind not in {"chat", "responses"}:
        raise HTTPException(409, "完整账目任务需要获准处理患者资料的文本模型")
    prompt, version = active_prompt(db, spec, config)
    return spec, config, provider, prompt, version


def _validation(config):
    return {
        "status": config.validation_status,
        "note": config.validation_note,
        "validated_by": config.validated_by,
        "validated_at": str(config.validated_at) if config.validated_at else None,
        "feature_revision": config.revision,
    }


def recheck(db, run, *, expected_epoch=None):
    from app.ai.runtime import provider_snapshot

    # Billing Gate and actual actor precede source or artifact locks.
    actor = current_actor(db, db.get(User, run.requested_by), expected=expected_epoch)
    if actor.token_invalid_before is not None and actor.token_invalid_before >= run.create_time:
        raise HTTPException(403, "任务创建后的登录授权已失效，请重新核对完整账目")
    snapshot, _, _, _ = load_snapshot(db, run)
    if sources.utcnow() - run.create_time > datetime.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS):
        raise AIExecutionError("TASK_EXPIRED", "任务等待时间过长，请核对当前完整账目后重新提交")
    spec, config, provider, prompt, version = _configuration(db, actor, bool(run.preview))
    if snapshot["catalog_version"] != CATALOG_VERSION or snapshot["provider_snapshot"] != provider_snapshot(provider) or snapshot["feature_validation"] != _validation(config):
        raise HTTPException(409, "完整账目任务的目录、模型或验证配置已改变")
    if run.prompt_version != version or snapshot["task_prompt"] != prompt:
        raise HTTPException(409, "完整账目任务Prompt已改变，请重新创建任务")
    expanded = expand_context(db, snapshot["payload"]["context"], user=actor, current=True)
    return spec, provider, {**snapshot, "payload": {**snapshot["payload"], "context": expanded}}, actor_epoch(actor)


def _create_charge_run(db, user, req):
    from app.ai.runtime import _check_run_storage_json, provider_snapshot

    if req.feature_key != FEATURE_KEY:
        raise HTTPException(422, "本任务仅接受完整账目功能")
    selection(req.input)
    actor = current_actor(db, user)
    epoch = actor_epoch(actor)
    spec, config, provider, prompt, version = _configuration(db, actor, req.preview, writing=True)
    bundle = charge_context(db, actor, req.patient_id, req.encounter_ref, req.input)
    clock = sources.utcnow()
    start = datetime.datetime.combine(clock.date(), datetime.time.min)
    # COUNT must be a current locking read, including after an older RR snapshot.
    used = db.query(func.count(AIRun.run_id)).filter(AIRun.feature_key == FEATURE_KEY, AIRun.requested_by == actor.user_id, AIRun.create_time >= start).with_for_update(read=True).scalar()
    if used >= config.daily_limit:
        raise HTTPException(429, "该功能今日调用额度已用完")
    metadata = {
        **context_metadata(bundle),
        "feature_revision": config.revision,
        "validation_status": config.validation_status,
        "tool_fingerprint": digest({}),
        "instructions_digest": hashlib.sha256(c.utf8(CHARGE_RECONCILIATION_SYSTEM_PROMPT + "\n\n" + prompt)).hexdigest(),
        "model_version": provider.model,
    }
    snapshot = {
        "catalog_version": CATALOG_VERSION,
        "system_prompt": CHARGE_RECONCILIATION_SYSTEM_PROMPT,
        "task_prompt": prompt,
        "payload": {"input": req.input, "context": bundle.data, "tools": {}, "evidence": bundle.evidence},
        "provider_snapshot": provider_snapshot(provider),
        "feature_validation": _validation(config),
    }
    serialized = {"input_json": c.canonical_json(snapshot), "evidence_json": c.canonical_json(bundle.evidence), "context_metadata_json": c.canonical_json(metadata)}
    _check_run_storage_json(serialized)
    run = AIRun(
        feature_key=FEATURE_KEY,
        provider_id=provider.provider_id,
        provider_revision=provider.revision,
        prompt_version=version,
        prompt_hash=digest([CHARGE_RECONCILIATION_SYSTEM_PROMPT, prompt]),
        context_digest=digest(bundle.data),
        patient_id=req.patient_id,
        encounter_ref=req.encounter_ref,
        requested_by=actor.user_id,
        preview=int(req.preview),
        status="queued",
        create_time=clock,
        **serialized,
    )
    db.add(run)
    db.flush()
    stage_anchor(db, run)
    audit(db, actor.user_id, "run.create", run.run_id, {"feature_key": FEATURE_KEY, "preview": req.preview})
    expected = acceptance_state(db, run, "run.create")
    expected["run"] = {key: getattr(run, key) for key in WRITE_FIELDS}
    artifact = db.get(AIChargeRunArtifact, run.run_id)
    expected["artifact"] = {key: getattr(artifact, key) for key in ARTIFACT_FIELDS}
    db.flush()
    _verify_write(db, run, expected)
    recheck(db, run, expected_epoch=epoch)
    db.commit()
    return run


def create_charge_run(db, user, req):
    try:
        return _create_charge_run(db, user, req)
    except Exception:
        db.rollback()
        raise


def authorize_charge_run(db, user, run):
    from app.ai.runtime import authorized_feature

    actor = current_actor(db, user)
    if actor.user_role != "super_admin" and run.requested_by != actor.user_id:
        raise HTTPException(403, "不能访问其他用户的 AI 任务")
    snapshot, binding, metadata, evidence = load_snapshot(db, run)
    authorized_feature(db, actor, FEATURE_KEY)
    expand_context(db, snapshot["payload"]["context"], user=actor, current=actor.user_role != "super_admin")
    return snapshot, binding, metadata, evidence
