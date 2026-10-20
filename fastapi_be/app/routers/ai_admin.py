"""Super-administrator-only management of every AI capability and dependency."""

import datetime
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURES
from app.ai.gateway import AIExecutionError
from app.ai.governance import (
    audit,
    describe_config,
    describe_provider,
    digest,
    encode_json,
    encrypt_credential,
    ensure_revision,
    feature_config,
    flush_or_conflict,
    get_spec,
    invalidate_feature,
    provider_feature_issues,
    validate_endpoint,
)
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIFeedback, AIKnowledgeDocument, AIPatientGrant, AIPromptVersion, AIProvider, AIRun, utcnow
from app.ai.pathway_knowledge import PATHWAY_SOURCE_KIND, PATHWAY_URI_PREFIX, import_content, pathway_hash, source_is_current, source_state
from app.ai.readiness import setup_reports
from app.ai.runtime import describe_run
from app.ai.schemas import FeatureWrite, KnowledgeReview, KnowledgeWrite, PathwayKnowledgeImport, PatientGrantWrite, PromptActivate, PromptWrite, ProviderCheck, ProviderWrite
from app.ai.speech_probe import inspect_speech_capabilities
from app.database import get_db
from app.dependencies import require_roles
from app.models import ClinicalPathway, Department, Patient, User

router = APIRouter(tags=["AI 超级管理员"], default_response_class=JSONResponse)


def _commit(db: Session) -> None:
    """Return a useful conflict instead of leaking database error details."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "名称、版本或配置已存在，请刷新后重试") from exc


@router.get("/ai/admin/features")
def list_features(db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """List all 80 capabilities, including disabled and unvalidated ones."""
    configs = {item.feature_key: item for item in db.query(AIFeatureConfig).all()}
    reports = setup_reports(db, configs)
    return {"code": 200, "msg": "success", "data": [{**describe_config(db, spec, configs.get(spec.key), True), "setup_check": reports[spec.key]} for spec in FEATURES]}


@router.put("/ai/admin/features/{key}")
def update_feature(key: str, req: FeatureWrite, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Configure roles, model, activation and explicit validation with optimistic locking."""
    spec = get_spec(key)
    config = feature_config(db, key, user.user_id, req.expected_revision)
    if "provider_id" in req.model_fields_set:
        if req.provider_id is not None and db.get(AIProvider, req.provider_id) is None:
            raise HTTPException(404, "模型配置不存在")
        if config.provider_id != req.provider_id:
            invalidate_feature(config)
        config.provider_id = req.provider_id
    if req.allowed_roles is not None:
        if not set(req.allowed_roles) <= set(spec.default_roles):
            raise HTTPException(422, "授权角色超出该功能允许的业务范围")
        config.allowed_roles_json = encode_json(sorted(set(req.allowed_roles)))
    if req.validation_status is not None:
        config.validation_status = req.validation_status
        config.validation_note = req.validation_note or ""
        if req.validation_status in {"pilot", "validated"}:
            if len(config.validation_note) < 10:
                raise HTTPException(422, "请记录至少10字的验证范围、结果和依据")
            config.validated_by = user.user_id
            config.validated_at = utcnow()
        else:
            config.enabled = 0
            config.validated_by = None
            config.validated_at = None
    elif req.validation_note is not None:
        config.validation_note = req.validation_note
    if req.daily_limit is not None:
        config.daily_limit = req.daily_limit
    if req.enabled is not None:
        config.enabled = int(req.enabled)
    if config.enabled:
        provider = db.get(AIProvider, config.provider_id) if config.provider_id else None
        if not provider or not provider.enabled:
            raise HTTPException(422, "启用前请选择已启用的模型")
        issues = provider_feature_issues(spec, provider)
        if issues:
            raise HTTPException(422, issues[0]["message"])
        if spec.clinical and config.validation_status != "validated":
            raise HTTPException(422, "临床功能完成验证后才能面向业务启用；超级管理员可先进行预览")
        if config.validation_status == "suspended":
            raise HTTPException(422, "已暂停的功能不能启用")
    config.revision += 1
    config.updated_by = user.user_id
    audit(db, user.user_id, "feature.update", key, {"revision": config.revision, "enabled": bool(config.enabled), "validation_status": config.validation_status, "provider_id": config.provider_id})
    _commit(db)
    return {"code": 200, "msg": "success", "data": describe_config(db, spec, config, True)}


