"""Actual mounted JWT/HTTP staffing source management and atomic audit rollback."""

import json

import pytest

from app.ai import governance
from app.ai.models import AIAuditEvent
from app.ai.roster_models import AIRosterSource
from tests.test_ai_roster_facts import NOTE, create, publish, request
from tests.test_ai_roster_facts import roster_case as roster_case


async def register(client, case, auth_headers, kind="qualification", actor=None):
    response = await client.post("/api/ai/roster-sources/" + kind, headers=auth_headers((actor or case["director"]).username), json=request(case, kind))
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["qualification", "duty_interval", "availability", "work_rule_policy"])
async def test_real_mounted_four_kinds_draft_publish_list_and_cas_revoke(async_client, roster_case, auth_headers, db_session, kind):
    case = roster_case
    data = await register(async_client, case, auth_headers, kind)
    assert data["status"] == "draft" and data["payload"] is not None and data["eligible"] is False
    assert data["can_record"] is data["can_revoke"] is True and data["can_review"] is False
    url = f"/api/ai/roster-sources/{kind}/{data['source_record_id']}"
    headers = auth_headers(case["super"].username)
    review = {"expected_revision": 1, "expected_content_hash": data["content_hash"], "decision": "publish", "review_basis_note": NOTE}
    response = await async_client.post(url + "/review", headers=headers, json=review)
    assert response.status_code == 200, response.text
    published = response.json()["data"]
    assert published["eligible"] is True and published["revision"] == 2 and published["recorded_at"].endswith(".123456Z")
    assert published["payload"] == data["payload"] and published["parent_binding"] == data["parent_binding"] and published["content_hash"] == data["content_hash"]
    ordinary = auth_headers(case["director"].username)
    read = await async_client.get(url, headers=ordinary)
    assert read.status_code == 200 and read.json()["data"]["payload"] == data["payload"]
    listing = await async_client.get("/api/ai/roster-sources/" + kind, headers=ordinary, params={"department_id": case["department"].department_id})
    assert listing.status_code == 200, listing.text
    item = next(item for item in listing.json()["data"]["items"] if item["source_record_id"] == data["source_record_id"])
    assert "payload" not in item and "parent_binding" not in item and "review_basis_note" not in item
    revoked = await async_client.post(url + "/revoke", headers=ordinary, json={"expected_revision": 2, "reason": "本人原资料主动停止新计划使用"})
    assert revoked.status_code == 200 and revoked.json()["data"]["revision"] == 3
    assert revoked.json()["data"]["payload"] is None
    duplicate = await async_client.post(url + "/revoke", headers=ordinary, json={"expected_revision": 2, "reason": "相同版本不能重放"})
    assert duplicate.status_code == 409
    frozen = await async_client.get("/api/ai/admin/roster-sources/" + data["source_record_id"], headers=headers)
    assert frozen.status_code == 200 and frozen.json()["data"]["payload"] == data["payload"]
    assert db_session.query(AIAuditEvent).filter_by(action="roster_source.revoke", target=data["source_record_id"]).count() == 1


@pytest.mark.asyncio
async def test_options_actual_scope_all_doctors_and_no_provider_dependency(async_client, roster_case, auth_headers):
    case = roster_case
    headers = auth_headers(case["director"].username)
    response = await async_client.get("/api/ai/roster-sources/options", headers=headers)
    assert response.status_code == 200
    assert {row["department_id"] for row in response.json()["data"]["departments"]} == {case["department"].department_id}
    response = await async_client.get("/api/ai/roster-sources/options", headers=headers, params={"department_id": case["department"].department_id})
    assert response.status_code == 200 and response.json()["data"]["provider_required"] is False
    assert case["unscheduled"].doctor_id in {row["doctor_id"] for row in response.json()["data"]["doctors"]}
    denied = await async_client.get("/api/ai/roster-sources/options", headers=headers, params={"department_id": case["foreign"].department_id})
    assert denied.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["department_id", "doctor_id", "page", "page_size"])
