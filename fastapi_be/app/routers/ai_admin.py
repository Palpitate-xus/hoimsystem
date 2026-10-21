"""Super-administrator-only management of every AI capability and dependency."""

import datetime
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from app.ai.catalog import FEATURES
from app.ai.ecg_probe import inspect_ecg_capabilities
from app.ai.forecast_probe import inspect_forecast_capabilities
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
from app.ai.imaging_probe import inspect_imaging_capabilities
from app.ai.knowledge_sources import is_document_source, lock_manual_review_target, source_is_current, source_state
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIFeedback, AIKnowledgeDocument, AIPatientGrant, AIPromptVersion, AIProvider, AIRun, utcnow
from app.ai.pathway_knowledge import PATHWAY_SOURCE_KIND, PATHWAY_URI_PREFIX, import_content, pathway_hash
from app.ai.readiness import setup_reports
from app.ai.runtime import describe_run
from app.ai.schemas import FeatureWrite, KnowledgeReview, KnowledgeWrite, PathwayKnowledgeImport, PatientGrantWrite, PromptActivate, PromptWrite, ProviderCheck, ProviderWrite
from app.ai.speech_probe import inspect_speech_capabilities
from app.database import get_db
from app.dependencies import require_roles
from app.models import ClinicalPathway, Department, Patient, User
from app.routers.inpatient_support import QueryPositiveInteger


class AIAdminRoute(APIRoute):
    """Reject invalid requests without echoing document text or credentials."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validated(request):
            try:
                return await handler(request)
            except RequestValidationError as exc:

                def safe(value):
                    return value.encode("utf-8", errors="backslashreplace").decode("utf-8") if isinstance(value, str) else value

                details = [{"type": safe(item["type"]), "loc": [safe(part) for part in item["loc"]], "msg": safe(item["msg"])} for item in exc.errors()]
                raise HTTPException(422, details) from exc

        return validated


router = APIRouter(tags=["AI 超级管理员"], default_response_class=JSONResponse, route_class=AIAdminRoute)


def _current_super_admin(db, user):
    """Recheck audit authority beyond a JWT-created MySQL RR snapshot."""
    state = inspect(user, raiseerr=False)
    user_id = state.identity[0] if state is not None and state.identity is not None else getattr(user, "user_id", None)
    # Preserve the already authenticated request's epoch before ORM refresh
    # mutates that same instance. Expired attributes must not trigger an earlier
    # unlocked SELECT; technical callers without loaded epochs get current SQL.
    loaded = {key: state.dict[key] for key in ("user_role", "token_invalid_before") if state is not None and key in state.dict}
    with db.no_autoflush:
        actor = db.query(User).filter_by(user_id=user_id).populate_existing().with_for_update(read=True).one_or_none()
    if actor is None or actor.user_role != "super_admin" or any(getattr(actor, key) != original for key, original in loaded.items()):
        raise HTTPException(403, "当前身份已无超级管理员审计权限")
    return actor


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
        if spec.requires_operational_validation and config.validation_status != "validated":
            purpose = "优化" if spec.engine == "optimizer" else "预测"
            raise HTTPException(422, f"运营{purpose}完成指定目标与范围的验证后才能启用；超级管理员可先预览，来源确认不代表实际业务验证")
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
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "仅读取服务声明与登记配置的匹配情况，不发送患者资料、不执行识别，不证明医疗质量或完成临床验证。",
        },
    }


@router.post("/ai/admin/providers/{provider_id}/ecg-capabilities")
async def check_ecg_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect only the saved ECG endpoint; never enable, save a model or approve clinical use."""
    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "ecg_analysis" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记心电辅助判读的专用服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()  # Release the read transaction before the network request.
    error = None
    try:
        capabilities = await inspect_ecg_capabilities(provider)
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
        audit(db, actor_id, "provider.ecg_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际版本不同；请核对并保存实际版本后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于心电服务处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.ecg_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "仅读取心电服务声明与登记配置的匹配情况，不发送患者资料、不执行分类，不证明临床适用性、识别质量或完成临床验证。",
        },
    }


