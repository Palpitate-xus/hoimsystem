"""Super-admin setup dependency inspection without sending model requests."""

import json

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import defer

from app.ai.catalog import FEATURES
from app.ai.governance import provider_credential, provider_feature_issues, validate_endpoint
from app.ai.knowledge_sources import source_is_current
from app.ai.models import AIKnowledgeDocument, AIProvider, AIRiskRuleProfile, utcnow
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
    rule_profile_ready = {}
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
            rule = {41: ("news2", "news2_2017", "NEWS2"), 42: ("qsofa", "qsofa_sepsis3_2016", "qSOFA"), 43: ("aki", "kdigo_aki_2012", "KDIGO AKI")}.get(spec.number)
            if spec.number == 42 and provider.model.startswith("sofa1:"):
                rule = ("sofa1", "sofa1_native_observed_v1", "SOFA-1本地原单位实施")
            if rule and provider.kind == "specialist" and provider.model.startswith(rule[0] + ":"):
                if rule[1] not in rule_profile_ready:
                    from app.ai.risk_rule_profiles import profile_current

                    if rule[0] == "news2":
                        from app.ai.news2_contract import recipe_digest
                    elif rule[0] == "qsofa":
                        from app.ai.qsofa_contract import recipe_digest
                    elif rule[0] == "sofa1":
                        from app.ai.sofa_contract import recipe_digest
                    else:
                        from app.ai.aki_contract import recipe_digest

                    rule_profile_ready[rule[1]] = False
                    rows = db.query(AIRiskRuleProfile).filter_by(rule_id=rule[1], recipe_digest=recipe_digest(), status="published").limit(2).all()
                    for row in rows:
                        try:
                            profile_current(db, row.rule_profile_id)
                        except HTTPException:
                            continue
                        rule_profile_ready[rule[1]] = True
                if not rule_profile_ready[rule[1]]:
                    issues.append({"code": rule[0].upper() + "_RULE_PROFILE_REQUIRED", "message": f"尚无当前固定{rule[2]}规则与输入策略的已审核发布版本，请由超级管理员核实"})
        if spec.clinical and (not config or config.validation_status != "validated"):
            issues.append({"code": "CLINICAL_VALIDATION_REQUIRED", "message": "临床能力尚未完成适用范围验证"})
        if spec.requires_operational_validation and (not config or config.validation_status != "validated"):
            optimization = spec.engine == "optimizer"
            issues.append(
                {
                    "code": "OPTIMIZATION_VALIDATION_REQUIRED" if optimization else "PREDICTION_VALIDATION_REQUIRED",
                    "message": "运营优化尚未完成指定目标与范围的验证；原件审核、约束算例和服务能力核对不代替实际业务验证"
                    if optimization
                    else "运营预测尚未完成指定目标与范围的验证；历史覆盖确认和服务能力检查不代替预测效果验证",
                }
            )
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
