"""Durable, permission-checked AI task creation, execution and human feedback."""

import datetime
import json
import time
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.ai.catalog import CATALOG_VERSION, COMMON_SYSTEM_PROMPT, FeatureSpec
from app.ai.context import ContextBundle, authorize_patient, context_metadata, minimize_identifiers, patient_snapshot
from app.ai.gateway import AIExecutionError, generate
from app.ai.governance import active_prompt, audit, digest, encode_json, get_spec, provider_credential, provider_feature_issues
from app.ai.knowledge import evidence_is_current, retrieve_evidence
from app.ai.models import AIFeatureConfig, AIProvider, AIRun, utcnow
from app.ai.schemas import RunRequest
from app.ai.tools import business_tools, operational_context
from app.config import settings
from app.models import Doctor, Patient, User


def authorized_feature(db: Session, user: User, key: str) -> tuple[FeatureSpec, AIFeatureConfig | None]:
    """Intersect configured authorization with the fixed capability role boundary."""
    spec = get_spec(key)
    config = db.get(AIFeatureConfig, key)
    roles = set(json.loads(config.allowed_roles_json)) if config else set(spec.default_roles)
    if user.user_role != "super_admin" and (user.user_role not in roles or user.user_role not in spec.default_roles):
        raise HTTPException(403, "没有使用该 AI 功能的权限")
    return spec, config


def check_configuration(db: Session, user: User, spec: FeatureSpec, config: AIFeatureConfig | None, preview: bool) -> AIProvider:
    """Keep preview, deployment, validation and patient-data authorization distinct."""
    if preview and user.user_role != "super_admin":
        raise HTTPException(403, "仅超级管理员可预览尚未启用的能力")
    if not config or not config.provider_id:
        raise HTTPException(409, "尚未为该功能配置模型服务")
    if not preview and not config.enabled:
        raise HTTPException(409, "该 AI 功能尚未启用")
    if not preview and spec.clinical and config.validation_status != "validated":
        raise HTTPException(409, "该临床功能尚未完成验证")
    provider = db.get(AIProvider, config.provider_id)
    if provider is None or not provider.enabled:
        raise HTTPException(409, "模型服务未启用")
    issues = provider_feature_issues(spec, provider)
    if issues:
        raise HTTPException(409, issues[0]["message"])
    provider_credential(provider)
    return provider


def provider_snapshot(provider: AIProvider) -> dict:
    """Freeze the requested model and limits for audit without any credential or environment reference."""
    fields = ("provider_id", "revision", "name", "kind", "api_base", "model", "timeout_seconds", "max_output_tokens", "validation_report")
    snapshot = {name: getattr(provider, name) for name in fields}
    snapshot["temperature"] = float(provider.temperature)
    snapshot["allows_patient_data"] = bool(provider.allows_patient_data)
    snapshot["effective_output_limit"] = min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS)
    return snapshot


