"""Durable seed-bound leaflet tasks, exact receipts, no business/clinical writes."""

import datetime
import time
import uuid
from dataclasses import replace
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import func

from app.ai import document_evidence_contract as d
from app.ai import drug_label_sources as sources
from app.ai import drug_label_storage as storage
from app.ai.catalog import CATALOG_VERSION
from app.ai.context import context_metadata
from app.ai.drug_label_context import prepare_context
from app.ai.drug_label_context_contract import expand_public_context, selection
from app.ai.drug_label_draft import MAX_JSON_BYTES, SYSTEM_PROMPT
from app.ai.drug_label_gateway import DrugLabelGatewayError, build_request, generate_drug_label
from app.ai.drug_label_run_contract import ACCEPT_ACTION, CREATE_ACTION, USAGE_ACTION, DrugLabelUsageReceipt
from app.ai.inventory_write_guard import current_inventory_rows
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.ai.native_acceptance import AUDIT_FIELDS, RUN_FIELDS
from app.config import settings
from app.models import User

FEATURE_KEY = storage.FEATURE_KEY
WRITE_FIELDS = (*RUN_FIELDS, "input_tokens", "output_tokens", "error_code", "error_message", "latency_ms")
CLOCK_FIELDS = ("create_time", "start_time", "finish_time")


def _second(value):
    # Existing AIRun DATETIME(0) is explicit; do not compare a lost fractional
    # clock with Artifact UTC6 or silently claim both have equal precision.
    return value.replace(microsecond=0)


def _state(run, artifact=None, audits=()):
    return {
        "run": {key: getattr(run, key) for key in (*WRITE_FIELDS, *CLOCK_FIELDS)},
        "artifact": {column.name: getattr(artifact, column.name) for column in artifact.__table__.columns} if artifact is not None else None,
        "audits": [(row, {name: getattr(row, name) for name in AUDIT_FIELDS}) for row in audits],
    }


def _verify(db, run, expected):
    actual = db.query(*(getattr(AIRun, key) for key in (*WRITE_FIELDS, *CLOCK_FIELDS))).filter_by(run_id=run.run_id).with_for_update().one_or_none()
    if actual is None or dict(actual._mapping) != expected["run"]:
        raise HTTPException(409, "说明书任务实际22字段或明确秒级时钟发生变化")
    if expected["artifact"] is not None:
        from app.ai.drug_label_run_models import AIDrugLabelRunArtifact

        artifact = db.query(*AIDrugLabelRunArtifact.__table__.columns).filter_by(run_id=run.run_id).with_for_update().one_or_none()
        if artifact is None or dict(artifact._mapping) != expected["artifact"]:
            raise HTTPException(409, "说明书完整任务或结果Artifact实际回读不符")
    for row, values in expected["audits"]:
        actual_event = db.query(*(getattr(AIAuditEvent, key) for key in AUDIT_FIELDS)).filter_by(event_id=row.event_id).with_for_update(read=True).one_or_none()
        if row.event_id is None or actual_event is None or dict(actual_event._mapping) != values:
            raise HTTPException(409, "说明书本次精确审计实际回读不符")


def _stage_audit(db, stored, actor_id, action, detail):
    run = stored.run if stored is not None else None
    event = AIAuditEvent(actor_id=actor_id, action=action, target=run.run_id, detail_json=detail)
    db.add(event)
    expected = _state(run, stored.artifact, (event,))
    db.flush()
    _verify(db, run, expected)
    return event, expected


def _configuration(db, actor, preview, *, writing=False):
    from app.ai.runtime import authorized_feature, check_configuration

    config = current_inventory_rows(db.query(AIFeatureConfig).filter_by(feature_key=FEATURE_KEY), shared=not writing).one_or_none()
    if config is None or config.provider_id is None:
        raise HTTPException(409, "说明书功能当前配置不存在")
    provider = current_inventory_rows(db.query(AIProvider).filter_by(provider_id=config.provider_id), shared=True).one_or_none()
    if provider is None:
        raise HTTPException(409, "说明书当前模型已删除")
    spec, actual = authorized_feature(db, actor, FEATURE_KEY)
    checked = check_configuration(db, actor, spec, actual, preview)
    if checked is not provider or provider.kind not in {"chat", "responses"} or provider.allows_patient_data != 1:
        raise HTTPException(409, "说明书原文须由明确允许患者原文的文字模型处理")
    if config.active_prompt_id:
        row = current_inventory_rows(db.query(AIPromptVersion).filter_by(prompt_id=config.active_prompt_id), shared=True).one_or_none()
        if row is None or row.feature_key != FEATURE_KEY:
            raise HTTPException(409, "说明书当前Prompt已删除或改绑")
        prompt, version = row.task_prompt, row.version
    else:
        prompt, version = spec.task_prompt, 0
    return spec, config, provider, prompt, version


