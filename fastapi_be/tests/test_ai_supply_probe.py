"""Metadata-only authenticated supply inspection rejects changed recipes and transport data."""

import copy
import json

import httpx
import pytest

from app.ai import supply_probe, supply_server
from app.ai.gateway import AIExecutionError
from app.ai.models import AIProvider
from app.ai.supply_config import SupplySettings, runtime_descriptor
from app.ai.supply_contract import SupplyRuntime, hash_content

KEY = "synthetic-supply-metadata-key-00000000001"


@pytest.fixture
def descriptor():
    return runtime_descriptor()


@pytest.mark.asyncio
async def test_actual_capability_inspection_sends_no_source_and_never_forecasts(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SUPPLY_API_KEY", KEY)

    def no_forecasting(*args, **kwargs):
        raise AssertionError("A metadata check cannot compute a forecast")

    monkeypatch.setattr(supply_server, "compute_supply", no_forecasting)
    config = SupplySettings(AI_PROVIDER_LOCAL_SUPPLY_API_KEY=KEY)
    native = supply_server.create_supply_app(config)
    calls = []

    class Wire(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append(request)
            assert request.method == "GET" and str(request.url) == "http://localhost:8822/capabilities"
            assert request.headers["Authorization"] == "Bearer " + KEY and request.content == b""
            return await httpx.ASGITransport(app=native).handle_async_request(request)

    value = await supply_probe.inspect_supply_capabilities(AIProvider(api_base="http://localhost:8822/", api_key_env="AI_PROVIDER_LOCAL_SUPPLY_API_KEY"), transport=Wire())
    assert value == runtime_descriptor(config) and len(calls) == 1
    assert value["forecast_only"] is True and value["coverage_guarantee"] == "not_provided"
    assert KEY not in json.dumps(value)


@pytest.mark.parametrize(
    "change",
    [
        "schema",
        "feature",
        "model",
        "recipe",
        "policy",
        "core_rehashed",
        "core_missing",
        "scope",
        "forecast_int",
        "independent_int",
        "coverage",
        "clinical",
        "operational",
        "timeout_bool",
        "request_small",
        "response_small",
        "python",
        "version_missing",
        "extra",
    ],
)
@pytest.mark.asyncio
async def test_complete_fixed_runtime_and_forecast_only_scope_are_verified(change, descriptor):
    value = copy.deepcopy(descriptor)
    changes = {
        "schema": ("schema_version", "12"),
        "feature": ("feature_key", "bed_forecast"),
        "model": ("model_version", "supply:" + "0" * 64),
        "scope": ("scope", "latent_demand_auto_purchase"),
        "forecast_int": ("forecast_only", 1),
        "independent_int": ("independent_implementation", 1),
        "coverage": ("coverage_guarantee", "complete"),
        "clinical": ("clinical_validation", "validated"),
        "operational": ("operational_validation", "validated"),
        "timeout_bool": ("timeout_seconds", True),
        "request_small": ("max_request_bytes", 65535),
        "response_small": ("max_response_bytes", 8388607),
        "python": ("python_version", "3.13"),
        "extra": ("private_note", "never-echo-this"),
    }
    if change in changes:
        field, replacement = changes[change]
        value[field] = replacement
    elif change in {"recipe", "policy"}:
        value["recipe" if change == "recipe" else "input_policy"]["never-echo-this"] = True
    elif change == "core_rehashed":
        value["core_sha256"]["supply_model"] = "0" * 64
        value["runtime_digest"] = hash_content({field: value[field] for field in SupplyRuntime.model_fields if field not in {"runtime_digest", "model_version"}})
        value["model_version"] = "supply:" + value["runtime_digest"]
    elif change == "core_missing":
        value["core_sha256"].pop("supply_server")
    else:
        value["engine_versions"].pop("fastapi")

    def response(request):
        assert request.method == "GET" and request.content == b""
        return httpx.Response(200, json=value)

    with pytest.raises(AIExecutionError) as error:
        await supply_probe.inspect_supply_capabilities(AIProvider(api_base="http://localhost:8822"), transport=httpx.MockTransport(response))
    assert error.value.code == "SUPPLY_CHECK_INVALID"
    assert "never-echo-this" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["redirect", "http", "large", "malformed", "duplicate", "nested_duplicate", "nonfinite", "invalid_utf8", "deep", "nonobject", "timeout"])
async def test_duplicate_nonfinite_unbounded_and_transport_failures_are_rejected(kind):
    calls = []

    def response(request):
        calls.append(request)
        if kind == "redirect":
            return httpx.Response(302, headers={"Location": "https://unapproved.example/never-echo-this"})
        if kind == "http":
            return httpx.Response(500, text="never-echo-this")
        if kind == "timeout":
            raise httpx.ReadTimeout("never-echo-this", request=request)
        bodies = {
            "large": b"x" * 65537,
            "malformed": b"never-echo-this",
            "duplicate": b'{"schema_version":"13","schema_version":"13"}',
            "nested_duplicate": b'{"recipe":{"same":1,"same":2}}',
            "nonfinite": b'{"schema_version":NaN}',
            "invalid_utf8": b"\xff\xfe",
            "deep": b"[" * 3000 + b"0" + b"]" * 3000,
            "nonobject": b"[]",
        }
        return httpx.Response(200, content=bodies[kind])

    with pytest.raises(AIExecutionError) as error:
        await supply_probe.inspect_supply_capabilities(AIProvider(api_base="http://localhost:8822"), transport=httpx.MockTransport(response))
    assert len(calls) == 1 and "never-echo-this" not in str(error.value)
