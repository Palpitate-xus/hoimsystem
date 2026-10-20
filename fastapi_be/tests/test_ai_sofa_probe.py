"""Only authenticated metadata is sent while the complete local policy is verified."""

import copy

import httpx
import pytest

from app.ai.gateway import AIExecutionError
from app.ai.models import AIProvider
from app.ai.sofa_config import runtime_descriptor
from app.ai.sofa_probe import inspect_sofa_capabilities


@pytest.mark.asyncio
async def test_actual_metadata_probe_sends_only_authenticated_get(monkeypatch):
    key = "synthetic-sofa-probe-independent-key-no-live-credential"
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SOFA_API_KEY", key)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and str(request.url) == "http://localhost:8818/capabilities"
        assert request.headers["Authorization"] == "Bearer " + key and not request.content
        return httpx.Response(200, json=runtime_descriptor())

    value = await inspect_sofa_capabilities(AIProvider(api_base="http://localhost:8818", api_key_env="AI_PROVIDER_LOCAL_SOFA_API_KEY"), transport=httpx.MockTransport(handler))
    assert value == runtime_descriptor() and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "schema",
        "model",
        "recipe",
        "policy",
        "core",
        "digest",
        "engine",
        "clinical",
        "prompt",
        "timeout",
        "boolean_limit",
        "response_limit",
        "extra",
        "redirect",
        "large",
        "malformed",
        "duplicate",
        "unavailable",
    ],
)
async def test_invalid_metadata_does_not_echo_service_material_or_follow_redirects(change):
    value = copy.deepcopy(runtime_descriptor())
    changes = {
        "schema": ("schema_version", "8"),
        "model": ("model_version", "sofa1:" + "0" * 64),
        "digest": ("policy_digest", "0" * 64),
        "engine": ("engine", "never-echo-this"),
        "clinical": ("clinical_validation", "never-echo-this"),
        "prompt": ("prompt_handling", "never-echo-this"),
        "timeout": ("timeout_seconds", "60"),
        "boolean_limit": ("max_request_bytes", True),
        "response_limit": ("max_response_bytes", 8388609),
        "extra": ("private_note", "never-echo-this"),
    }
    if change in changes:
        key, replacement = changes[change]
        value[key] = replacement
    elif change == "recipe":
        value["recipe"]["cardiovascular"] = {"never-echo-this": 99}
    elif change == "policy":
        value["input_policy"]["never-echo-this"] = True
    elif change == "core":
        value["core_sha256"]["sofa_model.py"] = "0" * 64
    calls = []

    def handler(request):
        calls.append(request)
        if change == "redirect":
            return httpx.Response(302, headers={"Location": "https://unapproved.example/never-echo-this"})
        if change == "large":
            return httpx.Response(200, content=b"never-echo-this" * 5000)
        if change == "malformed":
            return httpx.Response(200, content=b"never-echo-this")
        if change == "duplicate":
            return httpx.Response(200, content=b'{"schema_version":"9","schema_version":"9"}')
        if change == "unavailable":
            raise httpx.ConnectError("never-echo-this", request=request)
        return httpx.Response(200, json=value)

    with pytest.raises(AIExecutionError) as error:
        await inspect_sofa_capabilities(AIProvider(api_base="http://localhost:8818"), transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and "never-echo-this" not in error.value.message