@router.post("/ai/admin/providers/{provider_id}/image-capabilities")
async def check_image_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect only the saved image endpoint; no pixels, inference, enabling or clinical approval."""
    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "imaging_detection" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记医学影像辅助识别的专用服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()  # Release the read transaction before the metadata-only request.
    error = None
    try:
        capabilities = await inspect_imaging_capabilities(provider)
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
        audit(db, actor_id, "provider.image_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际版本不同；请核对并保存实际版本后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于影像服务处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.image_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "仅读取影像服务声明与登记配置的匹配情况，不发送患者资料或像素、不执行识别；不证明输入与训练预处理等价、临床适用性、诊断质量或完成临床验证。",
        },
    }


@router.post("/ai/admin/providers/{provider_id}/forecast-capabilities")
async def check_forecast_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Read saved adapter metadata; do not send records, predict or change validation."""
    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "visit_forecast" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记就诊量预测的专用统计服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()
    error = None
    try:
        capabilities = await inspect_forecast_capabilities(provider)
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
        audit(db, actor_id, "provider.forecast_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际版本不同；请核对并保存实际版本后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于统计服务处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.forecast_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "仅读取统计服务声明与登记配置的匹配情况，不发送挂号记录或日序列、不执行预测，不确认历史覆盖或预测效果，也不改变功能启停与验证状态。",
        },
    }


@router.post("/ai/admin/providers/{provider_id}/news2-capabilities")
async def check_news2_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect actual rule/runtime metadata without sending observations or scoring."""
    from app.ai.news2_probe import inspect_news2_capabilities

    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "deterioration_risk" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记病情恶化预警的专用NEWS2规则服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()
    error = None
    try:
        capabilities = await inspect_news2_capabilities(provider)
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
        audit(db, actor_id, "provider.news2_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际规则实现及运行版本不同，请核对并保存后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于规则服务处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.news2_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "只核对固定NEWS2算法、输入策略及运行版本，不发送患者点测、适用性声明或执行评分；不证明临床适用、原声明独立核实或效果验证，不改变功能启停与验证状态。",
        },
    }


@router.post("/ai/admin/providers/{provider_id}/aki-capabilities")
async def check_aki_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect actual rule/runtime metadata without sending observations or scoring."""
    from app.ai.aki_probe import inspect_aki_capabilities

    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "aki_risk" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记急性肾损伤判据核对的专用KDIGO AKI规则服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()
    error = None
    try:
        capabilities = await inspect_aki_capabilities(provider)
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
        audit(db, actor_id, "provider.aki_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际规则实现及运行版本不同，请核对并保存后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于规则服务处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.aki_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "只核对固定KDIGO AKI算法、输入策略及运行版本，不发送患者肌酐、尿量、适用性声明或执行分期；不证明临床适用、原声明独立核实或效果验证，不改变功能启停与验证状态。",
        },
    }


@router.post("/ai/admin/providers/{provider_id}/qsofa-capabilities")
async def check_qsofa_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect actual rule/runtime metadata without sending observations or scoring."""
    from app.ai.qsofa_probe import inspect_qsofa_capabilities

    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "sepsis_risk" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记脓毒症辅助资料核对的独立qSOFA规则服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()
    error = None
    try:
        capabilities = await inspect_qsofa_capabilities(provider)
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
        audit(db, actor_id, "provider.qsofa_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际规则实现及运行版本不同，请核对并保存后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于规则服务处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.qsofa_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "只核对固定qSOFA算法、输入策略及实际运行版本，不发送床旁原量、GCS或临床声明，不执行计分；不证明临床适用、历史感染已知性或效果验证，不改变功能启停与验证状态。",
        },
    }


@router.post("/ai/admin/providers/{provider_id}/sofa-capabilities")
async def check_sofa_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect actual rule/runtime metadata without sending observations or scoring."""
    from app.ai.sofa_probe import inspect_sofa_capabilities

    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "sepsis_risk" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记脓毒症辅助资料核对的独立SOFA-1完整原资料规则服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()
    error = None
    try:
        capabilities = await inspect_sofa_capabilities(provider)
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
        audit(db, actor_id, "provider.sofa_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际规则实现及运行版本不同，请核对并保存后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于规则服务处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.sofa_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "只核对六轴固定原单位规则、输入政策、四个实际核心文件及运行版本，不发送患者原件、不执行计分；不证明适用性、感染归因或临床效果，不改变功能启停与验证状态。",
        },
    }


