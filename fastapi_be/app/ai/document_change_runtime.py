"""Dedicated finite document comparison queue/worker; common dispatch stays separate.

Creation is a standalone clean unit of work. Current author X precedes Source
parents, configuration and new Run writes, serializing that author's quota. A
worker releases every SQL transaction before awaiting a provider. Accepted output
rechecks Source -> Run -> Artifact; technical receipts never reacquire Source.
"""

import asyncio
import datetime as dt
import time
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.ai import document_change_contract as c
from app.ai import document_change_gateway as gateway
from app.ai import document_change_result_storage as results
from app.ai import document_change_sources as sources
from app.ai import document_change_storage as storage
from app.ai import document_evidence_sources as originals
from app.ai.catalog import CATALOG_VERSION
from app.ai.context import context_metadata
from app.ai.document_change_context import prepare_context, selection
from app.ai.document_change_draft import SYSTEM_PROMPT
from app.ai.document_change_run_models import AIDocumentChangeRunArtifact
from app.ai.gateway import AIExecutionError
from app.ai.governance import active_prompt, digest, encode_json
from app.ai.models import AIFeatureConfig, AIProvider, AIRun
from app.config import settings
from app.models import User

FEATURE_KEY = storage.FEATURE_KEY
ZERO = {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}


def _configuration(db, actor, preview):
    from app.ai.runtime import authorized_feature, check_configuration

    with db.no_autoflush:
        config = db.query(AIFeatureConfig).filter_by(feature_key=FEATURE_KEY).populate_existing().with_for_update(read=True).one_or_none()
        if config is not None and config.provider_id is not None:
            db.query(AIProvider).filter_by(provider_id=config.provider_id).populate_existing().with_for_update(read=True).one_or_none()
    spec, config = authorized_feature(db, actor, FEATURE_KEY)
    provider = check_configuration(db, actor, spec, config, preview)
    if provider.kind not in {"chat", "responses"} or provider.allows_patient_data != 1:
        raise HTTPException(409, "版本原文仅由明确获准处理原件的文字服务接收")
    if not preview and (config.validation_status != "validated" or "super_admin" not in c.e.parse_json(config.allowed_roles_json)):
        raise HTTPException(409, "须明确启用并完成当前版本核对验证；超级管理员可显式预览")
    if config.active_prompt_id is None:
        prompt, version = spec.task_prompt, 0
    else:
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


def create_change_run(db, user, req):
    """Queue only a complete current Scope, with short immutable Run JSON."""
    from app.ai.runtime import _check_run_storage_json, provider_snapshot

    if req.feature_key != FEATURE_KEY or req.patient_id is not None or req.encounter_ref is not None or type(req.preview) is not bool:
        raise HTTPException(422, "版本核对仅接受本功能和独立有限范围原件，不接受患者或就诊引用")
    selection(req.input)
    # Do not discard a caller's writes. A prior read-only authentication RR
    # snapshot must not hide a committed earlier quota entry after waiting X.
    if db.new or db.dirty or db.deleted:
        raise HTTPException(409, "创建版本任务须使用无待写入数据的独立事务")
    epoch = originals._epoch(user)
    db.rollback()
    try:
        with db.no_autoflush:
            actor = db.query(User).filter_by(user_id=epoch[0]).populate_existing().with_for_update().one_or_none()
        if actor is None:
            raise HTTPException(403, "当前超级管理员已失效")
        actor = originals.current_super(db, actor, expected=epoch)
        bundle, _, source = prepare_context(db, actor, req.input)
        _, config, provider, prompt, version = _configuration(db, actor, req.preview)
        snapshot = {
            "catalog_version": CATALOG_VERSION,
            "system_prompt": SYSTEM_PROMPT,
            "task_prompt": prompt,
            "payload": {"input": req.input, "context": bundle.data, "tools": {}, "evidence": bundle.evidence},
            "provider_snapshot": provider_snapshot(provider),
            "feature_validation": _validation(config),
        }
        gateway.build_request(provider, prompt, snapshot["payload"], source)
        now = sources.utcnow()
        start = dt.datetime.combine(now.date(), dt.time.min)
        if type(config.daily_limit) is not int or config.daily_limit < 1:
            raise HTTPException(409, "当前任务配额无效")
        if db.query(AIRun).filter(AIRun.feature_key == FEATURE_KEY, AIRun.requested_by == actor.user_id, AIRun.create_time >= start).count() >= config.daily_limit:
            raise HTTPException(429, "该功能今日调用额度已用完")
        metadata = {
            **context_metadata(bundle),
            "feature_revision": config.revision,
            "validation_status": config.validation_status,
            "tool_fingerprint": digest({}),
            "instructions_digest": c.e.bytes_hash(SYSTEM_PROMPT + "\n\n" + prompt),
            "model_version": provider.model,
        }
        serialized = {"input_json": encode_json(snapshot), "evidence_json": encode_json(bundle.evidence), "context_metadata_json": encode_json(metadata)}
        _check_run_storage_json(serialized)
        run = AIRun(
            run_id=str(uuid.uuid4()),
            feature_key=FEATURE_KEY,
            provider_id=provider.provider_id,
            provider_revision=provider.revision,
            prompt_version=version,
            prompt_hash=digest([SYSTEM_PROMPT, prompt]),
            context_digest=digest(bundle.data),
            patient_id=None,
            encounter_ref=None,
            requested_by=actor.user_id,
            preview=int(req.preview),
            status="queued",
            create_time=now.replace(microsecond=0),
            **serialized,
        )
        db.add(run)
        db.flush()
        artifact = storage.stage_artifact(db, actor, run)
        expected_run = {name: getattr(run, name) for name in results.WRITE_FIELDS}
        expected_artifact = {column.name: getattr(artifact, column.name) for column in AIDocumentChangeRunArtifact.__table__.columns}
        event = results._event(db, actor.user_id, "run.create", run, {"feature_key": FEATURE_KEY, "preview": req.preview, "scope_id": artifact.scope_id, "source_digest": artifact.source_digest}, now)
        results._post_write(db, run, expected_run, expected_artifact, (event.event_id, results._audit_value(event)))
        recheck(db, run, expected_epoch=epoch)
        db.commit()
        return run
    except AIExecutionError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    except (SQLAlchemyError, ValueError, UnicodeError) as exc:
        db.rollback()
        raise HTTPException(409, "完整任务、来源或创建审计发生冲突，整笔未接受") from exc
    except Exception:
        db.rollback()
        raise


