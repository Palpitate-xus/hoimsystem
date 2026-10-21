"""Governance helpers shared by super-admin APIs and the execution service."""

import base64
import hashlib
import json
import os
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.catalog import FEATURE_BY_KEY, FeatureSpec, describe_feature
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIProvider
from app.config import settings


def encode_json(value: object) -> str:
    """Serialize portable UTF-8 JSON with deterministic ordering."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: object) -> str:
    """Identify exact prompt, context or knowledge versions without exposing content."""
    return hashlib.sha256(encode_json(value).encode()).hexdigest()


def get_spec(key: str) -> FeatureSpec:
    """Resolve catalog identity without allowing arbitrary executable task names."""
    spec = FEATURE_BY_KEY.get(key)
    if spec is None:
        raise HTTPException(404, "AI 功能不存在")
    return spec


def audit(db: Session, actor_id: int, action: str, target: str, detail: dict | None = None) -> None:
    """Stage an audit event in the caller's transaction; never include secrets."""
    db.add(AIAuditEvent(actor_id=actor_id, action=action, target=target, detail_json=encode_json(detail or {})))


def ensure_revision(actual: int, expected: int) -> None:
    """Reject lost updates when another administrator has already changed a resource."""
    if actual != expected:
        raise HTTPException(409, "配置已被修改，请刷新后重试")


def flush_or_conflict(db: Session) -> None:
    """Convert concurrent inserts and duplicate names into safe conflicts."""
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "名称、版本或配置已存在，请刷新后重试") from exc


def feature_config(db: Session, key: str, actor_id: int, expected: int) -> AIFeatureConfig:
    """Lock or create a configuration only in an explicit management mutation."""
    spec = get_spec(key)
    config = db.query(AIFeatureConfig).filter_by(feature_key=key).with_for_update().first()
    ensure_revision(config.revision if config else 0, expected)
    if config is None:
        config = AIFeatureConfig(feature_key=key, allowed_roles_json=encode_json(spec.default_roles), updated_by=actor_id, revision=0)
        db.add(config)
        flush_or_conflict(db)
    return config


def invalidate_feature(config: AIFeatureConfig) -> None:
    """A model/prompt change requires a fresh activation decision."""
    config.enabled = 0
    config.validation_status = "unreviewed"
    config.validated_by = None
    config.validated_at = None


def validate_endpoint(value: str) -> str:
    """Restrict egress to deployment-approved model hosts and disable URL credentials."""
    try:
        url = urlsplit(value.strip())
        host = (url.hostname or "").lower()
        port = url.port
    except ValueError as exc:
        raise HTTPException(422, "模型地址格式无效") from exc
    allowed = {item.strip().lower() for item in settings.AI_PROVIDER_ALLOWED_HOSTS.split(",") if item.strip()}
    if host not in allowed:
        raise HTTPException(422, "模型主机尚未加入 AI_PROVIDER_ALLOWED_HOSTS")
    if url.scheme not in {"https", "http"} or not host or url.username or url.password or url.query or url.fragment:
        raise HTTPException(422, "模型地址必须是无凭据、无查询参数的 HTTP(S) 地址")
    if url.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(422, "非本机模型端点必须使用 HTTPS")
    if port is not None and not 1 <= port <= 65535:
        raise HTTPException(422, "模型端口无效")
    return value.strip().rstrip("/")


def _cipher() -> Fernet:
    """A separate stable key enables credential storage; plaintext is never persisted."""
    if len(settings.AI_CREDENTIAL_KEY) < 32:
        raise HTTPException(503, "保存模型密钥前请配置至少32字符的 AI_CREDENTIAL_KEY，也可使用环境变量引用")
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.AI_CREDENTIAL_KEY.encode()).digest())
    return Fernet(key)


def encrypt_credential(secret: str) -> str:
    """Encrypt write-only provider credentials under the deployment key."""
    return _cipher().encrypt(secret.encode()).decode()


def provider_credential(provider: AIProvider) -> str:
    """Resolve credentials at execution time and return a sanitized configuration error."""
    if provider.api_key_env:
        credential = os.environ.get(provider.api_key_env, "")
        if not credential:
            raise HTTPException(503, "模型密钥环境变量尚未配置")
        return credential
    if provider.api_key_encrypted:
        try:
            return _cipher().decrypt(provider.api_key_encrypted.encode()).decode()
        except InvalidToken as exc:
            raise HTTPException(503, "模型密钥无法解密，请检查部署密钥并重新保存") from exc
    return ""  # Local gateways may intentionally require no API token.


