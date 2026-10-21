"""Actual main/JWT/ASGI wire proofs and transactional governance; synthetic SQL."""

# ruff: noqa: F811 -- explicit fixture exports are pytest registration.

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.ai import inventory_native_collection as collection
from app.ai import inventory_native_sources as sources
from app.ai.inventory_native_source_models import AIInventoryNativeSource
from app.ai.models import AIAuditEvent
from app.database import get_db
from app.main import app
from app.models import User
from tests.test_ai_inventory_native_collection import period
from tests.test_ai_inventory_native_source_input import NOTE
from tests.test_ai_inventory_native_sources import inventory_case, publish, source_request  # noqa: F401
from tests.test_ai_supply_sources import supply_case  # noqa: F401


@pytest.fixture
def source_app(db_session):
    original = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: db_session
    yield app
    if original is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = original


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["inventory_observation", "future_quantity_scenario", "purchase_candidate_plan"])
async def test_actual_main_microsecond_fullhash_create_review_list_revoke_and_super_frozen(source_app, db_session, inventory_case, auth_headers, kind):
    case = inventory_case
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        h = auth_headers(case["pharmacist"].username)
        su = auth_headers(case["super"].username)
        options = await client.get("/api/ai/inventory-native-sources/options", params={"item_kind": "pharmaceutical", "item_id": case["drug"].pharmaceutical_id}, headers=h)
        assert options.status_code == 200 and options.json()["data"]["professional_signer_user_id"] == case["pharmacist"].user_id
        created = await client.post("/api/ai/inventory-native-sources/" + kind, headers=h, json=source_request(case, kind, confirmed=True))
        assert created.status_code == 200, created.text
        draft = created.json()["data"]
        rid = draft["source_record_id"]
        path = "/api/ai/inventory-native-sources/" + kind + "/" + rid
        assert sources.verify_source_wrapper(draft) and draft["recorded_at"] == "2026-10-21T12:00:00.123456Z"
        if kind == "inventory_observation":
            assert draft["payload"]["observed_at"] == "2026-10-21T01:00:00.123456Z" and draft["parent_binding"]["legacy_snapshot"]["captured_at"].endswith(".123456Z")
        reviewed = await client.post(path + "/review", headers=su, json={"expected_revision": 1, "expected_content_hash": draft["content_hash"], "decision": "publish", "basis_note": NOTE})
        assert reviewed.status_code == 200 and reviewed.json()["data"]["reviewed_at"] == "2026-10-21T12:00:00.123456Z" and sources.verify_source_wrapper(reviewed.json()["data"])
        detail = await client.get(path, headers=h)
        assert detail.status_code == 200 and sources.verify_source_wrapper(detail.json()["data"]) and detail.json()["data"]["eligible"]
        seen = []
        conn = db_session.connection()

        def sql(c, cur, statement, p, ctx, many):
            seen.append(statement)

        event.listen(conn, "before_cursor_execute", sql)
        try:
            directory = await client.get("/api/ai/inventory-native-sources/" + kind, params={"item_kind": "pharmaceutical", "item_id": case["drug"].pharmaceutical_id}, headers=h)
            assert directory.status_code == 200, directory.text
        finally:
            try:
                event.remove(conn, "before_cursor_execute", sql)
            except Exception:
                pass
        value = directory.json()["data"]
        metadata = value["items"][0]
        assert value["total"] == 1 and value["detail_required"] and metadata["recorded_at"] == draft["recorded_at"]
        assert all(k not in metadata for k in ("payload", "parent_binding", "review_basis_note", "revoke_reason", "eligible"))
        assert not any("payload_json" in q or "parent_binding_json" in q for q in seen)
        capture = await client.post("/api/ai/inventory-native-sources/preview", headers=h, json=period(case))
        assert capture.status_code == 200 and collection.verify_capture(capture.json()["data"])
        revoked = await client.post(path + "/revoke", headers=h, json={"expected_revision": 2, "expected_content_hash": draft["content_hash"], "basis_note": "😀" * 1000})
        assert revoked.status_code == 200 and revoked.json()["data"]["payload"] is None and revoked.json()["data"]["revoked_at"].endswith(".123456Z")
        audit = await client.get("/api/ai/admin/inventory-native-sources/" + rid, headers=su)
        assert audit.status_code == 200 and sources.verify_source_wrapper(audit.json()["data"]) and audit.json()["data"]["revoke_reason"] == "😀" * 1000
        assert case["drug"].stock == 37


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "director", "super"])
async def test_actual_technical_role_never_becomes_professional_signer(source_app, inventory_case, auth_headers, role):
    case = inventory_case
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        h = auth_headers(case[role].username)
        resp = await client.post("/api/ai/inventory-native-sources/inventory_observation", headers=h, json=source_request(case, with_unit=False))
        assert resp.status_code == 200 and resp.json()["data"]["professional_status"] == "unknown"
        denied = await client.post("/api/ai/inventory-native-sources/inventory_observation", headers=h, json=source_request(case, confirmed=True))
        assert denied.status_code == 403
        opts = await client.get("/api/ai/inventory-native-sources/options", headers=h)
        assert opts.status_code == 200 and opts.json()["data"]["professional_signer_user_id"] is None and not opts.json()["data"]["can_confirm_professional"]


