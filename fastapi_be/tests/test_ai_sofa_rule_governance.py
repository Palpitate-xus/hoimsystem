"""SOFA has its own immutable publication slot without changing the other three."""

import copy

import pytest

from app.ai import risk_rule_profiles as profiles
from app.ai.models import AIAuditEvent, AIFeatureConfig
from app.ai.sofa_contract import INPUT_POLICY, RECIPE, RULE_ID, recipe_digest
from tests.test_ai_news2_governance import case as case
from tests.test_ai_news2_governance import client as client
from tests.test_ai_news2_governance import observation_case as observation_case
from tests.test_ai_news2_governance import profile_body, publish_body


def sofa_body(**changes):
    return profile_body(rule_id=RULE_ID, expected_recipe_digest=recipe_digest(), **changes)


def test_fourth_option_has_exact_distinct_recipe_policy_and_independent_copies():
    old = copy.deepcopy(profiles.fixed_options()[:3])
    option = profiles.fixed_options()[3]
    assert option == {"rule_id": RULE_ID, "recipe_digest": recipe_digest(), "recipe": RECIPE, "input_policy": INPUT_POLICY}
    option["recipe"].clear()
    option["input_policy"].clear()
    assert profiles.fixed_options()[:3] == old
    assert profiles.fixed_option(RULE_ID)["recipe"] == RECIPE


@pytest.mark.asyncio
async def test_actual_four_rule_publication_slots_are_independent_and_do_not_enable_ai(client, db_session, case, auth_headers):
    headers = auth_headers(case["seed"]["super_admin_user"].username)
    original = profiles.profile_current(db_session, case["profile"].rule_profile_id)
    configs = [(row.feature_key, row.enabled, row.validation_status, row.revision) for row in db_session.query(AIFeatureConfig).all()]
    published = [original]
    for option in profiles.fixed_options()[1:]:
        created = await client.post("/api/ai/admin/risk-rule-profiles", headers=headers, json=profile_body(rule_id=option["rule_id"], expected_recipe_digest=option["recipe_digest"]))
        assert created.status_code == 200, created.text
        draft = created.json()["data"]
        assert draft["status"] == "draft" and not draft["eligible"]
        result = await client.post(f"/api/ai/admin/risk-rule-profiles/{draft['rule_profile_id']}/publish", headers=headers, json=publish_body(expected_recipe_digest=option["recipe_digest"]))
        assert result.status_code == 200, result.text
        current = result.json()["data"]
        assert current["eligible"] and current["clinical_validation"] == "not_provided"
        published.append(current)
    assert {item["rule_id"] for item in published} == {item["rule_id"] for item in profiles.fixed_options()}
    assert all(profiles.profile_current(db_session, item["rule_profile_id"])["eligible"] for item in published)
    sofa = published[-1]
    duplicate = (await client.post("/api/ai/admin/risk-rule-profiles", headers=headers, json=sofa_body())).json()["data"]
    conflict = await client.post(f"/api/ai/admin/risk-rule-profiles/{duplicate['rule_profile_id']}/publish", headers=headers, json=publish_body(expected_recipe_digest=recipe_digest()))
    assert conflict.status_code == 409
    revoked = await client.post(
        f"/api/ai/admin/risk-rule-profiles/{sofa['rule_profile_id']}/revoke", headers=headers, json={"expected_revision": 2, "reason": "仅撤销合成SOFA实施审核，其余三个规则不受影响。"}
    )
    assert revoked.status_code == 200 and revoked.json()["data"]["status"] == "revoked"
    assert profiles.profile_detail(db_session, sofa["rule_profile_id"])["recipe"] == RECIPE
    assert all(profiles.profile_current(db_session, item["rule_profile_id"])["eligible"] for item in published[:-1])
    listed = await client.get("/api/ai/admin/risk-rule-profiles", headers=headers, params={"rule_id": RULE_ID, "page_size": 1})
    assert listed.status_code == 200 and listed.json()["data"]["total"] == 2
    assert all(row["rule_id"] == RULE_ID for row in listed.json()["data"]["items"])
    assert configs == [(row.feature_key, row.enabled, row.validation_status, row.revision) for row in db_session.query(AIFeatureConfig).all()]
    assert db_session.query(AIAuditEvent).filter_by(action="risk_rule_profile.publish", target=sofa["rule_profile_id"]).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["doctor_user", "nurse_user", "admin_user", "cashier_user", "pharmacist_user", "guide_user", "lab_tech_user", "registrar_user", "patient_user"])
async def test_only_actual_super_can_read_or_create_sofa_rules(role, client, db_session, case, auth_headers):
    headers = auth_headers(case["seed"][role].username)
    assert (await client.get("/api/ai/admin/risk-rule-profiles/options", headers=headers)).status_code == 403
    assert (await client.post("/api/ai/admin/risk-rule-profiles", headers=headers, json=sofa_body())).status_code == 403


@pytest.mark.asyncio
async def test_clients_cannot_upload_thresholds_or_claim_recipe_from_another_rule(client, case, auth_headers):
    headers = auth_headers(case["seed"]["super_admin_user"].username)
    assert (await client.post("/api/ai/admin/risk-rule-profiles", headers=headers, json={**sofa_body(), "thresholds": {"map": 999}})).status_code == 422
    wrong = await client.post("/api/ai/admin/risk-rule-profiles", headers=headers, json={**sofa_body(), "expected_recipe_digest": "0" * 64})
    assert wrong.status_code == 409
