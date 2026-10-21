"""Actual operational activation and execution gates, independent of source attestation."""

import uuid

import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY, FEATURES
from app.ai.governance import encode_json
from app.ai.models import AIFeatureConfig, AIProvider, utcnow
from app.ai.readiness import setup_reports
from app.ai.runtime import check_configuration

OPERATIONS = tuple(spec.key for spec in FEATURES if spec.number in range(62, 68))


def case(db, seed, key, status):
    spec = FEATURE_BY_KEY[key]
    config = db.get(AIFeatureConfig, key)
    if config is not None:
        db.delete(config)
        db.flush()
    provider = AIProvider(
        name="scope-validation-" + key + "-" + status + "-" + uuid.uuid4().hex[:8],
        api_base="http://localhost:11434",
        model="isolated-adapter",
        kind="specialist",
        supported_features_json=encode_json([key]),
        validation_report="合成适配器工程声明；不构成实际业务目标和范围验证",
        enabled=1,
        allows_patient_data=1,
        created_by=seed["super_admin_user"].user_id,
    )
    db.add(provider)
    db.flush()
    config = AIFeatureConfig(
        feature_key=key,
        provider_id=provider.provider_id,
        enabled=0,
        validation_status=status,
        validation_note="合成状态测试，不使用真实医院业务验证记录",
        validated_by=seed["super_admin_user"].user_id if status == "validated" else None,
        validated_at=utcnow() if status == "validated" else None,
        allowed_roles_json=encode_json(spec.default_roles),
        updated_by=seed["super_admin_user"].user_id,
        revision=1,
    )
    db.add(config)
    db.commit()
    return spec, provider, config


@pytest.mark.parametrize("key", OPERATIONS)
@pytest.mark.parametrize("status", ["unreviewed", "pilot", "suspended"])
@pytest.mark.asyncio
async def test_adapter_report_does_not_enable_unvalidated_operational_models(async_client, db_session, seed_data, auth_headers, key, status):
    spec, provider, config = case(db_session, seed_data, key, status)
    response = await async_client.put(
        "/api/ai/admin/features/" + key,
        headers=auth_headers(seed_data["super_admin_user"].username),
        json={"expected_revision": config.revision, "enabled": True},
    )
    assert response.status_code == 422 and "验证" in response.text
    db_session.expire_all()
    retained = db_session.get(AIFeatureConfig, key)
    assert retained.enabled == 0 and retained.validation_status == status and retained.revision == 1
    report = setup_reports(db_session, {key: retained})[key]
    code = "OPTIMIZATION_VALIDATION_REQUIRED" if spec.engine == "optimizer" else "PREDICTION_VALIDATION_REQUIRED"
    assert not report["ready"] and code in {item["code"] for item in report["issues"]}
    assert provider.validation_report


@pytest.mark.parametrize("key", OPERATIONS)
def test_enabled_legacy_configuration_still_requires_scope_validation_before_source_loading(db_session, seed_data, key):
    spec, provider, config = case(db_session, seed_data, key, "unreviewed")
    config.enabled = 1
    db_session.commit()
    with pytest.raises(HTTPException) as denial:
        check_configuration(db_session, seed_data["admin_user"], spec, config, False)
    assert denial.value.status_code == 409 and "验证" in denial.value.detail
    assert check_configuration(db_session, seed_data["super_admin_user"], spec, config, True).provider_id == provider.provider_id
    assert config.validation_status == "unreviewed"


@pytest.mark.parametrize("key", OPERATIONS)
@pytest.mark.asyncio
async def test_explicit_validated_scope_can_activate_without_source_confirmation_mutating_it(async_client, db_session, seed_data, auth_headers, key):
    spec, provider, config = case(db_session, seed_data, key, "validated")
    response = await async_client.put(
        "/api/ai/admin/features/" + key,
        headers=auth_headers(seed_data["super_admin_user"].username),
        json={"expected_revision": config.revision, "enabled": True},
    )
    assert response.status_code == 200, response.text
    db_session.expire_all()
    retained = db_session.get(AIFeatureConfig, key)
    assert retained.validation_status == "validated" and retained.enabled == 1 and retained.revision == 2
    assert check_configuration(db_session, seed_data["admin_user"], spec, retained, False).provider_id == provider.provider_id
    assert setup_reports(db_session, {key: retained})[key]["ready"] is True


def test_scope_validation_policy_covers_all_operational_prediction_and_optimization():
    assert {spec.number for spec in FEATURES if spec.requires_operational_validation} == set(range(62, 68)) | {79}
    assert FEATURE_BY_KEY["operations_support"].requires_operational_validation
    assert not FEATURE_BY_KEY["research_cohort"].requires_operational_validation
    from app.ai.catalog import describe_feature

    assert describe_feature(FEATURE_BY_KEY["roster_optimization"])["requires_operational_validation"] is True
    assert describe_feature(FEATURE_BY_KEY["research_cohort"])["requires_operational_validation"] is False