def create_run(db: Session, user: User, req: RunRequest) -> AIRun:
    """Freeze an authorized, source-linked request before a durable worker processes it."""
    spec, config = authorized_feature(db, user, req.feature_key)
    if len(encode_json(req.input)) > settings.AI_MAX_INPUT_CHARS:
        raise HTTPException(422, "任务输入超过允许长度")
    if spec.number in {51, 52}:
        from app.routers.triage import EMERGENCY_KEYWORDS

        if any(keyword in encode_json(req.input) for keyword in EMERGENCY_KEYWORDS):
            raise HTTPException(422, "检测到可能的急症描述，请立即拨打急救电话或前往急诊，不要等待 AI 生成结果")
    provider = check_configuration(db, user, spec, config, req.preview)
    original_revision = config.revision
    if spec.scope == "patient" and req.patient_id is None:
        raise HTTPException(422, "该功能需要选择已授权患者")
    if req.patient_id is not None and spec.scope != "patient":
        raise HTTPException(422, "该任务不接受额外加载个体患者资料")
    if req.patient_id is not None:
        bundle = patient_snapshot(db, user, spec, req.patient_id, req.encounter_ref, req.input)
    elif spec.scope == "hospital":
        bundle = operational_context(db, user)
    else:
        departments = {item[0] for item in db.query(Doctor.department_id).filter_by(user_id=user.user_id).all() if item[0]}
        bundle = ContextBundle(data={"scope": "task_input", "missing_data": []}, department_ids=departments)
    if spec.key == "treatment_pathway" and not bundle.data.get("current_confirmed_diagnoses"):
        raise HTTPException(409, "治疗路径推荐需要指定本次就诊，并提供该次就诊已确认的诊断")
    patient = db.get(Patient, req.patient_id) if req.patient_id else None
    clean_input = minimize_identifiers(req.input, patient)
    tools, tool_evidence = business_tools(db, spec, user, req.patient_id, clean_input, bundle)
    query = encode_json(clean_input) + " " + " ".join(bundle.data.get("current_confirmed_diagnoses", []))
    knowledge = retrieve_evidence(db, spec, query, bundle.department_ids)
    if spec.requires_knowledge and not knowledge:
        raise HTTPException(409, "未检索到本任务可用的已审核知识，请先录入并审核相关资料")
    evidence = [*bundle.evidence, *tool_evidence, *knowledge]
    prompt, version = active_prompt(db, spec, config)
    config = db.query(AIFeatureConfig).filter_by(feature_key=spec.key).populate_existing().with_for_update().one()
    if config.revision != original_revision:
        raise HTTPException(409, "功能配置在准备资料时已改变，请重新提交")
    start = datetime.datetime.combine(utcnow().date(), datetime.time.min)
    count = db.query(AIRun).filter(AIRun.feature_key == spec.key, AIRun.requested_by == user.user_id, AIRun.create_time >= start).count()
    if count >= config.daily_limit:
        raise HTTPException(429, "该功能今日调用额度已用完")
    payload = {"input": clean_input, "context": bundle.data, "tools": tools, "evidence": evidence}
    if len(encode_json(payload)) > settings.AI_MAX_CONTEXT_CHARS * 2:
        raise HTTPException(422, "组合后的资料超过任务上下文限制")
    run = AIRun(
        feature_key=spec.key,
        provider_id=provider.provider_id,
        provider_revision=provider.revision,
        prompt_version=version,
        prompt_hash=digest([COMMON_SYSTEM_PROMPT, prompt]),
        context_digest=digest(bundle.data),
        patient_id=req.patient_id,
        encounter_ref=req.encounter_ref,
        requested_by=user.user_id,
        preview=int(req.preview),
        status="queued",
        input_json=encode_json(
            {
                "catalog_version": CATALOG_VERSION,
                "system_prompt": COMMON_SYSTEM_PROMPT,
                "task_prompt": prompt,
                "payload": payload,
                "provider_snapshot": provider_snapshot(provider),
                "feature_validation": {
                    "status": config.validation_status,
                    "note": config.validation_note,
                    "validated_by": config.validated_by,
                    "validated_at": config.validated_at,
                    "feature_revision": config.revision,
                },
            }
        ),
        evidence_json=encode_json(evidence),
        context_metadata_json=encode_json({**context_metadata(bundle), "feature_revision": config.revision, "validation_status": config.validation_status, "tool_fingerprint": digest(tools)}),
    )
    db.add(run)
    db.flush()
    audit(db, user.user_id, "run.create", run.run_id, {"feature_key": spec.key, "preview": req.preview})
    db.commit()
    return run


def authorize_run(db: Session, user: User, run: AIRun) -> None:
    """Re-check current permissions, including revoked care access, on every result read."""
    if user.user_role != "super_admin" and run.requested_by != user.user_id:
        raise HTTPException(403, "不能访问其他用户的 AI 任务")
    spec, _ = authorized_feature(db, user, run.feature_key)
    if run.patient_id is not None:
        authorize_patient(db, user, run.patient_id, spec.category, run.encounter_ref)


def describe_run(run: AIRun, include_result: bool = True) -> dict:
    """Expose the user-facing result, not system instructions or provider secrets."""
    spec = get_spec(run.feature_key)
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
    data = {name: getattr(run, name) for name in fields}
    data.update({"feature_name": spec.name, "requires_human_review": True, "context_metadata": json.loads(run.context_metadata_json)})
    if include_result:
        data["result"] = json.loads(run.result_json)
        data["evidence"] = json.loads(run.evidence_json)
    return data


def claim_next_run(db: Session) -> tuple[str, str] | None:
    """Claim durable work without allowing two workers to execute the same queued task."""
    query = db.query(AIRun).filter_by(status="queued").order_by(AIRun.create_time)
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    run = query.first()
    if run is None:
        return None
    lease = str(uuid.uuid4())
    changed = db.query(AIRun).filter_by(run_id=run.run_id, status="queued").update({"status": "running", "start_time": utcnow(), "lease_token": lease}, synchronize_session=False)
    if changed != 1:
        db.rollback()
        return None
    run_id = run.run_id
    db.commit()
    return run_id, lease


