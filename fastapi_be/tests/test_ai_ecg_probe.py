"""The saved ECG capability check sends no patient data and cannot enable clinical use."""

import json
import uuid

import httpx
import pytest

from app.ai.ecg_probe import inspect_ecg_capabilities
from app.ai.gateway import AIExecutionError
from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIProvider
from app.config import settings
from app.database import get_db
from app.main import app
from app.routers import ai_admin


def capabilities():
    return {
        "schema_version": "3",
        "feature_key": "ecg_analysis",
        "model_version": "ssl-ecg:" + "a" * 64,
        "runtime_digest": "a" * 64,
        "engine": "ssl-ecg-cnn",
        "engine_versions": {"torch": "2.8.0+cpu", "numpy": "2.4.4", "safetensors": "0.6.2"},
        "model_repository": "Tumo505/SSL-ECG-Classification-model-card",
        "model_revision": "b" * 40,
        "model_digest": "c" * 64,
        "preprocessing_digest": "d" * 64,
        "required_leads": ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"],
        "sample_rate_hz": 100,
        "samples_per_lead": 1000,
        "labels": ["NORM", "CD", "HYP", "MI", "STTC"],
        "missing_sample_policy": "reject",
        "prompt_handling": "signal_only",
        "max_bytes": 33554432,
        "timeout_seconds": 110,
        "clinical_validation": "not_provided",
    }


@pytest.mark.asyncio
async def test_probe_uses_only_saved_fixed_capabilities_get_and_strips_unknown_properties(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ECG_API_KEY", "isolated-ecg-check-key")
    provider = AIProvider(api_base="http://localhost:8820", api_key_env="AI_PROVIDER_LOCAL_ECG_API_KEY")
    seen = []

    def handle(request):
        seen.append(request)
        assert request.method == "GET" and str(request.url) == "http://localhost:8820/capabilities"
        assert request.headers["Authorization"] == "Bearer isolated-ecg-check-key" and not request.content
        return httpx.Response(200, json={**capabilities(), "api_key": "must not be exposed", "disk_path": "/private/path", "patient": "must not be exposed"})

    result = await inspect_ecg_capabilities(provider, transport=httpx.MockTransport(handle))
    assert result == capabilities() and len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant",
    [
        "redirect",
        "large",
        "malformed",
        "model",
        "clinical_claim",
        "packages",
        "version",
        "repository",
        "revision",
        "recipe",
        "leads",
        "labels",
        "missing",
        "prompt",
        "rate_float",
        "samples_string",
        "max_bool",
        "timeout",
    ],
)
async def test_untrusted_or_inconsistent_capability_reports_fail_without_echoing_bodies(variant):
    body = capabilities()
    changes = {
        "model": ("model_version", "ssl-ecg:" + "0" * 64),
        "clinical_claim": ("clinical_validation", "validated_without_evidence"),
        "packages": ("engine_versions", {"torch": "2.8.0", "numpy": "2.4.4", "arbitrary_secret": "do-not-echo"}),
        "version": ("engine_versions", {"torch": "2.8.0\ndo-not-echo", "numpy": "2.4.4", "safetensors": "0.6.2"}),
        "repository": ("model_repository", "unapproved/model"),
        "revision": ("model_revision", "main"),
        "recipe": ("preprocessing_digest", "mutable"),
        "leads": ("required_leads", list(reversed(body["required_leads"]))),
        "labels": ("labels", list(reversed(body["labels"]))),
        "missing": ("missing_sample_policy", "zero_fill"),
        "prompt": ("prompt_handling", "text_conditioned"),
        "rate_float": ("sample_rate_hz", 100.0),
        "samples_string": ("samples_per_lead", "1000"),
        "max_bool": ("max_bytes", True),
        "timeout": ("timeout_seconds", 111),
    }
    if variant in changes:
        key, value = changes[variant]
        body[key] = value
    calls = []

    def handle(request):
        calls.append(request)
        if variant == "redirect":
            return httpx.Response(302, headers={"Location": "https://unapproved.example/tasks"}, text="do-not-echo")
        if variant == "large":
            return httpx.Response(200, content=b"do-not-echo" * 2000)
        if variant == "malformed":
            return httpx.Response(200, text="do-not-echo")
        return httpx.Response(200, json=body)

    with pytest.raises(AIExecutionError) as exc:
        await inspect_ecg_capabilities(AIProvider(api_base="http://localhost:8820"), transport=httpx.MockTransport(handle))
    assert "do-not-echo" not in exc.value.message and len(calls) == 1


@pytest.mark.asyncio
async def test_unapproved_host_fails_before_network_and_transport_error_is_sanitized(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "localhost")
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ConnectError("do-not-echo-secret", request=request)

    with pytest.raises(AIExecutionError) as exc:
        await inspect_ecg_capabilities(AIProvider(api_base="https://unapproved.example"), transport=httpx.MockTransport(handle))
    assert exc.value.code == "PROVIDER_CONFIGURATION" and not calls
    with pytest.raises(AIExecutionError) as exc:
        await inspect_ecg_capabilities(AIProvider(api_base="http://localhost:8820"), transport=httpx.MockTransport(handle))
    assert exc.value.code == "ECG_CHECK_UNAVAILABLE" and "do-not-echo" not in exc.value.message and len(calls) == 1