@pytest.mark.parametrize("bad", ["1.0", "true", "1e0"])
async def test_real_query_lexemes_cannot_bypass_strict_ids_or_pagination(async_client, roster_case, auth_headers, key, bad):
    case = roster_case
    response = await async_client.get("/api/ai/roster-sources/qualification", headers=auth_headers(case["director"].username), params={"department_id": case["department"].department_id, key: bad})
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [True, 1.0, "1"])
async def test_real_body_identity_is_strict_not_coerced(async_client, roster_case, auth_headers, bad):
    case = roster_case
    values = request(case)
    values["department_id"] = bad
    response = await async_client.post("/api/ai/roster-sources/qualification", headers=auth_headers(case["director"].username), json=values)
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/ai/admin/roster-sources", "/ai/admin/roster-sources/{id}", "/ai/roster-sources/qualification/{id}/review"])
async def test_only_current_super_reviews_or_uses_global_audit(async_client, roster_case, auth_headers, db_session, path):
    case = roster_case
    data = await register(async_client, case, auth_headers)
    url = "/api" + path.format(id=data["source_record_id"])
    headers = auth_headers(case["admin"].username)
    if url.endswith("/review"):
        response = await async_client.post(url, headers=headers, json={"expected_revision": 1, "expected_content_hash": data["content_hash"], "decision": "publish", "review_basis_note": NOTE})
    else:
        response = await async_client.get(url, headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_not_original_author_cannot_revoke_but_super_can(async_client, roster_case, auth_headers):
    case = roster_case
    data = await register(async_client, case, auth_headers)
    url = f"/api/ai/roster-sources/qualification/{data['source_record_id']}/revoke"
    response = await async_client.post(url, headers=auth_headers(case["admin"].username), json={"expected_revision": 1, "reason": "其他管理员不能替原作者撤销"})
    assert response.status_code == 403
    response = await async_client.post(url, headers=auth_headers(case["super"].username), json={"expected_revision": 1, "reason": "超管正式停止原草稿使用"})
    assert response.status_code == 200 and response.json()["data"]["revision"] == 2


@pytest.mark.asyncio
async def test_http_transferred_subject_stale_redaction_frozen_audit_and_publish_block(async_client, roster_case, auth_headers, db_session):
    case = roster_case
    data = await register(async_client, case, auth_headers)
    case["doctor"].department_id = case["foreign"].department_id
    db_session.commit()
    url = f"/api/ai/roster-sources/qualification/{data['source_record_id']}"
    ordinary = await async_client.get(url, headers=auth_headers(case["director"].username))
    assert ordinary.status_code == 200 and ordinary.json()["data"]["payload"] is None and ordinary.json()["data"]["parent_binding"] is None
    frozen = await async_client.get("/api/ai/admin/roster-sources/" + data["source_record_id"], headers=auth_headers(case["super"].username))
    assert frozen.status_code == 200 and frozen.json()["data"]["payload"] == data["payload"] and frozen.json()["data"]["can_revoke"] is True
    rejected = await async_client.post(
        url + "/review", headers=auth_headers(case["super"].username), json={"expected_revision": 1, "expected_content_hash": data["content_hash"], "decision": "publish", "review_basis_note": NOTE}
    )
    assert rejected.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "publish", "reject", "revoke"])
async def test_actual_failed_sql_audit_atomically_rolls_back_create_and_each_governance_transition(async_client, roster_case, auth_headers, db_session, monkeypatch, action):
    case = roster_case
    row = create(db_session, case) if action != "create" else None
    before_sources = db_session.query(AIRosterSource).count()
    before_audits = db_session.query(AIAuditEvent).count()
    before = (row.status, row.revision, row.payload_json, row.content_hash) if row is not None else None

    def invalid_sql_audit(db, actor_id, *args, **kwargs):
        db.add(AIAuditEvent(actor_id=actor_id, action=None, target="synthetic-roster-invalid-audit", detail_json="{}"))

    monkeypatch.setattr(governance, "audit", invalid_sql_audit)
    if action == "create":
        url, body, actor = "/api/ai/roster-sources/qualification", request(case), case["director"]
    elif action in {"publish", "reject"}:
        url = f"/api/ai/roster-sources/qualification/{row.source_record_id}/review"
        body, actor = {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": action, "review_basis_note": NOTE}, case["super"]
    else:
        url = f"/api/ai/roster-sources/qualification/{row.source_record_id}/revoke"
        body, actor = {"expected_revision": 1, "reason": "实际失败SQL审计必须原子撤销"}, case["director"]
    response = await async_client.post(url, headers=auth_headers(actor.username), json=body)
    assert response.status_code == 409, response.text
    assert db_session.query(AIRosterSource).count() == before_sources and db_session.query(AIAuditEvent).count() == before_audits
    if row is not None:
        db_session.refresh(row)
        assert (row.status, row.revision, row.payload_json, row.content_hash) == before
        assert row.reviewed_by is row.reviewed_at is row.revoked_by is row.revoked_at is None


@pytest.mark.asyncio
async def test_complete_bad_hash_blocks_super_detail_review_revoke_and_redacted_list(async_client, roster_case, auth_headers, db_session):
    case = roster_case
    row = create(db_session, case)
    row.content_hash = "0" * 64
    db_session.commit()
    headers = auth_headers(case["super"].username)
    audit = await async_client.get("/api/ai/admin/roster-sources/" + row.source_record_id, headers=headers)
    assert audit.status_code == 409
    revoke = await async_client.post(f"/api/ai/roster-sources/qualification/{row.source_record_id}/revoke", headers=headers, json={"expected_revision": 1, "reason": "损坏原件不能当完整冻结件"})
    assert revoke.status_code == 409
    assert db_session.get(AIRosterSource, row.source_record_id).status == "draft"


@pytest.mark.asyncio
async def test_published_source_survives_original_author_role_change_but_current_requester_scope_is_fresh(async_client, roster_case, auth_headers, db_session):
    case = roster_case
    row = publish(db_session, case, create(db_session, case))
    case["director"].user_role = "doctor"
    db_session.commit()
    url = f"/api/ai/roster-sources/qualification/{row.source_record_id}"
    old_actor = await async_client.get(url, headers=auth_headers(case["director"].username))
    assert old_actor.status_code == 403
    admin = await async_client.get(url, headers=auth_headers(case["admin"].username))
    assert admin.status_code == 200 and admin.json()["data"]["eligible"] is True
    assert json.loads(row.payload_json)["qualification_status"] == "verified"
