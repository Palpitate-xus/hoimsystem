"""Dedicated durable literal extraction with complete original and usage receipts."""

import datetime
import time

from fastapi import HTTPException

from app.ai import document_evidence_contract as c
from app.ai import document_evidence_sources as sources
from app.ai.catalog import CATALOG_VERSION
from app.ai.context import context_metadata
from app.ai.document_extraction_context import extraction_context, verify_context
from app.ai.document_extraction_contract import EXTRACTION_SYSTEM_PROMPT, require_text_capacity
from app.ai.document_extraction_prompt import instructions_digest
from app.ai.document_extraction_storage import FEATURE_KEY, load_result, load_snapshot, stage_anchor
from app.ai.gateway import AIExecutionError, generate
from app.ai.governance import active_prompt, audit, digest, encode_json
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIProvider, AIRun, utcnow
from app.ai.native_acceptance import AUDIT_FIELDS, RUN_FIELDS, acceptance_state, verify_accepted_result
from app.config import settings
from app.models import User

ACCEPT = "run.document_extraction.accept"
FINAL_ACTIONS = (ACCEPT, "run.document_extraction.fail", "run.document_extraction.cancel")


def _configuration(db, actor, preview, *, writing=False):
    from app.ai.runtime import authorized_feature, check_configuration

    config = db.query(AIFeatureConfig).filter_by(feature_key=FEATURE_KEY).populate_existing().with_for_update(read=not writing).one_or_none()
    if config is not None and config.provider_id is not None:
        db.query(AIProvider).filter_by(provider_id=config.provider_id).populate_existing().with_for_update(read=True).one_or_none()
    spec, config = authorized_feature(db, actor, FEATURE_KEY)
    provider = check_configuration(db, actor, spec, config, preview)
    if provider.kind not in {"chat", "responses"}:
        raise HTTPException(409, "原文提取须配置获准处理原件的文字模型服务")
    return spec, config, provider


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

    actor = db.get(User, run.requested_by)
    if actor is None:
        raise HTTPException(403, "任务原用户已失效")
    actor = sources.current_super(db, actor, expected=expected_epoch)
    if actor.token_invalid_before is not None and actor.token_invalid_before >= run.create_time:
        raise HTTPException(403, "任务创建后的登录授权已失效，请重新核对原件")
    snapshot, context, _ = load_snapshot(db, run)
    if utcnow() - run.create_time > datetime.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS):
        raise AIExecutionError("TASK_EXPIRED", "任务等待时间过长，请核对当前原件后重新提交")
    spec, config, provider = _configuration(db, actor, bool(run.preview))
    prompt, version = active_prompt(db, spec, config)
    if snapshot["catalog_version"] != CATALOG_VERSION or snapshot["provider_snapshot"] != provider_snapshot(provider) or snapshot["feature_validation"] != _validation(config):
        raise HTTPException(409, "原文提取的目录、模型或验证配置已改变")
    if run.prompt_version != version or snapshot["task_prompt"] != prompt:
        raise HTTPException(409, "原文提取Prompt已改变，请重新创建任务")
    verify_context(db, actor, context.model_dump(mode="json"), current=True)
    return spec, provider, snapshot, sources._epoch(actor)