@pytest.mark.asyncio
async def test_authentication_current_scope_kind_and_explicit_sku_no_patient_or_auto_selection(source_app, inventory_case, auth_headers):
    case = inventory_case
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        assert (await client.get("/api/ai/inventory-native-sources/options")).status_code == 401
        assert (await client.get("/api/ai/inventory-native-sources/options", headers=auth_headers(case["nurse"].username))).status_code == 403
        h = auth_headers(case["admin"].username)
        options = await client.get("/api/ai/inventory-native-sources/options", headers=h)
        assert options.status_code == 200 and options.json()["data"]["items"] == []
        assert (await client.get("/api/ai/inventory-native-sources/options", params={"item_id": 1}, headers=h)).status_code == 422
        bad = await client.post("/api/ai/inventory-native-sources/purchase_candidate_plan", headers=h, json=source_request(case))
        assert bad.status_code == 422
        raw = await client.post(
            "/api/ai/inventory-native-sources/legacy-capture", headers=h, json={"item_kind": "pharmaceutical", "item_id": case["drug"].pharmaceutical_id, "scope": "hospital_inventory"}
        )
        assert raw.status_code == 200 and collection.verify_legacy_capture(raw.json()["data"]) and raw.json()["data"]["captured_at"].endswith(".123456Z")
        assert (await client.get("/api/ai/admin/inventory-native-sources", headers=h)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["response", "audit", "postflight"])
async def test_postflush_failures_rollback_source_audit_and_preserve_stock(source_app, db_session, inventory_case, auth_headers, monkeypatch, failure):
    case = inventory_case
    before = (db_session.query(AIInventoryNativeSource).count(), db_session.query(AIAuditEvent).count())
    if failure == "response":
        monkeypatch.setattr(sources, "verify_source_wrapper", lambda *a, **kw: False)
    else:
        actual = sources.audit.audit

        def fail(db, actor, action, target, detail=None):
            actual(db, actor, action, target, detail)
            db.flush()
            if failure == "postflight":
                db.query(User).filter_by(user_id=actor).update({"user_role": "patient"}, synchronize_session=False)
            else:
                raise HTTPException(409, "synthetic audit failure")

        monkeypatch.setattr(sources.audit, "audit", fail)
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        resp = await client.post("/api/ai/inventory-native-sources/inventory_observation", headers=auth_headers(case["admin"].username), json=source_request(case))
    assert resp.status_code == (403 if failure == "postflight" else 409)
    assert (db_session.query(AIInventoryNativeSource).count(), db_session.query(AIAuditEvent).count()) == before and case["drug"].stock == 37


@pytest.mark.asyncio
@pytest.mark.parametrize("note,expected", [("a" * 1001, 422), ("a" * 1000, 200), ("😀" * 1000, 200)])
async def test_actual_revoke_codepoints_and_utf8_boundaries(source_app, db_session, inventory_case, auth_headers, note, expected):
    case = inventory_case
    row = sources.create_source(db_session, case["admin"], source_request(case))
    db_session.commit()
    publish(db_session, case, row)
    rid = row.source_record_id
    digest = row.content_hash
    before = db_session.query(AIAuditEvent).count()
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        resp = await client.post(
            "/api/ai/inventory-native-sources/inventory_observation/" + rid + "/revoke",
            headers=auth_headers(case["admin"].username),
            json={"expected_revision": 2, "expected_content_hash": digest, "basis_note": note},
        )
    assert resp.status_code == expected
    row = sources.record(db_session, rid, locking=True)
    assert row.status == ("revoked" if expected == 200 else "published") and db_session.query(AIAuditEvent).count() == before + (expected == 200)
    if expected == 200:
        assert row.revoke_reason == note
