"""Keep fixed rule identity separate from option ordering and the NEWS2 source path."""

import copy

import pytest
from fastapi import HTTPException

from app.ai import news2_sources, risk_rule_profiles
from app.ai.models import AIAuditEvent, AINews2Assessment, AIRiskRuleProfile
from app.ai.news2_contract import RECIPE, recipe_digest
from app.routers import ai_news2
from tests.test_ai_news2_governance import body, profile_body, scope
from tests.test_ai_news2_governance import case as case
from tests.test_ai_news2_governance import client as client
from tests.test_ai_news2_governance import observation_case as observation_case


def foreign_profile_row(db, case):
    """A deliberately invalid foreign body must never enter NEWS2 candidate parsing."""
    original = case["profile"]
    values = {column.name: getattr(original, column.name) for column in AIRiskRuleProfile.__table__.columns}
    values.update(
        rule_profile_id="00000000-0000-4000-8000-000000000001",
        rule_id="kdigo_aki_2012",
        identity_hash=risk_rule_profiles.hash_content({"rule_id": "kdigo_aki_2012"}),
        payload_json="invalid-foreign-body-not-a-rule-implementation",
        content_hash="0" * 64,
    )
    values["published_key"] = values["identity_hash"]
    row = AIRiskRuleProfile(**values)
    db.add(row)
    db.commit()
    return row


def test_news2_option_retains_original_manifest_policy_and_independent_copies():
    original = {
        "rule_id": "news2_2017",
        "recipe_digest": recipe_digest(),
        "recipe": copy.deepcopy(RECIPE),
        "input_policy": {
            "point_selection": "single_explicit_point",
            "temporal_fusion": "no_merge",
            "pulse_metric": "pulse_rate_only",
            "same_time_conflicts": "reject_same_time_relevant_conflict",
            "integer_chart_metrics": ["respiratory_rate", "spo2", "systolic_bp", "pulse_rate"],
            "temperature_step": "0.1",
            "rounding": "never",
            "imputation": "none",
            "unit_conversion": "none",
        },
    }
    assert risk_rule_profiles.fixed_options()[0] == original
    modified = risk_rule_profiles.fixed_options()[0]
    modified["recipe"].clear()
    modified["input_policy"].clear()
    assert risk_rule_profiles.fixed_options()[0] == original


def test_create_and_detail_select_exact_rule_identity_instead_of_first_option(db_session, case, monkeypatch):
    news2 = risk_rule_profiles.fixed_options()[0]
    # An identity-only sentinel tests lookup ordering without inventing a KDIGO
    # recipe or registering any executable implementation in production.
    monkeypatch.setattr(risk_rule_profiles, "fixed_options", lambda: [{"rule_id": "kdigo_aki_2012"}, news2])
    row = risk_rule_profiles.create_profile(db_session, case["seed"]["super_admin_user"], profile_body())
    db_session.commit()
    current = risk_rule_profiles.profile_detail(db_session, row)
    assert current["rule_id"] == "news2_2017" and current["recipe"] == RECIPE
    assert current["implementation_current"] is True


def test_unregistered_selected_rule_cannot_fall_back_to_news2_recipe(db_session, case, monkeypatch):
    news2 = risk_rule_profiles.fixed_options()[0]
    monkeypatch.setattr(risk_rule_profiles, "fixed_options", lambda: [news2])
    before = db_session.query(AIRiskRuleProfile).count()
    with pytest.raises(HTTPException) as caught:
        risk_rule_profiles.create_profile(db_session, case["seed"]["super_admin_user"], profile_body(rule_id="kdigo_aki_2012"))
    assert caught.value.status_code == 409
    assert db_session.query(AIRiskRuleProfile).count() == before and not db_session.new


@pytest.mark.asyncio
async def test_news2_candidates_exclude_other_rule_before_loading_its_body(client, db_session, case, auth_headers):
    foreign = foreign_profile_row(db_session, case)
    response = await client.get("/api/ai/news2-assessments/candidates", params={**scope(case), "window_id": case["window"].window_id}, headers=auth_headers(case["doctor"].username))
    assert response.status_code == 200, response.text
    profiles = response.json()["data"]["rule_profiles"]
    assert [item["rule_profile_id"] for item in profiles] == [case["profile"].rule_profile_id]
    assert foreign.rule_profile_id not in {item["rule_profile_id"] for item in profiles}