@router.post("/ai/admin/providers/{provider_id}/roster-capabilities")
async def check_roster_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect schema10 metadata, without personnel, demand or optimization."""
    from app.ai.roster_probe import inspect_roster_capabilities

    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "roster_optimization" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记排班与日期号源优化的独立规则服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()
    error = None
    try:
        capabilities = await inspect_roster_capabilities(provider)
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
        audit(db, actor_id, "provider.roster_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际规则实现及运行版本不同，请核对并保存后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于优化服务处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.roster_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "只核对固定排班约束、两种优化目标、输入政策、四个实际核心文件、时区数据库摘要及运行版本；不发送人员原件或日期需求，不执行优化，不证明业务效果，不改变功能启停与验证状态。",
        },
    }


@router.post("/ai/admin/providers/{provider_id}/bed-capabilities")
async def check_bed_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect schema11 metadata without Ward originals, capacity or forecasting."""
    from app.ai.bed_probe import inspect_bed_capabilities

    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "bed_forecast" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记病区实占及流转事件预测的独立统计服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()
    error = None
    try:
        capabilities = await inspect_bed_capabilities(provider)
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
        audit(db, actor_id, "provider.bed_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际规则实现及运行版本不同，请核对并保存后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于床位预测服务处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.bed_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "只核对五项实占与流转目标、固定预测与回测政策、四个实际核心文件、时区数据库摘要及运行版本；不发送病区原件或容量，不执行预测，不证明业务效果，不改变功能启停与验证状态。",
        },
    }


@router.post("/ai/admin/providers/{provider_id}/surgery-capabilities")
async def check_surgery_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect schema12 metadata without cases, resource facts or scheduling."""
    from app.ai.surgery_probe import inspect_surgery_capabilities

    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "surgery_scheduling" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记手术排程的独立阶段资源优化服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()
    error = None
    try:
        capabilities = await inspect_surgery_capabilities(provider)
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
        audit(db, actor_id, "provider.surgery_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际固定约束、配方及运行版本不同，请核对并保存后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于手术优化处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.surgery_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "只核对声明阶段资源、两种目标、固定输入政策、四个核心文件及实际运行版本；不发送病例或资源原件，不执行排程或预订，不证明临床及运营效果，不改变功能启停与验证状态。",
        },
    }


@router.post("/ai/admin/providers/{provider_id}/supply-capabilities")
async def check_supply_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect schema13 metadata without SKU originals, quantities or forecasting."""
    from app.ai.supply_probe import inspect_supply_capabilities

    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "supply_forecast" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记物资预测的独立原量预测服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()
    error = None
    try:
        capabilities = await inspect_supply_capabilities(provider)
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
        audit(db, actor_id, "provider.supply_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际固定约束、配方及运行版本不同，请核对并保存后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于物资预测处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.supply_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "只核对三类原量目标、固定六模型与回测政策、四个核心文件、时区数据库及实际运行版本；不发送物资、单位或原量原件，不执行预测或采购，不证明实际运营效果，不改变功能启停与验证状态。",
        },
    }


