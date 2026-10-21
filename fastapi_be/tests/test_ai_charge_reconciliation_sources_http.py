"""Actual main JWT/ASGI Source transport preserves all clocks and literal text."""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.ai import charge_reconciliation_sources as s
from app.ai.charge_reconciliation_models import AIChargeCaseSnapshot
from app.database import get_db
from app.main import app
from tests.test_ai_charge_reconciliation_sources import LITERAL, NOTE, cas, request
from tests.test_ai_charge_reconciliation_sources import charge_case as _charge_case

charge_case = _charge_case


@pytest.fixture
def source_app(db_session):
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: db_session
    yield app
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


@pytest.mark.asyncio
async def test_actual_main_complete_source_clock_literal_lifecycle_and_metadata_only_directory(source_app, charge_case, auth_headers):
    case, db = charge_case, charge_case["db"]
    headers = auth_headers(case["super_admin_user"].username)
    path = "/api/ai/charge-reconciliation"
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        options = await client.get(path + "/options", headers=headers, params=request(case))
        assert options.status_code == 200 and options.json()["data"]["cash_receipt"] == "not_provided"
        preview = await client.post(path + "/cases/preview", headers=headers, json=request(case))
        assert preview.status_code == 200, preview.text
        collection = preview.json()["data"]
        assert s.verify_capture(collection) and collection["captured_at"] == "2026-10-21T12:30:00.123456Z"
        assert LITERAL in preview.text
        made = await client.post(path + "/cases", headers=headers, json={"request": request(case), "expected_collection_digest": collection["collection_digest"], "note": NOTE})
        assert made.status_code == 200, made.text
        value = made.json()["data"]
        identifier = value["case_snapshot_id"]
        assert value["created_at"] == "2026-10-21T12:30:00.123456Z" and not value["eligible"]
        reviewed = await client.post(path + "/cases/" + identifier + "/review", headers=headers, json={**cas(value), "decision": "publish", "basis_note": NOTE})
        assert reviewed.status_code == 200, reviewed.text
        published = reviewed.json()["data"]
        assert published["reviewed_at"] == "2026-10-21T12:30:00.123456Z" and published["audit_only"]
        full = await client.get(path + "/cases/" + identifier, headers=headers)
        assert full.status_code == 200, full.text
        assert full.json()["data"]["eligible"] and LITERAL in full.text
        statements = []

        def observe(conn, cursor, query, parameters, context, many):
            statements.append(query)

        connection = db.connection()
        event.listen(connection, "before_cursor_execute", observe)
        try:
            listed = await client.get(path + "/cases", headers=headers, params=request(case))
        finally:
            event.remove(connection, "before_cursor_execute", observe)
        assert listed.status_code == 200 and listed.json()["data"]["items"][0]["detail_required"]
        assert not any("snapshot_json" in query or "projection_json" in query or "review_basis_note" in query for query in statements)
        assert LITERAL not in listed.text and "identity_secret" not in listed.text
        revoked = await client.post(path + "/cases/" + identifier + "/revoke", headers=headers, json={**cas(published), "basis_note": NOTE})
        assert revoked.status_code == 200, revoked.text
        normal = await client.get(path + "/cases/" + identifier, headers=headers)
        audit = await client.get(path + "/cases/" + identifier, headers=headers, params={"audit_only": True})
        assert normal.json()["data"]["snapshot"] is None
        assert audit.json()["data"]["snapshot"] == value["snapshot"] and not audit.json()["data"]["eligible"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["cashier_no_grant", "cross_patient", "non_super_audit", "surrogate_note", "unknown_field"])
async def test_actual_main_scope_privacy_role_and_utf8_fail_closed(source_app, charge_case, auth_headers, kind):
    case, db = charge_case, charge_case["db"]
    headers = auth_headers(case["cashier_user" if kind in {"cashier_no_grant", "non_super_audit"} else "super_admin_user"].username)
    path = "/api/ai/charge-reconciliation"
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        if kind == "non_super_audit":
            response = await client.get(path + "/cases", headers=headers, params={"audit_only": True})
        elif kind == "surrogate_note":
            body = {"request": request(case), "expected_collection_digest": "0" * 64, "note": "\ud800"}
            response = await client.post(path + "/cases", headers=headers, content=json.dumps(body))
        else:
            body = {**request(case)}
            if kind == "cross_patient":
                body["patient_id"] = case["patient2"].patient_id
            if kind == "unknown_field":
                body["cash_receipt_confirmed"] = True
            response = await client.post(path + "/cases/preview", headers=headers, json=body)
        assert response.status_code == (422 if kind in {"surrogate_note", "unknown_field"} else 403), response.text
        assert db.query(AIChargeCaseSnapshot).filter_by(admission_id=case["admission"].admission_id).count() == 0
        assert LITERAL not in response.text