def describe_provider(provider: AIProvider) -> dict:
    """Expose configuration while keeping encrypted and plaintext secrets private."""
    fields = (
        "provider_id",
        "name",
        "kind",
        "api_base",
        "model",
        "api_key_env",
        "enabled",
        "allows_patient_data",
        "timeout_seconds",
        "max_output_tokens",
        "temperature",
        "validation_report",
        "validated_at",
        "revision",
        "create_time",
        "update_time",
    )
    data = {name: getattr(provider, name) for name in fields}
    data["has_api_key"] = bool(provider.api_key_encrypted or provider.api_key_env)
    data["supported_features"] = json.loads(provider.supported_features_json)
    return data


def active_prompt(db: Session, spec: FeatureSpec, config: AIFeatureConfig | None) -> tuple[str, int]:
    """Resolve a saved immutable version or the packaged baseline."""
    if config and config.active_prompt_id:
        prompt = db.get(AIPromptVersion, config.active_prompt_id)
        if prompt is None or prompt.feature_key != spec.key:
            raise HTTPException(409, "功能 Prompt 版本配置无效")
        return prompt.task_prompt, prompt.version
    return spec.task_prompt, 0


def provider_feature_issues(spec: FeatureSpec, provider: AIProvider) -> list[dict]:
    """Share protocol and data-purpose checks between activation, execution and setup inspection."""
    issues = []
    if provider.model.startswith("inventory:") and (spec.number != 67 or provider.kind != "specialist"):
        issues.append({"code": "INVENTORY_SCOPE_MISMATCH", "message": "本地库存服务仅比较受审完整有限采购候选及逐日精确守恒和明确成本，不执行采购、调拨或库存写入"})
    if provider.model.startswith("supply:") and (spec.number != 66 or provider.kind != "specialist"):
        issues.append({"code": "SUPPLY_SCOPE_MISMATCH", "message": "本地物资服务仅用于单品种受审原量序列的固定预测，不推断潜在需求、采购量或承诺交期"})
    if provider.model.startswith("surgery:") and (spec.number != 65 or provider.kind != "specialist"):
        issues.append({"code": "SURGERY_SCOPE_MISMATCH", "message": "本地手术服务仅用于受审完整病例与共享资源声明场景的固定约束候选，不执行预订或临床处置"})
    if provider.model.startswith("roster:") and (spec.number != 63 or provider.kind != "specialist"):
        issues.append({"code": "ROSTER_SCOPE_MISMATCH", "message": "本地排班服务仅用于受审运营场景的固定约束与优化证明"})
    if provider.model.startswith("bed:") and (spec.number != 64 or provider.kind != "specialist"):
        issues.append({"code": "BED_SCOPE_MISMATCH", "message": "本地床位服务仅用于受审病区实占及流转事件序列的固定统计预测，不推断未满足需求或即时可收治床位"})
    if provider.model.startswith("sofa1:") and (spec.number != 42 or provider.kind != "specialist"):
        issues.append({"code": "SOFA_SCOPE_MISMATCH", "message": "本地SOFA-1固定实施仅用于完整原资料及独立变化核对，不用于自动诊断、风险概率或治疗"})
    if provider.model.startswith("news2:") and (spec.number != 41 or provider.kind != "specialist"):
        issues.append({"code": "NEWS2_SCOPE_MISMATCH", "message": "NEWS2规则服务只用于病情恶化预警的独立评分，不用于其他模型、脓毒症诊断或概率预测"})
    if provider.model.startswith("aki:") and (spec.number != 43 or provider.kind != "specialist"):
        issues.append({"code": "AKI_SCOPE_MISMATCH", "message": "KDIGO AKI规则只用于独立核对所选肾功能资料，不用于其他模型、未来风险概率或自动治疗"})
    if provider.model.startswith("qsofa:") and (spec.number != 42 or provider.kind != "specialist"):
        issues.append({"code": "QSOFA_SCOPE_MISMATCH", "message": "qSOFA只用于独立核对所选床旁三项资料，不用于单一脓毒症筛查、诊断、排除或风险概率"})
    if spec.engine == "llm" and provider.kind not in {"chat", "responses"}:
        issues.append({"code": "PROTOCOL_MISMATCH", "message": "该能力需要文本模型接口"})
    if spec.engine != "llm" and (provider.kind != "specialist" or spec.key not in json.loads(provider.supported_features_json) or not provider.validation_report):
        issues.append({"code": "SPECIALIST_NOT_READY", "message": "专用模型适配器、功能声明及验证报告尚未就绪"})
    if spec.requires_patient_data_permission and not provider.allows_patient_data:
        issues.append({"code": "PATIENT_DATA_NOT_APPROVED", "message": "该模型服务尚未获准处理患者资料"})
    return issues