@router.get("/ai/admin/providers")
def list_providers(db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Never return plaintext or encrypted API keys."""
    return {"code": 200, "msg": "success", "data": [describe_provider(item) for item in db.query(AIProvider).order_by(AIProvider.provider_id).all()]}


@router.post("/ai/admin/providers/{provider_id}/speech-capabilities")
async def check_speech_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect the saved endpoint only; never turn a connectivity check into clinical validation."""
    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "medical_transcription" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记医疗语音录入的专用服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()  # Release the read transaction before the network request.
    error = None
    try:
        capabilities = await inspect_speech_capabilities(provider)
    except AIExecutionError as exc:
        error = exc
    db.expire_all()
    actor, current = db.get(User, actor_id), db.get(AIProvider, provider_id)
    if actor is None or actor.user_role != "super_admin":
        raise HTTPException(403, "当前用户不再具备AI管理权限")
    if current is None:
        raise HTTPException(409, "模型配置已删除，请刷新后重试")
    ensure_revision(current.revision, revision)
    if error:
        audit(db, actor_id, "provider.speech_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际版本不同；请核对并保存实际版本后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于语音服务处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.speech_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {"code": 200, "msg": "success", "data": {
        "provider_id": provider_id, "provider_revision": revision, "configured_model": configured_model, "compatible": not issues,
        "capabilities": capabilities, "issues": issues,
        "scope_note": "仅读取服务声明与登记配置的匹配情况，不发送患者资料、不执行识别，不证明医疗质量或完成临床验证。",
    }}


