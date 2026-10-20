"""Synthetic real HTTP/ORM rule review and explicit point-source provenance, without external inference."""

import copy
import datetime
import json
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException

from app.ai import news2_contract, news2_sources, observation_windows, risk_rule_profiles
from app.ai.models import AIAuditEvent, AIFeatureConfig, AINews2Assessment, AIObservationWindow, AIPatientGrant, AIRiskRuleProfile
from app.ai.news2_model import news2_values
from app.database import get_db
from app.inpatient_observations import PointPayload, frozen_content_hash
from app.models import Admission, Doctor, InpatientObservation, User
from app.routers import ai_news2, ai_risk_rules
from tests.test_ai_observation_windows import observation_case as observation_case
from tests.test_ai_observation_windows import point, values

NOTE = "合成测试明确核对实施版本和原采样时点的人群适用性；这是人工声明而非独立临床验证。"


def profile_body(**changes):
    return {
        "name": "Synthetic NEWS2 profile",
        "rule_id": "news2_2017",
        "expected_recipe_digest": news2_contract.recipe_digest(),
        "evidence_reference": "Synthetic implementation review document",
        "rationale": NOTE,
        **changes,
    }


def publish_body(**changes):
    return {
        "expected_revision": 1,
        "expected_recipe_digest": news2_contract.recipe_digest(),
        "implementation_terms_confirmed": True,
        "review_note": NOTE,
        "review_evidence_reference": "Synthetic implementation and terms review only",
        **changes,
    }


def scale2_review(**changes):
    return {
        "hypercapnic_respiratory_failure_confirmed": True,
        "clinical_decision_confirmed": True,
        "target_range": "88-92",
        "blood_gas_reference": "合成已明确高碳酸呼衰血气证据，仅由临床签署者核实其真实性。",
        "clinical_decision_reference": "合成负责医生独立作出Scale2及88至92目标决定，不能只凭氧疗或COPD名称推断。",
        **changes,
    }


@pytest.fixture
def case(db_session, observation_case, monkeypatch):
    case = observation_case
    case["admission_id"] = case["admission"].admission_id
    db_session.query(AINews2Assessment).delete()
    db_session.query(AIRiskRuleProfile).delete()
    db_session.query(AIPatientGrant).filter_by(patient_id=case["patient_id"], category="inpatient").delete()
    for module in (news2_sources, risk_rule_profiles, ai_news2, ai_risk_rules):
        monkeypatch.setattr(module, "utcnow", lambda: case["now"])
    payload = {
        "measurements": {
            key: {"value": value, "unit": unit, "absent_reason": None}
            for key, value, unit in [("respiratory_rate", "16", "/min"), ("spo2", "97", "%"), ("systolic_bp", "120", "mm[Hg]"), ("pulse_rate", "80", "/min"), ("temperature", "36.5", "Cel")]
        },
        "supplemental_oxygen": "no",
        "consciousness": {"system": "ACVPU", "code": "alert"},
        "note": "原点测中文备注，不应外发给独立规则服务",
    }
    typed = PointPayload.model_validate(payload).model_dump(mode="json")
    case["point"].payload_json = news2_sources.canonical_json(typed)
    case["point"].content_hash = frozen_content_hash(case["point"], typed)
    db_session.commit()
    profile = risk_rule_profiles.create_profile(db_session, case["seed"]["super_admin_user"], profile_body())
    db_session.commit()
    ai_risk_rules.publish_profile(profile.rule_profile_id, ai_risk_rules.ProfilePublish(**publish_body()), db_session, case["seed"]["super_admin_user"])
    case["profile"] = profile
    case["window"] = observation_windows.create_window(db_session, case["doctor"], values(case))
    db_session.commit()
    return case


@pytest_asyncio.fixture
async def client(db_session):
    app = FastAPI()
    app.include_router(ai_risk_rules.router, prefix="/api")
    app.include_router(ai_news2.router, prefix="/api")

    def session_override():
        yield db_session

    app.dependency_overrides[get_db] = session_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as result:
        yield result


def scope(case):
    return {"patient_id": case["patient_id"], "admission_id": case["admission_id"]}