def recheck(db, run, *, expected_epoch=None):
    with db.no_autoflush:
        actor = db.query(User).filter_by(user_id=run.requested_by).populate_existing().with_for_update(read=True).one_or_none()
    if actor is None:
        raise HTTPException(403, "当前原任务用户已失效")
    actor = originals.current_super(db, actor, expected=expected_epoch)
    snapshot, metadata, evidence, binding, artifact, source = storage.load_snapshot(db, run, user=actor, current=True, execution=True)
    if sources.utcnow() - artifact.recorded_at > dt.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS):
        raise AIExecutionError("TASK_EXPIRED", "任务等待时间过长，请重新核对完整有限范围")
    _, config, provider, _, _ = _configuration(db, actor, bool(run.preview))
    # load_snapshot already compares all frozen12/5 fields and both Prompt
    # digests to actual configuration; no current value rewrites old metadata.
    if config.revision != metadata["feature_revision"]:
        raise HTTPException(409, "当前模型或功能配置已改变")
    return provider, snapshot, source, originals._epoch(actor)


def _receipt(inputs, outputs, attempted):
    if attempted is False:
        return dict(ZERO)
    return {"input_tokens": inputs, "output_tokens": outputs, "complete": inputs is not None and outputs is not None, "model_call_attempted": attempted}


def _fresh_run(db, run_id, lease, *, locking=False):
    with db.no_autoflush:
        query = db.query(AIRun).filter(AIRun.run_id == run_id, AIRun.feature_key == FEATURE_KEY, AIRun.lease_token == lease, AIRun.status.in_(["running", "cancelled"])).populate_existing()
        if locking:
            # Trusted lease receipt only: no Source or task body is returned.
            return query.with_for_update().one_or_none()
        header = db.query(AIRun.status, AIRun.latency_ms).filter(AIRun.run_id == run_id, AIRun.lease_token == lease).one_or_none()
        if header is None or header.latency_ms is not None:
            return None
        if header.status == "cancelled":
            return query.one_or_none()
        identity = storage.locate_artifact(db, run_id)
        if identity is None:
            raise HTTPException(409, "版本任务缺少完整实际Source身份")
        actor = db.query(User).filter_by(user_id=identity[2]).populate_existing().with_for_update(read=True).one_or_none()
        if actor is None:
            raise HTTPException(403, "当前原任务用户已失效")
        storage.authorize_run_id(db, actor, run_id, current=True)
        return query.one_or_none()


def _terminal(db, run_id, lease, receipt, elapsed, error):
    run = _fresh_run(db, run_id, lease, locking=True)
    if run is None or run.latency_ms is not None:
        return
    status = "cancelled" if run.status == "cancelled" else "failed"
    code, message = error or (None, None)
    storage.stage_terminal(db, run, lease, status=status, usage=receipt, latency_ms=elapsed, error_code=code, error_message=message)
    db.commit()


