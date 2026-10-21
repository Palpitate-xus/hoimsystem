"""Actual new router/JWT/SQLite ASGI; main registration remains Root integration."""

# ruff: noqa: F811 -- the imported real fixture is registered by pytest.

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.ai import document_change_contract as c
from app.ai.document_change_models import AIDocumentChangeScope, AIDocumentRuleLink
from app.database import get_db
from app.routers.ai_document_change import router
from tests.test_ai_document_change_sources import change_case, change_review, link_request, scope_request  # noqa: F401
from tests.test_ai_document_evidence_contract import NOTE, NOW
from tests.test_ai_document_evidence_sources import cas

ROOT = "/api/ai/admin/document-changes"


@pytest.fixture
def change_app(change_case):
    db, *_ = change_case
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return app


@pytest.mark.asyncio
async def test_actual_http_finite_capture_link_scope_governance_private_and_public(change_app, change_case, auth_headers):
    db, actor, _, _, pathway, _ = change_case
    headers = auth_headers(actor.username)
    async with AsyncClient(transport=ASGITransport(app=change_app), base_url="http://synthetic") as client:
        option = await client.get(ROOT + "/options", headers=headers)
        assert option.status_code == 200 and option.json()["data"]["automatic_supersession"] is False
        snap = await client.post(ROOT + "/target-snapshot", headers=headers, json={"kind": "clinical_pathway", "target_id": pathway.pathway_id})
        assert snap.status_code == 200, snap.text
        assert c.e.digest(snap.json()["data"]["snapshot"]) == snap.json()["data"]["snapshot_hash"]
        made = await client.post(ROOT + "/links", headers=headers, json=link_request(change_case))
        assert made.status_code == 200, made.text
        link = c.LinkRecord.model_validate(made.json()["data"])
        assert link.snapshot.recorded_at == NOW
        reviewed = await client.post(f"{ROOT}/links/{link.snapshot.link_id}/review", headers=headers, json=change_review(link))
        assert reviewed.status_code == 200, reviewed.text
        link = c.LinkRecord.model_validate(reviewed.json()["data"])
        assert link.eligible
        body = scope_request(change_case)
        captured = await client.post(ROOT + "/capture", headers=headers, json=body)
        assert captured.status_code == 200, captured.text
        inv = captured.json()["data"]
        assert inv["inventory_hash"] == c.e.digest(inv["inventory"])
        made = await client.post(ROOT + "/scopes", headers=headers, json={**body, "expected_inventory_hash": inv["inventory_hash"]})
        assert made.status_code == 200, made.text
        scope = c.ScopeRecord.model_validate(made.json()["data"])
        confirmed = await client.post(f"{ROOT}/scopes/{scope.snapshot.scope_id}/review", headers=headers, json=change_review(scope))
        assert confirmed.status_code == 200, confirmed.text
        scope = c.ScopeRecord.model_validate(confirmed.json()["data"])
        detailed = await client.get(f"{ROOT}/scopes/{scope.snapshot.scope_id}", headers=headers)
        assert detailed.status_code == 200, detailed.text
        value = detailed.json()
        assert c.ScopeRecord.model_validate(value["data"]) == scope
        public = c.DocumentChangeSource.model_validate(value["public_source"])
        assert public.scope.scope_id == scope.snapshot.scope_id
        assert pathway.name not in c.e.canonical_json(public) and NOTE not in c.e.canonical_json(public)
        for kind, forbidden in (("links", "link_json"), ("scopes", "scope_json")):
            statements = []
            connection = db.connection()

            def sql(conn, cursor, statement, parameters, context, many):
                statements.append(statement)

            event.listen(connection, "before_cursor_execute", sql)
            try:
                directory = await client.get(ROOT + "/" + kind, headers=headers)
            finally:
                event.remove(connection, "before_cursor_execute", sql)
            assert directory.status_code == 200, directory.text
            assert directory.json()["data"]["total"] == 1
            assert directory.json()["data"]["items"][0]["recorded_at"] == NOW
            assert not any(forbidden in statement for statement in statements)
        revoked = await client.post(f"{ROOT}/links/{link.snapshot.link_id}/revoke", headers=headers, json={**cas(link), "basis_note": NOTE})
        assert revoked.status_code == 200
        changed = await client.get(f"{ROOT}/scopes/{scope.snapshot.scope_id}", headers=headers)
        assert changed.status_code == 200 and not changed.json()["data"]["inventory_current"]
        assert changed.json()["data"]["snapshot"] == scope.snapshot.model_dump(mode="json")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin_user", "doctor_user", "pharmacist_user", "nurse_user"])
async def test_super_only_exact_role_on_actual_reads_and_writes(change_app, change_case, auth_headers, role):
    _, _, _, _, _, seed = change_case
    async with AsyncClient(transport=ASGITransport(app=change_app), base_url="http://synthetic") as client:
        assert (await client.get(ROOT + "/options")).status_code == 401
        headers = auth_headers(seed[role].username)
        assert (await client.get(ROOT + "/scopes", headers=headers)).status_code == 403
        assert (await client.post(ROOT + "/capture", headers=headers, json=scope_request(change_case))).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["same_original", "extra_hospital_scope", "wrong_target_type", "false_link_hash", "duplicate_json"])
async def test_source_scope_and_target_fields_fail_closed_without_writes(change_app, change_case, auth_headers, mutation):
    db, actor, *_ = change_case
    body = scope_request(change_case)
    if mutation == "same_original":
        body["candidate_original"] = body["baseline_original"]
    elif mutation == "extra_hospital_scope":
        body["hospital_wide_rule_inventory"] = "complete"
    elif mutation == "wrong_target_type":
        body["declared_targets"][0]["target_id"] = True
    elif mutation == "false_link_hash":
        body = link_request(change_case)
        body["expected_target_hash"] = "a" * 64
    async with AsyncClient(transport=ASGITransport(app=change_app), base_url="http://synthetic") as client:
        path = "/links" if mutation == "false_link_hash" else "/capture"
        if mutation == "duplicate_json":
            result = await client.post(ROOT + path, headers={**auth_headers(actor.username), "content-type": "application/json"}, content=b'{"baseline_original":{},"baseline_original":{}}')
        else:
            result = await client.post(ROOT + path, headers=auth_headers(actor.username), json=body)
    assert result.status_code == (409 if mutation == "false_link_hash" else 422), result.text
    assert db.query(AIDocumentRuleLink).count() == db.query(AIDocumentChangeScope).count() == 0