def body(case, **changes):
    return {
        **scope(case),
        "window_id": case["window"].window_id,
        "expected_window_hash": case["window"].content_hash,
        "point_id": case["point"].observation_id,
        "expected_point_hash": case["point"].content_hash,
        "rule_profile_id": case["profile"].rule_profile_id,
        "expected_rule_profile_hash": case["profile"].content_hash,
        "age_at_observation_years": 40,
        "age_basis_note": NOTE,
        "pregnancy_status": "not_pregnant",
        "pregnancy_basis_note": NOTE,
        "spo2_scale": 1,
        "scale2_review": None,
        **changes,
    }


def grant(db, case, user):
    row = AIPatientGrant(
        user_id=user.user_id,
        patient_id=case["patient_id"],
        category="inpatient",
        reason=NOTE,
        created_by=case["seed"]["super_admin_user"].user_id,
        expires_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + datetime.timedelta(days=1),
        revoked=0,
    )
    db.add(row)
    db.commit()
    return row


async def create(client, case, auth_headers, *, role="doctor_user", **changes):
    response = await client.post("/api/ai/news2-assessments", headers=auth_headers(case["seed"][role].username), json=body(case, **changes))
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_fixed_rule_draft_review_publication_unique_slot_revoke_and_no_activation(client, db_session, case, auth_headers):
    headers = auth_headers(case["seed"]["super_admin_user"].username)
    db_session.add_all(
        [
            AIFeatureConfig(feature_key="deterioration_risk", enabled=0, validation_status="unreviewed", updated_by=case["seed"]["super_admin_user"].user_id),
            AIFeatureConfig(feature_key="aki_risk", enabled=1, validation_status="validated", updated_by=case["seed"]["super_admin_user"].user_id),
        ]
    )
    db_session.commit()
    before = [(row.feature_key, row.enabled, row.validation_status) for row in db_session.query(AIFeatureConfig)]
    options = (await client.get("/api/ai/admin/risk-rule-profiles/options", headers=headers)).json()["data"]
    assert options["items"][0]["recipe"] == news2_contract.RECIPE and options["clinical_validation"] == "not_provided"
    response = await client.post("/api/ai/admin/risk-rule-profiles", headers=headers, json=profile_body())
    assert response.status_code == 200
    draft = response.json()["data"]
    assert draft["status"] == "draft" and draft["revision"] == 1 and draft["eligible"] is False
    endpoint = "/api/ai/admin/risk-rule-profiles/" + draft["rule_profile_id"]
    assert (await client.post(endpoint + "/publish", headers=headers, json=publish_body())).status_code == 409
    original = case["profile"].payload_json
    withdrawn = await client.post(f"/api/ai/admin/risk-rule-profiles/{case['profile'].rule_profile_id}/revoke", headers=headers, json={"expected_revision": 2, "reason": NOTE})
    assert withdrawn.status_code == 200 and withdrawn.json()["data"]["revision"] == 3
    assert case["profile"].payload_json == original
    reviewed = await client.post(endpoint + "/publish", headers=headers, json=publish_body())
    assert reviewed.status_code == 200 and reviewed.json()["data"]["implementation_terms_confirmed"] is True
    assert reviewed.json()["data"]["content_hash"] == draft["content_hash"]
    assert (await client.post(endpoint + "/publish", headers=headers, json=publish_body())).status_code == 409
    assert [(row.feature_key, row.enabled, row.validation_status) for row in db_session.query(AIFeatureConfig)] == before
    for method in ("PUT", "PATCH", "DELETE"):
        assert (await client.request(method, endpoint, headers=headers)).status_code == 405


@pytest.mark.parametrize("role", ["doctor_user", "director_user", "nurse_user", "admin_user", "lab_tech_user", "patient_user"])
@pytest.mark.asyncio
async def test_only_actual_super_can_manage_profiles(role, client, case, auth_headers):
    headers = auth_headers(case["seed"][role].username)
    assert (await client.get("/api/ai/admin/risk-rule-profiles/options", headers=headers)).status_code == 403
    assert (await client.post("/api/ai/admin/risk-rule-profiles", headers=headers, json=profile_body())).status_code == 403


