"""Real main/JWT/ASGI with isolated SQL originals, never hospital data."""

# ruff: noqa: F811 -- imported fixture names are explicit pytest registration.

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.ai import coding_evidence_sources as sources
from app.ai.coding_evidence_models import AICodingCaseSnapshot, AICodingRulePackage
from app.ai.models import AIAuditEvent
from app.database import get_db
from app.main import app
from tests.test_ai_coding_evidence_sources import NOTE, case, coding_case, request  # noqa:F401


@pytest.fixture
def source_app(db_session):
    old = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: db_session
    yield app
    if old is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = old


async def create_case(client, headers, c):
    preview = await client.post("/api/ai/coding-evidence/cases/preview", headers=headers, json=request(c))
    assert preview.status_code == 200, preview.text
    value = preview.json()["data"]
    assert sources.verify_capture(value)
    created = await client.post("/api/ai/coding-evidence/cases", headers=headers, json={"request": request(c), "expected_collection_digest": value["collection_digest"], "note": NOTE})
    assert created.status_code == 200, created.text
    return created.json()["data"]


@pytest.mark.asyncio
async def test_actual_main_utc6_full_proof_governance_and_metadata_directory(source_app, db_session, case, auth_headers):
    c = case
    doctor, su = auth_headers(c["doctor_user"].username), auth_headers(c["super_admin_user"].username)
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        options = await client.get("/api/ai/coding-evidence/options", headers=doctor)
        assert options.status_code == 200 and options.json()["data"]["professional_qualification"] == "not_provided"
        homes = await client.get("/api/ai/coding-evidence/homes", headers=doctor, params={"patient_id": c["patient"].patient_id, "admission_id": c["admission"].admission_id})
        assert homes.status_code == 200 and homes.json()["data"]["items"][0]["home_id"] == c["home"].home_id
        assert "admission_diagnosis" not in homes.text
        draft = await create_case(client, doctor, c)
        rid = draft["case_snapshot_id"]
        path = "/api/ai/coding-evidence/cases/" + rid
        assert draft["created_at"] == "2026-10-21T12:30:00.123456Z"
        proof = {k: draft[k] for k in (*sources.IDENTITY, *sources.GOVERNANCE, "content_hash", "source_id", "governance_hash", "snapshot")}
        assert sources.verify_original(proof) and draft["public_source"] is None
        review = await client.post(path + "/review", headers=su, json={"expected_revision": 1, "expected_content_hash": draft["content_hash"], "decision": "publish", "basis_note": NOTE})
        assert review.status_code == 200, review.text
        value = review.json()["data"]
        assert value["reviewed_at"] == "2026-10-21T12:30:00.123456Z" and value["eligible"]
        detail = await client.get(path, headers=doctor)
        assert detail.status_code == 200 and detail.json()["data"]["public_source"] == value["public_source"]
        statements = []
        conn = db_session.connection()

        def record_sql(conn, cursor, statement, params, context, many):
            statements.append(statement)

        event.listen(conn, "before_cursor_execute", record_sql)
        try:
            listing = await client.get("/api/ai/coding-evidence/cases", headers=doctor, params={"patient_id": c["patient"].patient_id, "admission_id": c["admission"].admission_id})
        finally:
            event.remove(conn, "before_cursor_execute", record_sql)
        assert listing.status_code == 200 and listing.json()["data"]["detail_required"]
        listed = next(item for item in listing.json()["data"]["items"] if item["case_snapshot_id"] == rid)
        assert listed["created_at"] == draft["created_at"]
        assert not {"snapshot", "public_source", "review_basis_note", "revoke_reason", "eligible"} & listed.keys()
        assert not any("snapshot_json" in sql or "projection_json" in sql for sql in statements)
        revoked = await client.post(path + "/revoke", headers=doctor, json={"expected_revision": 2, "expected_content_hash": draft["content_hash"], "basis_note": NOTE})
        assert revoked.status_code == 200, revoked.text
        v = revoked.json()["data"]
        assert all(v[k] is None for k in ("snapshot", "public_source", "review_basis_note", "revoke_reason")) and v["revoked_at"].endswith(".123456Z")
        audit = await client.get(path, headers=su, params={"audit_only": True})
        assert audit.status_code == 200 and audit.json()["data"]["public_source"] == value["public_source"]


