"""Actual same-case Main packets for explicit Source→Scenario→Profile form flows."""

# ruff: noqa: F811 -- actual synthetic SQL fixtures are intentionally registered.

import json

import pytest

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_profile_input as p
from app.ai import infection_cluster_scenario_input as s
from tests.test_ai_infection_cluster_profiles import configuration_request, profile_case  # noqa: F401
from tests.test_ai_infection_cluster_sources import cas

ROOT = "/api/ai/infection-cluster"


@pytest.mark.asyncio
async def test_actual_main_same_case_source_scenario_profile_forms_and_current_independent_governance(async_client, profile_case, auth_headers, tmp_path):
    case, packets = profile_case, []
    own, reviewer = auth_headers(case["author"].username), auth_headers(case["reviewer"].username)

    async def send(path, method="GET", body=None, headers=own):
        response = await async_client.request(method, ROOT + path, json=body, headers=headers)
        assert response.status_code == 200, response.text
        packets.append(
            dict(
                path=ROOT + path,
                method=method,
                request=body,
                status=response.status_code,
                raw_utf8=response.text,
                bytes=len(response.content),
                sha256=c.text_digest(response.text),
                response=response.json(),
            )
        )
        return response.json()["data"]

    await send("/snapshots")
    private = await send(f"/snapshots/{case['meta']['snapshot_id']}/parts/private")
    await send(f"/snapshots/{case['meta']['snapshot_id']}/parts/public")
    await send("/registry/definition")
    definition = await send("/registry/definition/" + case["profile_request"]["scope"]["definition_id"])
    await send("/departments?size=100&page=1")
    await send("/local-implementation")
    await send("/roots/preview", "POST", dict(patient_ids=private["value"]["patient_ids"], window=private["value"]["window"], definition_id=definition["record_id"]))
    scenario = s.ScenarioRecord.model_validate(await send("/scenarios", "POST", case["create"]))
    await send("/scenarios")
    await send(f"/scenarios/{scenario.scenario_id}")
    scenario = s.ScenarioRecord.model_validate(
        await send(
            f"/scenarios/{scenario.scenario_id}/review",
            "POST",
            {**cas(scenario), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "parameters_review": "confirmed"},
            reviewer,
        )
    )
    await send("/scenarios")
    await send(f"/scenarios/{scenario.scenario_id}")
    profile = p.ProfileRecord.model_validate(await send("/local-profiles", "POST", case["profile_request"]))
    await send("/local-profiles")
    await send(f"/local-profiles/{profile.profile_id}")
    profile = p.ProfileRecord.model_validate(
        await send(
            f"/local-profiles/{profile.profile_id}/review",
            "POST",
            {**cas(profile), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "parameters_review": "confirmed"},
            reviewer,
        )
    )
    await send("/local-profiles")
    await send(f"/local-profiles/{profile.profile_id}")
    await send("/local-configuration?management=true")
    config = await send("/local-configuration", "PUT", configuration_request(profile.profile_id))
    assert config["enabled"] is False and config["provider_id"] is None and config["validation_status"] == "unreviewed"
    await send("/local-configuration?management=true")
    await send(f"/local-profiles/{profile.profile_id}/revoke", "POST", cas(profile), reviewer)
    await send(f"/scenarios/{scenario.scenario_id}/revoke", "POST", cas(scenario), reviewer)
    (tmp_path / "actual-infection-governance-forms-main-http.json").write_text(
        json.dumps(
            dict(
                scope="Actual same-case Main JWT/ASGI synthetic SQLite, independent Sup publication, explicit unreviewed disabled local configuration; no clinical validation or model inference",
                packets=packets,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