@pytest.mark.parametrize("field,value", [("thresholds", {}), ("recipe", {}), ("rule_id", "edited-news2"), ("expected_recipe_digest", "0" * 64)])
@pytest.mark.asyncio
async def test_profile_cannot_configure_arbitrary_thresholds_or_stale_recipe(field, value, client, case, auth_headers):
    response = await client.post("/api/ai/admin/risk-rule-profiles", headers=auth_headers(case["seed"]["super_admin_user"].username), json=profile_body(**{field: value}))
    assert response.status_code == (409 if field == "expected_recipe_digest" else 422)


@pytest.mark.parametrize(
    "field,value", [("implementation_terms_confirmed", False), ("implementation_terms_confirmed", 1), ("expected_revision", True), ("review_note", " " * 25), ("review_evidence_reference", " ")]
)
@pytest.mark.asyncio
async def test_publication_needs_literal_terms_and_review_evidence(field, value, client, case, auth_headers):
    response = await client.post(
        f"/api/ai/admin/risk-rule-profiles/{case['profile'].rule_profile_id}/publish", headers=auth_headers(case["seed"]["super_admin_user"].username), json=publish_body(**{field: value})
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_real_assessment_binds_exact_window_point_and_minimized_typed_projection(client, db_session, case, auth_headers):
    headers = auth_headers(case["doctor"].username)
    candidates = await client.get("/api/ai/news2-assessments/candidates", headers=headers, params={**scope(case), "window_id": case["window"].window_id})
    assert candidates.status_code == 200
    candidate = candidates.json()["data"]
    assert candidate["can_create_scale2"] is True and candidate["points"][0]["observation_id"] == case["point"].observation_id
    assert candidate["rule_profiles"][0]["rule_profile_id"] == case["profile"].rule_profile_id
    data = await create(client, case, auth_headers)
    row = db_session.get(AINews2Assessment, data["assessment_id"])
    assert data["snapshot"]["point"]["payload"]["note"] == "原点测中文备注，不应外发给独立规则服务"
    assert data["content_hash"] == news2_sources.hash_content(data["snapshot"])
    assert "points" not in data["snapshot"]["window_binding"] and data["eligible"] is True
    source = data["specialist_source"]
    assert news2_contract.News2Source.model_validate(source).model_dump(mode="json") == source
    assert source["source_governance_hash"] == data["governance_hash"] and source["content_hash"] == data["content_hash"]
    assert all(text not in json.dumps(source, ensure_ascii=False) for text in ("patient_id", "admission_id", "note", NOTE, "原点测中文备注"))
    assert source["measurements"]["pulse_rate"]["value"] == "80" and "heart_rate" not in source["measurements"]
    assert news2_values(source)["total_score"] == 0
    assert (
        news2_sources.authorize_assessment(db_session, case["doctor"], case["patient_id"], case["admission"].admission_id, row.assessment_id, window_id=case["window"].window_id)["specialist_source"]
        == source
    )
    with pytest.raises(HTTPException) as caught:
        news2_sources.assessment_current(db_session, row)
    assert caught.value.status_code == 422
    assert news2_sources.assessment_current(db_session, row, user=case["doctor"])["snapshot"] == data["snapshot"]
    listed = (await client.get("/api/ai/news2-assessments", headers=headers, params=scope(case))).json()["data"]
    assert listed == {"items": [data], "total": 1, "page": 1, "page_size": 50}
    event = db_session.query(AIAuditEvent).filter_by(action="news2_assessment.create", target=row.assessment_id).one()
    assert json.loads(event.detail_json)["content_hash"] == row.content_hash and NOTE not in event.detail_json
    assert row.created_at == case["now"] and data["created_at"] == observation_windows.iso(case["now"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("age_at_observation_years", True),
        ("age_at_observation_years", "40"),
        ("age_at_observation_years", None),
        ("age_at_observation_years", 131),
        ("spo2_scale", True),
        ("spo2_scale", "1"),
        ("spo2_scale", 3),
        ("age_basis_note", " " * 25),
        ("pregnancy_basis_note", "short"),
        ("pregnancy_status", "normal"),
        ("measurements", {}),
        ("supplemental_oxygen", "no"),
        ("point_id", "not-uuid"),
    ],
)
@pytest.mark.asyncio
async def test_assessment_requires_explicit_typed_declarations_and_rejects_value_override(field, value, client, case, auth_headers):
    response = await client.post("/api/ai/news2-assessments", headers=auth_headers(case["doctor"].username), json=body(case, **{field: value}))
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["expected_window_hash", "expected_point_hash", "expected_rule_profile_hash"])
@pytest.mark.asyncio
async def test_original_selection_hashes_are_compare_and_use_not_advisory(field, client, case, auth_headers):
    response = await client.post("/api/ai/news2-assessments", headers=auth_headers(case["doctor"].username), json=body(case, **{field: "0" * 64}))
    assert response.status_code == 409