def _validation(config):
    return {
        "status": config.validation_status,
        "note": config.validation_note,
        "validated_by": config.validated_by,
        "validated_at": str(config.validated_at) if config.validated_at is not None else None,
        "feature_revision": config.revision,
    }


def current_daily_count(db, actor_id, now):
    start = datetime.datetime.combine(now.date(), datetime.time.min)
    # All 73 creators already hold Gate. The existing feature-time index avoids
    # an unrelated feature's locked Run while still counting old/broken 73 rows.
    return (
        db.query(func.count(AIRun.run_id))
        .with_hint(AIRun, "FORCE INDEX (idx_ai_run_feature_time)", dialect_name="mysql")
        .filter(AIRun.feature_key == FEATURE_KEY, AIRun.requested_by == actor_id, AIRun.create_time >= start)
        .with_for_update(read=True)
        .scalar()
    )


def recheck(db, stored, *, expected_epoch=None):
    from app.ai.runtime import provider_snapshot

    actor = db.get(User, stored.run.requested_by)  # already current SHARE in source-first load_snapshot
    if actor is None or actor.user_role not in sources.c.SOURCE_ROLES:
        raise HTTPException(403, "任务原账户当前已无说明书权限")
    epoch = (actor.user_role, actor.token_invalid_before)
    if expected_epoch is not None and expected_epoch != epoch or actor.token_invalid_before is not None and actor.token_invalid_before >= stored.artifact.created_at:
        raise HTTPException(403, "任务创建后的角色或登录授权已变化")
    current = storage.authorize_drug_label_run(db, actor, stored.run)
    if sources.utcnow() - current.artifact.created_at > datetime.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS):
        raise HTTPException(409, "任务等待过久，请明确重读当前说明书后重新提交")
    spec, config, provider, prompt, version = _configuration(db, actor, bool(current.run.preview))
    if (
        current.snapshot["catalog_version"] != CATALOG_VERSION
        or current.snapshot["provider_snapshot"] != provider_snapshot(provider)
        or current.snapshot["feature_validation"] != _validation(config)
        or current.run.prompt_version != version
        or current.snapshot["task_prompt"] != prompt
    ):
        raise HTTPException(409, "说明书模型、Prompt、验证或目录配置已改变")
    return current, provider, epoch


