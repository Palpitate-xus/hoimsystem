"""Actual shared HTTP routes, requester care, Super governance and atomic audit failures."""

import datetime
import json

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.ai import governance
from app.ai.models import AIAuditEvent
from app.database import get_db
from app.inpatient_observations import utc_text
from app.inpatient_respiratory_models import InpatientArterialPairSource
from app.models import NursingRecord
from app.routers import inpatient_support as routes
from tests.test_inpatient_respiratory_contract import NOTE, map_payload, support_payload
from tests.test_inpatient_respiratory_sources import body
from tests.test_inpatient_respiratory_sources import observation_case as observation_case
from tests.test_inpatient_respiratory_sources import source_case as source_case


@pytest_asyncio.fixture
async def source_client(db_session):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic-organ-support") as client:
        yield client


def request(case, kind):
    value = (
        body(case)
        if kind == "arterial_pair"
        else map_payload(observed_at=utc_text(case["start"]))
        if kind == "map"
        else support_payload(start_at=utc_text(case["start"]), verified_until_at=utc_text(case["end"]))
    )
    return {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id, "payload": value}


def scope(case):
    return {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id}


async def register(client, case, headers, kind="arterial_pair"):
    response = await client.post(f"/api/inpatient-support/{kind}", headers=headers, json=request(case, kind))
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["map", "respiratory_support", "arterial_pair"])
async def test_real_shared_http_create_detail_list_options_and_super_audit_preserve_exact_original(source_client, source_case, auth_headers, db_session, kind):
    case = source_case
    headers = auth_headers(case["doctor"].username)
    data = await register(source_client, case, headers, kind)
    assert data["kind"] == kind and data["patient_id"] == case["patient_id"]
    assert data["can_record"] is data["can_revoke"] is data["eligible"] is True
    assert data["payload"] == request(case, kind)["payload"]
    detail = await source_client.get(f"/api/inpatient-support/{kind}/{data['support_source_id']}", headers=headers, params=scope(case))
    assert detail.status_code == 200 and detail.json()["data"] == data
    listed = await source_client.get(f"/api/inpatient-support/{kind}", headers=headers, params={**scope(case), "page": 1, "page_size": 100})
    assert listed.status_code == 200
    assert data in listed.json()["data"]["items"] and listed.json()["data"]["can_record"] is True
    options = await source_client.get("/api/inpatient-support/options", headers=headers, params=scope(case))
    assert options.status_code == 200 and len(options.json()["data"]["kinds"]) == 5
    assert options.json()["data"]["clinical_mappings_seeded"] is False
    audit = await source_client.get(f"/api/ai/admin/support-sources/{kind}/{data['support_source_id']}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert audit.status_code == 200
    assert audit.json()["data"] == {**data, "can_record": False, "can_revoke": True}
    audit_event = db_session.query(AIAuditEvent).filter_by(target=data["support_source_id"], action="support_source.create").one()
    assert json.loads(audit_event.detail_json) == {"kind": kind, "content_hash": data["content_hash"], "source_verification": "explicit_human_record_not_independently_verified"}


@pytest.mark.asyncio
async def test_nonauthor_care_nurse_can_read_but_cannot_revoke_doctor_original(source_client, source_case, auth_headers, db_session):
    case = source_case
    db_session.add(NursingRecord(patient_id=case["patient_id"], admission_id=case["admission"].admission_id, nurse_id=case["seed"]["nurse_user"].user_id, note="合成实际照护"))
    db_session.commit()
    data = await register(source_client, case, auth_headers(case["doctor"].username))
    nurse_headers = auth_headers(case["seed"]["nurse_user"].username)
    response = await source_client.get(f"/api/inpatient-support/arterial_pair/{data['support_source_id']}", headers=nurse_headers, params=scope(case))
    assert response.status_code == 200 and response.json()["data"]["can_record"] is False and response.json()["data"]["can_revoke"] is False
    denied = await source_client.post(f"/api/inpatient-support/arterial_pair/{data['support_source_id']}/revoke", headers=nurse_headers, json={**scope(case), "expected_revision": 1, "reason": NOTE})
    assert denied.status_code == 403
    assert db_session.get(InpatientArterialPairSource, data["support_source_id"]).status == "active"


@pytest.mark.asyncio
async def test_original_author_cas_revoke_is_audited_once_and_does_not_mutate_frozen_body(source_client, source_case, auth_headers, db_session):
    case = source_case
    headers = auth_headers(case["doctor"].username)
    data = await register(source_client, case, headers)
    request_body = {**scope(case), "expected_revision": 1, "reason": NOTE}
    url = f"/api/inpatient-support/arterial_pair/{data['support_source_id']}/revoke"
    response = await source_client.post(url, headers=headers, json=request_body)
    assert response.status_code == 200, response.text
    revoked = response.json()["data"]
    assert revoked["status"] == "revoked" and revoked["revision"] == 2 and revoked["can_revoke"] is revoked["eligible"] is False
    assert revoked["content_hash"] == data["content_hash"] and revoked["reference_snapshots"] == data["reference_snapshots"]
    assert revoked["governance_hash"] != data["governance_hash"]
    duplicate = await source_client.post(url, headers=headers, json=request_body)
    assert duplicate.status_code == 409
    assert db_session.query(AIAuditEvent).filter_by(target=data["support_source_id"], action="support_source.revoke").count() == 1


@pytest.mark.asyncio
async def test_changed_admission_original_is_only_super_frozen_audit_and_can_be_cas_revoked(source_client, source_case, auth_headers, db_session):
    case = source_case
    doctor_headers = auth_headers(case["doctor"].username)
    super_headers = auth_headers(case["seed"]["super_admin_user"].username)
    data = await register(source_client, case, doctor_headers)
    case["admission"].patient_id = case["seed"]["patient2"].patient_id
    db_session.commit()
    ordinary = await source_client.get(f"/api/inpatient-support/arterial_pair/{data['support_source_id']}", headers=doctor_headers, params=scope(case))
    assert ordinary.status_code in (403, 404, 409)
    audit = await source_client.get(f"/api/ai/admin/support-sources/arterial_pair/{data['support_source_id']}", headers=super_headers)
    assert audit.status_code == 200
    frozen = audit.json()["data"]
    assert frozen["eligible"] is frozen["original_admission_current"] is frozen["can_record"] is False and frozen["can_revoke"] is True
    assert frozen["reference_snapshots"] == data["reference_snapshots"] and frozen["content_hash"] == data["content_hash"]
    response = await source_client.post(f"/api/inpatient-support/arterial_pair/{data['support_source_id']}/revoke", headers=super_headers, json={**scope(case), "expected_revision": 1, "reason": NOTE})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "revoked" and response.json()["data"]["eligible"] is False
    assert case["admission"].patient_id == case["seed"]["patient2"].patient_id


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "revoke"])
async def test_real_sql_audit_failure_rolls_back_both_original_change_and_audit(source_client, source_case, auth_headers, db_session, monkeypatch, action):
    case = source_case
    headers = auth_headers(case["doctor"].username)
    data = await register(source_client, case, headers) if action == "revoke" else None
    before = db_session.query(InpatientArterialPairSource).count()
    before_audits = db_session.query(AIAuditEvent).count()

    def invalid_audit(db, *args, **kwargs):
        db.add(AIAuditEvent(actor_id=args[0], action=None, target="synthetic-actual-audit-failure", detail_json="{}", create_time=datetime.datetime.now(datetime.UTC).replace(tzinfo=None)))

    monkeypatch.setattr(governance, "audit", invalid_audit)
    if action == "create":
        response = await source_client.post("/api/inpatient-support/arterial_pair", headers=headers, json=request(case, "arterial_pair"))
    else:
        response = await source_client.post(f"/api/inpatient-support/arterial_pair/{data['support_source_id']}/revoke", headers=headers, json={**scope(case), "expected_revision": 1, "reason": NOTE})
    assert response.status_code == 409, response.text
    assert db_session.query(InpatientArterialPairSource).count() == before and db_session.query(AIAuditEvent).count() == before_audits
    if data:
        row = db_session.get(InpatientArterialPairSource, data["support_source_id"])
        assert row.status == "active" and row.revision == 1 and row.revoked_at is row.revoked_by is None and row.revoke_reason == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, 1.0, "1"])
