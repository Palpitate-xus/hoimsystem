"""Actual authenticated schema10 metadata and Super-admin CAS-only inspection."""

import copy
import json

import httpx
import pytest

from app.ai import roster_probe
from app.ai.gateway import AIExecutionError
from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIProvider, AIRun
from app.ai.roster_config import RosterSettings, runtime_descriptor
from app.ai.roster_server import create_roster_app
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure


@pytest.mark.asyncio
async def test_metadata_is_only_authenticated_get_and_never_posts_problem(monkeypatch):
    key = "synthetic-roster-probe-independent-key-1234567890"
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ROSTER_API_KEY", key)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and str(request.url) == "http://localhost:8819/capabilities"
        assert request.headers["Authorization"] == "Bearer " + key and not request.content
        return httpx.Response(200, json=runtime_descriptor())

    value = await roster_probe.inspect_roster_capabilities(AIProvider(api_base="http://localhost:8819", api_key_env="AI_PROVIDER_LOCAL_ROSTER_API_KEY"), transport=httpx.MockTransport(handler))
    assert value == runtime_descriptor() and len(calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        "schema",
        "model",
        "recipe",
        "policy",
        "core",
        "tz",
        "digest",
        "engine",
        "operational",
        "prompt",
        "timeout",
        "boolean_limit",
        "response_limit",
        "plan_only",
        "independent",
        "extra",
        "redirect",
        "large",
        "malformed",
        "duplicate",
        "nonfinite",
        "unavailable",
    ],
)
@pytest.mark.asyncio
async def test_invalid_metadata_is_rejected_without_echo_or_redirect(change):
    value = copy.deepcopy(runtime_descriptor())
    changes = {
        "schema": ("schema_version", "9"),
        "model": ("model_version", "roster:" + "0" * 64),
        "tz": ("timezone_database_digest", "0" * 64),
        "digest": ("runtime_digest", "0" * 64),
        "engine": ("engine", "never-echo-this"),
        "operational": ("operational_validation", "validated"),
        "prompt": ("prompt_handling", "never-echo-this"),
        "timeout": ("timeout_seconds", "60"),
        "boolean_limit": ("max_request_bytes", True),
        "response_limit": ("max_response_bytes", 8388609),
        "plan_only": ("plan_only", 1),
        "independent": ("independent_implementation", 1),
        "extra": ("private_note", "never-echo-this"),
    }
    if change in changes:
        key, replacement = changes[change]
        value[key] = replacement
    elif change == "recipe":
        value["recipe"]["never-echo-this"] = 99
    elif change == "policy":
        value["input_policy"]["never-echo-this"] = True
    elif change == "core":
        value["core_sha256"]["roster_model"] = "0" * 64
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
            return httpx.Response(200, content=b'{"schema_version":"10","schema_version":"10"}')
        if change == "nonfinite":
            return httpx.Response(200, content=b'{"schema_version":NaN}')
        if change == "unavailable":
            raise httpx.ConnectError("never-echo-this", request=request)
        return httpx.Response(200, json=value)

    with pytest.raises(AIExecutionError) as error:
        await roster_probe.inspect_roster_capabilities(AIProvider(api_base="http://localhost:8819"), transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and "never-echo-this" not in error.value.message


@pytest.fixture
def roster_probe_case(db_session, seed_data, clean_ai_tasks, monkeypatch):
    key = "synthetic-roster-admin-independent-key-1234567890"
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ROSTER_API_KEY", key)
    config = RosterSettings(AI_PROVIDER_LOCAL_ROSTER_API_KEY=key)
    provider, feature = configure(db_session, seed_data, "roster_optimization")
    provider.kind, provider.model = "specialist", runtime_descriptor(config)["model_version"]
    provider.api_base, provider.api_key_env = "http://localhost:8819", "AI_PROVIDER_LOCAL_ROSTER_API_KEY"
    provider.supported_features_json = encode_json(["roster_optimization"])
    provider.validation_report = "Synthetic metadata protocol, not operational outcome validation."
    provider.timeout_seconds = 110
    db_session.commit()
    return {"seed": seed_data, "provider": provider, "feature": feature, "service": create_roster_app(config)}


def install(monkeypatch, case, *, after=None, error=None):
    calls = []
    inner = httpx.ASGITransport(app=case["service"])

    class MetadataTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append((request.method, request.url.path, request.content))
            return await inner.handle_async_request(request)

    original = roster_probe.inspect_roster_capabilities

    async def inspect(provider):
        value = await original(provider, transport=MetadataTransport())
        if after:
            after()
        if error:
            raise error
        return value

    monkeypatch.setattr(roster_probe, "inspect_roster_capabilities", inspect)
    return calls


async def check(client, headers, case, revision=None):
    return await client.post(
        f"/api/ai/admin/providers/{case['provider'].provider_id}/roster-capabilities", headers=headers, json={"expected_revision": case["provider"].revision if revision is None else revision}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [None, "model", "timeout"])
async def test_actual_metadata_route_reports_issues_never_validates_or_optimizes(mismatch, monkeypatch, async_client, auth_headers, db_session, roster_probe_case):
    case = roster_probe_case
    if mismatch == "model":
        case["provider"].model = "roster:" + "0" * 64
    elif mismatch == "timeout":
        case["provider"].timeout_seconds = 15
    db_session.commit()
    calls = install(monkeypatch, case)
    state = (case["feature"].enabled, case["feature"].validation_status, case["feature"].revision, case["provider"].model)
    runs = db_session.query(AIRun).count()
    audits = db_session.query(AIAuditEvent).filter_by(action="provider.roster_check").count()
    response = await check(async_client, auth_headers(case["seed"]["super_admin_user"].username), case)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["compatible"] is (mismatch is None)
    assert data["capabilities"]["schema_version"] == "10"
    assert data["capabilities"]["operational_validation"] == "not_provided"
    assert calls == [("GET", "/capabilities", b"")]
    db_session.expire_all()
    assert state == (case["feature"].enabled, case["feature"].validation_status, case["feature"].revision, case["provider"].model)
    assert db_session.query(AIRun).count() == runs
    assert db_session.query(AIAuditEvent).filter_by(action="provider.roster_check").count() == audits + 1
    assert data["provider_id"] == case["provider"].provider_id


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin_user", "director_user", "doctor_user", "nurse_user", "cashier_user", "pharmacist_user", "guide_user", "lab_tech_user", "registrar_user", "patient_user"])
async def test_all_non_super_roles_denied_before_metadata_access(role, monkeypatch, async_client, auth_headers, roster_probe_case):
    case = roster_probe_case
    calls = install(monkeypatch, case)
    response = await check(async_client, auth_headers(case["seed"][role].username), case)
    assert response.status_code == 403
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["role", "revision", "delete"])
async def test_held_response_rechecks_super_authority_and_current_saved_revision(change, monkeypatch, async_client, auth_headers, db_session, roster_probe_case):
    case = roster_probe_case

    def mutate():
        if change == "role":
            case["seed"]["super_admin_user"].user_role = "admin"
        elif change == "revision":
            db_session.add(case["provider"])
            case["provider"].revision += 1
        else:
            db_session.add(case["provider"])
            db_session.delete(case["provider"])
        db_session.commit()

    calls = install(monkeypatch, case, after=mutate)
    response = await check(async_client, auth_headers(case["seed"]["super_admin_user"].username), case)
    assert response.status_code == (403 if change == "role" else 409), response.text
    assert calls == [("GET", "/capabilities", b"")]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stale_revision", "protocol", "purpose"])
