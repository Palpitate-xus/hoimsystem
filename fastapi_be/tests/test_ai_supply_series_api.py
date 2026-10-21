"""Actual JWT/ASGI/SQlAlchemy routes; isolated app, not a hospital backend."""

import copy

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.ai import governance
from app.ai.models import AIAuditEvent
from app.ai.supply_series_models import AISupplySeries
from app.database import get_db
from app.routers.ai_supply_series import router
from tests.test_ai_supply_series import NOTE, request_for
from tests.test_ai_supply_series import series_case as series_case
from tests.test_ai_supply_sources import supply_case as supply_case

BASE = "/api/ai/supply-series"


@pytest_asyncio.fixture
async def supply_client(db_session):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def session():
        yield db_session

    app.dependency_overrides[get_db] = session
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://isolated-inventory") as client:
        yield client


def headers(auth_headers, case, role="admin"):
    return auth_headers(case[role].username)


async def create_http(client, auth_headers, db, case):
    body = request_for(db, case)
    r = await client.post(BASE, headers=headers(auth_headers, case), json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"], body


@pytest.mark.asyncio
async def test_actual_eight_routes_preview_create_publish_metadata_list_revoke_and_frozen_audit(supply_client, series_case, auth_headers, db_session):
    case = series_case
    h = headers(auth_headers, case)
    paths = [(r.path, m) for r in router.routes for m in r.methods]
    assert len(paths) == len(set(paths)) == 8
    body = request_for(db_session, case)
    preview = await supply_client.post(BASE + "/preview", headers=h, json={k: body["request"][k] for k in ("item_kind", "item_id", "scope", "timezone", "date_from", "date_to", "as_of")})
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["expected_capture_digest"] == body["expected_capture_digest"]
    row, _ = await create_http(supply_client, auth_headers, db_session, case)
    assert row["snapshot"]["request"] == body["request"] and row["status"] == "draft" and row["can_revoke"] and not row["eligible"]
    url = BASE + "/" + row["series_id"]
    review = {"expected_revision": 1, "expected_content_hash": row["content_hash"], "basis_note": NOTE, "decision": "publish"}
    forbidden = await supply_client.post(url + "/review", headers=h, json=review)
    assert forbidden.status_code == 403
    response = await supply_client.post(url + "/review", headers=headers(auth_headers, case, "super"), json=review)
    assert response.status_code == 200, response.text
    published = response.json()["data"]
    assert published["eligible"] and published["public_source"]["profile_governance_hash"] == published["governance_hash"]
    current = await supply_client.get(url, headers=headers(auth_headers, case, "pharmacist"))
    assert current.status_code == 200 and not current.json()["data"]["audit_only"]
    sql = []

    def capture(conn, cursor, statement, parameters, context, many):
        sql.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture)
    try:
        listed = await supply_client.get(BASE, headers=h, params={"item_kind": "pharmaceutical", "item_id": case["drug"].pharmaceutical_id, "page": 1, "page_size": 20})
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture)
    assert listed.status_code == 200, listed.text
    item = listed.json()["data"]["items"][0]
    assert item["series_id"] == row["series_id"] and not any(k in item for k in ("snapshot", "public_source", "local_resolution", "review_basis_note", "revoke_reason"))
    assert not any("snapshot_json" in query or "projection_json" in query for query in sql)
    req = {"expected_revision": 2, "expected_content_hash": row["content_hash"], "basis_note": NOTE}
    nonauthor = await supply_client.post(url + "/revoke", headers=headers(auth_headers, case, "pharmacist"), json=req)
    assert nonauthor.status_code == 403
    revoked = await supply_client.post(url + "/revoke", headers=h, json=req)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["data"]["snapshot"] is None and revoked.json()["data"]["public_source"] is None
    audit = await supply_client.get("/api/ai/admin/supply-series/" + row["series_id"], headers=headers(auth_headers, case, "super"))
    assert audit.status_code == 200 and audit.json()["data"]["public_source"] == published["public_source"] and audit.json()["data"]["snapshot"] == row["snapshot"]
    assert (await supply_client.post(url + "/revoke", headers=h, json=req)).status_code == 409
    assert case["drug"].stock == 37 and case["consumable"].stock == 11


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [{"item_id": "1.0"}, {"item_id": "true"}, {"page": "1e0"}, {"page": "01"}, {"page_size": "101"}, {"page_size": "false"}, {"item_id": "1"}, {"item_kind": "pharmaceutical"}, {"status": "unknown"}],
)
async def test_strict_query_scalars_and_actual_paired_scope(supply_client, series_case, auth_headers, query):
    r = await supply_client.get(BASE, headers=headers(auth_headers, series_case), params=query)
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["nurse"])
async def test_no_inventory_source_scope_is_not_granted_by_series_endpoint(supply_client, series_case, auth_headers, db_session, role):
    h = headers(auth_headers, series_case, role)
    body = request_for(db_session, series_case)
    assert (await supply_client.get(BASE, headers=h)).status_code == 403
    assert (await supply_client.post(BASE, headers=h, json=body)).status_code == 403
    assert (
        await supply_client.post(BASE + "/preview", headers=h, json={k: body["request"][k] for k in ("item_kind", "item_id", "scope", "timezone", "date_from", "date_to", "as_of")})
    ).status_code == 403


@pytest.mark.asyncio
async def test_schema_rejection_is_before_actual_sql_and_raw_unit_is_not_a_guess(supply_client, series_case, auth_headers, db_session):
    body = request_for(db_session, series_case)
    before = db_session.query(AISupplySeries).count()
    changes = [
        lambda x: x["request"].pop("parameters"),
        lambda x: x["request"]["parameters"]["alpha_size"].update(numerator=1),
        lambda x: x["request"].update(item_id=True),
        lambda x: x["request"].update(unit_definition_id=None),
        lambda x: x["request"].update(department_id=1),
    ]
    for change in changes:
        bad = copy.deepcopy(body)
        change(bad)
        r = await supply_client.post(BASE, headers=headers(auth_headers, series_case), json=bad)
        assert r.status_code == 422, r.text
    assert db_session.query(AISupplySeries).count() == before


@pytest.mark.asyncio
async def test_actual_sql_audit_failure_returns_no_partial_series_or_audit(supply_client, series_case, auth_headers, db_session, monkeypatch):
    body = request_for(db_session, series_case)
    before = (db_session.query(AISupplySeries).count(), db_session.query(AIAuditEvent).count())

    def fail(*args, **kwargs):
        raise RuntimeError("isolated audit insert failed")

    monkeypatch.setattr(governance, "audit", fail)
    result = await supply_client.post(BASE, headers=headers(auth_headers, series_case), json=body)
    assert result.status_code == 500
    assert (db_session.query(AISupplySeries).count(), db_session.query(AIAuditEvent).count()) == before


@pytest.mark.asyncio
async def test_canonical_uuid_and_ordinary_admin_audit_restriction(supply_client, series_case, auth_headers, db_session):
    row, _ = await create_http(supply_client, auth_headers, db_session, series_case)
    assert (await supply_client.get("/api/ai/admin/supply-series/" + row["series_id"], headers=headers(auth_headers, series_case))).status_code == 403
    for value in ("not-a-uuid", row["series_id"].upper(), "00000000-0000-0000-0000-000000000000"):
        r = await supply_client.get(BASE + "/" + value, headers=headers(auth_headers, series_case))
        assert r.status_code == (404 if value.startswith("00000000") else 422), r.text