@pytest.mark.parametrize(
    "population,status", [({"pregnancy_status": "unknown"}, "insufficient_data"), ({"pregnancy_status": "pregnant"}, "outside_scope"), ({"age_at_observation_years": 15}, "outside_scope")]
)
@pytest.mark.asyncio
async def test_unknown_or_outside_population_is_preserved_without_fake_compliance(population, status, client, case, auth_headers):
    data = await create(client, case, auth_headers, **population)
    assert data["eligible"] is True
    result = news2_values(data["specialist_source"])
    assert result["calculation_status"] == status and result["total_score"] is None


@pytest.mark.asyncio
async def test_nurse_can_create_scale1_and_use_existing_doctor_scale2_but_cannot_sign_scale2(client, db_session, case, auth_headers):
    nurse = case["seed"]["nurse_user"]
    grant(db_session, case, nurse)
    candidate = await client.get("/api/ai/news2-assessments/candidates", headers=auth_headers(nurse.username), params={**scope(case), "window_id": case["window"].window_id})
    assert candidate.json()["data"]["can_create_scale2"] is False
    assert (await create(client, case, auth_headers, role="nurse_user"))["eligible"] is True
    denied = await client.post("/api/ai/news2-assessments", headers=auth_headers(nurse.username), json=body(case, spo2_scale=2, scale2_review=scale2_review()))
    assert denied.status_code == 403
    signed = await create(client, case, auth_headers, spo2_scale=2, scale2_review=scale2_review())
    selected = news2_sources.authorize_assessment(db_session, nurse, case["patient_id"], case["admission"].admission_id, signed["assessment_id"])
    assert selected["specialist_source"]["spo2_scale"] == 2
    review = selected["specialist_source"]["scale2_review"]
    assert set(review) == {"hypercapnic_respiratory_failure_confirmed", "clinical_decision_confirmed", "target_range", "blood_gas_reference_hash", "clinical_decision_reference_hash"}
    assert "合成" not in json.dumps(review, ensure_ascii=False)


@pytest.mark.asyncio
async def test_super_management_never_becomes_scale2_clinical_care_by_role_alone(client, db_session, case, auth_headers):
    supervisor = case["seed"]["super_admin_user"]
    headers = auth_headers(supervisor.username)
    request = body(case, spo2_scale=2, scale2_review=scale2_review())
    assert (await client.post("/api/ai/news2-assessments", headers=headers, json=request)).status_code == 403
    doctor = Doctor(user_id=supervisor.user_id, name="Synthetic actual doctor")
    db_session.add(doctor)
    db_session.commit()
    assert (await client.post("/api/ai/news2-assessments", headers=headers, json=request)).status_code == 403
    grant(db_session, case, supervisor)
    assert (await client.post("/api/ai/news2-assessments", headers=headers, json=request)).status_code == 200


@pytest.mark.parametrize(
    "review",
    [
        None,
        scale2_review(hypercapnic_respiratory_failure_confirmed=1),
        scale2_review(clinical_decision_confirmed=False),
        scale2_review(target_range="90-94"),
        scale2_review(blood_gas_reference="short"),
    ],
)
@pytest.mark.asyncio
async def test_scale2_requires_separate_explicit_blood_gas_and_clinical_decision(review, client, case, auth_headers):
    response = await client.post("/api/ai/news2-assessments", headers=auth_headers(case["doctor"].username), json=body(case, spo2_scale=2, scale2_review=review))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_historical_doctor_role_is_frozen_but_reassigned_doctor_identity_is_detected(client, db_session, case, auth_headers):
    data = await create(client, case, auth_headers, spo2_scale=2, scale2_review=scale2_review())
    db_session.query(User).filter_by(user_id=case["doctor"].user_id).update({"user_role": "nurse"})
    db_session.commit()
    supervisor = case["seed"]["super_admin_user"]
    assert news2_sources.authorize_assessment(db_session, supervisor, case["patient_id"], case["admission"].admission_id, data["assessment_id"])["eligible"] is True
    doctor_id = data["snapshot"]["author_qualification"]["doctor_id"]
    db_session.query(Doctor).filter_by(doctor_id=doctor_id).update({"user_id": supervisor.user_id})
    db_session.commit()
    current = news2_sources.assessment_current(db_session, data["assessment_id"], allow_revoked=True, user=supervisor)
    assert current["eligible"] is False and "clinical_signer_relationship_changed" in current["exclusion_reasons"]


