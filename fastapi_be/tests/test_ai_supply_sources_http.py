"""Actual JWT/ASGI sources, CAS, UTF-8 and transaction rollback; synthetic SQL only."""

# ruff: noqa: F811 -- imported pytest fixture is registered at module scope.

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.ai import supply_sources as s
from app.ai.models import AIAuditEvent
from app.ai.supply_source_models import AISupplyDailyQuantity, AISupplyUnitDefinition
from app.database import get_db
from app.routers import ai_supply_sources as api
from tests.test_ai_supply_collection import period
from tests.test_ai_supply_source_input import NOTE
from tests.test_ai_supply_sources import create_unit, source_request, supply_case, unit_request  # noqa: F401


@pytest.fixture
def source_app(db_session):
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db_session
    return app


@pytest.mark.asyncio
async def test_real_jwt_pharmacist_unit_daily_super_review_catalog_and_redaction(source_app, db_session, supply_case, auth_headers):
    case = supply_case
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        pharmacy = auth_headers(case["pharmacist"].username)
        super_headers = auth_headers(case["super"].username)
        self_identity = await client.get("/api/ai/supply-sources/options", headers=pharmacy)
        assert self_identity.status_code == 200 and self_identity.json()["data"]["professional_signer_user_id"] == case["pharmacist"].user_id
        response = await client.post("/api/ai/supply-sources/units", json=unit_request(case), headers=pharmacy)
        assert response.status_code == 200
        draft = response.json()["data"]
        assert s.verify_source_wrapper(draft) and draft["can_revoke"] and not draft["can_review"]
        review = {"expected_revision": 1, "expected_content_hash": draft["content_hash"], "decision": "publish", "basis_note": NOTE}
        reviewed = await client.post(f"/api/ai/supply-sources/units/{draft['source_record_id']}/review", json=review, headers=super_headers)
        assert reviewed.status_code == 200 and reviewed.json()["data"]["eligible"]
        unit = s.record(db_session, "unit", draft["source_record_id"])
        created = await client.post("/api/ai/supply-sources/daily", json=source_request(case, unit), headers=pharmacy)
        assert created.status_code == 200 and created.json()["data"]["payload"]["quantity"]["value"] == "0.000000"
        row = created.json()["data"]
        review["expected_content_hash"] = row["content_hash"]
        pub = await client.post(f"/api/ai/supply-sources/daily/{row['source_record_id']}/review", json=review, headers=super_headers)
        assert pub.status_code == 200 and s.verify_source_wrapper(pub.json()["data"])
        stale = await client.post(f"/api/ai/supply-sources/daily/{row['source_record_id']}/review", json=review, headers=super_headers)
        assert stale.status_code == 409
        params = {"item_kind": "pharmaceutical", "item_id": case["drug"].pharmaceutical_id}
        listing = await client.get("/api/ai/supply-sources/daily", params=params, headers=pharmacy)
        assert listing.status_code == 200 and listing.json()["data"]["detail_required"]
        metadata = listing.json()["data"]["items"][0]
        assert metadata["source_record_id"] == row["source_record_id"] and all(k not in metadata for k in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
        capture = await client.post("/api/ai/supply-sources/preview", json=period(case), headers=pharmacy)
        assert capture.status_code == 200 and capture.json()["data"]["source_records"][0]["source"]["eligible"]
        revoke = {"expected_revision": 2, "expected_content_hash": row["content_hash"], "basis_note": NOTE}
        terminal = await client.post(f"/api/ai/supply-sources/daily/{row['source_record_id']}/revoke", json=revoke, headers=pharmacy)
        assert terminal.status_code == 200 and terminal.json()["data"]["status"] == "revoked" and terminal.json()["data"]["payload"] is None
        audit = await client.get(f"/api/ai/admin/supply-sources/{row['source_record_id']}", params={"record_kind": "daily"}, headers=super_headers)
        assert audit.status_code == 200 and audit.json()["data"]["audit_only"] and audit.json()["data"]["payload"]["quantity"]["value"] == "0.000000"
        assert case["drug"].stock == 37 and case["consumable"].stock == 11
        assert db_session.query(AIAuditEvent).filter(AIAuditEvent.target == row["source_record_id"]).count() == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "director", "super"])
async def test_real_jwt_technical_role_may_record_unknown_but_never_sign_as_pharmacist(source_app, supply_case, auth_headers, role):
    case = supply_case
    request = source_request(case)
    headers = auth_headers(case[role].username)
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        unknown = await client.post("/api/ai/supply-sources/daily", json=request, headers=headers)
        assert unknown.status_code == 200 and unknown.json()["data"]["professional_status"] == "unknown"
        request["payload"]["professional_attestation"] = {"status": "confirmed", "signer_user_id": case["pharmacist"].user_id, "basis_note": NOTE}
        denied = await client.post("/api/ai/supply-sources/daily", json=request, headers=headers)
        assert denied.status_code == 403
        options = await client.get("/api/ai/supply-sources/options", headers=headers)
        assert options.status_code == 200 and options.json()["data"]["items"] == [] and not options.json()["data"]["can_confirm_professional"]
        assert options.json()["data"]["professional_signer_user_id"] is None


