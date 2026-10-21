"""Actual application Main/JWT/ASGI source lifecycle, not a model or hospital trial."""

# ruff: noqa: F811 -- importing the actual synthetic SQL fixture registers it.

import json

import pytest
from sqlalchemy import event

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_registry as r
from app.ai.infection_cluster_models import AIInfectionSnapshot
from app.main import app
from app.routers.ai_infection_cluster_sources import router
from tests.test_ai_infection_cluster_sources import NOTE, cas, infection_case, ready  # noqa: F401

ROOT = "/api/ai/infection-cluster"


@pytest.mark.asyncio
async def test_actual_main_full_independent_chain_literal_time_and_withdrawal(async_client, infection_case, auth_headers, tmp_path):
    db, author, reviewer, patient, _ = infection_case
    headers, other = auth_headers(author.username), auth_headers(reviewer.username)
    packets = []

    async def send(path, body=None, *, actor=headers, method="POST"):
        response = await async_client.request(method, ROOT + path, headers=actor, json=body)
        packets.append(
            {
                "path": ROOT + path,
                "method": method,
                "status": response.status_code,
                "request": body,
                "response": response.json(),
                "raw_utf8": response.content.decode("utf-8"),
                "raw_sha256": c.text_digest(response.content.decode("utf-8")),
            }
        )
        assert response.status_code == 200, response.text
        return response.json()["data"]

    grants = []
    for recipient in (author, reviewer):
        draft = await send(
            "/grants",
            {
                "patient_id": patient.patient_id,
                "user_id": recipient.user_id,
                "purpose": "infection_surveillance_processing",
                "valid_from": "2026-10-01T00:00:00.000000Z",
                "valid_to": "2026-11-01T00:00:00.000000Z",
                "basis_note": NOTE,
            },
        )
        assert draft["payload"]["recorded_at"] == "2026-10-21T12:00:00.123456Z"
        full = r.RegistryRecord.model_validate(draft)
        grants.append(await send(f"/registry/grant/{full.record_id}/review", {**cas(full), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed"}, actor=other))
    draft = await send("/definitions", {"version_label": "合成v1", "definition_text": "\ufeff完整原文\r\n😀时间字面量2026-10-21T12:00:00.123456Z", "infection_type_codes": [], "pathogen_codes": []})
    definition = r.RegistryRecord.model_validate(draft)
    definition = await send(
        f"/registry/definition/{definition.record_id}/review", {**cas(definition), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed"}, actor=other
    )
    assert definition["payload"]["definition_text"].endswith(".123456Z")
    scope = {
        "patient_ids": [patient.patient_id],
        "definition_id": definition["record_id"],
        "window": {"date_from": "2026-10-01", "date_to": "2026-10-21", "coordinate_basis": "recorded_onset_date_inclusive_no_event_timezone"},
    }
    preview = await send("/roots/preview", scope)
    raw, pure = preview["originals"][0], preview["definition"]
    assert raw["original"]["description"].endswith(".123456Z") and raw["original"]["pathogen"] == ""
    proposal = {
        "case_id": raw["original"]["case_id"],
        "original_content_hash": raw["content_hash"],
        "definition_id": definition["record_id"],
        "definition_content_hash": pure["content_hash"],
        "definition_governance_hash": pure["governance_hash"],
        "assessment": "not_assessed",
        "basis_note": NOTE,
    }
    for field in ("infection_type", "pathogen"):
        value = raw["original"][field]
        proposal[field] = {"original_state": c.value_state(value), "original_value_hash": c.digest(value), "assessment": "not_assessed", "reviewed_code": None, "basis_note": NOTE}
    draft = r.RegistryRecord.model_validate(await send("/case-reviews", proposal))
    await send(f"/registry/review/{draft.record_id}/review", {**cas(draft), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed"}, actor=other)
    snapshot = await send("/snapshots", scope)
    await send("/snapshots", method="GET")
    private = await send(f"/snapshots/{snapshot['snapshot_id']}/parts/private", method="GET")
    public = await send(f"/snapshots/{snapshot['snapshot_id']}/parts/public", method="GET")
    assert private["value"]["originals"][0] == raw
    assert public["value"]["reports"][0]["human_assessment"] == "not_assessed"
    assert public["value"]["denominator"]["status"] == "not_provided"
    for kind in ("grant", "definition", "review"):
        listing = await send("/registry/" + kind, method="GET")
        assert listing["total"] == (2 if kind == "grant" else 1)
        assert all("payload" not in row and row["detail_required"] for row in listing["items"])
    grant = r.RegistryRecord.model_validate(grants[0])
    await send(f"/registry/grant/{grant.record_id}/revoke", cas(grant), actor=other)
    statements = []

    def record(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        denied = await async_client.get(ROOT + f"/snapshots/{snapshot['snapshot_id']}/parts/private", headers=headers)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    assert denied.status_code == 403
    assert not any("hoimsystem_ai_infection_snapshot.private_json" in sql or "hoimsystem_infection_case.description" in sql for sql in statements)
    assert db.query(AIInfectionSnapshot).count() == 1
    assert all("mapping_key" not in packet["raw_utf8"] for packet in packets)
    (tmp_path / "actual-infection-main-http.json").write_text(json.dumps({"scope": "actual_main_jwt_asgi_synthetic_sql_not_model_execution", "packets": packets}, ensure_ascii=False, indent=2) + "\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin_user", "doctor_user", "nurse_user", "pharmacist_user", "patient_user"])
async def test_source_governance_does_not_inherit_legacy_broad_roles(async_client, infection_case, auth_headers, role, seed_data):
    _, _, _, _, _ = infection_case
    response = await async_client.get(ROOT + "/registry/definition", headers=auth_headers(seed_data[role].username))
    assert response.status_code == 403


def test_actual_source_router_keeps_jsonresponse_whole_body():
    assert router.default_response_class.__name__ == "JSONResponse"
    assert any(route.path == ROOT + "/snapshots/{snapshot_id}/parts/{part}" for route in app.routes)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b'{"version_label":"a","version_label":"b"}', b'{"a":NaN}', b'{"a":"\\ud800"}', b'{"a":"\xff"}'])
async def test_actual_main_rejects_duplicate_nonfinite_surrogate_or_nonutf8(async_client, infection_case, auth_headers, body):
    db, author, _, _, _ = infection_case
    before = db.query(r.AIInfectionDefinition).count()
    response = await async_client.post(ROOT + "/definitions", headers={**auth_headers(author.username), "content-type": "application/json"}, content=body)
    assert response.status_code == 422
    assert db.query(r.AIInfectionDefinition).count() == before
    assert "input" not in response.json()