def create_drug_label_run(db, user, req):
    from app.ai.runtime import _check_run_storage_json, provider_snapshot

    try:
        if req.feature_key != FEATURE_KEY or req.patient_id is not None or req.encounter_ref is not None:
            raise HTTPException(422, "本任务只绑定明确说明书来源，不接受患者、就诊或其它功能")
        selection(req.input)
        bundle, record, public, seed = prepare_context(db, user, req.input)
        actor = sources.current_actor(db, user)
        epoch = (actor.user_role, actor.token_invalid_before)
        spec, config, provider, prompt, version = _configuration(db, actor, req.preview, writing=True)
        if current_daily_count(db, actor.user_id, sources.utcnow()) >= config.daily_limit:
            raise HTTPException(429, "该功能今日调用额度已用完")
        expanded = {"input": req.input, "context": expand_public_context(bundle.data, public), "tools": {}, "evidence": bundle.evidence}
        build_request(provider, prompt, expanded)  # actual complete wire bound BEFORE persistence
        metadata = {
            **context_metadata(bundle),
            "feature_revision": config.revision,
            "validation_status": config.validation_status,
            "tool_fingerprint": d.digest({}),
            "instructions_digest": storage.instructions_digest(SYSTEM_PROMPT, prompt),
            "model_version": provider.model,
        }
        snapshot = {
            "catalog_version": CATALOG_VERSION,
            "system_prompt": SYSTEM_PROMPT,
            "task_prompt": prompt,
            "payload": {"input": req.input, "context": bundle.data, "tools": {}, "evidence": bundle.evidence},
            "provider_snapshot": provider_snapshot(provider),
            "feature_validation": _validation(config),
        }
        serialized = {"input_json": d.canonical_json(snapshot), "evidence_json": d.canonical_json(bundle.evidence), "context_metadata_json": d.canonical_json(metadata)}
        _check_run_storage_json(serialized)
        run = AIRun(
            feature_key=FEATURE_KEY,
            provider_id=provider.provider_id,
            provider_revision=provider.revision,
            prompt_version=version,
            prompt_hash=d.digest([SYSTEM_PROMPT, prompt]),
            context_digest=d.digest(bundle.data),
            requested_by=actor.user_id,
            preview=int(req.preview),
            status="queued",
            create_time=_second(sources.utcnow()),
            **serialized,
        )
        db.add(run)
        db.flush()
        binding = storage._task(run)[1]
        audit = AIAuditEvent(actor_id=actor.user_id, action=CREATE_ACTION, target=run.run_id, detail_json=storage.create_audit_detail(run, binding))
        db.add(audit)
        expected = _state(run, audits=(audit,))
        db.flush()
        _verify(db, run, expected)
        stored = storage.stage_artifact(db, run, mapping_seed=seed, create_event_id=audit.event_id)
        staged = _state(run, stored.artifact, (audit,))
        _verify(db, run, staged)
        recheck(db, stored, expected_epoch=epoch)
        db.commit()
        return run
    except Exception:
        db.rollback()
        raise


def _terminal(db, stored, *, inputs, outputs, attempted, result, started):
    run, artifact = stored.run, stored.artifact
    if artifact.receipt_event_id is not None or artifact.result_json is not None:
        raise HTTPException(409, "本任务已有实际终态回执，未重复写入")
    raw = d.canonical_json(result) if result is not None else None
    result_hash = storage.text_hash(raw, MAX_JSON_BYTES) if raw is not None else None
    run.input_tokens = inputs if inputs is not None else 0
    run.output_tokens = outputs if outputs is not None else 0
    run.latency_ms = max(0, int((time.monotonic() - started) * 1000))
    run.finish_time = _second(sources.utcnow())
    receipt = DrugLabelUsageReceipt(
        schema_version="drug_label_usage_receipt_v1",
        run_id=run.run_id,
        source_binding_hash=artifact.source_binding_hash,
        input_hash=artifact.input_hash,
        evidence_hash=artifact.evidence_hash,
        metadata_hash=artifact.metadata_hash,
        lease_token=run.lease_token,
        model_call_attempted=attempted,
        input_tokens=inputs,
        output_tokens=outputs,
        result_hash=result_hash,
        status=run.status,
    )
    usage, usage_state = _stage_audit(db, stored, run.requested_by, USAGE_ACTION, d.canonical_json(receipt))
    accept = None
    if result is not None:
        accepted_at = sources.utcnow()
        planned = replace(
            stored, artifact=SimpleNamespace(result_hash=result_hash, result_bytes=len(d.utf8(raw)), accepted_at=accepted_at, accepted_lease=run.lease_token, receipt_event_id=usage.event_id)
        )
        accept, _ = _stage_audit(db, stored, run.requested_by, ACCEPT_ACTION, storage.accept_audit_detail(planned))
        artifact.result_json, artifact.result_hash, artifact.result_bytes = raw, result_hash, len(d.utf8(raw))
        artifact.accepted_at, artifact.accepted_lease, artifact.accept_event_id = accepted_at, run.lease_token, accept.event_id
        run.result_json = d.canonical_json(storage.result_pointer(run.run_id, result_hash, artifact.result_bytes))
    else:
        run.result_json = "{}"
    artifact.receipt_event_id = usage.event_id
    expected = _state(run, artifact, (usage,) if accept is None else (usage, accept))
    db.flush()
    _verify(db, run, expected)
    verified = storage.load_snapshot(db, run, writing=True)
    if storage.verify_artifact_result(db, verified) != result:
        raise HTTPException(409, "实际完整结果与本次接受不符")
    _verify(db, run, expected)
    return expected