def create_document_run(db, user, req):
    from app.ai.runtime import _check_run_storage_json, provider_snapshot

    actor = sources.current_super(db, user)
    epoch = sources._epoch(actor)
    if req.patient_id is not None or req.encounter_ref is not None:
        raise HTTPException(422, "指南原文任务仅绑定独立原件，不接受患者或就诊引用")
    spec, config, provider = _configuration(db, actor, req.preview, writing=True)
    bundle = extraction_context(db, actor, req.input)
    prompt, version = active_prompt(db, spec, config)
    start = datetime.datetime.combine(utcnow().date(), datetime.time.min)
    if db.query(AIRun).filter(AIRun.feature_key == FEATURE_KEY, AIRun.requested_by == actor.user_id, AIRun.create_time >= start).count() >= config.daily_limit:
        raise HTTPException(429, "该功能今日调用额度已用完")
    metadata = {
        **context_metadata(bundle),
        "feature_revision": config.revision,
        "validation_status": config.validation_status,
        "tool_fingerprint": digest({}),
        "instructions_digest": instructions_digest(prompt),
        "model_version": provider.model,
    }
    snapshot = {
        "catalog_version": CATALOG_VERSION,
        "system_prompt": EXTRACTION_SYSTEM_PROMPT,
        "task_prompt": prompt,
        "payload": {"input": req.input, "context": bundle.data, "tools": {}, "evidence": bundle.evidence},
        "provider_snapshot": provider_snapshot(provider),
        "feature_validation": _validation(config),
    }
    serialized = {"input_json": encode_json(snapshot), "evidence_json": encode_json(bundle.evidence), "context_metadata_json": encode_json(metadata)}
    _check_run_storage_json(serialized)
    run = AIRun(
        feature_key=FEATURE_KEY,
        provider_id=provider.provider_id,
        provider_revision=provider.revision,
        prompt_version=version,
        prompt_hash=digest([EXTRACTION_SYSTEM_PROMPT, prompt]),
        context_digest=digest(bundle.data),
        patient_id=None,
        encounter_ref=None,
        requested_by=actor.user_id,
        preview=int(req.preview),
        status="queued",
        **serialized,
    )
    try:
        db.add(run)
        db.flush()
        stage_anchor(db, run)
        audit(db, actor.user_id, "run.create", run.run_id, {"feature_key": FEATURE_KEY, "preview": req.preview})
        expected = acceptance_state(db, run, "run.create")
        db.flush()
        actual = db.query(*(getattr(AIRun, key) for key in RUN_FIELDS)).filter_by(run_id=run.run_id).with_for_update().one_or_none()
        event = db.query(*(getattr(AIAuditEvent, key) for key in AUDIT_FIELDS)).filter_by(event_id=expected["event"].event_id).with_for_update(read=True).one_or_none()
        if actual is None or dict(actual._mapping) != expected["run"] or event is None or dict(event._mapping) != expected["audit"]:
            raise HTTPException(409, "原件任务实际写入与本次完整入队审计不符")
        db.refresh(run)
        recheck(db, run, expected_epoch=epoch)
        db.commit()
        return run
    except Exception:
        db.rollback()
        raise


def _receipt(inputs=None, outputs=None, sent=False):
    return {"input_tokens": inputs, "output_tokens": outputs, "complete": inputs is not None and outputs is not None, "model_call_attempted": sent}


def _final_audit(db, run, action, receipt):
    audit(
        db,
        run.requested_by,
        action,
        run.run_id,
        {
            "schema_version": "document_extraction_receipt_v1",
            "lease_token": run.lease_token,
            "usage": receipt,
            "result_hash": c.bytes_hash(run.result_json) if action == ACCEPT else None,
            "error_code": run.error_code,
        },
    )


def _account(run, receipt, started):
    # Legacy integer counters cannot represent unknown. The typed audit/API
    # receipt retains nullable actual counts; integer zero is only a placeholder.
    run.input_tokens = receipt["input_tokens"] if receipt["input_tokens"] is not None else 0
    run.output_tokens = receipt["output_tokens"] if receipt["output_tokens"] is not None else 0
    run.latency_ms = int((time.monotonic() - started) * 1000)
    run.finish_time = utcnow()


async def execute_document_claimed(run_id, lease, *, transport=None):
    from app import database

    started, error, result, epoch = time.monotonic(), None, None, None
    receipt = _receipt()
    try:
        with database.SessionLocal() as db:
            run = db.query(AIRun).filter_by(run_id=run_id, status="running", lease_token=lease).one_or_none()
            if run is None:
                return
            spec, provider, snapshot, epoch = recheck(db, run)
            db.expunge(provider)
        receipt["model_call_attempted"] = True
        result, inputs, outputs = await generate(provider, spec, snapshot["task_prompt"], snapshot["payload"], transport=transport)
        receipt = _receipt(inputs, outputs, True)
        require_text_capacity(result.model_dump(mode="json"))
    except AIExecutionError as exc:
        receipt = _receipt(exc.input_tokens, exc.output_tokens, receipt["model_call_attempted"])
        error = (exc.code, exc.message)
    except HTTPException as exc:
        error = ("TASK_NO_LONGER_AUTHORIZED", str(exc.detail))
    except (ValueError, TypeError, UnicodeError):
        error = ("DOCUMENT_RESULT_REJECTED", "完整原文草稿或结果超过存储容量或未通过核对，未截断")
    except Exception:
        error = ("TASK_EXECUTION_ERROR", "原文提取处理失败，请联系管理员核对状态")
    with database.SessionLocal() as db:
        run = db.query(AIRun).filter(AIRun.run_id == run_id, AIRun.status.in_(["running", "cancelled"]), AIRun.lease_token == lease).populate_existing().with_for_update().one_or_none()
        if run is None:
            return
        try:
            if run.status != "cancelled" and error is None:
                try:
                    recheck(db, run, expected_epoch=epoch)
                except AIExecutionError as exc:
                    error = (exc.code, exc.message)
                except HTTPException as exc:
                    error = ("TASK_NO_LONGER_AUTHORIZED", str(exc.detail))
            _account(run, receipt, started)
            if run.status == "cancelled":
                action = "run.document_extraction.cancel"
            elif error:
                run.status, (run.error_code, run.error_message) = "failed", error
                action = "run.document_extraction.fail"
            else:
                run.result_json = encode_json(result.model_dump(mode="json"))
                run.status = "succeeded"
                action = ACCEPT
            _final_audit(db, run, action, receipt)
            expected = acceptance_state(db, run, action)
            db.flush()
            if action == ACCEPT:
                verify_accepted_result(db, run, lease, expected, result.model_dump(mode="json"), result_reader=load_result)
                recheck(db, run, expected_epoch=epoch)
            db.commit()
        except Exception:
            db.rollback()
            failed = db.query(AIRun).filter_by(run_id=run_id, status="running", lease_token=lease).populate_existing().with_for_update().one_or_none()
            if failed is not None:
                failed.status = "failed"
                failed.result_json = "{}"
                failed.error_code = "RESULT_STORAGE_ERROR"
                failed.error_message = "完整原文、结果与接收审计未能原子保存，草稿未接收"
                _account(failed, receipt, started)
                _final_audit(db, failed, "run.document_extraction.fail", receipt)
                db.commit()