@router.get("/ai/admin/runs")
def list_global_runs(
    feature_key: str | None = None,
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = None,
    outcome: Literal["accepted", "rejected", "modified"] | None = None,
    requested_by: int | None = Query(None, ge=1),
    patient_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> dict:
    """Inspect all users' task metadata and feedback counts without loading clinical payloads."""
    query = db.query(AIRun)
    if feature_key:
        get_spec(feature_key)
        query = query.filter(AIRun.feature_key == feature_key)
    if status:
        query = query.filter(AIRun.status == status)
    if requested_by:
        query = query.filter(AIRun.requested_by == requested_by)
    if patient_id:
        query = query.filter(AIRun.patient_id == patient_id)
    if outcome:
        query = query.filter(AIRun.run_id.in_(db.query(AIFeedback.run_id).filter(AIFeedback.outcome == outcome)))
    total = query.count()
    rows = (
        query.options(defer(AIRun.input_json), defer(AIRun.result_json), defer(AIRun.evidence_json))
        .order_by(AIRun.create_time.desc(), AIRun.run_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    counts = dict(db.query(AIFeedback.run_id, func.count(AIFeedback.feedback_id)).filter(AIFeedback.run_id.in_([item.run_id for item in rows])).group_by(AIFeedback.run_id).all()) if rows else {}
    data = [{**describe_run(item, False), "requested_by": item.requested_by, "provider_id": item.provider_id, "feedback_count": counts.get(item.run_id, 0)} for item in rows]
    return {"code": 200, "msg": "success", "data": data, "total": total, "page": page, "page_size": page_size}


@router.get("/ai/admin/runs/{run_id}")
def inspect_run_trace(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Read the frozen prompts, requested model, source payload and append-only review history."""
    run = db.get(AIRun, run_id)
    if run is None:
        raise HTTPException(404, "AI 任务不存在")
    snapshot = json.loads(run.input_json)
    feedback = db.query(AIFeedback).filter_by(run_id=run_id).order_by(AIFeedback.create_time.desc(), AIFeedback.feedback_id).limit(101).all()
    return {
        "code": 200,
        "msg": "success",
        "data": {
            **describe_run(run),
            "requested_by": run.requested_by,
            "provider_id": run.provider_id,
            "frozen_request": snapshot,
            "snapshot_complete": all(key in snapshot for key in ("system_prompt", "provider_snapshot", "catalog_version")),
            "feedback": [{name: getattr(item, name) for name in ("feedback_id", "reviewer_id", "outcome", "comment", "create_time")} for item in feedback[:100]],
            "feedback_truncated": len(feedback) > 100,
        },
    }


def _write_provider(db: Session, req: ProviderWrite, user: User, provider: AIProvider | None) -> AIProvider:
    endpoint = validate_endpoint(req.api_base)
    ensure_revision(provider.revision if provider else 0, req.expected_revision)
    for key in req.supported_features:
        get_spec(key)
    if req.api_key and req.clear_api_key:
        raise HTTPException(422, "不能同时保存和清除密钥")
    if provider is None:
        provider = AIProvider(created_by=user.user_id, revision=0)
        db.add(provider)
    else:
        for config in db.query(AIFeatureConfig).filter_by(provider_id=provider.provider_id).with_for_update().all():
            invalidate_feature(config)
            config.revision += 1
            config.updated_by = user.user_id
    for name in ("name", "kind", "model", "api_key_env", "timeout_seconds", "max_output_tokens", "temperature", "validation_report"):
        setattr(provider, name, getattr(req, name))
    provider.api_base = endpoint
    provider.enabled = int(req.enabled)
    provider.allows_patient_data = int(req.allows_patient_data)
    provider.supported_features_json = encode_json(sorted(set(req.supported_features)))
    provider.validated_at = utcnow() if req.validation_report else None
    if req.api_key:
        provider.api_key_encrypted = encrypt_credential(req.api_key)
    elif req.clear_api_key:
        provider.api_key_encrypted = ""
    provider.revision += 1
    flush_or_conflict(db)
    audit(db, user.user_id, "provider.save", str(provider.provider_id), {"name": provider.name, "revision": provider.revision, "credential_changed": bool(req.api_key or req.clear_api_key)})
    _commit(db)
    return provider


@router.post("/ai/admin/providers")
def create_provider(req: ProviderWrite, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Create a deployment-approved endpoint with write-only credentials."""
    provider = _write_provider(db, req, user, None)
    return {"code": 200, "msg": "success", "data": describe_provider(provider)}


@router.put("/ai/admin/providers/{provider_id}")
def update_provider(provider_id: int, req: ProviderWrite, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Changing a provider invalidates activation of its dependent capabilities."""
    provider = db.query(AIProvider).filter_by(provider_id=provider_id).with_for_update().first()
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    return {"code": 200, "msg": "success", "data": describe_provider(_write_provider(db, req, user, provider))}


@router.get("/ai/admin/prompts/{key}")
def list_prompts(key: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Display the fixed system contract and immutable task prompt history."""
    spec = get_spec(key)
    versions = db.query(AIPromptVersion).filter_by(feature_key=key).order_by(AIPromptVersion.version.desc()).all()
    baseline = {"prompt_id": None, "version": 0, "task_prompt": spec.task_prompt, "change_note": "项目默认任务 Prompt"}
    data = [{name: getattr(item, name) for name in ("prompt_id", "version", "task_prompt", "change_note", "created_by", "create_time")} for item in versions]
    return {"code": 200, "msg": "success", "data": {"system_prompt": COMMON_SYSTEM_PROMPT, "versions": [*data, baseline]}}


@router.post("/ai/admin/prompts/{key}")
def create_prompt(key: str, req: PromptWrite, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Save a new revision; never modify historical prompt content."""
    config = feature_config(db, key, user.user_id, req.expected_revision)
    version = (db.query(func.max(AIPromptVersion.version)).filter_by(feature_key=key).scalar() or 0) + 1
    prompt = AIPromptVersion(feature_key=key, version=version, task_prompt=req.task_prompt, change_note=req.change_note, created_by=user.user_id)
    db.add(prompt)
    flush_or_conflict(db)
    if req.activate:
        config.active_prompt_id = prompt.prompt_id
        invalidate_feature(config)
    config.revision += 1
    config.updated_by = user.user_id
    audit(db, user.user_id, "prompt.create", key, {"version": version, "activated": req.activate, "prompt_hash": digest(req.task_prompt)})
    _commit(db)
    return {"code": 200, "msg": "success", "data": {"prompt_id": prompt.prompt_id, "version": version, "revision": config.revision}}


@router.post("/ai/admin/prompts/{key}/activate")
def activate_prompt(key: str, req: PromptActivate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Activate a historical version or revert to the baseline, then require revalidation."""
    config = feature_config(db, key, user.user_id, req.expected_revision)
    if req.prompt_id:
        prompt = db.get(AIPromptVersion, req.prompt_id)
        if not prompt or prompt.feature_key != key:
            raise HTTPException(422, "Prompt 版本不属于该功能")
    config.active_prompt_id = req.prompt_id
    invalidate_feature(config)
    config.revision += 1
    config.updated_by = user.user_id
    audit(db, user.user_id, "prompt.activate", key, {"prompt_id": req.prompt_id, "revision": config.revision})
    _commit(db)
    return {"code": 200, "msg": "success", "data": describe_config(db, get_spec(key), config, True)}


@router.get("/ai/admin/knowledge")
def list_knowledge(db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin")), limit: int = Query(100, ge=1, le=300)) -> dict:
    """List version metadata; full text is retrieved only when explicitly inspected."""
    items = db.query(AIKnowledgeDocument).order_by(AIKnowledgeDocument.create_time.desc()).limit(limit).all()
    names = ("document_id", "title", "version", "source_uri", "category", "status", "content_hash", "department_id", "effective_from", "effective_to", "reviewed_by", "reviewed_at", "create_time")
    data = [
        {
            **{name: getattr(item, name) for name in names},
            "feature_keys": json.loads(item.feature_keys_json),
            "source_kind": item.source_kind,
            "source_reference_id": item.source_reference_id,
            "source_state": source_state(db, item),
        }
        for item in items
    ]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/ai/admin/knowledge/{document_id}")
def knowledge_detail(document_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect exact text and its hash before a publication decision."""
    item = db.get(AIKnowledgeDocument, document_id)
    if item is None:
        raise HTTPException(404, "知识文档不存在")
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "document_id": item.document_id,
            "title": item.title,
            "version": item.version,
            "content": item.content,
            "content_hash": item.content_hash,
            "status": item.status,
            "source_kind": item.source_kind,
            "source_reference_id": item.source_reference_id,
            "source_snapshot_hash": item.source_snapshot_hash,
            "source_state": source_state(db, item),
        },
    }


@router.post("/ai/admin/knowledge")
def create_knowledge(req: KnowledgeWrite, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Create an immutable draft without fetching arbitrary external URLs."""
    for key in req.feature_keys:
        get_spec(key)
    if req.effective_from and req.effective_to and req.effective_from >= req.effective_to:
        raise HTTPException(422, "知识生效时间必须早于失效时间")
    if req.department_id and db.get(Department, req.department_id) is None:
        raise HTTPException(404, "科室不存在")
    item = AIKnowledgeDocument(**req.model_dump(exclude={"feature_keys"}), feature_keys_json=encode_json(sorted(set(req.feature_keys))), content_hash=digest(req.content), created_by=user.user_id)
    db.add(item)
    flush_or_conflict(db)
    audit(db, user.user_id, "knowledge.create", item.document_id, {"title": item.title, "version": item.version, "content_hash": item.content_hash})
    _commit(db)
    return {"code": 200, "msg": "success", "data": {"document_id": item.document_id, "content_hash": item.content_hash, "status": item.status}}


@router.post("/ai/admin/knowledge/{document_id}/review")
def review_knowledge(document_id: str, req: KnowledgeReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Publish exactly the reviewed version or retire it without deleting evidence history."""
    item = db.query(AIKnowledgeDocument).filter_by(document_id=document_id).with_for_update().first()
    if item is None:
        raise HTTPException(404, "知识文档不存在")
    if item.content_hash != req.content_hash:
        raise HTTPException(409, "知识内容与审核版本不一致")
    if req.status == "published" and (item.source_kind is not None or item.source_uri.lower().startswith(PATHWAY_URI_PREFIX)):
        if item.status != "draft":
            raise HTTPException(409, "路径快照只能从待审核发布；停用后须重新导入新版本")
        if not source_is_current(db, item) or digest(item.content) != item.content_hash:
            raise HTTPException(409, "路径来源或快照内容已变化，请重新导入当前版本后审核")
    item.status = req.status
    item.reviewed_by = user.user_id
    item.reviewed_at = utcnow()
    audit(db, user.user_id, "knowledge.review", document_id, {"status": req.status, "content_hash": item.content_hash})
    _commit(db)
    return {"code": 200, "msg": "success", "data": {"document_id": item.document_id, "status": item.status}}


@router.get("/ai/admin/pathway-sources")
def list_pathway_sources(db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin")), limit: int = Query(100, ge=1, le=300)) -> dict:
    """Offer source metadata without treating an active business template as reviewed knowledge."""
    rows = db.query(ClinicalPathway).order_by(ClinicalPathway.pathway_id.desc()).limit(limit + 1).all()
    items = []
    for row in rows[:limit]:
        issues = []
        try:
            import_content(row)
        except HTTPException as exc:
            issues.append(str(exc.detail))
        items.append(
            {
                "pathway_id": row.pathway_id,
                "name": row.name,
                "disease_code": row.disease_code,
                "disease_name": row.disease_name,
                "status": row.status,
                "expected_days": row.expected_days,
                "source_hash": pathway_hash(row),
                "importable": not issues,
                "issues": issues,
            }
        )
    return {"code": 200, "msg": "success", "data": {"items": items, "truncated": len(rows) > limit}}


@router.post("/ai/admin/pathway-sources/{pathway_id}/import")
def import_pathway_knowledge(pathway_id: int, req: PathwayKnowledgeImport, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Freeze the exact hospital template; publication remains a separate review action."""
    row = db.query(ClinicalPathway).filter_by(pathway_id=pathway_id).with_for_update().populate_existing().first()
    if row is None:
        raise HTTPException(404, "临床路径不存在")
    source_hash = pathway_hash(row)
    if source_hash != req.expected_source_hash:
        raise HTTPException(409, "路径来源已变化，请重新加载后导入")
    for key in req.feature_keys:
        get_spec(key)
    if req.effective_from and req.effective_to and req.effective_from >= req.effective_to:
        raise HTTPException(422, "知识生效时间必须早于失效时间")
    if req.department_id and db.get(Department, req.department_id) is None:
        raise HTTPException(404, "科室不存在")
    content = import_content(row)
    title = f"院内路径 #{row.pathway_id}：{row.name}"
    versions = {item[0] for item in db.query(AIKnowledgeDocument.version).filter_by(title=title).all()}
    ordinal = 1
    while f"v{ordinal}" in versions:
        ordinal += 1
    item = AIKnowledgeDocument(
        title=title,
        version=f"v{ordinal}",
        source_uri=PATHWAY_URI_PREFIX + str(row.pathway_id),
        source_kind=PATHWAY_SOURCE_KIND,
        source_reference_id=row.pathway_id,
        source_snapshot_hash=source_hash,
        category="clinical",
        content=content,
        content_hash=digest(content),
        feature_keys_json=encode_json(sorted(set(req.feature_keys))),
        department_id=req.department_id,
        effective_from=req.effective_from,
        effective_to=req.effective_to,
        status="draft",
        created_by=user.user_id,
    )
    db.add(item)
    flush_or_conflict(db)
    audit(db, user.user_id, "knowledge.pathway_import", item.document_id, {"pathway_id": pathway_id, "source_hash": source_hash, "content_hash": item.content_hash, "version": item.version})
    _commit(db)
    return {"code": 200, "msg": "success", "data": {"document_id": item.document_id, "status": item.status, "content_hash": item.content_hash, "version": item.version}}


@router.get("/ai/admin/grants")
def list_grants(db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin")), limit: int = Query(100, ge=1, le=300)) -> dict:
    """Inspect explicit care access without returning patient direct identifiers."""
    items = db.query(AIPatientGrant).order_by(AIPatientGrant.create_time.desc()).limit(limit).all()
    names = ("grant_id", "user_id", "patient_id", "category", "reason", "expires_at", "revoked", "created_by")
    return {"code": 200, "msg": "success", "data": [{name: getattr(item, name) for name in names} for item in items]}


@router.post("/ai/admin/grants")
def create_grant(req: PatientGrantWrite, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Authorize a care role for one category and patient for at most 90 days."""
    categories = {spec.category for spec in FEATURES}
    target_user = db.get(User, req.user_id)
    if not target_user or db.get(Patient, req.patient_id) is None:
        raise HTTPException(404, "用户或患者不存在")
    if target_user.user_role in {"patient", "guide", "cashier", "registrar"}:
        raise HTTPException(422, "该角色不能被授予跨患者临床访问权限")
    if req.category not in categories:
        raise HTTPException(422, "功能分类无效")
    if not utcnow() < req.expires_at <= utcnow() + datetime.timedelta(days=90):
        raise HTTPException(422, "授权应在未来90天内到期")
    grant = AIPatientGrant(**req.model_dump(), created_by=user.user_id)
    db.add(grant)
    flush_or_conflict(db)
    audit(db, user.user_id, "grant.create", str(grant.grant_id), {"user_id": grant.user_id, "patient_id": grant.patient_id, "category": grant.category})
    _commit(db)
    return {"code": 200, "msg": "success", "data": {"grant_id": grant.grant_id}}


@router.delete("/ai/admin/grants/{grant_id}")
def revoke_grant(grant_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Revoke care access while preserving who granted it and why."""
    grant = db.get(AIPatientGrant, grant_id)
    if grant is None:
        raise HTTPException(404, "授权不存在")
    grant.revoked = 1
    audit(db, user.user_id, "grant.revoke", str(grant_id))
    _commit(db)
    return {"code": 200, "msg": "success"}


@router.get("/ai/admin/audit")
def list_audit(db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin")), limit: int = Query(100, ge=1, le=300)) -> dict:
    """Review redacted configuration changes by their actual administrator identity."""
    items = db.query(AIAuditEvent).order_by(AIAuditEvent.event_id.desc()).limit(limit).all()
    names = ("event_id", "actor_id", "action", "target", "create_time")
    return {"code": 200, "msg": "success", "data": [{**{name: getattr(item, name) for name in names}, "detail": json.loads(item.detail_json)} for item in items]}


@router.get("/ai/admin/usage")
def usage_summary(db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Return aggregate usage without exposing patient inputs or model output."""
    rows = db.query(AIRun.feature_key, AIRun.status, func.count(AIRun.run_id), func.sum(AIRun.input_tokens), func.sum(AIRun.output_tokens)).group_by(AIRun.feature_key, AIRun.status).all()
    return {
        "code": 200,
        "msg": "success",
        "data": [{"feature_key": key, "status": status, "count": count, "input_tokens": inputs or 0, "output_tokens": outputs or 0} for key, status, count, inputs, outputs in rows],
    }