def _recheck_task(db: Session, run: AIRun) -> tuple[FeatureSpec, AIProvider, dict]:
    if utcnow() - run.create_time > datetime.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS):
        raise AIExecutionError("TASK_EXPIRED", "任务等待时间过长，请重新加载最新资料后提交")
    user = db.get(User, run.requested_by)
    if user is None:
        raise HTTPException(403, "任务用户已失效")
    authorize_run(db, user, run)
    spec, config = authorized_feature(db, user, run.feature_key)
    provider = check_configuration(db, user, spec, config, bool(run.preview))
    if provider.provider_id != run.provider_id or provider.revision != run.provider_revision:
        raise HTTPException(409, "模型配置已改变，请重新创建任务")
    metadata = json.loads(run.context_metadata_json)
    if config.revision != metadata["feature_revision"]:
        raise HTTPException(409, "功能或 Prompt 配置已改变，请重新创建任务")
    snapshot = json.loads(run.input_json)
    if snapshot.get("catalog_version") != CATALOG_VERSION or snapshot.get("system_prompt") != COMMON_SYSTEM_PROMPT:
        raise AIExecutionError("TASK_CONTRACT_CHANGED", "任务目录或系统契约已改变，请重新创建任务")
    if digest(provider_snapshot(provider)) != digest(snapshot.get("provider_snapshot")):
        raise AIExecutionError("TASK_MODEL_CHANGED", "模型参数或输出限制已改变，请重新创建任务")
    if digest(snapshot["payload"]["context"]) != run.context_digest:
        raise AIExecutionError("TASK_SNAPSHOT_INVALID", "任务资料快照校验不一致，请重新创建任务")
    if digest([COMMON_SYSTEM_PROMPT, snapshot["task_prompt"]]) != run.prompt_hash:
        raise HTTPException(409, "任务系统契约已改变，请重新创建任务")
    if not evidence_is_current(db, json.loads(run.evidence_json)):
        raise HTTPException(409, "任务引用的知识已停用或过期，请重新创建任务")
    if run.patient_id is not None:
        current_bundle = patient_snapshot(db, user, spec, run.patient_id, run.encounter_ref, snapshot["payload"]["input"])
        if context_metadata(current_bundle)["clinical_context_fingerprint"] != metadata.get("clinical_context_fingerprint"):
            raise AIExecutionError("TASK_CONTEXT_CHANGED", "患者资料或诊断确认状态已改变，请重新加载最新资料后生成")
    else:
        current_bundle = ContextBundle(data=snapshot["payload"]["context"])
    current_tools, _ = business_tools(db, spec, user, run.patient_id, snapshot["payload"]["input"], current_bundle)
    if digest(current_tools) != metadata.get("tool_fingerprint"):
        raise AIExecutionError("TASK_TOOLS_CHANGED", "相关审方规则、目录或业务状态已改变，请重新生成")
    return spec, provider, snapshot


async def execute_claimed(run_id: str, lease: str, *, transport=None) -> None:
    """Release SQL connections during inference; recheck authorization before storing results."""
    from app import database

    started = time.monotonic()
    error = result = None
    inputs = outputs = 0
    try:
        with database.SessionLocal() as db:
            run = db.get(AIRun, run_id)
            if not run or run.status != "running" or run.lease_token != lease:
                return
            spec, provider, snapshot = _recheck_task(db, run)
            db.expunge(provider)
        result, inputs, outputs = await generate(provider, spec, snapshot["task_prompt"], snapshot["payload"], transport=transport)
        review = snapshot["payload"].get("tools", {}).get("prescription_review", {})
        for finding in review.get("findings", []):
            if finding.get("severity") == 3:
                result.warnings.append("现有审方禁止：" + finding["message"])
        triage = snapshot["payload"].get("tools", {}).get("triage_rules", {})
        if triage.get("emergency"):
            result.warnings.insert(0, triage["emergency_message"])
    except AIExecutionError as exc:
        error = (exc.code, exc.message)
    except HTTPException as exc:
        error = ("TASK_NO_LONGER_AUTHORIZED", str(exc.detail))
    except Exception:
        error = ("TASK_EXECUTION_ERROR", "任务处理失败，请联系管理员查看执行状态")
    with database.SessionLocal() as db:
        run = db.query(AIRun).filter(AIRun.run_id == run_id, AIRun.status.in_(["running", "cancelled"]), AIRun.lease_token == lease).with_for_update().first()
        if run is None:
            return
        if run.status == "cancelled":
            # Cancelling receipt cannot undo a provider request that has already been sent.
            # Keep reported usage while leaving the generated result unaccepted.
            run.input_tokens, run.output_tokens = inputs, outputs
            run.latency_ms = int((time.monotonic() - started) * 1000)
            run.finish_time = utcnow()
            db.commit()
            return
        if error is None:
            try:
                _recheck_task(db, run)
            except AIExecutionError as exc:
                error = (exc.code, exc.message)
            except HTTPException as exc:
                error = ("TASK_NO_LONGER_AUTHORIZED", str(exc.detail))
        run.input_tokens, run.output_tokens = inputs, outputs
        run.latency_ms = int((time.monotonic() - started) * 1000)
        run.finish_time = utcnow()
        if error:
            run.status = "failed"
            run.error_code, run.error_message = error
        else:
            run.status = "succeeded"
            run.result_json = encode_json(result.model_dump())
        db.commit()


def expire_interrupted_runs(db: Session) -> int:
    """Mark abandoned inference failed without repeating potentially billable calls."""
    deadline = utcnow() - datetime.timedelta(minutes=10)
    count = (
        db.query(AIRun)
        .filter(AIRun.status == "running", AIRun.start_time < deadline)
        .update({"status": "failed", "error_code": "WORKER_INTERRUPTED", "error_message": "执行进程中断，任务未自动重试，可检查后重新提交", "finish_time": utcnow()}, synchronize_session=False)
    )
    db.commit()
    return count