@pytest.mark.parametrize("change", ["point", "window", "profile", "recipe", "deleted_point", "deleted_admission"])
@pytest.mark.asyncio
async def test_current_governance_changes_stop_execution_and_super_can_withdraw_frozen_source(change, client, db_session, case, auth_headers, monkeypatch):
    data = await create(client, case, auth_headers)
    if change == "point":
        case["point"].payload_json = "{}"
    elif change == "window":
        case["window"].status, case["window"].revision, case["window"].revoked_at, case["window"].revoked_by, case["window"].revoke_reason = "revoked", 2, case["now"], case["doctor"].user_id, NOTE
    elif change == "profile":
        ai_risk_rules.revoke_profile(case["profile"].rule_profile_id, ai_risk_rules.ProfileRevoke(expected_revision=2, reason=NOTE), db_session, case["seed"]["super_admin_user"])
    elif change == "recipe":
        altered = copy.deepcopy(news2_contract.RECIPE)
        altered["version"] += "-changed"
        monkeypatch.setattr(news2_contract, "RECIPE", altered)
    elif change == "deleted_point":
        db_session.query(InpatientObservation).filter_by(observation_id=case["point"].observation_id).delete(synchronize_session=False)
    elif change == "deleted_admission":
        db_session.query(Admission).filter_by(admission_id=case["admission"].admission_id).delete(synchronize_session=False)
    db_session.commit()
    with pytest.raises(HTTPException):
        news2_sources.authorize_assessment(db_session, case["doctor"], case["patient_id"], case["admission_id"], data["assessment_id"])
    ordinary = await client.get(f"/api/ai/news2-assessments/{data['assessment_id']}", headers=auth_headers(case["doctor"].username), params=scope(case))
    if change == "deleted_admission":
        assert ordinary.status_code == 404
    else:
        assert ordinary.status_code == 200 and ordinary.json()["data"]["snapshot"] is None and ordinary.json()["data"]["specialist_source"] is None
    super_headers = auth_headers(case["seed"]["super_admin_user"].username)
    audit = await client.get(f"/api/ai/admin/news2-assessments/{data['assessment_id']}", headers=super_headers)
    assert audit.status_code == 200 and audit.json()["data"]["snapshot"] == data["snapshot"] and audit.json()["data"]["eligible"] is False
    revoked = await client.post(f"/api/ai/news2-assessments/{data['assessment_id']}/revoke", headers=super_headers, json={**scope(case), "expected_revision": 1, "reason": NOTE})
    assert revoked.status_code == 200 and revoked.json()["data"]["status"] == "revoked"


@pytest.mark.asyncio
async def test_same_time_conflicts_use_window_quality_and_no_temporal_or_heart_rate_merge(client, db_session, case, auth_headers):
    payload = json.loads(case["point"].payload_json)
    conflict = copy.deepcopy(payload)
    conflict["measurements"]["pulse_rate"]["value"] = "140"
    point(db_session, case, payload=conflict)
    case["window"] = observation_windows.create_window(db_session, case["doctor"], values(case))
    db_session.commit()
    data = await create(client, case, auth_headers)
    assert data["specialist_source"]["conflict_codes"] == ["pulse_rate"]
    assert data["specialist_source"]["measurements"]["pulse_rate"]["value"] == "80"
    assert news2_values(data["specialist_source"])["calculation_status"] == "insufficient_data"
    with pytest.raises(HTTPException):
        news2_sources.authorize_assessment(db_session, case["doctor"], case["patient_id"], case["other"].admission_id, data["assessment_id"])