def claim_drug_label_run(db, run_id):
    """Trusted worker entry; source/gate before Run/private text, no model call."""
    try:
        stored = storage.load_snapshot(db, run_id, writing=True)
        run = stored.run
        if run.status != "queued":
            db.rollback()
            return None
        if (
            any(getattr(run, field) is not None for field in ("lease_token", "start_time", "finish_time", "latency_ms", "error_code", "error_message"))
            or run.result_json != "{}"
            or run.input_tokens != 0
            or run.output_tokens != 0
        ):
            raise HTTPException(409, "排队任务已有执行痕迹")
        try:
            recheck(db, stored)
        except (HTTPException, DrugLabelGatewayError):
            run.status, run.error_code, run.error_message = "failed", "TASK_NO_LONGER_AUTHORIZED", "当前来源或配置已改变，模型未调用"
            _terminal(db, stored, inputs=0, outputs=0, attempted=False, result=None, started=time.monotonic())
            db.commit()
            return None
        lease = str(uuid.uuid4())
        run.status, run.lease_token, run.start_time = "running", lease, _second(sources.utcnow())
        event, expected = _stage_audit(db, stored, run.requested_by, "run.drug_label.claim", d.canonical_json({"lease_token": lease}))
        recheck(db, storage.load_snapshot(db, run, writing=True))
        _verify(db, run, expected)
        db.commit()
        return lease
    except Exception:
        db.rollback()
        raise


def cancel_drug_label_run(db, user, run_id, *, frozen_audit=False):
    try:
        stored = storage.authorize_drug_label_run(db, user, run_id, frozen_audit=frozen_audit, writing=True)
        run = stored.run
        if run.status not in {"queued", "running"}:
            raise HTTPException(409, "任务已结束")
        queued = run.status == "queued"
        if queued and (
            any(getattr(run, field) is not None for field in ("lease_token", "start_time", "finish_time", "latency_ms", "error_code", "error_message"))
            or run.result_json != "{}"
            or run.input_tokens != 0
            or run.output_tokens != 0
        ):
            raise HTTPException(409, "任务已有执行痕迹，不能声明未调用模型")
        run.status, run.finish_time = "cancelled", _second(sources.utcnow())
        if queued:
            _terminal(db, stored, inputs=0, outputs=0, attempted=False, result=None, started=time.monotonic())
        actor = sources.current_actor(db, user)
        event, expected = _stage_audit(db, stored, actor.user_id, "run.drug_label.cancel", d.canonical_json({"queued_before_claim": queued}))
        storage.authorize_drug_label_run(db, actor, run, frozen_audit=frozen_audit, writing=True)
        _verify(db, run, expected)
        db.commit()
    except Exception:
        db.rollback()
        raise


async def execute_drug_label_claimed(run_id, lease, *, transport=None):
    from app import database

    started, result, error, epoch = time.monotonic(), None, None, None
    inputs, outputs, attempted = 0, 0, False
    try:
        with database.SessionLocal() as db:
            stored = storage.load_snapshot(db, run_id, writing=True)
            if stored.run.lease_token != lease or stored.run.status not in {"running", "cancelled"} or stored.artifact.receipt_event_id is not None:
                return
            cancelled = stored.run.status == "cancelled"
            if not cancelled:
                stored, provider, epoch = recheck(db, stored)
                payload = {**stored.snapshot["payload"], "context": expand_public_context(stored.snapshot["payload"]["context"], stored.public_source)}
                prompt = stored.snapshot["task_prompt"]
                db.expunge(provider)
        if not cancelled:
            attempted, inputs, outputs = None, None, None
            result, inputs, outputs = await generate_drug_label(provider, prompt, payload, transport=transport)
            attempted = True
    except DrugLabelGatewayError as exc:
        attempted = exc.model_call_attempted
        inputs, outputs = (0, 0) if attempted is False else (exc.input_tokens, exc.output_tokens)
        error = (exc.code, exc.message)
    except HTTPException:
        error = ("TASK_NO_LONGER_AUTHORIZED", "当前来源、账户或配置已改变，未接受字段草稿")
    except Exception:
        error = ("TASK_EXECUTION_ERROR", "完整说明书任务处理失败，请核对实际用量")
    with database.SessionLocal() as db:
        try:
            stored = storage.load_snapshot(db, run_id, writing=True)
            run = stored.run
            if run.lease_token != lease or run.status not in {"running", "cancelled"} or stored.artifact.receipt_event_id is not None:
                return
            if run.status != "cancelled" and error is None:
                try:
                    stored, _, _ = recheck(db, stored, expected_epoch=epoch)
                except (HTTPException, DrugLabelGatewayError):
                    error = ("TASK_NO_LONGER_AUTHORIZED", "调用后来源、身份或配置已改变；保留真实用量但未接受草稿")
            if run.status != "cancelled":
                run.status = "failed" if error else "succeeded"
                if error:
                    run.error_code, run.error_message = error
            accepted = result.model_dump(mode="json") if run.status == "succeeded" and result is not None else None
            expected = _terminal(db, stored, inputs=inputs, outputs=outputs, attempted=attempted, result=accepted, started=started)
            if accepted is not None:
                recheck(db, storage.load_snapshot(db, run, writing=True), expected_epoch=epoch)
                _verify(db, run, expected)
            db.commit()
        except Exception:
            db.rollback()
            try:
                failed = storage.load_snapshot(db, run_id, writing=True)
                if failed.run.lease_token != lease or failed.run.status not in {"running", "cancelled"} or failed.artifact.receipt_event_id is not None:
                    return
                failed.run.status = "cancelled" if failed.run.status == "cancelled" else "failed"
                failed.run.error_code, failed.run.error_message = "RESULT_STORAGE_ERROR", "完整结果和具体接受审计未能原子保存，草稿未接受"
                _terminal(db, failed, inputs=inputs, outputs=outputs, attempted=attempted, result=None, started=started)
                db.commit()
            except Exception:
                db.rollback()
                raise


