"""Admin dependency checks expose actionable gaps while keeping provider secrets private."""

import datetime
import json

import pytest

from app.ai.governance import digest
from app.ai.models import AIFeatureConfig, AIKnowledgeDocument, AIProvider, utcnow


@pytest.fixture(autouse=True)
def reset_setup(db_session):
    db_session.query(AIFeatureConfig).delete()
    db_session.query(AIProvider).delete()
    db_session.query(AIKnowledgeDocument).delete()
    db_session.commit()


async def feature_setup(async_client, auth_headers, key):
    response = await async_client.get("/api/ai/admin/features", headers=auth_headers("super01"))
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["data"] if item["key"] == key)
    return row["setup_check"]


@pytest.mark.asyncio
async def test_unconfigured_capabilities_explain_missing_model_knowledge_and_validation(async_client, seed_data, auth_headers):
    check = await feature_setup(async_client, auth_headers, "treatment_pathway")
    assert check["ready"] is False
    assert {item["code"] for item in check["issues"]} == {"FEATURE_DISABLED", "MODEL_UNASSIGNED", "CLINICAL_VALIDATION_REQUIRED", "KNOWLEDGE_NOT_PUBLISHED"}
    denied = await async_client.get("/api/ai/admin/features", headers=auth_headers("admin"))
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_live_credential_resolution_does_not_expose_the_value(async_client, seed_data, auth_headers, db_session, monkeypatch):
    variable = "AI_PROVIDER_READINESS_TEST_API_KEY"
    monkeypatch.delenv(variable, raising=False)
    provider = AIProvider(
        name="readiness-credential",
        api_base="http://localhost:11434/v1",
        model="test",
        kind="chat",
        enabled=1,
        allows_patient_data=1,
        api_key_env=variable,
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key="patient_summary",
            provider_id=provider.provider_id,
            enabled=1,
            validation_status="validated",
            allowed_roles_json='["doctor","super_admin"]',
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    missing = await feature_setup(async_client, auth_headers, "patient_summary")
    assert {item["code"] for item in missing["issues"]} == {"CREDENTIAL_UNAVAILABLE"}
    monkeypatch.setenv(variable, "never-return-readiness-secret")
    available = await feature_setup(async_client, auth_headers, "patient_summary")
    assert available["ready"] is True
    assert "never-return-readiness-secret" not in json.dumps(available)


@pytest.mark.asyncio
async def test_only_effective_reviewed_published_knowledge_satisfies_setup_dependencies(async_client, seed_data, auth_headers, db_session):
    user_id = seed_data["super_admin_user"].user_id
    provider = AIProvider(name="readiness-knowledge", api_base="http://localhost:11434/v1", model="test", kind="chat", enabled=1, allows_patient_data=1, created_by=user_id)
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(feature_key="guideline_qa", provider_id=provider.provider_id, enabled=1, validation_status="validated", allowed_roles_json='["doctor","super_admin"]', updated_by=user_id)
    )
    document = AIKnowledgeDocument(
        title="测试知识",
        version="test",
        source_uri="hospital://isolated-test",
        content="隔离测试资料",
        content_hash=digest("隔离测试资料"),
        feature_keys_json='["guideline_qa"]',
        status="draft",
        created_by=user_id,
    )
    db_session.add(document)
    db_session.commit()
    draft = await feature_setup(async_client, auth_headers, "guideline_qa")
    assert {item["code"] for item in draft["issues"]} == {"KNOWLEDGE_NOT_PUBLISHED"}
    document.status = "published"
    document.reviewed_by = user_id
    document.reviewed_at = utcnow()
    document.effective_to = utcnow() - datetime.timedelta(minutes=1)
    db_session.commit()
    expired = await feature_setup(async_client, auth_headers, "guideline_qa")
    assert expired["ready"] is False
    document.effective_to = utcnow() + datetime.timedelta(days=1)
    db_session.commit()
    published = await feature_setup(async_client, auth_headers, "guideline_qa")
    assert published["ready"] is True
