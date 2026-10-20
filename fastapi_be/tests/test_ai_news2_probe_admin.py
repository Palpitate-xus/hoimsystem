"""Super-admin inspection of the real metadata endpoint without patient scoring."""

import httpx
import pytest

from app.ai import news2_probe
from app.ai.gateway import AIExecutionError
from app.ai.models import AIAuditEvent, AIRun
from tests.test_ai_news2_pipeline import news2_case as news2_case
from tests.test_ai_observation_windows import observation_case as observation_case
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks


class MetadataTransport(httpx.AsyncBaseTransport):
    def __init__(self, app):
        self.inner = httpx.ASGITransport(app=app)
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append((request.method, request.url.path, request.content))
        return await self.inner.handle_async_request(request)


def install_inspector(monkeypatch, case, *, after=None, error=None):
    transport = MetadataTransport(case["service"])
    original = news2_probe.inspect_news2_capabilities

    async def inspect(provider):
        value = await original(provider, transport=transport)
        if after:
            after()
        if error:
            raise error
        return value

    monkeypatch.setattr(news2_probe, "inspect_news2_capabilities", inspect)
    return transport


async def check(client, headers, case, revision=None):
    return await client.post(
        f"/api/ai/admin/providers/{case['provider'].provider_id}/news2-capabilities", headers=headers, json={"expected_revision": revision if revision is not None else case["provider"].revision}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [None, "model", "timeout"])
async def test_actual_metadata_only_probe_reports_runtime_and_never_approves_or_scores(mismatch, monkeypatch, async_client, auth_headers, db_session, news2_case):
    case = news2_case
    if mismatch == "model":
        case["provider"].model = "news2:" + "0" * 64
    elif mismatch == "timeout":
        case["provider"].timeout_seconds = 15
    db_session.commit()
    transport = install_inspector(monkeypatch, case)
    state = (case["feature"].enabled, case["feature"].validation_status, case["feature"].revision, case["provider"].model)
    count = db_session.query(AIRun).count()
    response = await check(async_client, auth_headers(case["seed"]["super_admin_user"].username), case)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["compatible"] is (mismatch is None)
    assert data["capabilities"]["schema_version"] == "6"
    assert data["capabilities"]["clinical_validation"] == "not_provided"
    assert data["capabilities"]["model_version"].startswith("news2:")
    assert transport.requests == [("GET", "/capabilities", b"")]
    db_session.expire_all()
    assert state == (case["feature"].enabled, case["feature"].validation_status, case["feature"].revision, case["provider"].model)
    assert db_session.query(AIRun).count() == count
    assert db_session.query(AIAuditEvent).filter_by(action="provider.news2_check").count() >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin_user", "director_user", "doctor_user", "nurse_user", "cashier_user", "pharmacist_user", "guide_user", "lab_tech_user", "registrar_user", "patient_user"])
async def test_all_non_super_roles_are_denied_before_service_access(role, monkeypatch, async_client, auth_headers, news2_case):
    case = news2_case
    transport = install_inspector(monkeypatch, case)
    response = await check(async_client, auth_headers(case["seed"][role].username), case)
    assert response.status_code == 403
    assert transport.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["role", "revision", "delete"])
async def test_held_metadata_reply_cannot_outlive_management_authority_or_saved_revision(change, monkeypatch, async_client, auth_headers, db_session, news2_case):
    case = news2_case

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

    transport = install_inspector(monkeypatch, case, after=mutate)
    response = await check(async_client, auth_headers(case["seed"]["super_admin_user"].username), case)
    assert response.status_code == (403 if change == "role" else 409), response.text
    assert transport.requests == [("GET", "/capabilities", b"")]


@pytest.mark.asyncio
async def test_failed_metadata_probe_keeps_configuration_and_audits_sanitized_error(monkeypatch, async_client, auth_headers, db_session, news2_case):
    case = news2_case
    install_inspector(monkeypatch, case, error=AIExecutionError("NEWS2_CHECK_INVALID", "合成无效服务声明"))
    response = await check(async_client, auth_headers(case["seed"]["super_admin_user"].username), case)
    assert response.status_code == 502 and "合成无效服务声明" in response.text
    db_session.expire_all()
    assert case["feature"].enabled == 1 and case["feature"].validation_status == "validated"
    assert db_session.query(AIAuditEvent).filter_by(action="provider.news2_check_failed").count() >= 1


@pytest.mark.asyncio
async def test_stale_revision_or_non_specialist_provider_does_not_contact_service(monkeypatch, async_client, auth_headers, db_session, news2_case):
    case = news2_case
    transport = install_inspector(monkeypatch, case)
    headers = auth_headers(case["seed"]["super_admin_user"].username)
    assert (await check(async_client, headers, case, revision=case["provider"].revision + 1)).status_code == 409
    case["provider"].kind = "chat"
    db_session.commit()
    assert (await check(async_client, headers, case)).status_code == 422
    assert transport.requests == []