@pytest.mark.asyncio
async def test_profile_rule_filter_applies_before_pagination_and_rejects_unknown_rules(client, db_session, case, auth_headers):
    foreign_profile_row(db_session, case)
    headers = auth_headers(case["seed"]["super_admin_user"].username)
    response = await client.get("/api/ai/admin/risk-rule-profiles", params={"rule_id": "news2_2017", "page_size": 1}, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 1 and data["items"][0]["rule_profile_id"] == case["profile"].rule_profile_id
    assert (await client.get("/api/ai/admin/risk-rule-profiles", params={"rule_id": "custom_thresholds"}, headers=headers)).status_code == 422


@pytest.mark.asyncio
async def test_news2_create_rejects_current_foreign_rule_before_projection_or_writes(client, db_session, case, auth_headers, monkeypatch):
    foreign = risk_rule_profiles.profile_current(db_session, case["profile"].rule_profile_id)
    foreign["rule_id"] = "kdigo_aki_2012"
    monkeypatch.setattr(news2_sources, "profile_current", lambda *args, **kwargs: foreign)
    before = (db_session.query(AINews2Assessment).count(), db_session.query(AIAuditEvent).count())
    response = await client.post("/api/ai/news2-assessments", json=body(case), headers=auth_headers(case["doctor"].username))
    assert response.status_code == 409 and "NEWS2" in response.text
    assert (db_session.query(AINews2Assessment).count(), db_session.query(AIAuditEvent).count()) == before
    assert not db_session.new


def test_current_foreign_profile_stops_existing_news2_projection_and_hides_ordinary_snapshot(db_session, case, monkeypatch):
    row = news2_sources.create_assessment(db_session, case["doctor"], body(case))
    db_session.commit()
    frozen = row.snapshot_json
    foreign = risk_rule_profiles.profile_current(db_session, case["profile"].rule_profile_id)
    foreign["rule_id"] = "kdigo_aki_2012"
    monkeypatch.setattr(news2_sources, "profile_current", lambda *args, **kwargs: foreign)
    current = news2_sources.assessment_current(db_session, row, allow_revoked=True, user=case["doctor"])
    assert current["eligible"] is False and "profile_rule_mismatch" in current["exclusion_reasons"]
    assert current["specialist_source"] is None
    with pytest.raises(HTTPException) as caught:
        news2_sources.assessment_current(db_session, row, user=case["doctor"])
    assert caught.value.status_code == 409
    assert ai_news2.detail(db_session, case["doctor"], row)["snapshot"] is None
    assert ai_news2.detail(db_session, case["seed"]["super_admin_user"], row)["snapshot"] == current["snapshot"]
    assert row.snapshot_json == frozen


def test_frozen_foreign_profile_cannot_become_news2_even_with_recomputed_outer_hash(db_session, case):
    row = news2_sources.create_assessment(db_session, case["doctor"], body(case))
    db_session.commit()
    snapshot = copy.deepcopy(news2_sources.assessment_current(db_session, row, user=case["doctor"])["snapshot"])
    snapshot["rule_profile"]["rule_id"] = "kdigo_aki_2012"
    row.snapshot_json = news2_sources.canonical_json(snapshot)
    row.content_hash = news2_sources.hash_content(snapshot)
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        news2_sources.assessment_current(db_session, row, allow_revoked=True, user=case["doctor"])
    assert caught.value.status_code == 409


@pytest.mark.asyncio
async def test_two_actual_fixed_rules_publish_independently_and_news2_rejects_aki_profile(client, db_session, case, auth_headers):
    from app.ai.aki_contract import INPUT_POLICY as AKI_INPUT_POLICY
    from app.ai.aki_contract import RECIPE as AKI_RECIPE
    from app.ai.aki_contract import recipe_digest as aki_recipe_digest
    from app.routers import ai_risk_rules

    options = risk_rule_profiles.fixed_options()
    assert options[0]["rule_id"] == "news2_2017"
    assert options[1] == {"rule_id": "kdigo_aki_2012", "recipe_digest": aki_recipe_digest(), "recipe": AKI_RECIPE, "input_policy": AKI_INPUT_POLICY}
    supervisor = case["seed"]["super_admin_user"]
    row = risk_rule_profiles.create_profile(db_session, supervisor, profile_body(rule_id="kdigo_aki_2012", expected_recipe_digest=aki_recipe_digest()))
    db_session.commit()
    reviewed = ai_risk_rules.publish_profile(
        row.rule_profile_id,
        ai_risk_rules.ProfilePublish(
            expected_revision=1,
            expected_recipe_digest=aki_recipe_digest(),
            implementation_terms_confirmed=True,
            review_note="明确审核固定原算法和输入政策，仅为工程测试并非临床验证。",
            review_evidence_reference="Synthetic actual KDIGO fixed recipe review",
        ),
        db_session,
        supervisor,
    )["data"]
    assert reviewed["eligible"] and risk_rule_profiles.profile_current(db_session, case["profile"].rule_profile_id)["eligible"]
    assert reviewed["rule_id"] == "kdigo_aki_2012" and row.published_key != case["profile"].published_key
    headers = auth_headers(supervisor.username)
    response = await client.get("/api/ai/admin/risk-rule-profiles", params={"rule_id": "kdigo_aki_2012", "page_size": 1}, headers=headers)
    assert response.status_code == 200 and response.json()["data"]["total"] == 1
    assert response.json()["data"]["items"][0]["rule_profile_id"] == row.rule_profile_id
    before = db_session.query(AINews2Assessment).count(), db_session.query(AIAuditEvent).count()
    wrong = await client.post(
        "/api/ai/news2-assessments", json=body(case, rule_profile_id=row.rule_profile_id, expected_rule_profile_hash=row.content_hash), headers=auth_headers(case["doctor"].username)
    )
    assert wrong.status_code == 409
    assert (db_session.query(AINews2Assessment).count(), db_session.query(AIAuditEvent).count()) == before
    ai_risk_rules.revoke_profile(row.rule_profile_id, ai_risk_rules.ProfileRevoke(expected_revision=2, reason="独立撤销KDIGO工程实施，不影响NEWS2已审核实施。"), db_session, supervisor)
    assert risk_rule_profiles.profile_current(db_session, case["profile"].rule_profile_id)["eligible"]