def guard_drug_label_run_id(db, user, run_id, *, frozen_audit=False):
    identifier = storage._opaque_run_id(run_id)
    hint = storage._locator(db, identifier)
    if hint is not None:
        storage.load_snapshot(db, sources._key(identifier), user=user, frozen_audit=frozen_audit)
        return True
    # Only a nonlocking feature locator follows an absent opaque Artifact. Do
    # not lock/read a generic or Doc Run before its own domain authorization.
    feature = db.query(AIRun.feature_key).filter_by(run_id=identifier).one_or_none()
    if feature is not None and feature[0] == FEATURE_KEY:
        raise HTTPException(409, "旧说明书任务缺少完整Artifact，不能降级读取")
    return False


def describe_drug_label_run(db, user, run, include_result=True, *, frozen_audit=False):
    stored = storage.authorize_drug_label_run(db, user, run, frozen_audit=frozen_audit)
    actual = stored.run
    result = storage.verify_artifact_result(db, stored)
    receipt = storage.usage_receipt(db, stored)
    data = {
        key: getattr(actual, key)
        for key in (
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
            "latency_ms",
            "create_time",
            "start_time",
            "finish_time",
        )
    }
    data.update(
        feature_name="药品说明书逐字字段草稿",
        requires_human_review=True,
        context_metadata=stored.metadata,
        drug_label_source_binding_id=stored.artifact.source_binding_id,
        usage_receipt=receipt.model_dump(mode="json") if receipt is not None else None,
        input_tokens=receipt.input_tokens if receipt is not None else None,
        output_tokens=receipt.output_tokens if receipt is not None else None,
        usage_receipt_status="recorded" if receipt is not None else "pending",
    )
    if include_result:
        data.update(
            result=result,
            evidence=stored.snapshot["payload"]["evidence"],
            drug_label_artifact=storage.artifact_view(stored),
            drug_label_findings={
                "context": stored.snapshot["payload"]["context"],
                "input": stored.snapshot["payload"]["input"],
                "drug_label_binding": stored.binding.model_dump(mode="json"),
                "drug_label_source": stored.public_source.model_dump(mode="json"),
                "drug_label_source_record": stored.source_record.model_dump(mode="json"),
                "frozen_task_view": True,
                "can_record": False,
                "can_review": False,
                "can_revoke": False,
            },
        )
    # Validate the ACTUAL whole wrapper, not just each individually legal blob.
    serializable = {key: d.utc_text(value) if isinstance(value, datetime.datetime) else value for key, value in data.items()}
    if len(d.utf8(d.canonical_json(serializable))) > MAX_JSON_BYTES:
        raise HTTPException(409, "完整任务详情组合超过8MiB；未截断或省略依据")
    return data