@pytest.mark.asyncio
async def test_actual_auth_scope_role_and_pagination_do_not_offer_unrestricted_raw_or_implicit_first_sku(source_app, supply_case, auth_headers):
    case = supply_case
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        assert (await client.get("/api/ai/supply-sources/options")).status_code == 401
        assert (await client.get("/api/ai/supply-sources/options", headers=auth_headers(case["nurse"].username))).status_code == 403
        headers = auth_headers(case["admin"].username)
        bad = await client.get("/api/ai/supply-sources/options", params={"item_id": case["drug"].pharmaceutical_id}, headers=headers)
        assert bad.status_code == 422
        good = await client.get("/api/ai/supply-sources/options", params={"item_kind": "pharmaceutical", "item_id": case["drug"].pharmaceutical_id, "page_size": 1}, headers=headers)
        value = good.json()["data"]
        assert good.status_code == 200 and value["total"] == 1 and value["items"][0]["item_id"] == case["drug"].pharmaceutical_id
        assert all(k not in value["items"][0] for k in ("price", "stock", "payload", "patient_id", "department_id"))
        assert (await client.get("/api/ai/admin/supply-sources", params={"record_kind": "unit"}, headers=headers)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("note,expected", [("字" * 1001, 422), ("a" * 1000, 200), ("😀" * 1000, 200)])
async def test_revoke_unicode_codepoints_and_utf8_rollback_boundaries(source_app, db_session, supply_case, auth_headers, note, expected):
    case = supply_case
    unit = create_unit(db_session, case)
    unit_id, digest = unit.unit_definition_id, unit.content_hash
    before = db_session.query(AIAuditEvent).count()
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        response = await client.post(
            f"/api/ai/supply-sources/units/{unit_id}/revoke", headers=auth_headers(case["super"].username), json={"expected_revision": 2, "expected_content_hash": digest, "basis_note": note}
        )
    assert response.status_code == expected
    db_session.expire_all()
    row = s.record(db_session, "unit", unit_id)
    assert row.status == ("revoked" if expected == 200 else "published") and db_session.query(AIAuditEvent).count() == before + (expected == 200)
    if expected == 200:
        assert row.revoke_reason == note and len(row.revoke_reason.encode()) <= 4000


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["response_proof", "audit_write", "postflight_identity"])
async def test_create_source_and_audit_roll_back_together_on_actual_postflush_failures(source_app, db_session, supply_case, auth_headers, monkeypatch, failure):
    case = supply_case
    before = db_session.query(AISupplyDailyQuantity).count(), db_session.query(AIAuditEvent).count()
    if failure == "response_proof":
        monkeypatch.setattr(s, "verify_source_wrapper", lambda *args, **kwargs: False)
    else:
        actual = s.audit_governance.audit

        def fail(db, actor, action, target, detail=None):
            actual(db, actor, action, target, detail)
            db.flush()
            if failure == "postflight_identity":
                from app.models import User

                db.query(User).filter_by(user_id=actor).update({"user_role": "nurse"}, synchronize_session=False)
            else:
                raise HTTPException(409, "synthetic audit failure")

        monkeypatch.setattr(s.audit_governance, "audit", fail)
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        response = await client.post("/api/ai/supply-sources/daily", json=source_request(case), headers=auth_headers(case["admin"].username))
    assert response.status_code == (403 if failure == "postflight_identity" else 409)
    assert (db_session.query(AISupplyDailyQuantity).count(), db_session.query(AIAuditEvent).count()) == before
    assert case["drug"].stock == 37 and case["consumable"].stock == 11


@pytest.mark.asyncio
async def test_review_and_audit_rollback_on_response_proof_failure(source_app, db_session, supply_case, auth_headers, monkeypatch):
    case = supply_case
    row = s.create_unit(db_session, case["pharmacist"], unit_request(case))
    db_session.commit()
    rid, digest = row.unit_definition_id, row.content_hash
    before = db_session.query(AIAuditEvent).count()
    monkeypatch.setattr(s, "verify_source_wrapper", lambda *args, **kwargs: False)
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        response = await client.post(
            f"/api/ai/supply-sources/units/{rid}/review",
            headers=auth_headers(case["super"].username),
            json={"expected_revision": 1, "expected_content_hash": digest, "decision": "publish", "basis_note": NOTE},
        )
    assert response.status_code == 409
    db_session.expire_all()
    current = db_session.query(AISupplyUnitDefinition).filter_by(unit_definition_id=rid).one()
    assert current.status == "draft" and current.revision == 1 and db_session.query(AIAuditEvent).count() == before
