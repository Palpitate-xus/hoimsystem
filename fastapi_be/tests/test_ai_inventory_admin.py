"""Actual Super-only inventory metadata route, saved revision and current role checks."""

import json

import httpx
import pytest

from app.ai import inventory_probe
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError
from app.ai.governance import encode_json, provider_feature_issues
from app.ai.inventory_config import InventorySettings, runtime_descriptor
from app.ai.inventory_server import create_inventory_app
from app.ai.models import AIAuditEvent, AIRun
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure


@pytest.fixture
def inventory_probe_case(db_session, seed_data, clean_ai_tasks, monkeypatch):
    key = "synthetic-inventory-admin-independent-key-1234567890"
    monkeypatch.setenv("AI_PROVIDER_LOCAL_INVENTORY_API_KEY", key)
    config = InventorySettings(AI_PROVIDER_LOCAL_INVENTORY_API_KEY=key)
    provider, feature = configure(db_session, seed_data, "inventory_optimization")
    provider.kind, provider.model = "specialist", runtime_descriptor(config)["model_version"]
    provider.api_base, provider.api_key_env = "http://localhost:8823", "AI_PROVIDER_LOCAL_INVENTORY_API_KEY"
    provider.supported_features_json = encode_json(["inventory_optimization"])
    provider.validation_report = "Synthetic metadata protocol, not operational outcome validation."
    provider.timeout_seconds = 110
    db_session.commit()
    return {"seed": seed_data, "provider": provider, "feature": feature, "service": create_inventory_app(config)}


def install(monkeypatch, case, *, after=None, error=None):
    calls = []
    inner = httpx.ASGITransport(app=case["service"])

    class MetadataTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append((request.method, request.url.path, request.content))
            return await inner.handle_async_request(request)

    original = inventory_probe.inspect_inventory_capabilities

    async def inspect(provider):
        value = await original(provider, transport=MetadataTransport())
        if after:
            after()
        if error:
            raise error
        return value

    monkeypatch.setattr(inventory_probe, "inspect_inventory_capabilities", inspect)
    return calls


async def check(client, headers, case, revision=None):
    return await client.post(
        f"/api/ai/admin/providers/{case['provider'].provider_id}/inventory-capabilities", headers=headers, json={"expected_revision": case["provider"].revision if revision is None else revision}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [None, "model", "timeout"])
async def test_actual_metadata_route_reports_issues_never_validates_or_compares(mismatch, monkeypatch, async_client, auth_headers, db_session, inventory_probe_case, tmp_path):
    case = inventory_probe_case
    if mismatch == "model":
        case["provider"].model = "inventory:" + "0" * 64
    elif mismatch == "timeout":
        case["provider"].timeout_seconds = 15
    db_session.commit()
    calls = install(monkeypatch, case)
    state = (case["feature"].enabled, case["feature"].validation_status, case["feature"].revision, case["provider"].model)
    runs = db_session.query(AIRun).count()
    audits = db_session.query(AIAuditEvent).filter_by(action="provider.inventory_check").count()
    response = await check(async_client, auth_headers(case["seed"]["super_admin_user"].username), case)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["compatible"] is (mismatch is None)
    assert data["capabilities"]["schema_version"] == "14"
    assert data["capabilities"]["operational_validation"] == "not_provided"
    assert calls == [("GET", "/capabilities", b"")]
    assert "共同约束" in data["scope_note"] and "六模型" not in data["scope_note"]
    db_session.expire_all()
    assert state == (case["feature"].enabled, case["feature"].validation_status, case["feature"].revision, case["provider"].model)
    assert db_session.query(AIRun).count() == runs
    assert db_session.query(AIAuditEvent).filter_by(action="provider.inventory_check").count() == audits + 1
    assert data["provider_id"] == case["provider"].provider_id
    (tmp_path / "actual-inventory-capabilities-check.json").write_text(json.dumps(response.json(), ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin_user", "director_user", "doctor_user", "nurse_user", "cashier_user", "pharmacist_user", "guide_user", "lab_tech_user", "registrar_user", "patient_user"])
async def test_all_non_super_roles_denied_before_metadata_access(role, monkeypatch, async_client, auth_headers, inventory_probe_case):
    case = inventory_probe_case
    calls = install(monkeypatch, case)
    response = await check(async_client, auth_headers(case["seed"][role].username), case)
    assert response.status_code == 403
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["role", "revision", "delete"])
async def test_held_response_rechecks_super_authority_and_current_saved_revision(change, monkeypatch, async_client, auth_headers, db_session, inventory_probe_case):
    case = inventory_probe_case

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
async def test_preflight_rejects_wrong_revision_protocol_or_feature_before_service(change, monkeypatch, async_client, auth_headers, db_session, inventory_probe_case):
    case = inventory_probe_case
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
async def test_failed_probe_has_sanitized_audit_and_no_feature_change(monkeypatch, async_client, auth_headers, db_session, inventory_probe_case):
    case = inventory_probe_case
    install(monkeypatch, case, error=AIExecutionError("INVENTORY_CHECK_INVALID", "合成无效服务声明"))
    response = await check(async_client, auth_headers(case["seed"]["super_admin_user"].username), case)
    assert response.status_code == 502
    audit = db_session.query(AIAuditEvent).filter_by(action="provider.inventory_check_failed").one()
    assert "INVENTORY_CHECK_INVALID" in audit.detail_json
    assert case["feature"].validation_status == "validated"


@pytest.mark.parametrize("feature,kind", [("operations_qa", "specialist"), ("bed_forecast", "specialist"), ("inventory_optimization", "chat"), ("inventory_optimization", "responses")])
def test_native_inventory_model_configuration_requires_its_own_feature_and_protocol(feature, kind, inventory_probe_case):
    provider = inventory_probe_case["provider"]
    provider.kind = kind
    assert "INVENTORY_SCOPE_MISMATCH" in {issue["code"] for issue in provider_feature_issues(FEATURE_BY_KEY[feature], provider)}
