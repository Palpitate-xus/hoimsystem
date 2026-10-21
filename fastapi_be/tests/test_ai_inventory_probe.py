"""Metadata-only authenticated inventory inspection rejects changed recipes and transport data."""

import copy
import json

import httpx
import pytest

from app.ai import inventory_probe, inventory_server
from app.ai.gateway import AIExecutionError
from app.ai.inventory_config import InventorySettings, runtime_descriptor
from app.ai.inventory_contract import InventoryRuntime, hash_content
from app.ai.models import AIProvider

KEY = "synthetic-inventory-metadata-key-00000000001"


@pytest.fixture
def descriptor():
    return runtime_descriptor()


@pytest.mark.asyncio
async def test_actual_capability_inspection_sends_no_source_and_never_forecasts(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_INVENTORY_API_KEY", KEY)

    def no_forecasting(*args, **kwargs):
        raise AssertionError("A metadata check cannot compute a forecast")

    monkeypatch.setattr(inventory_server, "compute_inventory", no_forecasting)
    config = InventorySettings(AI_PROVIDER_LOCAL_INVENTORY_API_KEY=KEY)
    native = inventory_server.create_inventory_app(config)
    calls = []

    class Wire(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append(request)
            assert request.method == "GET" and str(request.url) == "http://localhost:8823/capabilities"
            assert request.headers["Authorization"] == "Bearer " + KEY and request.content == b""
            return await httpx.ASGITransport(app=native).handle_async_request(request)

    value = await inventory_probe.inspect_inventory_capabilities(AIProvider(api_base="http://localhost:8823/", api_key_env="AI_PROVIDER_LOCAL_INVENTORY_API_KEY"), transport=Wire())
    assert value == runtime_descriptor(config) and len(calls) == 1
    assert value["comparison_only"] is True and value["coverage_guarantee"] == "not_provided"
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
async def test_complete_fixed_runtime_and_comparison_only_scope_are_verified(change, descriptor):
    value = copy.deepcopy(descriptor)
    changes = {
        "schema": ("schema_version", "12"),
        "feature": ("feature_key", "bed_forecast"),
        "model": ("model_version", "inventory:" + "0" * 64),
        "scope": ("scope", "latent_demand_auto_purchase"),
        "forecast_int": ("comparison_only", 1),
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
        value["core_sha256"]["inventory_model"] = "0" * 64
        value["runtime_digest"] = hash_content({field: value[field] for field in InventoryRuntime.model_fields if field not in {"runtime_digest", "model_version"}})
        value["model_version"] = "inventory:" + value["runtime_digest"]
    elif change == "core_missing":
        value["core_sha256"].pop("inventory_server")
    else:
        value["engine_versions"].pop("fastapi")

    def response(request):
        assert request.method == "GET" and request.content == b""
        return httpx.Response(200, json=value)

    with pytest.raises(AIExecutionError) as error:
        await inventory_probe.inspect_inventory_capabilities(AIProvider(api_base="http://localhost:8823"), transport=httpx.MockTransport(response))
    assert error.value.code == "INVENTORY_CHECK_INVALID"
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
            "duplicate": b'{"schema_version":"14","schema_version":"14"}',
            "nested_duplicate": b'{"recipe":{"same":1,"same":2}}',
            "nonfinite": b'{"schema_version":NaN}',
            "invalid_utf8": b"\xff\xfe",
            "deep": b"[" * 3000 + b"0" + b"]" * 3000,
            "nonobject": b"[]",
        }
        return httpx.Response(200, content=bodies[kind])

    with pytest.raises(AIExecutionError) as error:
        await inventory_probe.inspect_inventory_capabilities(AIProvider(api_base="http://localhost:8823"), transport=httpx.MockTransport(response))
    assert len(calls) == 1 and "never-echo-this" not in str(error.value)
