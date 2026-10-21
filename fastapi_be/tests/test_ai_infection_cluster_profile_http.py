"""Actual Main JWT/ASGI local governance, separate from clinical validation."""

# ruff: noqa: F811 -- importing the actual same-case SQL fixture registers it.

import json

import pytest
from sqlalchemy import event

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_profile_input as i
from app.ai import infection_cluster_profiles as p
from app.ai import infection_cluster_registry as registry
from app.ai.infection_cluster_profile_models import AIInfectionLocalSelection
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion
from app.main import app
from app.routers.ai_infection_cluster_profiles import router
from tests.test_ai_infection_cluster_profiles import configuration_request, profile_case  # noqa: F401
from tests.test_ai_infection_cluster_sources import cas

ROOT = "/api/ai/infection-cluster"


@pytest.mark.asyncio
async def test_actual_main_profile_independent_review_explicit_selection_cas_and_withdrawal(async_client, profile_case, auth_headers, tmp_path):
    case = profile_case
    author, reviewer = auth_headers(case["author"].username), auth_headers(case["reviewer"].username)
    packets = []

    async def send(path, *, method="GET", body=None, headers=author, status=200):
        response = await async_client.request(method, ROOT + path, headers=headers, json=body)
        packets.append(dict(path=ROOT + path, method=method, request=body, http_status=response.status_code, raw_utf8=response.text, raw_sha256=c.text_digest(response.text), response=response.json()))
        assert response.status_code == status, response.text
        return response.json().get("data")

    before = await send("/local-configuration?management=true")
    assert before["requires_explicit_configuration"] and before["feature_revision"] == before["selection_revision"] == 0
    req = {**case["profile_request"], "basis_note": "\ufeff原样实现审核依据\r\n😀2026-10-21T12:00:00.123456Z"}
    full = i.ProfileRecord.model_validate(await send("/local-profiles", method="POST", body=req))
    assert full.payload.basis_note == req["basis_note"] and full.payload.recorded_at == "2026-10-21T12:00:00.123456Z"
    review = {**cas(full), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "parameters_review": "confirmed"}
    await send(f"/local-profiles/{full.profile_id}/review", method="POST", body=review, status=409)
    full = i.ProfileRecord.model_validate(await send(f"/local-profiles/{full.profile_id}/review", method="POST", body=review, headers=reviewer))
    assert full.eligible and full.payload.validation_status == "unreviewed"
    listing = await send("/local-profiles")
    assert listing["total"] == 1 and listing["items"][0]["detail_required"] and "payload" not in listing["items"][0]
    assert await send(f"/local-profiles/{full.profile_id}") == full.model_dump(mode="json")
    state = await send("/local-configuration", method="PUT", body=configuration_request(full.profile_id))
    assert not state["enabled"] and state["provider_id"] is None and state["profile_id"] == full.profile_id
    await send("/local-configuration", method="PUT", body=configuration_request(full.profile_id), status=409)
    revoked = await send(f"/local-profiles/{full.profile_id}/revoke", method="POST", body=cas(full), headers=reviewer)
    assert not revoked["eligible"] and revoked["governance"]["status"] == "revoked"
    assert (await send("/local-configuration?management=true"))["profile"]["current_issues"] == ["not_published"]
    assert all("mapping_key" not in packet["raw_utf8"] for packet in packets)
    (tmp_path / "actual-infection-local-profile-main-http.json").write_text(
        json.dumps(
            {"scope": "Actual Main JWT/ASGI; underlying Source uses actual synthetic SQLite services; no real clinical validation or native Task is implied", "packets": packets},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin_user", "doctor_user", "patient_user"])
async def test_current_governance_is_not_granted_by_old_business_role(async_client, profile_case, auth_headers, seed_data, role):
    headers = auth_headers(seed_data[role].username)
    for path in ("/local-profiles", "/local-configuration"):
        response = await async_client.request(
            "POST" if path == "/local-profiles" else "PUT", ROOT + path, headers=headers, json=profile_case["profile_request"] if path == "/local-profiles" else configuration_request()
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_all_generic_feature_and_prompt_mutation_paths_refuse_local_model_replacement_before_any_write(async_client, profile_case, auth_headers):
    case = profile_case
    headers = auth_headers(case["author"].username)
    audit_count, prompt_count = case["db"].query(AIAuditEvent).count(), case["db"].query(AIPromptVersion).count()
    calls = [
        ("PUT", "/api/ai/admin/features/infection_cluster", dict(expected_revision=0, provider_id=None, enabled=True)),
        ("POST", "/api/ai/admin/prompts/infection_cluster", dict(expected_revision=0, task_prompt="旧外部模型Prompt不得替代实际受审本地统计配方。" * 2, change_note="明确拒绝", activate=True)),
        ("POST", "/api/ai/admin/prompts/infection_cluster/activate", dict(expected_revision=0, prompt_id=None)),
    ]
    for method, path, body in calls:
        response = await async_client.request(method, path, json=body, headers=headers)
        assert response.status_code == 409, response.text
    assert case["db"].get(AIFeatureConfig, p.KEY) is None
    assert case["db"].query(AIInfectionLocalSelection).count() == 0
    assert case["db"].query(AIAuditEvent).count() == audit_count and case["db"].query(AIPromptVersion).count() == prompt_count


@pytest.mark.asyncio
async def test_method_configuration_does_not_restore_withdrawn_patient_purpose_or_read_any_clinical_body(async_client, profile_case, auth_headers):
    case = profile_case
    grant = case["grants"][0]
    registry.revoke_record(case["db"], case["reviewer"], "grant", grant.record_id, cas(grant))
    case["db"].commit()
    queries = []

    def capture(conn, cursor, sql, params, context, many):
        queries.append(sql)

    event.listen(case["db"].get_bind(), "before_cursor_execute", capture)
    try:
        headers = auth_headers(case["author"].username)
        configured = await async_client.put(ROOT + "/local-configuration", headers=headers, json=configuration_request())
        denied = await async_client.get(ROOT + f"/snapshots/{case['meta']['snapshot_id']}/parts/private", headers=headers)
    finally:
        event.remove(case["db"].get_bind(), "before_cursor_execute", capture)
    assert configured.status_code == 200 and denied.status_code == 403
    assert not any("hoimsystem_infection_case.description" in sql or "hoimsystem_ai_infection_snapshot.private_json" in sql for sql in queries)


def test_actual_router_explicit_jsonresponse_and_seven_routes_mounted():
    assert router.default_response_class.__name__ == "JSONResponse" and len(router.routes) == 7
    assert all(any(actual.path == "/api" + route.path for actual in app.routes) for route in router.routes)
