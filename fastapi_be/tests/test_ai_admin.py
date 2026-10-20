"""Exercise super-admin governance, immutable versions and secret protection."""

import pytest

from app.ai.models import AIAuditEvent, AIFeatureConfig, AIProvider
from app.config import settings


@pytest.mark.asyncio
async def test_all_ai_management_reads_reject_ordinary_admin(async_client, seed_data, auth_headers):
    paths = ["features", "providers", "prompts/patient_summary", "knowledge", "grants", "audit", "usage"]
    for path in paths:
        response = await async_client.get(f"/api/ai/admin/{path}", headers=auth_headers("admin"))
        assert response.status_code == 403, path
    response = await async_client.get("/api/ai/admin/features")
    assert response.status_code == 401
    response = await async_client.get("/api/ai/admin/features", headers=auth_headers("super01"))
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 80
    assert any(item["key"] == "treatment_pathway" for item in data)


@pytest.mark.asyncio
async def test_provider_secret_encryption_and_redacted_audit(async_client, seed_data, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(settings, "AI_CREDENTIAL_KEY", "a-stable-test-only-encryption-key-123456")
    headers = auth_headers("super01")
    body = {"name": "encrypted-test", "api_base": "http://localhost:11434/v1", "model": "local-test", "api_key": "never-return-this-test-secret"}
    response = await async_client.post("/api/ai/admin/providers", headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert "never-return-this-test-secret" not in response.text
    provider = db_session.get(AIProvider, response.json()["data"]["provider_id"])
    assert provider.api_key_encrypted
    assert provider.api_key_encrypted != body["api_key"]
    listed = await async_client.get("/api/ai/admin/providers", headers=headers)
    assert body["api_key"] not in listed.text
    assert "api_key_encrypted" not in listed.text
    audit = await async_client.get("/api/ai/admin/audit", headers=headers)
    assert body["api_key"] not in audit.text
    assert any(event["action"] == "provider.save" for event in audit.json()["data"])
    body["name"] = "not-allowed-host"
    body["api_base"] = "https://unapproved-provider.example/v1"
    denied = await async_client.post("/api/ai/admin/providers", headers=headers, json=body)
    assert denied.status_code == 422


@pytest.mark.asyncio
async def test_feature_role_ceiling_revision_and_clinical_gate(async_client, seed_data, auth_headers):
    headers = auth_headers("super01")
    path = "/api/ai/admin/features/treatment_pathway"
    denied = await async_client.put(path, headers=headers, json={"expected_revision": 0, "allowed_roles": ["patient"]})
    assert denied.status_code == 422
    response = await async_client.put(path, headers=headers, json={"expected_revision": 0, "allowed_roles": ["doctor", "super_admin"]})
    assert response.status_code == 200, response.text
    revision = response.json()["data"]["revision"]
    stale = await async_client.put(path, headers=headers, json={"expected_revision": 0, "daily_limit": 10})
    assert stale.status_code == 409
    provider = await async_client.post("/api/ai/admin/providers", headers=headers, json={"name": "clinical-gate-test", "api_base": "http://localhost:11434/v1", "model": "test", "enabled": True})
    provider_id = provider.json()["data"]["provider_id"]
    denied = await async_client.put(path, headers=headers, json={"expected_revision": revision, "provider_id": provider_id, "enabled": True})
    assert denied.status_code == 422
    good = await async_client.put(
        path,
        headers=headers,
        json={"expected_revision": revision, "provider_id": provider_id, "enabled": True, "validation_status": "validated", "validation_note": "仅限指定测试病种，已完成独立病例回放验证"},
    )
    assert good.status_code == 200, good.text
    assert good.json()["data"]["enabled"] is True


@pytest.mark.asyncio
async def test_prompt_versions_immutable_and_activation_invalidates_validation(async_client, seed_data, auth_headers, db_session):
    headers = auth_headers("super01")
    key = "outpatient_note"
    baseline = await async_client.get(f"/api/ai/admin/prompts/{key}", headers=headers)
    original = baseline.json()["data"]["versions"][0]["task_prompt"]
    first = await async_client.post(
        f"/api/ai/admin/prompts/{key}",
        headers=headers,
        json={"expected_revision": 0, "task_prompt": original + "\n额外要求：按院内门诊模板整理，不补写未提供的信息。", "change_note": "补充院内模板要求", "activate": True},
    )
    assert first.status_code == 200, first.text
    config = db_session.get(AIFeatureConfig, key)
    assert config.enabled == 0
    assert config.validation_status == "unreviewed"
    second = await async_client.post(
        f"/api/ai/admin/prompts/{key}",
        headers=headers,
        json={"expected_revision": first.json()["data"]["revision"], "task_prompt": original + "\n额外要求：明确展示需要医生确认的部分。", "change_note": "强调医生复核"},
    )
    assert second.status_code == 200
    history = (await async_client.get(f"/api/ai/admin/prompts/{key}", headers=headers)).json()["data"]["versions"]
    assert [item["version"] for item in history] == [2, 1, 0]
    assert history[-1]["task_prompt"] == original
    assert "院内门诊模板" in history[1]["task_prompt"]
    restore = await async_client.post(f"/api/ai/admin/prompts/{key}/activate", headers=headers, json={"expected_revision": second.json()["data"]["revision"], "prompt_id": None})
    assert restore.status_code == 200
    assert restore.json()["data"]["prompt_version"] == 0


@pytest.mark.asyncio
async def test_knowledge_requires_exact_review_hash_and_preserves_versions(async_client, seed_data, auth_headers):
    headers = auth_headers("super01")
    body = {
        "title": "测试院内规范",
        "version": "test-v1",
        "source_uri": "hospital://test/guideline",
        "content": "这是测试专用的院内规范资料，只用于测试知识审核状态和版本追踪，不提供实际诊疗建议。",
        "feature_keys": ["guideline_qa"],
    }
    created = await async_client.post("/api/ai/admin/knowledge", headers=headers, json=body)
    assert created.status_code == 200, created.text
    item = created.json()["data"]
    assert item["status"] == "draft"
    wrong = await async_client.post(f"/api/ai/admin/knowledge/{item['document_id']}/review", headers=headers, json={"content_hash": "0" * 64, "status": "published"})
    assert wrong.status_code == 409
    reviewed = await async_client.post(f"/api/ai/admin/knowledge/{item['document_id']}/review", headers=headers, json={"content_hash": item["content_hash"], "status": "published"})
    assert reviewed.status_code == 200
    duplicate = await async_client.post("/api/ai/admin/knowledge", headers=headers, json=body)
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_write_routes_cannot_be_reached_by_non_super_admin(async_client, seed_data, auth_headers, db_session):
    before = db_session.query(AIAuditEvent).count()
    configs_before = db_session.query(AIFeatureConfig).count()
    requests = [("POST", "/providers"), ("PUT", "/providers/1"), ("PUT", "/features/patient_summary"), ("POST", "/prompts/patient_summary"), ("POST", "/knowledge"), ("POST", "/grants")]
    for method, path in requests:
        response = await async_client.request(method, "/api/ai/admin" + path, headers=auth_headers("admin"), json={})
        assert response.status_code == 403
    assert db_session.query(AIAuditEvent).count() == before
    assert db_session.query(AIFeatureConfig).count() == configs_before