async def test_preflight_rejects_wrong_revision_protocol_or_feature_before_service(change, monkeypatch, async_client, auth_headers, db_session, roster_probe_case):
    case = roster_probe_case
    revision = case["provider"].revision
    if change == "stale_revision":
        case["provider"].revision += 1
    elif change == "protocol":
        case["provider"].kind = "chat"
    else:
        case["provider"].supported_features_json = json.dumps(["sepsis_risk"])
    db_session.commit()
    calls = install(monkeypatch, case)
    response = await check(async_client, auth_headers(case["seed"]["super_admin_user"].username), case, revision=revision)
    assert response.status_code == (409 if change == "stale_revision" else 422)
    assert calls == []


@pytest.mark.asyncio
async def test_failed_probe_has_sanitized_audit_and_no_feature_change(monkeypatch, async_client, auth_headers, db_session, roster_probe_case):
    case = roster_probe_case
    install(monkeypatch, case, error=AIExecutionError("ROSTER_CHECK_INVALID", "合成无效服务声明"))
    response = await check(async_client, auth_headers(case["seed"]["super_admin_user"].username), case)
    assert response.status_code == 502
    audit = db_session.query(AIAuditEvent).filter_by(action="provider.roster_check_failed").one()
    assert "ROSTER_CHECK_INVALID" in audit.detail_json
    assert case["feature"].validation_status == "validated"
