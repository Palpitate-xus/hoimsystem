"""Actual authenticated schema11 read-only capabilities and strict failure boundaries."""

import copy
import json

import httpx
import pytest
from sqlalchemy import event

from app.ai import bed_probe, bed_server
from app.ai.bed_config import BedSettings, runtime_descriptor
from app.ai.bed_contract import BedRuntime, hash_content
from app.ai.gateway import AIExecutionError
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIProvider, AIRun

KEY = "synthetic-bed-probe-independent-key-1234567890"


@pytest.fixture
def descriptor():
    return runtime_descriptor()


@pytest.mark.asyncio
async def test_inspection_only_performs_authenticated_get_with_no_originals_or_forecast(monkeypatch, descriptor):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_BED_API_KEY", KEY)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and str(request.url) == "http://localhost:8820/capabilities"
        assert request.headers["Authorization"] == "Bearer " + KEY and request.content == b""
        return httpx.Response(200, json=descriptor)

    value = await bed_probe.inspect_bed_capabilities(AIProvider(api_base="http://localhost:8820/", api_key_env="AI_PROVIDER_LOCAL_BED_API_KEY"), transport=httpx.MockTransport(handler))
    assert value == descriptor and len(calls) == 1
    assert value["forecast_only"] is True and value["operational_validation"] == value["clinical_validation"] == "not_provided"
    assert KEY not in json.dumps(value)