@pytest.mark.asyncio
async def test_actual_main_local_rule_package_super_only_and_original_no_financial_directory(source_app, db_session, case, auth_headers):
    c = case
    doctor, su = auth_headers(c["doctor_user"].username), auth_headers(c["super_admin_user"].username)
    body = {"package_kind": "local_prefix_snapshot", "rule_ids": [c["rule"].rule_id], "basis_note": NOTE}
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        assert (await client.get("/api/ai/coding-evidence/rules", headers=doctor)).status_code == 403
        assert (await client.post("/api/ai/coding-evidence/packages", headers=doctor, json=body)).status_code == 403
        directory = await client.get("/api/ai/coding-evidence/rules", headers=su, params={"page": 1, "page_size": 1})
        assert directory.status_code == 200 and directory.json()["data"]["page_size"] == 1
        assert "expected_amount" not in directory.text and directory.json()["data"]["official_rules_seeded"] is False
        created = await client.post("/api/ai/coding-evidence/packages", headers=su, json=body)
        assert created.status_code == 200, created.text
        draft = created.json()["data"]
        path = "/api/ai/coding-evidence/packages/" + draft["package_id"]
        published = await client.post(path + "/review", headers=su, json={"expected_revision": 1, "expected_content_hash": draft["content_hash"], "decision": "publish", "basis_note": NOTE})
        assert published.status_code == 200 and published.json()["data"]["reviewed_at"].endswith(".123456Z")
        ordinary = await client.get(path, headers=doctor)
        assert ordinary.status_code == 200 and ordinary.json()["data"]["eligible"]
        proof = sources.original(db_session.query(AICodingRulePackage).filter_by(package_id=draft["package_id"]).one(), "package")
        assert sources.verify_original(proof, "package")
        revoked = await client.post(path + "/revoke", headers=su, json={"expected_revision": 2, "expected_content_hash": draft["content_hash"], "basis_note": NOTE})
        assert revoked.status_code == 200
        hidden = await client.get(path, headers=doctor)
        assert hidden.status_code == 200 and all(hidden.json()["data"][k] is None for k in ("snapshot", "review_basis_note", "revoke_reason"))


@pytest.mark.asyncio
async def test_actual_main_authentication_current_role_and_case_scope(source_app, db_session, case, auth_headers):
    c = case
    h = auth_headers(c["doctor_user"].username)
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        assert (await client.get("/api/ai/coding-evidence/options")).status_code == 401
        assert (await client.get("/api/ai/coding-evidence/cases", headers=h)).status_code == 422
        wrong = request(c)
        wrong["patient_id"] = c["patient2"].patient_id
        assert (await client.post("/api/ai/coding-evidence/cases/preview", headers=h, json=wrong)).status_code == 403
        assert (await client.get("/api/ai/coding-evidence/cases", headers=h, params={"audit_only": True})).status_code == 403
        c["doctor_user"].user_role = "patient"
        db_session.commit()
        assert (await client.get("/api/ai/coding-evidence/options", headers=h)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["audit", "authority_postflight"])
async def test_mutation_postflush_failure_rolls_back_original_and_audit(source_app, db_session, case, auth_headers, monkeypatch, failure):
    c = case
    before = (db_session.query(AICodingCaseSnapshot).count(), db_session.query(AIAuditEvent).count())
    actual = sources.audit

    def fail(db, actor, action, target, detail=None):
        actual(db, actor, action, target, detail)
        db.flush()
        if failure == "audit":
            raise HTTPException(409, "synthetic postflush audit failure")
        from app.models import User

        db.query(User).filter_by(user_id=actor).update({"user_role": "patient"}, synchronize_session=False)

    monkeypatch.setattr(sources, "audit", fail)
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        h = auth_headers(c["doctor_user"].username)
        preview = await client.post("/api/ai/coding-evidence/cases/preview", headers=h, json=request(c))
        assert preview.status_code == 200
        response = await client.post("/api/ai/coding-evidence/cases", headers=h, json={"request": request(c), "expected_collection_digest": preview.json()["data"]["collection_digest"], "note": NOTE})
        assert response.status_code == (409 if failure == "audit" else 403)
    assert (db_session.query(AICodingCaseSnapshot).count(), db_session.query(AIAuditEvent).count()) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("note,expected", [("x" * 1001, 422), ("x" * 1000, 200), ("😀" * 1000, 200)])
async def test_actual_revoke_unicode_codepoints_and_utf8_limit(source_app, db_session, case, auth_headers, note, expected):
    c = case
    async with AsyncClient(transport=ASGITransport(app=source_app), base_url="http://synthetic") as client:
        h = auth_headers(c["doctor_user"].username)
        draft = await create_case(client, h, c)
        path = "/api/ai/coding-evidence/cases/" + draft["case_snapshot_id"]
        response = await client.post(path + "/revoke", headers=h, json={"expected_revision": 1, "expected_content_hash": draft["content_hash"], "basis_note": note})
        assert response.status_code == expected, response.text
        row = db_session.query(AICodingCaseSnapshot).filter_by(case_snapshot_id=draft["case_snapshot_id"]).one()
        assert row.revoke_reason == (note if expected == 200 else "")
