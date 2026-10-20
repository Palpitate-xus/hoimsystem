"""Super-admin checks are bounded metadata requests, not inference or validation approval."""

import json
import uuid

import httpx
import pytest

from app.ai.gateway import AIExecutionError
from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIProvider
from app.ai.speech_probe import inspect_speech_capabilities
from app.routers import ai_admin


def capabilities():
    return {
        "schema_version": "2",
        "feature_key": "medical_transcription",
        "model_version": "fw:" + "a" * 64,
        "runtime_digest": "a" * 64,
        "engine": "faster-whisper",
        "engine_versions": {"faster-whisper": "1.2.1", "ctranslate2": "4.8.3", "onnxruntime": "1.31.0", "av": "16.1.0", "tokenizers": "0.23.3", "numpy": "2.4.4"},
        "model_repository": "example/offline-model",
        "model_revision": "b" * 40,
        "model_digest": "c" * 64,
        "decoding_options_hash": "d" * 64,
        "language": "zh",
        "max_bytes": 67108864,
        "max_duration_seconds": 300,
        "timeout_seconds": 110,
        "prompt_handling": "acoustic_only",
        "diarization": False,
        "clinical_validation": "not_provided",
    }


@pytest.mark.asyncio
async def test_probe_uses_only_fixed_capabilities_get_and_sanitizes_unknown_properties(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SPEECH_API_KEY", "test-probe-credential")
    provider = AIProvider(api_base="http://localhost:8810", api_key_env="AI_PROVIDER_LOCAL_SPEECH_API_KEY")
    seen = []

    def handle(request):
        seen.append(request)
        assert request.method == "GET" and str(request.url) == "http://localhost:8810/capabilities"
        assert request.headers["Authorization"] == "Bearer test-probe-credential" and not request.content
        return httpx.Response(200, json={**capabilities(), "api_key": "must not be exposed", "disk_path": "/private/path"})

    result = await inspect_speech_capabilities(provider, transport=httpx.MockTransport(handle))
    assert result == capabilities() and len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["redirect", "large", "malformed", "model", "clinical_claim", "diarization", "packages"])
async def test_untrusted_or_inconsistent_capability_reports_fail_without_echoing_bodies(variant):
    body = capabilities()
    if variant == "model":
        body["model_version"] = "fw:" + "0" * 64
    elif variant == "clinical_claim":
        body["clinical_validation"] = "validated_without_evidence"
    elif variant == "diarization":
        body["diarization"] = True
    elif variant == "packages":
        body["engine_versions"]["arbitrary_secret"] = "do-not-echo"

    def handle(request):
        if variant == "redirect":
            return httpx.Response(302, headers={"Location": "https://unapproved.example/tasks"}, text="do-not-echo")
        if variant == "large":
            return httpx.Response(200, content=b"do-not-echo" * 2000)
        if variant == "malformed":
            return httpx.Response(200, text="do-not-echo")
        return httpx.Response(200, json=body)

    with pytest.raises(AIExecutionError) as exc:
        await inspect_speech_capabilities(AIProvider(api_base="http://localhost:8810"), transport=httpx.MockTransport(handle))
    assert "do-not-echo" not in exc.value.message


@pytest.fixture
def provider(db_session, seed_data):
    value = AIProvider(
        name="local-speech-check-" + uuid.uuid4().hex,
        kind="specialist",
        api_base="http://localhost:8810",
        model="fw:" + "a" * 64,
        timeout_seconds=120,
        enabled=0,
        supported_features_json=encode_json(["medical_transcription"]),
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(value)
    db_session.commit()
    return value


@pytest.mark.asyncio
async def test_only_super_admin_can_check_and_check_does_not_enable_or_validate(provider, db_session, seed_data, auth_headers, async_client, monkeypatch):
    calls = []

    async def inspect(value):
        calls.append(value.provider_id)
        return capabilities()

    monkeypatch.setattr(ai_admin, "inspect_speech_capabilities", inspect)
    url = f"/api/ai/admin/providers/{provider.provider_id}/speech-capabilities"
    for role in ("doctor_user", "admin_user", "patient_user"):
        response = await async_client.post(url, headers=auth_headers(seed_data[role].username), json={"expected_revision": provider.revision})
        assert response.status_code == 403
    assert not calls
    response = await async_client.post(url, headers=auth_headers(seed_data["super_admin_user"].username), json={"expected_revision": provider.revision})
    assert response.status_code == 200 and response.json()["data"]["compatible"] is True
    db_session.refresh(provider)
    assert provider.enabled == 0 and provider.validated_at is None
    audit = db_session.query(AIAuditEvent).filter_by(action="provider.speech_check", target=str(provider.provider_id)).one()
    assert json.loads(audit.detail_json)["compatible"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["before", "during", "role", "mismatch", "network"])
async def test_stale_saved_config_or_role_is_rejected_and_mismatch_is_reviewable(variant, provider, db_session, seed_data, auth_headers, async_client, monkeypatch):
    expected = provider.revision
    if variant == "before":
        provider.revision += 1
        db_session.commit()
    calls = []

    async def inspect(value):
        calls.append(value.provider_id)
        if variant == "during":
            row = db_session.get(AIProvider, value.provider_id)
            row.revision += 1
            db_session.commit()
        elif variant == "role":
            seed_data["super_admin_user"].user_role = "admin"
            db_session.commit()
        elif variant == "network":
            raise AIExecutionError("SPEECH_CHECK_UNAVAILABLE", "隔离连接失败")
        report = capabilities()
        if variant == "mismatch":
            report["model_version"] = "fw:" + "0" * 64
        return report

    monkeypatch.setattr(ai_admin, "inspect_speech_capabilities", inspect)
    response = await async_client.post(
        f"/api/ai/admin/providers/{provider.provider_id}/speech-capabilities", headers=auth_headers(seed_data["super_admin_user"].username), json={"expected_revision": expected}
    )
    expected_status = {"before": 409, "during": 409, "role": 403, "mismatch": 200, "network": 502}[variant]
    assert response.status_code == expected_status, response.text
    if variant == "before":
        assert not calls
    elif variant == "mismatch":
        assert response.json()["data"]["compatible"] is False and response.json()["data"]["issues"]
    elif variant == "network":
        assert db_session.query(AIAuditEvent).filter_by(action="provider.speech_check_failed").count() >= 1