async def test_create_patient_identifier_is_actual_integer_not_boolean_float_or_text(source_client, source_case, auth_headers, value):
    case = source_case
    response = await source_client.post("/api/inpatient-support/map", headers=auth_headers(case["doctor"].username), json={**request(case, "map"), "patient_id": value})
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["hoimsystem_inpatient_map_source", "unsupported", "MAP"])
async def test_url_kind_cannot_select_physical_table_or_unregistered_domain(source_client, source_case, auth_headers, kind):
    response = await source_client.get(f"/api/inpatient-support/{kind}", headers=auth_headers(source_case["doctor"].username), params=scope(source_case))
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["1.0", "true", "1e0"])
async def test_query_patient_identifier_does_not_coerce_float_boolean_or_exponent(source_client, source_case, auth_headers, value):
    response = await source_client.get("/api/inpatient-support/map", headers=auth_headers(source_case["doctor"].username), params={**scope(source_case), "patient_id": value})
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("query_key", ["page", "page_size"])
@pytest.mark.parametrize("value", ["1.0", "true", "1e0"])
async def test_query_pagination_does_not_coerce_float_boolean_or_exponent(source_client, source_case, auth_headers, query_key, value):
    response = await source_client.get("/api/inpatient-support/map", headers=auth_headers(source_case["doctor"].username), params={**scope(source_case), query_key: value})
    assert response.status_code == 422
