"""Metadata-only AKI inspection validates fixed rules without sending patients."""

import copy

import httpx
import pytest

from app.ai.aki_config import runtime_descriptor
from app.ai.aki_probe import inspect_aki_capabilities
from app.ai.gateway import AIExecutionError
from app.ai.models import AIProvider


@pytest.mark.asyncio
async def test_actual_metadata_probe_sends_only_authenticated_get(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_AKI_API_KEY", "synthetic-aki-probe-credential-only")
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and str(request.url) == "http://localhost:8815/capabilities"
        assert request.headers["Authorization"] == "Bearer synthetic-aki-probe-credential-only"
        assert not request.content
        return httpx.Response(200, json=runtime_descriptor())

    descriptor = await inspect_aki_capabilities(AIProvider(api_base="http://localhost:8815", api_key_env="AI_PROVIDER_LOCAL_AKI_API_KEY"), transport=httpx.MockTransport(handler))
    assert descriptor == runtime_descriptor() and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["schema", "model", "recipe", "source", "hash", "versions", "certified", "timeout", "bytes", "extra", "redirect", "large", "malformed", "duplicate", "unavailable"])
async def test_bad_capabilities_fail_without_echoing_the_service_body(case):
    descriptor = copy.deepcopy(runtime_descriptor())
    if case == "schema":
        descriptor["schema_version"] = "5"
    elif case == "model":
        descriptor["model_version"] = "aki:" + "0" * 64
    elif case == "recipe":
        descriptor["recipe"]["absolute_stage3"]["at_least"]["mg/dL"] = "99"
    elif case == "source":
        descriptor["implementation"]["aki_model.py"] = "0" * 64
    elif case == "hash":
        descriptor["recipe_digest"] = "0" * 64
    elif case == "versions":
        descriptor["engine_versions"]["never-echo-this"] = "99.0.0"
    elif case == "certified":
        descriptor["clinical_validation"] = "RCP-certified-never-echo-this"
    elif case == "timeout":
        descriptor["timeout_seconds"] = "15"
    elif case == "bytes":
        descriptor["max_request_bytes"] = True
    elif case == "extra":
        descriptor["private_material"] = "never-echo-this"
    calls = []

    def handler(request):
        calls.append(request)
        if case == "redirect":
            return httpx.Response(302, headers={"Location": "https://unapproved.example/never-echo-this"})
        if case == "large":
            return httpx.Response(200, content=b"never-echo-this" * 2000)
        if case == "malformed":
            return httpx.Response(200, content=b"never-echo-this")
        if case == "duplicate":
            return httpx.Response(200, content=b'{"schema_version":"7","schema_version":"7"}')
        if case == "unavailable":
            raise httpx.ConnectError("never-echo-this", request=request)
        return httpx.Response(200, json=descriptor)

    with pytest.raises(AIExecutionError) as exc:
        await inspect_aki_capabilities(AIProvider(api_base="http://localhost:8815"), transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and "never-echo-this" not in exc.value.message