async def execute_change_claimed(run_id, lease, *, transport=None):
    """Trusted durable claim execution; no transaction is kept across await."""
    from app import database

    started, epoch, result, error = time.monotonic(), None, None, None
    receipt, interrupted = dict(ZERO), None
    try:
        with database.SessionLocal() as db:
            run = _fresh_run(db, run_id, lease)
            if run is None or run.latency_ms is not None:
                return
            expected_header = {name: getattr(run, name) for name in results.IMMUTABLE_FIELDS}
            initially_cancelled = run.status == "cancelled"
            if not initially_cancelled:
                provider, snapshot, source, epoch = recheck(db, run)
                gateway.build_request(provider, snapshot["task_prompt"], snapshot["payload"], source)
                db.expunge(provider)
        # A cancellation committed while current parents were being checked must
        # be observed in a fresh RR transaction before attempting model HTTP.
        with database.SessionLocal() as db:
            current = _fresh_run(db, run_id, lease)
            if current is None or current.latency_ms is not None:
                return
            if any(getattr(current, name) != value for name, value in expected_header.items()):
                raise HTTPException(409, "实际任务不可变字段已改变")
            if initially_cancelled and current.status != "cancelled":
                raise HTTPException(409, "取消状态不能回退为执行")
            cancelled_before_call = current.status == "cancelled"
        if not cancelled_before_call:
            receipt = _receipt(None, None, True)
            result, inputs, outputs = await gateway.generate_document_change(provider, snapshot["task_prompt"], snapshot["payload"], source, transport=transport)
            receipt = _receipt(inputs, outputs, True)
    except AIExecutionError as exc:
        receipt = _receipt(exc.input_tokens, exc.output_tokens, getattr(exc, "model_call_attempted", receipt["model_call_attempted"]))
        error = exc.code, exc.message
    except HTTPException:
        error = "TASK_NO_LONGER_AUTHORIZED", "当前权限、完整原文或配置已改变，未接收问题正文"
    except asyncio.CancelledError as exc:
        receipt = _receipt(getattr(exc, "input_tokens", None), getattr(exc, "output_tokens", None), getattr(exc, "model_call_attempted", receipt["model_call_attempted"]))
        error, interrupted = ("WORKER_INTERRUPTED", "工作进程中断，未接收问题正文；已收到用量如实保留"), exc
    except Exception:
        error = "TASK_EXECUTION_ERROR", "版本核对执行未能完成，未接收问题正文"
    elapsed = int((time.monotonic() - started) * 1000)
    if result is not None and error is None:
        try:
            with database.SessionLocal() as db:
                with db.no_autoflush:
                    actor = db.query(User).filter_by(user_id=epoch[0]).populate_existing().with_for_update(read=True).one_or_none()
                if actor is None:
                    raise HTTPException(403, "原任务用户已失效")
                actor = originals.current_super(db, actor, expected=epoch)
                run = _fresh_run(db, run_id, lease)
                if run is None:
                    return
                # stage_result locks current Source before any Run/Artifact lock.
                storage.stage_result(db, actor, run, lease, result, receipt, latency_ms=elapsed)
                db.commit()
        except Exception:
            error = "RESULT_NOT_ACCEPTED", "完整结果未通过当前原件、权限、租约或原子保存核对，正文未接收"
        else:
            return
    with database.SessionLocal() as db:
        try:
            _terminal(db, run_id, lease, receipt, elapsed, error)
        except Exception:
            db.rollback()
            raise
    if interrupted is not None:
        raise interrupted


def cancel_change_run(db, user, run_id):
    """Current Super -> Run -> Artifact; never waits for live Source parents."""
    try:
        actor = originals.current_super(db, user)
        epoch = originals._epoch(actor)
        with db.no_autoflush:
            run = db.query(AIRun).filter_by(run_id=run_id, feature_key=FEATURE_KEY).populate_existing().with_for_update().one_or_none()
        if run is None:
            raise HTTPException(404, "版本核对任务不存在")
        if run.status not in {"queued", "running"}:
            raise HTTPException(409, "该任务已结束")
        queued = run.status == "queued"
        if queued:
            storage.cancel_unclaimed(db, actor, run)
        else:
            task = storage._task(run)
            results._artifact(db, run, task[1])
            if run.result_json != "{}" or run.latency_ms is not None or type(run.lease_token) is not str:
                raise HTTPException(409, "实际执行或结果状态不一致")
            run.status, run.finish_time = "cancelled", sources.utcnow().replace(microsecond=0)
        with db.no_autoflush:
            artifact = db.query(AIDocumentChangeRunArtifact).filter_by(run_id=run.run_id).populate_existing().with_for_update().one()
        expected_artifact = {column.name: getattr(artifact, column.name) for column in AIDocumentChangeRunArtifact.__table__.columns}
        expected_run = {name: getattr(run, name) for name in results.WRITE_FIELDS}
        event = results._event(db, actor.user_id, "run.cancel", run, {"feature_key": FEATURE_KEY, "receipt_pending": not queued}, sources.utcnow())
        results._post_write(db, run, expected_run, expected_artifact, (event.event_id, results._audit_value(event)))
        originals.current_super(db, actor, expected=epoch)
        db.commit()
    except (SQLAlchemyError, ValueError, UnicodeError) as exc:
        db.rollback()
        raise HTTPException(409, "实际取消状态、用量或独立审计发生冲突，整笔未接受") from exc
    except Exception:
        db.rollback()
        raise


usage_receipt = storage.usage_receipt