def describe_config(db: Session, spec: FeatureSpec, config: AIFeatureConfig | None, management: bool = False) -> dict:
    """Keep configured, implementation and validation status independently visible."""
    data = describe_feature(spec)
    if spec.number == 69:
        data["input_mode"] = "charge_reconciliation"
    if spec.number == 70:
        data["input_mode"] = "satisfaction_evidence"
    if spec.number == 73:
        data["input_mode"] = "drug_label_evidence"
    if spec.number == 72:
        data["input_mode"] = "document_change_evidence"
    if spec.number == 71:
        data["input_mode"] = "document_extraction"
    if spec.number == 68:
        data["input_mode"] = "coding_evidence"
    if spec.number == 63:
        provider = db.get(AIProvider, config.provider_id) if config and config.provider_id else None
        data["input_mode"] = "roster" if provider and provider.kind == "specialist" and provider.model.startswith("roster:") else "external_optimizer"
    if spec.number == 64:
        provider = db.get(AIProvider, config.provider_id) if config and config.provider_id else None
        data["input_mode"] = "bed" if provider and provider.kind == "specialist" and provider.model.startswith("bed:") else "external_forecast"
    if spec.number == 65:
        provider = db.get(AIProvider, config.provider_id) if config and config.provider_id else None
        data["input_mode"] = "surgery" if provider and provider.kind == "specialist" and provider.model.startswith("surgery:") else "external_optimizer"
    if spec.number == 67:
        provider = db.get(AIProvider, config.provider_id) if config and config.provider_id else None
        data["input_mode"] = "inventory" if provider and provider.kind == "specialist" and provider.model.startswith("inventory:") else "external_optimizer"
    if spec.number == 66:
        provider = db.get(AIProvider, config.provider_id) if config and config.provider_id else None
        data["input_mode"] = "supply" if provider and provider.kind == "specialist" and provider.model.startswith("supply:") else "external_forecast"
    if spec.number in {41, 42, 43}:
        provider = db.get(AIProvider, config.provider_id) if config and config.provider_id else None
        mode = {41: "news2", 42: "qsofa", 43: "aki"}.get(spec.number)
        if spec.number == 42 and provider and provider.model.startswith("sofa1:"):
            mode = "sofa1"
        data["input_mode"] = mode if mode and provider and provider.kind == "specialist" and provider.model.startswith(mode + ":") else "observation_window"
    roles = json.loads(config.allowed_roles_json) if config else list(spec.default_roles)
    _, version = active_prompt(db, spec, config)
    data.update(
        {
            "enabled": bool(config and config.enabled),
            "allowed_roles": roles,
            "validation_status": config.validation_status if config else "unreviewed",
            "prompt_version": version,
            "revision": config.revision if config else 0,
            "implementation_status": "gateway" if spec.engine == "llm" else "requires_specialist_adapter",
            "daily_limit": config.daily_limit if config else 100,
            "provider_configured": bool(config and config.provider_id),
        }
    )
    if management:
        from app.ai.feature_prompts import system_prompt_for_feature

        data.update(
            {
                "provider_id": config.provider_id if config else None,
                "active_prompt_id": config.active_prompt_id if config else None,
                "validation_note": config.validation_note if config else "",
                "validated_by": config.validated_by if config else None,
                "validated_at": config.validated_at if config else None,
                "system_prompt_hash": digest(system_prompt_for_feature(spec)),
            }
        )
    return data