@router.post("/ai/admin/providers/{provider_id}/inventory-capabilities")
async def check_inventory_provider(provider_id: int, req: ProviderCheck, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect schema14 metadata without SKU originals, quantities or comparison."""
    from app.ai.inventory_probe import inspect_inventory_capabilities

    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "模型配置不存在")
    ensure_revision(provider.revision, req.expected_revision)
    if provider.kind != "specialist" or "inventory_optimization" not in json.loads(provider.supported_features_json):
        raise HTTPException(422, "请选择已登记库存候选比较的独立候选比较服务")
    actor_id, revision, configured_model, timeout = user.user_id, provider.revision, provider.model, provider.timeout_seconds
    db.expunge(provider)
    db.commit()
    error = None
    try:
        capabilities = await inspect_inventory_capabilities(provider)
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
        audit(db, actor_id, "provider.inventory_check_failed", str(provider_id), {"revision": revision, "error_code": error.code})
        _commit(db)
        raise HTTPException(502, error.message)
    issues = []
    if capabilities["model_version"] != configured_model:
        issues.append("登记模型与服务实际固定约束、配方及运行版本不同，请核对并保存后重新评审")
    if timeout <= capabilities["timeout_seconds"]:
        issues.append("模型请求超时应大于库存候选比较处理时限，保留传输和回执时间")
    audit(db, actor_id, "provider.inventory_check", str(provider_id), {"revision": revision, "compatible": not issues, "actual_model": capabilities["model_version"]})
    _commit(db)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "provider_id": provider_id,
            "provider_revision": revision,
            "configured_model": configured_model,
            "compatible": not issues,
            "capabilities": capabilities,
            "issues": issues,
            "scope_note": "只核对完整有限采购候选、逐日效期与冻结量守恒、明确采购成本、共同约束政策、四个核心文件、时区数据库及实际运行版本；不发送库存或采购原件，不执行比较或采购，不证明实际运营效果，不改变功能启停与验证状态。",
        },
    }


@router.get("/ai/admin/runs")
def list_global_runs(
    feature_key: str | None = None,
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = None,
    outcome: Literal["accepted", "rejected", "modified"] | None = None,
    requested_by: int | None = Query(None, ge=1),
    patient_id: int | None = Query(None, ge=1),
    department_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    surgery_pool_id: str | None = Query(None, max_length=36),
    surgery_scenario_id: str | None = Query(None, max_length=36),
    supply_item_kind: str | None = Query(None, max_length=20),
    supply_item_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    supply_series_id: str | None = Query(None, max_length=36),
    inventory_item_kind: str | None = Query(None, max_length=20),
    inventory_item_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    inventory_scenario_id: str | None = Query(None, max_length=36),
    coding_case_id: str | None = Query(None, max_length=36),
    charge_case_id: str | None = Query(None, max_length=36),
    satisfaction_case_id: str | None = None,
    satisfaction_native_only: bool = False,
    encounter_ref: str | None = Query(None, max_length=64),
    document_original_id: str | None = Query(None, max_length=36),
    drug_label_source_binding_id: str | None = None,
    document_change_scope_id: str | None = Query(None, max_length=36),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> dict:
    """Return all users' audited task metadata and feedback counts without exposing full payloads."""
    from app.ai.native_task_access import lock_directory_gates

    # A global directory may contain native charge tasks. Billing precedes
    # current User/Run/Artifact locks even when no feature filter was supplied.
    lock_directory_gates(db)
    user = _current_super_admin(db, user)
    query = db.query(AIRun).options(*(defer(getattr(AIRun, key)) for key in ("input_json", "evidence_json", "context_metadata_json", "result_json")))
    if feature_key == "guideline_change_review" or document_change_scope_id is not None:
        from app.ai.document_change_history import filter_history

        query = filter_history(
            db,
            user,
            query,
            feature_key=feature_key,
            scope_id=document_change_scope_id,
            other_scope=(
                patient_id,
                encounter_ref,
                department_id,
                surgery_pool_id,
                surgery_scenario_id,
                supply_item_kind,
                supply_item_id,
                supply_series_id,
                inventory_item_kind,
                inventory_item_id,
                inventory_scenario_id,
                coding_case_id,
                charge_case_id,
                document_original_id,
                satisfaction_case_id,
                True if satisfaction_native_only else None,
                drug_label_source_binding_id,
            ),
            frozen_audit=True,
        )
    if drug_label_source_binding_id is not None:
        from app.ai.drug_label_history import filter_history

        query = filter_history(
            db,
            user,
            query,
            feature_key=feature_key,
            binding_id=drug_label_source_binding_id,
            other_scope=(
                patient_id,
                encounter_ref,
                department_id,
                surgery_pool_id,
                surgery_scenario_id,
                supply_item_kind,
                supply_item_id,
                supply_series_id,
                inventory_item_kind,
                inventory_item_id,
                inventory_scenario_id,
                coding_case_id,
                charge_case_id,
                document_original_id,
                satisfaction_case_id,
                True if satisfaction_native_only else None,
                document_change_scope_id,
            ),
        )
    if satisfaction_case_id is not None or satisfaction_native_only:
        from app.ai.satisfaction_history import filter_history

        query = filter_history(
            db,
            user,
            query,
            feature_key=feature_key,
            case_id=satisfaction_case_id,
            native_only=satisfaction_native_only,
            other_scope=(
                patient_id,
                encounter_ref,
                department_id,
                surgery_pool_id,
                surgery_scenario_id,
                supply_item_kind,
                supply_item_id,
                supply_series_id,
                inventory_item_kind,
                inventory_item_id,
                inventory_scenario_id,
                coding_case_id,
                charge_case_id,
                document_original_id,
                drug_label_source_binding_id,
                document_change_scope_id,
            ),
        )
    if feature_key == "guideline_ingestion" or document_original_id is not None:
        from app.ai.document_extraction_history import filter_document_history

        query = filter_document_history(
            db,
            user,
            query,
            feature_key=feature_key,
            original_id=document_original_id,
            other_scope=(
                patient_id,
                True if satisfaction_native_only else None,
                satisfaction_case_id,
                encounter_ref,
                charge_case_id,
                drug_label_source_binding_id,
                department_id,
                surgery_pool_id,
                surgery_scenario_id,
                supply_item_kind,
                supply_item_id,
                supply_series_id,
                inventory_item_kind,
                inventory_item_id,
                inventory_scenario_id,
                coding_case_id,
                document_change_scope_id,
            ),
        )
    if encounter_ref is not None and feature_key != "charge_reconciliation":
        raise HTTPException(422, "该管理历史的住院筛选仅用于完整账目功能")
    if charge_case_id is not None:
        if feature_key != "charge_reconciliation" or any(
            value is not None
            for value in (
                document_original_id,
                department_id,
                surgery_pool_id,
                surgery_scenario_id,
                supply_item_kind,
                supply_item_id,
                supply_series_id,
                inventory_item_kind,
                inventory_item_id,
                inventory_scenario_id,
                coding_case_id,
            )
        ):
            raise HTTPException(422, "账目管理历史仅筛选一件完整住院账目及其实际患者住院")
        from app.ai.charge_reconciliation_history import filter_history

        query = filter_history(db, user, query, charge_case_id=charge_case_id, patient_id=patient_id, encounter_ref=encounter_ref)
    elif coding_case_id is not None:
        if feature_key != "drg_evidence_review" or any(
            value is not None
            for value in (department_id, surgery_pool_id, surgery_scenario_id, supply_item_kind, supply_item_id, supply_series_id, inventory_item_kind, inventory_item_id, inventory_scenario_id)
        ):
            raise HTTPException(422, "编码证据管理历史仅筛选明确病案快照及其实际患者")
        from app.ai.coding_evidence_history import filter_history

        query = filter_history(db, user, query, coding_case_id=coding_case_id, patient_id=patient_id)
    elif any(value is not None for value in (inventory_item_kind, inventory_item_id, inventory_scenario_id)):
        if feature_key != "inventory_optimization" or any(
            value is not None for value in (patient_id, department_id, surgery_pool_id, surgery_scenario_id, supply_item_kind, supply_item_id, supply_series_id)
        ):
            raise HTTPException(422, "库存比较管理历史仅筛选明确品种与原场景，不能与其他运营或患者范围混用")
        from app.ai.inventory_history import filter_history

        query = filter_history(db, user, query, inventory_item_kind=inventory_item_kind, inventory_item_id=inventory_item_id, inventory_scenario_id=inventory_scenario_id)
    elif any(value is not None for value in (supply_item_kind, supply_item_id, supply_series_id)):
        if feature_key != "supply_forecast" or any(value is not None for value in (patient_id, department_id, surgery_pool_id, surgery_scenario_id)):
            raise HTTPException(422, "物资管理历史仅筛选明确品种与原序列，不能与科室、其他运营或患者范围混用")
        from app.ai.supply_history import filter_history

        query = filter_history(db, user, query, supply_item_kind=supply_item_kind, supply_item_id=supply_item_id, supply_series_id=supply_series_id)
    elif department_id is not None or surgery_pool_id is not None or surgery_scenario_id is not None:
        if feature_key != "surgery_scheduling" or patient_id is not None:
            raise HTTPException(422, "手术管理历史筛选仅用于手术科室、资源池或原场景")
        from app.ai.surgery_history import filter_history

        actor = db.query(User).filter_by(user_id=user.user_id).populate_existing().one_or_none()
        if actor is None or actor.user_role != "super_admin":
            raise HTTPException(403, "当前身份已无超级管理员历史审计权限")
        query = filter_history(db, actor, query, department_id=department_id, surgery_pool_id=surgery_pool_id, surgery_scenario_id=surgery_scenario_id)
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
    if encounter_ref is not None:
        query = query.filter(AIRun.encounter_ref == encounter_ref)
    total = query.with_entities(func.count(AIRun.run_id)).with_for_update(read=True).scalar() if feature_key == "charge_reconciliation" else query.count()
    rows = (
        query.options(defer(AIRun.input_json), defer(AIRun.result_json), defer(AIRun.evidence_json), defer(AIRun.context_metadata_json))
        .order_by(AIRun.create_time.desc(), AIRun.run_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    counts = dict(db.query(AIFeedback.run_id, func.count(AIFeedback.feedback_id)).filter(AIFeedback.run_id.in_([item.run_id for item in rows])).group_by(AIFeedback.run_id).all()) if rows else {}
    from app.ai.document_change_storage import is_document_change_run
    from app.ai.document_change_views import run_view

    data = [
        {
            **(run_view(db, user, item, False, current=False) if is_document_change_run(db, item) else describe_run(item, False, user=user)),
            "requested_by": item.requested_by,
            "provider_id": item.provider_id,
            "feedback_count": counts.get(item.run_id, 0),
        }
        for item in rows
    ]
    return {"code": 200, "msg": "success", "data": data, "total": total, "page": page, "page_size": page_size}


@router.get("/ai/admin/runs/{run_id}")
def inspect_run_trace(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Read the frozen prompts, requested model, source payload and append-only review history."""
    from app.ai.native_task_access import guard_private_task_read, lock_directory_gates

    lock_directory_gates(db)
    user = _current_super_admin(db, user)
    from app.ai.document_change_runtime import guard_change_run_id
    from app.ai.document_change_views import trace_view
    from app.ai.native_task_routing import locate_native_task

    locate_native_task(db, run_id)  # Reject contradictory immutable anchors.
    if guard_change_run_id(db, user, run_id, current=False):
        return {"code": 200, "msg": "success", "data": trace_view(db, user, db.get(AIRun, run_id))}
    guard_private_task_read(db, user, run_id)
    run = db.get(AIRun, run_id)
    if run is None:
        raise HTTPException(404, "AI 任务不存在")
    from app.ai.drug_label_storage import is_drug_label_run

    if is_drug_label_run(db, run):
        from app.ai.drug_label_views import response, trace_view

        return response(trace_view(db, user, run))
    from app.ai.charge_reconciliation_storage import is_charge_run

    charge = is_charge_run(db, run)
    if charge:
        from app.ai.charge_reconciliation_runtime import authorize_charge_run

        authorize_charge_run(db, user, run)
    from app.ai.satisfaction_storage import is_satisfaction_run

    satisfaction = not charge and is_satisfaction_run(db, run)
    satisfaction_trace = {}
    if satisfaction:
        from app.ai.satisfaction_views import trace_proof

        snapshot, satisfaction_trace = trace_proof(db, user, run)
    from app.ai.document_extraction_storage import authorize_document_run, is_extraction_run

    document_trace = {}
    if not charge and not satisfaction and is_extraction_run(db, run):
        snapshot, _, _ = authorize_document_run(db, user, run, current=False)
        document_trace = {"frozen_request_json": run.input_json, "frozen_evidence_json": run.evidence_json, "frozen_context_metadata_json": run.context_metadata_json}
    elif not satisfaction:
        snapshot = json.loads(run.input_json)
    from app.ai.coding_evidence_storage import is_coding_run

    if is_coding_run(db, run):
        from app.ai.coding_evidence_context import expand_context
        from app.ai.runtime import authorize_run

        authorize_run(db, user, run)
        snapshot["payload"]["context"] = expand_context(db, snapshot["payload"]["context"])
    from app.ai.inventory_storage import is_inventory_snapshot

    if is_inventory_snapshot(snapshot):
        from app.ai.inventory_context import expand_context
        from app.ai.runtime import authorize_run

        authorize_run(db, user, run)
        snapshot["payload"]["context"] = expand_context(db, snapshot["payload"]["context"])
    from app.ai.supply_storage import is_supply_snapshot

    if is_supply_snapshot(snapshot):
        from app.ai.runtime import authorize_run
        from app.ai.supply_context import expand_context

        actor = db.query(User).filter_by(user_id=user.user_id).populate_existing().one_or_none()
        if actor is None or actor.user_role != "super_admin":
            raise HTTPException(403, "当前身份已无超级管理员完整物资审计权限")
        authorize_run(db, actor, run)
        snapshot["payload"]["context"] = expand_context(db, snapshot["payload"]["context"])
    from app.ai.surgery_storage import is_surgery_snapshot

    if is_surgery_snapshot(snapshot):
        from app.ai.runtime import authorize_run
        from app.ai.surgery_context import expand_context

        actor = db.query(User).filter_by(user_id=user.user_id).populate_existing().one_or_none()
        if actor is None or actor.user_role != "super_admin":
            raise HTTPException(403, "当前身份已无超级管理员完整手术审计权限")
        authorize_run(db, actor, run)
        snapshot["payload"]["context"] = expand_context(db, snapshot["payload"]["context"])
    if snapshot.get("payload", {}).get("context", {}).get("roster_binding"):
        from app.ai.roster_context import authorize_roster_snapshot, expand_context

        authorize_roster_snapshot(db, user, snapshot["payload"]["context"])
        snapshot["payload"]["context"] = expand_context(db, snapshot["payload"]["context"])
    if snapshot.get("payload", {}).get("context", {}).get("bed_binding"):
        from app.ai.bed_context import authorize_bed_snapshot, expand_context

        authorize_bed_snapshot(db, user, snapshot["payload"]["context"])
        snapshot["payload"]["context"] = expand_context(db, snapshot["payload"]["context"])
    if snapshot.get("payload", {}).get("context", {}).get("sofa_binding"):
        from app.ai.sofa_context import expand_context

        snapshot["payload"]["context"] = expand_context(db, snapshot["payload"]["context"])
    feedback = db.query(AIFeedback).filter_by(run_id=run_id).order_by(AIFeedback.create_time.desc(), AIFeedback.feedback_id).limit(101).all()
    response = {
        "code": 200,
        "msg": "success",
        "data": {
            **describe_run(run, user=user),
            **document_trace,
            **satisfaction_trace,
            "requested_by": run.requested_by,
            "provider_id": run.provider_id,
            "frozen_request": snapshot,
            **({"raw_frozen_json": {"input_json": run.input_json, "evidence_json": run.evidence_json, "context_metadata_json": run.context_metadata_json}} if charge else {}),
            "snapshot_complete": all(key in snapshot for key in ("system_prompt", "provider_snapshot", "catalog_version")),
            "feedback": [{name: getattr(item, name) for name in ("feedback_id", "reviewer_id", "outcome", "comment", "create_time")} for item in feedback[:100]],
            "feedback_truncated": len(feedback) > 100,
        },
    }
    if satisfaction:
        from app.ai.satisfaction_views import TRACE_RESPONSE_BYTES, checked_response

        return checked_response(response, TRACE_RESPONSE_BYTES)
    return response


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
    from app.ai.feature_prompts import system_prompt_for_feature

    _current_super_admin(db, user)
    spec = get_spec(key)
    versions = db.query(AIPromptVersion).filter_by(feature_key=key).order_by(AIPromptVersion.version.desc()).all()
    baseline = {"prompt_id": None, "version": 0, "task_prompt": spec.task_prompt, "change_note": "项目默认任务 Prompt"}
    data = [{name: getattr(item, name) for name in ("prompt_id", "version", "task_prompt", "change_note", "created_by", "create_time")} for item in versions]
    return {
        "code": 200,
        "msg": "success",
        "data": {"system_prompt": system_prompt_for_feature(spec), "versions": [*data, baseline]},
    }


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
    _current_super_admin(db, user)
    items = db.query(AIKnowledgeDocument).order_by(AIKnowledgeDocument.create_time.desc()).limit(limit).all()
    names = ("document_id", "title", "version", "source_uri", "category", "status", "content_hash", "department_id", "effective_from", "effective_to", "reviewed_by", "reviewed_at", "create_time")
    data = [
        {
            **{name: getattr(item, name) for name in names},
            "feature_keys": json.loads(item.feature_keys_json),
            "source_kind": item.source_kind,
            "source_reference_id": item.source_reference_id,
            "source_state": source_state(db, item),
            "document_evidence_bound": is_document_source(db, item),
        }
        for item in items
    ]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/ai/admin/knowledge/{document_id}")
def knowledge_detail(document_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect exact text and its hash before a publication decision."""
    _current_super_admin(db, user)
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
            "document_evidence_bound": is_document_source(db, item),
        },
    }


@router.post("/ai/admin/knowledge")
def create_knowledge(req: KnowledgeWrite, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Create an immutable draft without fetching arbitrary external URLs."""
    _current_super_admin(db, user)
    try:
        content_bytes = len(req.content.encode("utf-8", errors="strict"))
    except UnicodeError as exc:
        raise HTTPException(422, "知识正文须为有效UTF8，未登记或替换字符") from exc
    if content_bytes > 65535:
        raise HTTPException(422, "完整知识正文超过65535个UTF8字节，未截断或登记")
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
    _current_super_admin(db, user)
    # Document publication/revocation locks parents before knowledge. Reject
    # this alternate writer before taking a knowledge X lock, including when
    # mutable URI/kind markers were stripped from a still-bound row.
    item = lock_manual_review_target(db, document_id)
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
