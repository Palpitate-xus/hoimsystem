from tests.routing import api_routes

"""Actual Main/JWT ASGI governance; Source fixture uses actual SQLite services."""

# ruff: noqa: F811 -- importing the actual same-case SQL fixture registers it.

import json

import pytest
from sqlalchemy import event

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_registry as registry
from app.ai import infection_cluster_scenario_input as i
from app.main import app
from app.routers.ai_infection_cluster_scenarios import router
from tests.test_ai_infection_cluster_scenario import body_queries, scenario_case  # noqa: F401
from tests.test_ai_infection_cluster_sources import cas

ROOT = "/api/ai/infection-cluster"


@pytest.mark.asyncio
async def test_actual_main_explicit_department_family_independent_review_revoke_and_utc6(async_client, scenario_case, auth_headers, tmp_path):
    case = scenario_case
    author, reviewer = auth_headers(case["author"].username), auth_headers(case["reviewer"].username)
    packets = []

    async def send(path, *, method="GET", body=None, headers=author, status=200):
        response = await async_client.request(method, ROOT + path, headers=headers, json=body)
        packets.append(
            dict(
                path=ROOT + path,
                method=method,
                request=body,
                http_status=response.status_code,
                raw_utf8=response.content.decode("utf-8"),
                raw_sha256=c.text_digest(response.content.decode("utf-8")),
                response=response.json(),
            )
        )
        assert response.status_code == status, response.text
        return response.json().get("data")

    directory = await send("/departments?size=1&page=1")
    assert directory["total"] > len(directory["items"]) == 1
    await send("/departments?size=1&page=2")
    descriptor = await send("/local-implementation")
    assert descriptor["engine"] == "prediction" and descriptor["automatic_enable"] is False
    request = {**case["create"], "basis_note": "\ufeff原样方案依据\r\n😀2026-10-21T12:00:00.123456Z"}
    value = i.ScenarioRecord.model_validate(await send("/scenarios", method="POST", body=request))
    assert value.payload.recorded_at == "2026-10-21T12:00:00.123456Z"
    assert value.payload.basis_note == request["basis_note"]
    await send(
        f"/scenarios/{value.scenario_id}/review",
        method="POST",
        body={**cas(value), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "parameters_review": "confirmed"},
        status=409,
    )
    value = i.ScenarioRecord.model_validate(
        await send(
            f"/scenarios/{value.scenario_id}/review",
            method="POST",
            headers=reviewer,
            body={**cas(value), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "parameters_review": "confirmed"},
        )
    )
    assert value.eligible and len(value.payload.plan.department_tokens) == 2
    listing = await send("/scenarios")
    assert listing["total"] == 1 and listing["items"][0]["detail_required"]
    assert "payload" not in listing["items"][0]
    assert await send(f"/scenarios/{value.scenario_id}") == value.model_dump(mode="json")
    revoked = await send(f"/scenarios/{value.scenario_id}/revoke", method="POST", headers=reviewer, body=cas(value))
    assert revoked["status"] == "revoked" and not revoked["can_execute"]
    assert all("mapping_key" not in packet["raw_utf8"] for packet in packets)
    (tmp_path / "actual-infection-scenario-main-http.json").write_text(
        json.dumps({"scope": "Actual Main JWT/ASGI; fixture Source is real SQLite service-created, not HTTP-source or Task execution", "packets": packets}, ensure_ascii=False, indent=2) + "\n"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin_user", "doctor_user", "nurse_user", "patient_user"])
async def test_actual_main_does_not_promote_old_business_roles_to_governance(async_client, scenario_case, auth_headers, seed_data, role):
    response = await async_client.post(ROOT + "/scenarios", headers=auth_headers(seed_data[role].username), json=scenario_case["create"])
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_actual_withdrawn_super_reads_technical_directory_and_zero_clinical_body(async_client, scenario_case, auth_headers):
    from app.ai import infection_cluster_scenario as s

    case = scenario_case
    value = s.create_scenario(case["db"], case["author"], case["create"])
    case["db"].commit()
    grant = case["grants"][0]
    registry.revoke_record(case["db"], case["reviewer"], "grant", grant.record_id, cas(grant))
    case["db"].commit()
    sql = []

    def capture(conn, cursor, query, params, context, many):
        sql.append(query)

    event.listen(case["db"].get_bind(), "before_cursor_execute", capture)
    try:
        headers = auth_headers(case["author"].username)
        listed = await async_client.get(ROOT + "/scenarios", headers=headers)
        denied = await async_client.get(ROOT + f"/scenarios/{value.scenario_id}", headers=headers)
    finally:
        event.remove(case["db"].get_bind(), "before_cursor_execute", capture)
    assert listed.status_code == 200 and denied.status_code == 403
    assert body_queries(sql) == []


def test_actual_router_explicit_json_response_and_seven_mounted_routes():
    assert router.default_response_class.__name__ == "JSONResponse"
    assert len(router.routes) == 7
    assert all(any("/api" + route.path == actual.path for actual in api_routes(app.routes)) for route in router.routes)
