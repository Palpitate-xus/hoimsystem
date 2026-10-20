"""Super-admin setup dependency inspection without sending model requests."""

import json

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import defer

from app.ai.catalog import FEATURES
from app.ai.governance import provider_credential, provider_feature_issues, validate_endpoint
from app.ai.models import AIKnowledgeDocument, AIProvider, utcnow
from app.ai.pathway_knowledge import source_is_current
from app.models import ClinicalPathway


def setup_reports(db, configs: dict) -> dict:
    """Inspect provider, data-purpose, knowledge and validation prerequisites in a bounded batch."""
    now = utcnow()
    providers = {item.provider_id: item for item in db.query(AIProvider).all()}
    published = set()
    documents = (
        db.query(AIKnowledgeDocument)
        .options(defer(AIKnowledgeDocument.content))
        .filter(
            AIKnowledgeDocument.status == "published",
            AIKnowledgeDocument.reviewed_by.isnot(None),
            AIKnowledgeDocument.reviewed_at.isnot(None),
            or_(AIKnowledgeDocument.effective_from.is_(None), AIKnowledgeDocument.effective_from <= now),
            or_(AIKnowledgeDocument.effective_to.is_(None), AIKnowledgeDocument.effective_to > now),
        )
        .all()
    )
    source_ids = {row.source_reference_id for row in documents if row.source_kind == "clinical_pathway"}
    sources = {row.pathway_id: row for row in db.query(ClinicalPathway).filter(ClinicalPathway.pathway_id.in_(source_ids)).all()} if source_ids else {}
    for row in documents:
        if source_is_current(db, row, sources):
            published.update(json.loads(row.feature_keys_json))
    provider_checks = {}
    for provider in providers.values():
        issues = []
        if not provider.enabled:
            issues.append({"code": "PROVIDER_DISABLED", "message": "模型服务尚未启用"})
        try:
            validate_endpoint(provider.api_base)
        except HTTPException as exc:
            issues.append({"code": "ENDPOINT_CONFIGURATION", "message": str(exc.detail)})
        try:
            provider_credential(provider)
        except HTTPException as exc:
            issues.append({"code": "CREDENTIAL_UNAVAILABLE", "message": str(exc.detail)})
        provider_checks[provider.provider_id] = issues
    reports = {}
    for spec in FEATURES:
        config = configs.get(spec.key)
        provider = providers.get(config.provider_id) if config and config.provider_id else None
        issues = []
        if not config or not config.enabled:
            issues.append({"code": "FEATURE_DISABLED", "message": "该能力尚未面向业务启用"})
        if provider is None:
            issues.append({"code": "MODEL_UNASSIGNED", "message": "尚未选择模型服务"})
        else:
            issues.extend(provider_checks[provider.provider_id])
            issues.extend(provider_feature_issues(spec, provider))
        if spec.clinical and (not config or config.validation_status != "validated"):
            issues.append({"code": "CLINICAL_VALIDATION_REQUIRED", "message": "临床能力尚未完成适用范围验证"})
        if config and config.validation_status == "suspended":
            issues.append({"code": "FEATURE_SUSPENDED", "message": "该能力处于暂停状态"})
        if spec.requires_knowledge and spec.key not in published:
            issues.append({"code": "KNOWLEDGE_NOT_PUBLISHED", "message": "尚无分配给该能力且仍有效的已审核知识"})
        reports[spec.key] = {
            "ready": not issues,
            "issues": issues,
            "checked_at": now,
            "scope_note": "基础依赖检查；实际执行仍按患者、科室、问题和资料范围核验，不代表模型联通测试或临床效果验证",
        }
    return reports