@pytest.mark.asyncio
async def test_author_field_cannot_bootstrap_care_and_revocation_is_owner_or_super_cas(client, db_session, case, auth_headers):
    data = await create(client, case, auth_headers)
    row = db_session.get(AINews2Assessment, data["assessment_id"])
    nurse = case["seed"]["nurse_user"]
    row.created_by = nurse.user_id
    db_session.commit()
    assert (await client.get(f"/api/ai/news2-assessments/{row.assessment_id}", headers=auth_headers(nurse.username), params=scope(case))).status_code == 403
    row.created_by = case["doctor"].user_id
    db_session.commit()
    endpoint = f"/api/ai/news2-assessments/{row.assessment_id}/revoke"
    req = {**scope(case), "expected_revision": 1, "reason": NOTE}
    assert (await client.post(endpoint, headers=auth_headers(case["seed"]["admin_user"].username), json=req)).status_code == 403
    assert (await client.post(endpoint, headers=auth_headers(case["doctor"].username), json={**req, "expected_revision": 2})).status_code == 409
    revoked = await client.post(endpoint, headers=auth_headers(case["doctor"].username), json=req)
    assert revoked.status_code == 200 and revoked.json()["data"]["content_hash"] == data["content_hash"] and revoked.json()["data"]["snapshot"] is None
    assert (await client.post(endpoint, headers=auth_headers(case["doctor"].username), json=req)).status_code == 409


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_actual_assessment_create_and_revoke(client, db_session, case, auth_headers, monkeypatch):
    data = await create(client, case, auth_headers)
    before = db_session.query(AINews2Assessment).count()
    monkeypatch.setattr(ai_news2, "audit", lambda db, actor, *args: db.add(AIAuditEvent(actor_id=actor, action=None, target="synthetic-invalid-audit", detail_json="{}")))
    headers = auth_headers(case["doctor"].username)
    failure = await client.post("/api/ai/news2-assessments", headers=headers, json=body(case))
    assert failure.status_code == 409 and db_session.query(AINews2Assessment).count() == before
    revoke = await client.post(f"/api/ai/news2-assessments/{data['assessment_id']}/revoke", headers=headers, json={**scope(case), "expected_revision": 1, "reason": NOTE})
    assert revoke.status_code == 409 and db_session.get(AINews2Assessment, data["assessment_id"]).status == "active"


def test_stale_super_object_cannot_create_fixed_profile_after_role_loss(db_session, case):
    actor = SimpleNamespace(user_id=case["seed"]["super_admin_user"].user_id, user_role="super_admin")
    db_session.query(User).filter_by(user_id=actor.user_id).update({"user_role": "admin"})
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        risk_rule_profiles.create_profile(db_session, actor, profile_body())
    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_assessment_list_filters_selected_window_before_pagination(client, db_session, case, auth_headers):
    first = await create(client, case, auth_headers)
    previous = case["window"]
    case["window"] = observation_windows.create_window(db_session, case["doctor"], values(case))
    db_session.commit()
    second = await create(client, case, auth_headers)
    headers = auth_headers(case["doctor"].username)
    listing = await client.get("/api/ai/news2-assessments", headers=headers, params={**scope(case), "window_id": previous.window_id, "page_size": 1})
    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 1 and listing.json()["data"]["items"][0]["assessment_id"] == first["assessment_id"]
    assert second["assessment_id"] != first["assessment_id"]
    assert (await client.get("/api/ai/news2-assessments", headers=headers, params={**scope(case), "window_id": "invalid"})).status_code == 422


@pytest.mark.asyncio
async def test_original_v1_window_is_bound_without_upgrading_its_hash_or_shape(client, db_session, case, auth_headers):
    fields = {**values(case), "window_id": "11111111-2222-4333-8444-555555555555", "created_by": case["doctor"].user_id, "created_at": case["now"]}
    frozen = observation_windows.build_snapshot(db_session, **fields, schema_version="inpatient_window_v1")
    window = AIObservationWindow(
        **fields, schema_version="inpatient_window_v1", snapshot_json=observation_windows.canonical_json(frozen), content_hash=frozen["content_hash"], status="active", revision=1, revoke_reason=""
    )
    db_session.add(window)
    db_session.commit()
    case["window"] = window
    before = window.snapshot_json
    data = await create(client, case, auth_headers)
    assert data["snapshot"]["window_binding"]["schema_version"] == "inpatient_window_v1" and data["window_content_hash"] == window.content_hash
    assert news2_values(data["specialist_source"])["total_score"] == 0
    assert window.snapshot_json == before and observation_windows.snapshot_current(db_session, case["doctor"], window) == frozen


