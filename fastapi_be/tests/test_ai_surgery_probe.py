"""Authenticated metadata-only surgery capability checks and strict rejection."""

import copy
import json

import httpx
import pytest

from app.ai import surgery_probe, surgery_server
from app.ai.gateway import AIExecutionError
from app.ai.models import AIProvider
from app.ai.surgery_config import SurgerySettings, runtime_descriptor
from app.ai.surgery_contract import SurgeryRuntime, hash_content

KEY = "synthetic-surgery-metadata-key-00000000001"


@pytest.fixture
def descriptor():
    return runtime_descriptor()


@pytest.mark.asyncio
async def test_actual_native_capabilities_get_has_auth_no_body_and_never_invokes_solver(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SURGERY_API_KEY", KEY)

    def no_solving(*args, **kwargs):
        raise AssertionError("A capability check must never solve a case")

    monkeypatch.setattr(surgery_server, "compute_surgery", no_solving)
    config = SurgerySettings(AI_PROVIDER_LOCAL_SURGERY_API_KEY=KEY)
    native = surgery_server.create_surgery_app(config)
    calls = []

    class Wire(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append(request)
            assert request.method == "GET" and str(request.url) == "http://localhost:8821/capabilities"
            assert request.headers["Authorization"] == "Bearer " + KEY and request.content == b""
            return await httpx.ASGITransport(app=native).handle_async_request(request)

    value = await surgery_probe.inspect_surgery_capabilities(AIProvider(api_base="http://localhost:8821/", api_key_env="AI_PROVIDER_LOCAL_SURGERY_API_KEY"), transport=Wire())
    assert value == runtime_descriptor(config) and len(calls) == 1
    assert value["candidate_only"] is True and value["automatic_booking"] is False
    assert value["clinical_validation"] == value["operational_validation"] == "not_provided"
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
        "automatic_booking",
        "automatic_booking_int",
        "candidate_int",
        "independent_int",
        "usage_claim",
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
async def test_complete_runtime_and_nonclinical_candidate_only_declarations_are_verified(change, descriptor):
    value = copy.deepcopy(descriptor)
    changes = {
        "schema": ("schema_version", "11"),
        "feature": ("feature_key", "bed_forecast"),
        "model": ("model_version", "surgery:" + "0" * 64),
        "scope": ("scope", "hospital_wide_auto_booking"),
        "automatic_booking": ("automatic_booking", True),
        "automatic_booking_int": ("automatic_booking", 0),
        "candidate_int": ("candidate_only", 1),
        "independent_int": ("independent_implementation", 1),
        "usage_claim": ("forecast_or_clinical_guarantee", "guaranteed"),
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
        value["core_sha256"]["surgery_model"] = "0" * 64
        value["runtime_digest"] = hash_content({field: value[field] for field in SurgeryRuntime.model_fields if field not in {"runtime_digest", "model_version"}})
        value["model_version"] = "surgery:" + value["runtime_digest"]
    elif change == "core_missing":
        value["core_sha256"].pop("surgery_server")
    else:
        value["engine_versions"].pop("fastapi")

    def response(request):
        assert request.method == "GET" and request.content == b""
        return httpx.Response(200, json=value)

    with pytest.raises(AIExecutionError) as error:
        await surgery_probe.inspect_surgery_capabilities(AIProvider(api_base="http://localhost:8821"), transport=httpx.MockTransport(response))
    assert error.value.code == "SURGERY_CHECK_INVALID"
    assert "never-echo-this" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["redirect", "http", "large", "malformed", "duplicate", "nested_duplicate", "nonfinite", "invalid_utf8", "deep", "nonobject", "timeout"])
async def test_unbounded_duplicate_nonfinite_transport_failures_and_redirect_are_rejected(kind):
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
            "duplicate": b'{"schema_version":"12","schema_version":"12"}',
            "nested_duplicate": b'{"recipe":{"same":1,"same":2}}',
            "nonfinite": b'{"schema_version":NaN}',
            "invalid_utf8": b"\xff\xfe",
            "deep": b"[" * 3000 + b"0" + b"]" * 3000,
            "nonobject": b"[]",
        }
        return httpx.Response(200, content=bodies[kind])

    with pytest.raises(AIExecutionError) as error:
        await surgery_probe.inspect_surgery_capabilities(AIProvider(api_base="http://localhost:8821"), transport=httpx.MockTransport(response))
    assert len(calls) == 1 and "never-echo-this" not in str(error.value)