@pytest.mark.parametrize(
    "change",
    [
        "schema",
        "feature",
        "rule",
        "model",
        "recipe",
        "policy",
        "core_missing",
        "core_extra",
        "core_rehashed",
        "tz_digest",
        "digest",
        "engine",
        "clinical",
        "operational",
        "prompt",
        "coverage",
        "scope",
        "python",
        "versions",
        "versions_missing",
        "timeout_string",
        "timeout_zero",
        "timeout_big",
        "request_bool",
        "request_small",
        "request_big",
        "response_small",
        "response_big",
        "forecast_only",
        "independent",
        "extra",
        "redirect",
        "bad_http",
        "large",
        "malformed",
        "duplicate",
        "nested_duplicate",
        "nonfinite",
        "unavailable",
        "timeout",
        "nonobject",
        "invalid_utf8",
        "deep",
    ],
)
@pytest.mark.asyncio
async def test_false_or_unbounded_runtime_declarations_fail_without_echo_or_redirect(change, descriptor):
    value = copy.deepcopy(descriptor)
    changes = {
        "schema": ("schema_version", "10"),
        "feature": ("feature_key", "roster_optimization"),
        "rule": ("rule_id", "roster_declared_constraints_v1"),
        "model": ("model_version", "bed:" + "0" * 64),
        "tz_digest": ("timezone_database_digest", "0" * 64),
        "digest": ("runtime_digest", "0" * 64),
        "engine": ("engine", "never-echo-this"),
        "clinical": ("clinical_validation", "validated"),
        "operational": ("operational_validation", "validated"),
        "prompt": ("prompt_handling", "never-echo-this"),
        "coverage": ("coverage_guarantee", "validated"),
        "scope": ("scope", "admittable_slots"),
        "python": ("python_version", "3.13"),
        "timeout_string": ("timeout_seconds", "60"),
        "timeout_zero": ("timeout_seconds", 0),
        "timeout_big": ("timeout_seconds", 111),
        "request_bool": ("max_request_bytes", True),
        "request_small": ("max_request_bytes", 65535),
        "request_big": ("max_request_bytes", 8388609),
        "response_small": ("max_response_bytes", 8388607),
        "response_big": ("max_response_bytes", 8388609),
        "forecast_only": ("forecast_only", 1),
        "independent": ("independent_implementation", 1),
        "extra": ("private_note", "never-echo-this"),
    }
    if change in changes:
        key, replacement = changes[change]
        value[key] = replacement
    elif change == "recipe":
        value["recipe"]["never-echo-this"] = 1
    elif change == "policy":
        value["input_policy"]["never-echo-this"] = True
    elif change == "core_missing":
        value["core_sha256"].pop("bed_model")
    elif change == "core_extra":
        value["core_sha256"]["roster_model"] = "0" * 64
    elif change == "core_rehashed":
        value["core_sha256"]["bed_model"] = "0" * 64
        identity = {key: value[key] for key in BedRuntime.model_fields if key not in {"runtime_digest", "model_version"}}
        value["runtime_digest"] = hash_content(identity)
        value["model_version"] = "bed:" + value["runtime_digest"]
    elif change == "versions":
        value["engine_versions"]["fastapi"] = "never-echo-this"
    elif change == "versions_missing":
        value["engine_versions"].pop("fastapi")
    calls = []

    def handler(request):
        calls.append(request)
        if change == "redirect":
            return httpx.Response(302, headers={"Location": "https://unapproved.example/never-echo-this"})
        if change == "bad_http":
            return httpx.Response(500, text="never-echo-this")
        if change == "large":
            return httpx.Response(200, content=b"never-echo-this" * 5000)
        if change == "malformed":
            return httpx.Response(200, content=b"never-echo-this")
        if change == "duplicate":
            return httpx.Response(200, content=b'{"schema_version":"11","schema_version":"11"}')
        if change == "nested_duplicate":
            return httpx.Response(200, content=b'{"recipe":{"same":1,"same":2}}')
        if change == "nonfinite":
            return httpx.Response(200, content=b'{"schema_version":NaN}')
        if change == "unavailable":
            raise httpx.ConnectError("never-echo-this", request=request)
        if change == "timeout":
            raise httpx.ReadTimeout("never-echo-this", request=request)
        if change == "nonobject":
            return httpx.Response(200, json=[value])
        if change == "invalid_utf8":
            return httpx.Response(200, content=b"\xff\xfe\xfd")
        if change == "deep":
            return httpx.Response(200, content=b"[" * 3000 + b"0" + b"]" * 3000)
        return httpx.Response(200, json=value)

    with pytest.raises(AIExecutionError) as error:
        await bed_probe.inspect_bed_capabilities(AIProvider(api_base="http://localhost:8820"), transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and calls[0].method == "GET" and calls[0].content == b""
    assert error.value.code.startswith("BED_CHECK_") and "never-echo-this" not in error.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize("configuration", ["missing_secret", "disallowed_host", "userinfo", "query", "remote_http"])
async def test_bad_provider_configuration_fails_before_any_request(monkeypatch, configuration):
    provider = AIProvider(api_base="http://localhost:8820")
    if configuration == "missing_secret":
        monkeypatch.delenv("AI_PROVIDER_LOCAL_BED_API_KEY", raising=False)
        provider.api_key_env = "AI_PROVIDER_LOCAL_BED_API_KEY"
    else:
        provider.api_base = {
            "disallowed_host": "https://unapproved.example",
            "userinfo": "http://never-echo-this@localhost:8820",
            "query": "http://localhost:8820?secret=never-echo-this",
            "remote_http": "http://unapproved.example",
        }[configuration]
    calls = []

    def handler(request):
        calls.append(request)
        raise AssertionError("Invalid configuration must not perform I/O")

    with pytest.raises(AIExecutionError) as error:
        await bed_probe.inspect_bed_capabilities(provider, transport=httpx.MockTransport(handler))
    assert error.value.code == "PROVIDER_CONFIGURATION" and "never-echo-this" not in error.value.message
    assert not calls


@pytest.mark.asyncio
async def test_actual_native_asgi_metadata_never_calls_tasks_or_changes_database(seed_data, db_session, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_BED_API_KEY", KEY)
    monkeypatch.setenv("HTTP_PROXY", "http://unapproved.example/never-echo-this")
    monkeypatch.setenv("HTTPS_PROXY", "http://unapproved.example/never-echo-this")
    monkeypatch.setenv("NO_PROXY", "")

    def no_forecast(*args, **kwargs):
        raise AssertionError("Capabilities must not submit or calculate any forecast")

    monkeypatch.setattr(bed_server, "compute_bed", no_forecast)
    service = bed_server.create_bed_app(BedSettings(AI_PROVIDER_LOCAL_BED_API_KEY=KEY))
    native = httpx.ASGITransport(app=service)
    calls = []

    class OnlyCapabilities(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append((request.method, request.url.path, request.content))
            assert request.method == "GET" and request.url.path == "/capabilities"
            return await native.handle_async_request(request)

    provider = AIProvider(api_base="http://localhost:8820", api_key_env="AI_PROVIDER_LOCAL_BED_API_KEY")
    before = {model.__tablename__: db_session.query(model).count() for model in (AIRun, AIFeatureConfig, AIAuditEvent, AIProvider)}
    writes = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        capabilities = await bed_probe.inspect_bed_capabilities(provider, transport=OnlyCapabilities())
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)
    assert capabilities == runtime_descriptor()
    assert calls == [("GET", "/capabilities", b"")]
    assert not writes
    assert before == {model.__tablename__: db_session.query(model).count() for model in (AIRun, AIFeatureConfig, AIAuditEvent, AIProvider)}


@pytest.mark.asyncio
async def test_native_credential_failure_is_sanitized_without_forecast(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_BED_API_KEY", "different-synthetic-bed-metadata-key-123456789")
    service = bed_server.create_bed_app(BedSettings(AI_PROVIDER_LOCAL_BED_API_KEY=KEY))
    with pytest.raises(AIExecutionError) as error:
        await bed_probe.inspect_bed_capabilities(AIProvider(api_base="http://localhost:8820", api_key_env="AI_PROVIDER_LOCAL_BED_API_KEY"), transport=httpx.ASGITransport(app=service))
    assert error.value.code == "BED_CHECK_HTTP_ERROR" and KEY not in error.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize("extra_bytes", [0, 1])
async def test_actual_streamed_report_boundary_checks_bytes_before_appending(extra_bytes, descriptor):
    body = json.dumps(descriptor).encode()
    padding = bed_probe.MAX_REPORT_BYTES - len(body)
    assert padding > 0
    chunks = [body, b" " * padding]
    if extra_bytes:
        chunks.append(b" ")

    class ReportStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in chunks:
                yield chunk

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=ReportStream())

    operation = bed_probe.inspect_bed_capabilities(AIProvider(api_base="http://localhost:8820"), transport=httpx.MockTransport(handler))
    if extra_bytes:
        with pytest.raises(AIExecutionError) as error:
            await operation
        assert error.value.code == "BED_CHECK_TOO_LARGE"
    else:
        assert await operation == descriptor
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_endpoint_with_nonprintable_path_is_a_sanitized_configuration_error_before_io():
    calls = []

    def handler(request):
        calls.append(request)
        raise AssertionError("Invalid endpoint cannot perform a request")

    with pytest.raises(AIExecutionError) as error:
        await bed_probe.inspect_bed_capabilities(AIProvider(api_base="http://localhost:8820/never-echo-this\npath"), transport=httpx.MockTransport(handler))
    assert error.value.code == "PROVIDER_CONFIGURATION" and "never-echo-this" not in error.value.message
    assert not calls