@pytest.mark.asyncio
async def test_revoked_prior_care_blocks_current_request_but_not_historical_human_declaration(client, db_session, case, auth_headers):
    nurse = case["seed"]["nurse_user"]
    grant_row = grant(db_session, case, nurse)
    data = await create(client, case, auth_headers, role="nurse_user", pregnancy_status="unknown")
    grant_row.revoked = 1
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        news2_sources.authorize_assessment(db_session, nurse, case["patient_id"], case["admission_id"], data["assessment_id"])
    assert caught.value.status_code == 403
    assert news2_sources.authorize_assessment(db_session, case["seed"]["super_admin_user"], case["patient_id"], case["admission_id"], data["assessment_id"])["eligible"] is True


@pytest.mark.asyncio
async def test_profile_audit_failure_rolls_back_creation_publication_and_revocation(client, db_session, case, auth_headers, monkeypatch):
    headers = auth_headers(case["seed"]["super_admin_user"].username)
    before = db_session.query(AIRiskRuleProfile).count()

    def invalid_audit(db, actor, *args):
        db.add(AIAuditEvent(actor_id=actor, action=None, target="synthetic-profile-invalid-audit", detail_json="{}"))

    with monkeypatch.context() as patched:
        patched.setattr(ai_risk_rules, "audit", invalid_audit)
        failed_create = await client.post("/api/ai/admin/risk-rule-profiles", headers=headers, json=profile_body())
        assert failed_create.status_code == 409 and db_session.query(AIRiskRuleProfile).count() == before
        failed_revoke = await client.post(f"/api/ai/admin/risk-rule-profiles/{case['profile'].rule_profile_id}/revoke", headers=headers, json={"expected_revision": 2, "reason": NOTE})
        assert failed_revoke.status_code == 409 and risk_rule_profiles.profile_current(db_session, case["profile"].rule_profile_id)["status"] == "published"
    ai_risk_rules.revoke_profile(case["profile"].rule_profile_id, ai_risk_rules.ProfileRevoke(expected_revision=2, reason=NOTE), db_session, case["seed"]["super_admin_user"])
    draft = risk_rule_profiles.create_profile(db_session, case["seed"]["super_admin_user"], profile_body())
    db_session.commit()
    monkeypatch.setattr(ai_risk_rules, "audit", invalid_audit)
    failed_publish = await client.post(f"/api/ai/admin/risk-rule-profiles/{draft.rule_profile_id}/publish", headers=headers, json=publish_body())
    assert failed_publish.status_code == 409 and risk_rule_profiles.profile_detail(db_session, draft)["status"] == "draft"
    assert draft.published_key is None and draft.implementation_terms_confirmed == 0


def test_utf8_source_budget_rejects_oversized_frozen_body_before_window_recheck(db_session, case, monkeypatch):
    row = news2_sources.create_assessment(db_session, case["doctor"], body(case))
    db_session.commit()
    snapshot = json.loads(row.snapshot_json)
    snapshot["synthetic_boundary"] = "中" * 88000
    row.snapshot_json = news2_sources.canonical_json(snapshot)
    row.content_hash = news2_sources.hash_content(snapshot)
    db_session.commit()
    assert len(snapshot["synthetic_boundary"]) < news2_sources.MAX_SNAPSHOT_BYTES < len(row.snapshot_json.encode("utf-8"))

    def must_not_recheck(*args):
        raise AssertionError("Oversized UTF-8 body must fail before loading the original window")

    monkeypatch.setattr(observation_windows, "snapshot_current", must_not_recheck)
    with pytest.raises(HTTPException) as caught:
        news2_sources.assessment_current(db_session, row, allow_revoked=True, user=case["doctor"])
    assert caught.value.status_code == 409


@pytest.mark.asyncio
async def test_unsupported_source_roles_cannot_read_or_register(client, case, auth_headers):
    for role in ("cashier_user", "lab_tech_user", "patient_user"):
        headers = auth_headers(case["seed"][role].username)
        assert (await client.get("/api/ai/news2-assessments", params=scope(case), headers=headers)).status_code == 403
        assert (await client.post("/api/ai/news2-assessments", json=body(case), headers=headers)).status_code == 403
