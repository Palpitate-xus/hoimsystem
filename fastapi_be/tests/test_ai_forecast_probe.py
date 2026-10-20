"""Saved forecast metadata checks cannot predict, enable or approve a source."""

import copy
import hashlib
import json
import uuid

import httpx
import pytest

from app.ai.forecast_config import runtime_descriptor
from app.ai.forecast_contract import canonical_json
from app.ai.forecast_probe import inspect_forecast_capabilities
from app.ai.gateway import AIExecutionError
from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIProvider
from app.routers import ai_admin


@pytest.mark.asyncio
async def test_capability_check_only_gets_metadata_and_strips_unexpected_properties(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_FORECAST_API_KEY", "test-only-forecast-probe-key")
    expected = runtime_descriptor()
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and str(request.url) == "http://localhost:8813/capabilities"
        assert not request.content and request.headers["Authorization"] == "Bearer test-only-forecast-probe-key"
        return httpx.Response(200, json={**expected, "api_key": "never-return-this", "database": "never-return-this"})

    result = await inspect_forecast_capabilities(AIProvider(api_base="http://localhost:8813", api_key_env="AI_PROVIDER_LOCAL_FORECAST_API_KEY"), transport=httpx.MockTransport(handler))
    assert result == expected and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant",
    [
        "schema",
        "model",
        "recipe",
        "hash",
        "source_files",
        "runtime_rehash",
        "validation",
        "guarantee",
        "horizons",
        "horizon_type",
        "min_days",
        "origins",
        "bounds_bool",
        "bounds_large",
        "timeout",
        "nested_secret",
        "redirect",
        "large",
        "invalid_json",
        "unavailable",
    ],
)
async def test_untrusted_metadata_is_rejected_without_echoing_bodies(variant):
    value = copy.deepcopy(runtime_descriptor())
    if variant == "schema":
        value["schema_version"] = "1"
    elif variant == "model":
        value["model_version"] = "stat-forecast:" + "0" * 64
    elif variant == "recipe":
        value["recipe"] = "invented-best-model"
    elif variant == "hash":
        value["recipe_digest"] = "0" * 64
    elif variant == "source_files":
        value["implementation"]["forecast_model.py"] = "0" * 64
    elif variant == "runtime_rehash":
        value["implementation"]["forecast_model.py"] = "0" * 64
        fields = {
            key: value[key]
            for key in (
                "engine",
                "recipe",
                "recipe_digest",
                "implementation",
                "python_version",
                "engine_versions",
                "prompt_handling",
                "clinical_validation",
                "operational_validation",
                "coverage_guarantee",
            )
        }
        value["runtime_digest"] = hashlib.sha256(canonical_json(fields).encode()).hexdigest()
        value["model_version"] = "stat-forecast:" + value["runtime_digest"]
    elif variant == "validation":
        value["operational_validation"] = "independently_validated_without_evidence"
    elif variant == "guarantee":
        value["coverage_guarantee"] = "guaranteed"
    elif variant == "horizons":
        value["horizon_days"] = [7, 28]
    elif variant == "horizon_type":
        value["horizon_days"] = [7.0, 14]
    elif variant == "min_days":
        value["history_min_days"] = 28
    elif variant == "origins":
        value["backtest_origins"] = 29
    elif variant == "bounds_bool":
        value["max_request_bytes"] = True
    elif variant == "bounds_large":
        value["max_request_bytes"] = 131073
    elif variant == "timeout":
        value["timeout_seconds"] = "30"
    elif variant == "nested_secret":
        value["engine_versions"]["secret"] = "never-echo-this"
    calls = []

    def handler(request):
        calls.append(request)
        if variant == "redirect":
            return httpx.Response(302, headers={"Location": "https://unapproved.example/tasks"}, text="never-echo-this")
        if variant == "large":
            return httpx.Response(200, content=b"never-echo-this" * 2000)
        if variant == "invalid_json":
            return httpx.Response(200, text="never-echo-this")
        if variant == "unavailable":
            raise httpx.ConnectError("never-echo-this", request=request)
        return httpx.Response(200, json=value)

    with pytest.raises(AIExecutionError) as exc:
        await inspect_forecast_capabilities(AIProvider(api_base="http://localhost:8813"), transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and "never-echo-this" not in exc.value.message


@pytest.fixture
def provider(db_session, seed_data):
    row = AIProvider(
        name="forecast-probe-" + uuid.uuid4().hex,
        kind="specialist",
        api_base="http://localhost:8813",
        model="not-yet-matched",
        enabled=0,
        timeout_seconds=10,
        supported_features_json=encode_json(["visit_forecast"]),
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.mark.asyncio
async def test_saved_check_is_super_only_and_never_changes_feature_or_provider(async_client, db_session, seed_data, auth_headers, provider, monkeypatch):
    calls = []

    async def inspect(saved):
        calls.append(saved.provider_id)
        return runtime_descriptor()

    monkeypatch.setattr(ai_admin, "inspect_forecast_capabilities", inspect)
    path = f"/api/ai/admin/providers/{provider.provider_id}/forecast-capabilities"
    before = (provider.revision, provider.model, provider.enabled, provider.validation_report)
    feature_before = db_session.query(AIFeatureConfig).count()
    denied = await async_client.post(path, headers=auth_headers(seed_data["admin_user"].username), json={"expected_revision": provider.revision})
    assert denied.status_code == 403 and not calls
    response = await async_client.post(path, headers=auth_headers(seed_data["super_admin_user"].username), json={"expected_revision": provider.revision})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["compatible"] is False and len(data["issues"]) == 2
    assert data["capabilities"]["operational_validation"] == "not_provided"
    db_session.expire_all()
    saved = db_session.get(AIProvider, provider.provider_id)
    assert (saved.revision, saved.model, saved.enabled, saved.validation_report) == before
    assert db_session.query(AIFeatureConfig).count() == feature_before
    audit = db_session.query(AIAuditEvent).filter_by(action="provider.forecast_check", target=str(saved.provider_id)).one()
    assert json.loads(audit.detail_json)["compatible"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["revision", "deleted", "role", "failure"])
async def test_async_check_rechecks_actor_and_saved_configuration(async_client, db_session, seed_data, auth_headers, provider, monkeypatch, variant):
    original_revision = provider.revision

    async def inspect(saved):
        current = db_session.get(AIProvider, saved.provider_id)
        if variant == "revision":
            current.revision += 1
        elif variant == "deleted":
            db_session.delete(current)
        elif variant == "role":
            seed_data["super_admin_user"].user_role = "admin"
        if variant == "failure":
            raise AIExecutionError("FORECAST_CHECK_INVALID", "安全的错误说明")
        db_session.commit()
        return runtime_descriptor()

    monkeypatch.setattr(ai_admin, "inspect_forecast_capabilities", inspect)
    response = await async_client.post(
        f"/api/ai/admin/providers/{provider.provider_id}/forecast-capabilities", headers=auth_headers(seed_data["super_admin_user"].username), json={"expected_revision": original_revision}
    )
    assert response.status_code == {"revision": 409, "deleted": 409, "role": 403, "failure": 502}[variant], response.text
    if variant != "failure":
        assert db_session.query(AIAuditEvent).filter_by(action="provider.forecast_check", target=str(provider.provider_id)).count() == 0