def usage_receipt(db, run):
    rows = db.query(AIAuditEvent).filter(AIAuditEvent.target == run.run_id, AIAuditEvent.action.in_(FINAL_ACTIONS)).populate_existing().with_for_update(read=True).all()
    if not rows:
        if run.status in {"queued", "running", "cancelled"} or run.error_code == "WORKER_INTERRUPTED":
            return _receipt(sent=None)
        raise HTTPException(409, "原文提取最终用量及接收审计缺失")
    try:
        if len(rows) != 1:
            raise ValueError("A task has exactly one terminal receipt")
        row = rows[0]
        detail = c.parse_json(row.detail_json)
        if not isinstance(detail, dict) or set(detail) != {"schema_version", "lease_token", "usage", "result_hash", "error_code"}:
            raise ValueError("Closed final receipt required")
        receipt = detail["usage"]
        if not isinstance(receipt, dict) or set(receipt) != {"input_tokens", "output_tokens", "complete", "model_call_attempted"}:
            raise ValueError("Closed actual usage required")
        for name in ("input_tokens", "output_tokens"):
            if receipt[name] is not None and (type(receipt[name]) is not int or not 0 <= receipt[name] <= 2000000):
                raise ValueError("Actual usage must be a reported nonnegative integer or unknown")
            if getattr(run, name) != (receipt[name] if receipt[name] is not None else 0):
                raise ValueError("Legacy counters differ from the actual receipt")
        if (
            type(receipt["complete"]) is not bool
            or receipt["complete"] != (receipt["input_tokens"] is not None and receipt["output_tokens"] is not None)
            or type(receipt["model_call_attempted"]) is not bool
        ):
            raise ValueError("Actual completeness/call attempt must be explicit")
        expected_action = ACCEPT if run.status == "succeeded" else "run.document_extraction.cancel" if run.status == "cancelled" else "run.document_extraction.fail" if run.status == "failed" else None
        expected_hash = c.bytes_hash(run.result_json) if run.status == "succeeded" else None
        if (
            row.action != expected_action
            or row.actor_id != run.requested_by
            or detail != {"schema_version": "document_extraction_receipt_v1", "lease_token": run.lease_token, "usage": receipt, "result_hash": expected_hash, "error_code": run.error_code}
        ):
            raise ValueError("The exact final receipt differs from its actual Run")
        if run.status == "succeeded" and not receipt["complete"]:
            raise ValueError("An accepted result requires complete actual provider usage")
        return receipt
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "原文提取的实际用量、完整结果或最终审计不一致") from exc


def describe_document_run(db, user, run, include_result=True):
    from app.ai.document_extraction_storage import authorize_document_run

    snapshot, context, metadata = authorize_document_run(db, user, run, current=False)
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
        "latency_ms",
        "create_time",
        "start_time",
        "finish_time",
    )
    receipt = usage_receipt(db, run)
    data = {name: getattr(run, name) for name in fields}
    data.update(
        feature_name="指南入库助手",
        requires_human_review=True,
        context_metadata=metadata,
        usage_receipt=receipt,
        input_tokens=receipt["input_tokens"],
        output_tokens=receipt["output_tokens"],
        document_original_id=context.document_binding.original.original_id,
    )
    if include_result:
        data["result"] = load_result(db, run)
        data["evidence"] = snapshot["payload"]["evidence"]
        data["document_extraction_findings"] = context.model_dump(mode="json")
        data["document_original"] = sources.original_detail(db, user, context.document_binding.original.original_id).model_dump(mode="json")
    return data