@pytest.fixture
def provider(db_session, seed_data):
    value = AIProvider(
        name="local-ecg-check-" + uuid.uuid4().hex,
        kind="specialist",
        api_base="http://localhost:8820",
        model="ssl-ecg:" + "a" * 64,
        timeout_seconds=120,
        enabled=0,
        supported_features_json=encode_json(["ecg_analysis"]),
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(value)
    db_session.commit()
    return value


@pytest.mark.asyncio
async def test_only_super_admin_can_check_without_saving_enabling_or_validating(provider, db_session, seed_data, auth_headers, async_client, monkeypatch):
    calls = []
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: db_session)
    db_session.add(AIFeatureConfig(feature_key="ecg_analysis", provider_id=provider.provider_id, enabled=0, validation_status="unreviewed", updated_by=seed_data["super_admin_user"].user_id))
    db_session.commit()
    revision = provider.revision

    async def inspect(value):
        assert not db_session.in_transaction(), "network must not hold a database read transaction"
        calls.append(value.provider_id)
        return capabilities()

    monkeypatch.setattr(ai_admin, "inspect_ecg_capabilities", inspect)
    url = f"/api/ai/admin/providers/{provider.provider_id}/ecg-capabilities"
    for role in ("doctor_user", "director_user", "nurse_user", "admin_user", "patient_user", "lab_tech_user", "cashier_user", "pharmacist_user", "guide_user", "registrar_user"):
        response = await async_client.post(url, headers=auth_headers(seed_data[role].username), json={"expected_revision": revision})
        assert response.status_code == 403
    assert not calls
    response = await async_client.post(url, headers=auth_headers(seed_data["super_admin_user"].username), json={"expected_revision": revision})
    assert response.status_code == 200 and response.json()["data"]["compatible"] is True
    provider = db_session.get(AIProvider, provider.provider_id)
    assert provider.enabled == 0 and provider.validated_at is None and provider.revision == revision
    config = db_session.get(AIFeatureConfig, "ecg_analysis")
    assert config.enabled == 0 and config.validation_status == "unreviewed" and config.validated_at is None
    audit = db_session.query(AIAuditEvent).filter_by(action="provider.ecg_check", target=str(provider.provider_id)).one()
    assert json.loads(audit.detail_json) == {"revision": revision, "compatible": True, "actual_model": capabilities()["model_version"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["before", "during", "role", "deleted", "mismatch", "timeout", "network"])
async def test_saved_revision_role_downgrade_and_inflight_changes_are_rechecked(variant, provider, db_session, seed_data, auth_headers, async_client, monkeypatch):
    expected, provider_id = provider.revision, provider.provider_id
    if variant == "before":
        provider.revision += 1
        db_session.commit()
    elif variant == "timeout":
        provider.timeout_seconds = 110
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
        elif variant == "deleted":
            db_session.delete(db_session.get(AIProvider, value.provider_id))
            db_session.commit()
        elif variant == "network":
            raise AIExecutionError("ECG_CHECK_UNAVAILABLE", "隔离连接失败")
        report = capabilities()
        if variant == "mismatch":
            report["model_version"] = "ssl-ecg:" + "0" * 64
            report["runtime_digest"] = "0" * 64
        return report

    monkeypatch.setattr(ai_admin, "inspect_ecg_capabilities", inspect)
    response = await async_client.post(f"/api/ai/admin/providers/{provider_id}/ecg-capabilities", headers=auth_headers(seed_data["super_admin_user"].username), json={"expected_revision": expected})
    expected_status = {"before": 409, "during": 409, "role": 403, "deleted": 409, "mismatch": 200, "timeout": 200, "network": 502}[variant]
    assert response.status_code == expected_status, response.text
    if variant == "before":
        assert not calls
    elif variant in {"mismatch", "timeout"}:
        assert response.json()["data"]["compatible"] is False and response.json()["data"]["issues"]
        db_session.refresh(provider)
        assert provider.enabled == 0 and provider.validated_at is None and provider.model == "ssl-ecg:" + "a" * 64
    elif variant == "network":
        audit = db_session.query(AIAuditEvent).filter_by(action="provider.ecg_check_failed", target=str(provider_id)).one()
        assert json.loads(audit.detail_json) == {"revision": expected, "error_code": "ECG_CHECK_UNAVAILABLE"}


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["missing", "wrong_kind", "wrong_feature", "extra_request_fields"])
async def test_only_saved_specialist_ecg_provider_can_be_checked(variant, provider, db_session, seed_data, auth_headers, async_client, monkeypatch):
    calls = []

    async def inspect(value):
        calls.append(value.provider_id)
        return capabilities()

    monkeypatch.setattr(ai_admin, "inspect_ecg_capabilities", inspect)
    if variant == "wrong_kind":
        provider.kind = "chat"
    elif variant == "wrong_feature":
        provider.supported_features_json = encode_json(["medical_transcription"])
    db_session.commit()
    request = {"expected_revision": provider.revision}
    if variant == "extra_request_fields":
        request["api_base"] = "https://unapproved.example"
    response = await async_client.post(
        f"/api/ai/admin/providers/{provider.provider_id if variant != 'missing' else 999999}/ecg-capabilities",
        headers=auth_headers(seed_data["super_admin_user"].username),
        json=request,
    )
    assert response.status_code == (404 if variant == "missing" else 422) and not calls
