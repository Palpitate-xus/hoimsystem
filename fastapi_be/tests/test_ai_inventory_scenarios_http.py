"""Actual main/JWT/SQLite source and scenario routes; no mocked authorization."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai import governance
from app.ai import inventory_contract as core
from app.ai.inventory_scenario_models import AIInventoryScenario
from app.ai.inventory_scenarios import scenario_proof
from tests.test_ai_inventory_native_source_input import NOTE
from tests.test_ai_inventory_scenarios import create_request, period
from tests.test_ai_inventory_scenarios import inventory_case as inventory_case


@pytest.mark.asyncio
async def test_actual_main_eight_routes_preserve_utc6_whole_hash_and_independent_governance(async_client, auth_headers, db_session, inventory_case):
    case = inventory_case
    ordinary = auth_headers(case["admin"].username)
    super_headers = auth_headers(case["super"].username)
    preview = await async_client.post("/api/ai/inventory-scenarios/preview", headers=ordinary, json=period(case))
    assert preview.status_code == 200, preview.text
    values = create_request(db_session, case)
    assert preview.json()["data"]["collection_digest"] == values["expected_collection_digest"]
    response = await async_client.post("/api/ai/inventory-scenarios", headers=ordinary, json=values)
    assert response.status_code == 200, response.text
    draft = response.json()["data"]
    identifier = draft["scenario_id"]
    assert draft["revision"] == 1 and draft["status"] == "draft" and draft["public_source"] is None
    assert draft["as_of"].endswith(".123456Z") and draft["created_at"].endswith(".123456Z")
    assert core.hash_content(draft["snapshot"]) == draft["content_hash"]
    denied = await async_client.get("/api/ai/admin/inventory-scenarios/" + identifier, headers=ordinary)
    assert denied.status_code == 403
    denied = await async_client.post(
        "/api/ai/inventory-scenarios/" + identifier + "/review",
        headers=ordinary,
        json={"expected_revision": 1, "expected_content_hash": draft["content_hash"], "decision": "publish", "basis_note": NOTE},
    )
    assert denied.status_code == 403
    response = await async_client.post(
        "/api/ai/inventory-scenarios/" + identifier + "/review",
        headers=super_headers,
        json={"expected_revision": 1, "expected_content_hash": draft["content_hash"], "decision": "publish", "basis_note": NOTE},
    )
    assert response.status_code == 200, response.text
    published = response.json()["data"]
    assert published["eligible"] and published["revision"] == 2 and core.hash_content(published["public_source"]) == published["projection_hash"]
    assert published["snapshot"] == draft["snapshot"] and published["content_hash"] == draft["content_hash"]
    assert published["public_source"]["governance_hash"] == published["governance_hash"]
    detail = await async_client.get("/api/ai/inventory-scenarios/" + identifier, headers=ordinary)
    assert detail.status_code == 200 and detail.json()["data"]["public_source"] == published["public_source"]
    params = {"item_kind": "pharmaceutical", "item_id": case["drug"].pharmaceutical_id}
    for url in ["/api/ai/inventory-scenarios", "/api/ai/admin/inventory-scenarios"]:
        listing = await async_client.get(url, headers=super_headers, params=params)
        assert listing.status_code == 200 and listing.json()["data"]["total"] == 1
        item = listing.json()["data"]["items"][0]
        assert item["scenario_id"] == identifier and not ({"snapshot", "public_source", "review_basis_note", "revoke_reason"} & item.keys())
    denied = await async_client.get("/api/ai/admin/inventory-scenarios", headers=ordinary)
    assert denied.status_code == 403
    stale = await async_client.post(
        "/api/ai/inventory-scenarios/" + identifier + "/review",
        headers=super_headers,
        json={"expected_revision": 1, "expected_content_hash": draft["content_hash"], "decision": "reject", "basis_note": NOTE},
    )
    assert stale.status_code == 409
    revoked = await async_client.post(
        "/api/ai/inventory-scenarios/" + identifier + "/revoke", headers=super_headers, json={"expected_revision": 2, "expected_content_hash": draft["content_hash"], "basis_note": NOTE}
    )
    assert revoked.status_code == 200 and revoked.json()["data"]["revision"] == 3
    ordinary_detail = await async_client.get("/api/ai/inventory-scenarios/" + identifier, headers=ordinary)
    assert ordinary_detail.status_code == 200 and ordinary_detail.json()["data"]["snapshot"] is None
    assert ordinary_detail.json()["data"]["review_basis_note"] is None
    audit = await async_client.get("/api/ai/admin/inventory-scenarios/" + identifier, headers=super_headers)
    assert audit.status_code == 200 and audit.json()["data"]["snapshot"] == draft["snapshot"] and audit.json()["data"]["public_source"] == published["public_source"]
    assert case["drug"].stock == case["batch"].stock == 10


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        {"item_kind": "pharmaceutical"},
        {"item_id": "1"},
        {"item_kind": "pharmaceutical", "item_id": "1.0"},
        {"item_kind": "pharmaceutical", "item_id": "true"},
        {"item_kind": "pharmaceutical", "item_id": "01"},
        {"page": "1.0"},
        {"page": "true"},
        {"page_size": "1e0"},
        {"page_size": "101"},
        {"status": "archived"},
    ],
)
async def test_actual_http_query_scalars_do_not_coerce_or_silently_ignore_scope(async_client, auth_headers, inventory_case, query):
    response = await async_client.get("/api/ai/inventory-scenarios", headers=auth_headers(inventory_case["admin"].username), params=query)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_ordinary_scope_metadata_list_never_loads_complete_private_blob(async_client, auth_headers, db_session, inventory_case):
    from tests.test_ai_inventory_scenarios import published

    case = inventory_case
    row = published(db_session, case)
    item_id = row.item_id  # Resolve expired fixture metadata before endpoint SQL capture.
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "hoimsystem_ai_inventory_scenario" in statement:
            statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        response = await async_client.get("/api/ai/inventory-scenarios", headers=auth_headers(case["admin"].username), params={"item_kind": "pharmaceutical", "item_id": item_id})
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)
    assert response.status_code == 200 and statements
    assert all("snapshot_json" not in sql and "projection_json" not in sql for sql in statements)
    assert row.snapshot_json not in response.text


@pytest.mark.asyncio
async def test_real_audit_failure_after_scene_insert_rolls_back_both_row_and_event(async_client, auth_headers, db_session, inventory_case, monkeypatch):
    from app.ai.models import AIAuditEvent

    case = inventory_case
    values = create_request(db_session, case)
    before_scenes = db_session.query(AIInventoryScenario).count()
    before_audit = db_session.query(AIAuditEvent).count()
    original = governance.audit

    def failing(db, *args, **kwargs):
        original(db, *args, **kwargs)
        db.flush()
        raise HTTPException(409, "独立合成SQL审计提交失败，场景必须整体回滚")

    monkeypatch.setattr(governance, "audit", failing)
    response = await async_client.post("/api/ai/inventory-scenarios", headers=auth_headers(case["admin"].username), json=values)
    assert response.status_code == 409, response.text
    db_session.expire_all()
    assert db_session.query(AIInventoryScenario).count() == before_scenes
    assert db_session.query(AIAuditEvent).count() == before_audit


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["bad", "00000000-0000-4000-8000-00000000006A"])
async def test_noncanonical_scenario_uuid_rejected_before_any_private_result(async_client, auth_headers, inventory_case, identifier):
    response = await async_client.get("/api/ai/inventory-scenarios/" + identifier, headers=auth_headers(inventory_case["admin"].username))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_unimplemented_and_injected_recipe_payload_is_rejected_without_scene_write(async_client, auth_headers, db_session, inventory_case):
    values = create_request(db_session, inventory_case)
    count = db_session.query(AIInventoryScenario).count()
    for key, value in [("horizon_days", 7), ("recipe", {}), ("profile_id", "00000000-0000-4000-8000-000000000001")]:
        modified = copy.deepcopy(values)
        modified["request"][key] = value
        response = await async_client.post("/api/ai/inventory-scenarios", headers=auth_headers(inventory_case["admin"].username), json=modified)
        assert response.status_code == 422, response.text
    assert db_session.query(AIInventoryScenario).count() == count


@pytest.mark.asyncio
async def test_revoke_1001_rejects_before_sql_and_full_1000_unicode_codepoints_survive_actual_main(async_client, auth_headers, db_session, inventory_case):
    from tests.test_ai_inventory_scenarios import published

    case = inventory_case
    row = published(db_session, case)
    base = {"expected_revision": 2, "expected_content_hash": row.content_hash}
    headers = auth_headers(case["super"].username)
    rejected = await async_client.post("/api/ai/inventory-scenarios/" + row.scenario_id + "/revoke", headers=headers, json={**base, "basis_note": "撤" * 1001})
    assert rejected.status_code == 422
    db_session.refresh(row)
    assert row.status == "published" and row.revision == 2
    note = "🧪" * 1000
    accepted = await async_client.post("/api/ai/inventory-scenarios/" + row.scenario_id + "/revoke", headers=headers, json={**base, "basis_note": note})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["revoke_reason"] == note
    db_session.refresh(row)
    assert row.revoke_reason == note and row.revision == 3
    assert scenario_proof(row)
