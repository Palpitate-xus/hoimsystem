"""Synthetic real HTTP/ORM qSOFA sources: current retrospective review, never historical prediction."""

import copy
import datetime
import json

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app import inpatient_gcs
from app.ai import observation_windows, qsofa_sources, risk_rule_profiles
from app.ai.models import AIAuditEvent, AIPatientGrant, AIQsofaAssessment, AIRiskRuleProfile
from app.ai.qsofa_contract import QsofaSource, recipe_digest
from app.database import get_db
from app.inpatient_observations import PointPayload, canonical_json, frozen_content_hash, utc_text
from app.models import Doctor, InpatientGcsObservation
from app.routers import ai_qsofa, ai_risk_rules
from tests.test_ai_observation_windows import observation_case as observation_case
from tests.test_ai_observation_windows import point, values
from tests.test_inpatient_gcs import payload as gcs_payload

NOTE = "合成临床医生在现在回顾核实原床旁时刻的人群和感染声明，明确不是原截止时已经知道的信息或历史风险预测。"


@pytest.fixture
def case(db_session, observation_case, monkeypatch):
    case = observation_case
    case["admission_id"] = case["admission"].admission_id
    db_session.query(AIQsofaAssessment).delete()
    db_session.query(InpatientGcsObservation).delete()
    db_session.query(AIRiskRuleProfile).delete()
    db_session.query(AIPatientGrant).delete()
    for module in (qsofa_sources, ai_qsofa, risk_rule_profiles, ai_risk_rules):
        monkeypatch.setattr(module, "utcnow", lambda: case["now"])
    typed = PointPayload.model_validate(
        {
            "measurements": {"respiratory_rate": {"value": "22.00000000", "unit": "/min", "absent_reason": None}, "systolic_bp": {"value": "100.00000000", "unit": "mm[Hg]", "absent_reason": None}},
            "supplemental_oxygen": "unknown",
            "note": "原始点测备注不得外发给独立规则服务",
        }
    ).model_dump(mode="json")
    case["point"].payload_json = canonical_json(typed)
    case["point"].content_hash = frozen_content_hash(case["point"], typed)
    db_session.commit()
    # The original GCS was actually recorded by the old cutoff; the current
    # clinical review below is separately signed at server now.
    monkeypatch.setattr(inpatient_gcs, "utcnow", lambda: case["as_of"])
    source = inpatient_gcs.create_source(
        db_session,
        case["doctor"],
        {"patient_id": case["patient_id"], "admission_id": case["admission_id"], "observed_at": utc_text(case["start"] + datetime.timedelta(minutes=1)), "payload": gcs_payload(case)},
    )
    db_session.commit()
    monkeypatch.setattr(inpatient_gcs, "utcnow", lambda: case["now"])
    case["gcs"] = source
    profile = risk_rule_profiles.create_profile(
        db_session,
        case["seed"]["super_admin_user"],
        {
            "name": "Synthetic qSOFA retrospective source profile",
            "rule_id": "qsofa_sepsis3_2016",
            "expected_recipe_digest": recipe_digest(),
            "evidence_reference": "Synthetic independently reviewed original qSOFA recipe",
            "rationale": NOTE,
        },
    )
    db_session.commit()
    ai_risk_rules.publish_profile(
        profile.rule_profile_id,
        ai_risk_rules.ProfilePublish(
            expected_revision=1,
            expected_recipe_digest=recipe_digest(),
            implementation_terms_confirmed=True,
            review_note=NOTE,
            review_evidence_reference="Synthetic original definition and current guidance review",
        ),
        db_session,
        case["seed"]["super_admin_user"],
    )
    case["profile"] = profile
    case["window"] = observation_windows.create_window(db_session, case["doctor"], values(case))
    db_session.commit()
    return case


def body(case, **changes):
    return {
        "patient_id": case["patient_id"],
        "admission_id": case["admission_id"],
        "window_id": case["window"].window_id,
        "expected_window_hash": case["window"].content_hash,
        "point_id": case["point"].observation_id,
        "expected_point_hash": case["point"].content_hash,
        "rule_profile_id": case["profile"].rule_profile_id,
        "expected_rule_profile_hash": case["profile"].content_hash,
        "age_at_observation_years": 58,
        "age_basis_note": NOTE,
        "care_setting": "non_icu",
        "care_setting_basis_note": NOTE,
        "infection_status": "suspected",
        "infection_basis_note": NOTE,
        "gcs_observation": {"gcs_observation_id": case["gcs"].gcs_observation_id, "expected_content_hash": case["gcs"].content_hash},
        "gcs_interpretability": "confirmed",
        "gcs_review_note": NOTE,
        **changes,
    }


def scope(case):
    return {"patient_id": case["patient_id"], "admission_id": case["admission_id"]}


def create(db, case, **changes):
    row = qsofa_sources.create_assessment(db, case["doctor"], body(case, **changes))
    db.commit()
    return row


def extra_gcs(db, case, monkeypatch, *, recorded=None, components=None, anchor=None, observed=None):
    monkeypatch.setattr(inpatient_gcs, "utcnow", lambda: recorded or case["as_of"])
    data = gcs_payload(case)
    if components is not None:
        data["components"] = components
    if anchor is not None:
        data["anchor_point"] = {"observation_id": anchor.observation_id, "expected_content_hash": anchor.content_hash}
    row = inpatient_gcs.create_source(db, case["doctor"], {**scope(case), "observed_at": utc_text(observed or case["start"] + datetime.timedelta(minutes=2)), "payload": data})
    db.commit()
    monkeypatch.setattr(inpatient_gcs, "utcnow", lambda: case["now"])
    return row


@pytest_asyncio.fixture
async def client(db_session):
    app = FastAPI()
    app.include_router(ai_qsofa.router, prefix="/api")
    app.include_router(ai_risk_rules.router, prefix="/api")

    def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic-qsofa-source") as client:
        yield client


@pytest.mark.asyncio
async def test_actual_source_api_freezes_exact_originals_current_review_and_published_independent_recipe(client, db_session, case, auth_headers):
    before = (case["point"].payload_json, case["gcs"].payload_json, case["profile"].payload_json)
    response = await client.post("/api/ai/qsofa-assessments", headers=auth_headers(case["doctor"].username), json=body(case))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    source = QsofaSource.model_validate(data["specialist_source"])
    row = db_session.get(AIQsofaAssessment, data["assessment_id"])
    assert data["eligible"] and data["freshness"] == {"state": "current"} and data["can_revoke"] is True
    assert source.measurements["respiratory_rate"].value == "22.00000000" and source.measurements["systolic_bp"].value == "100.00000000"
    assert source.review_mode == "current_retrospective_review" and source.historical_prediction is False
    assert source.clinical_statements_recorded_at == source.evaluation_at == utc_text(case["now"]) > source.as_of
    assert source.clinical_scope_applies_to == source.observed_at == utc_text(case["start"])
    assert source.gcs.observed_at != source.observed_at and source.gcs.recorded_at == source.as_of
    assert data["snapshot"]["point"]["governance_hash"] == source.point_governance_hash
    assert data["snapshot"]["gcs_observation"]["patient_id"] == data["patient_id"] == case["patient_id"]
    assert data["snapshot"]["author_qualification"]["doctor_id"] == case["seed"]["doctor"].doctor_id
    assert row.evaluation_at == row.created_at == case["now"] and row.snapshot_json == canonical_json(data["snapshot"])
    assert (case["point"].payload_json, case["gcs"].payload_json, case["profile"].payload_json) == before
    outbound = canonical_json(data["specialist_source"])
    assert NOTE not in outbound and "patient_id" not in outbound and "admission_id" not in outbound and "note" not in outbound
    assert db_session.query(AIAuditEvent).filter_by(action="qsofa_assessment.create", target=row.assessment_id).count() == 1
    listed = await client.get("/api/ai/qsofa-assessments", headers=auth_headers(case["doctor"].username), params={**scope(case), "window_id": row.window_id})
    assert listed.json()["data"]["items"] == [data]
    current = await client.get(f"/api/ai/qsofa-assessments/{row.assessment_id}", headers=auth_headers(case["doctor"].username), params=scope(case))
    assert current.json()["data"] == data


@pytest.mark.asyncio
async def test_candidates_expose_only_explicit_cutoff_originals_and_clinical_signing_rights(client, db_session, case, auth_headers, monkeypatch):
    late = extra_gcs(db_session, case, monkeypatch, recorded=case["now"])
    response = await client.get("/api/ai/qsofa-assessments/candidates", headers=auth_headers(case["doctor"].username), params={**scope(case), "window_id": case["window"].window_id})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["can_sign_clinical"] is True and [item["gcs_observation_id"] for item in data["gcs_observations"]] == [case["gcs"].gcs_observation_id]
    assert late.gcs_observation_id not in canonical_json(data) and "future" not in canonical_json(data)
    assert [item["rule_id"] for item in data["rule_profiles"]] == ["qsofa_sepsis3_2016"]
    admin = await client.get("/api/ai/qsofa-assessments/candidates", headers=auth_headers(case["seed"]["super_admin_user"].username), params={**scope(case), "window_id": case["window"].window_id})
    assert admin.status_code == 200 and admin.json()["data"]["can_sign_clinical"] is False


@pytest.mark.parametrize("role", ["nurse_user", "admin_user", "super_admin_user"])
def test_new_review_requires_actual_doctor_and_original_care_even_when_all_scope_declarations_unknown(db_session, case, role):
    with pytest.raises(HTTPException) as error:
        qsofa_sources.create_assessment(db_session, case["seed"][role], body(case, age_at_observation_years=None, care_setting="unknown", infection_status="unknown"))
    assert error.value.status_code == 403
    assert db_session.query(AIQsofaAssessment).count() == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"age_at_observation_years": True},
        {"age_at_observation_years": "58"},
        {"age_at_observation_years": -1},
        {"age_at_observation_years": 131},
        {"care_setting": "ward"},
        {"infection_status": "confirmed_sepsis"},
        {"care_setting_basis_note": " " * 25},
        {"age_basis_note": "short"},
        {"gcs_observation": None},
        {"gcs_review_note": None},
        {"historical_prediction": False},
        {"evaluation_at": "2000-01-01T00:00:00Z"},
        {"pregnancy_status": "unknown"},
    ],
)
def test_clinical_schema_rejects_coercion_backdating_unsupported_scope_and_missing_review(case, changes):
    with pytest.raises(ValidationError):
        qsofa_sources.AssessmentCreate.model_validate(body(case, **changes))


def test_unknown_age_and_no_gcs_are_retained_without_imputation(db_session, case):
    row = create(db_session, case, age_at_observation_years=None, gcs_observation=None, gcs_interpretability="unknown", gcs_review_note=None)
    source = qsofa_sources.assessment_current(db_session, row, user=case["doctor"])["specialist_source"]
    assert source["age_at_observation_years"] is None and source["gcs"] is None and source["gcs_interpretability"] == "unknown"
    assert source["gcs_review_evidence_hash"] is None and source["measurements"]["respiratory_rate"]["value"] == "22.00000000"


@pytest.mark.parametrize("mode", ["late", "other_anchor", "unanchored", "outside_window"])
def test_gcs_requires_explicit_same_exam_original_anchor_and_cutoff_not_nearest(db_session, case, monkeypatch, mode):
    if mode == "late":
        row = extra_gcs(db_session, case, monkeypatch, recorded=case["now"])
    elif mode == "other_anchor":
        other = point(db_session, case, observed=case["start"] + datetime.timedelta(minutes=3))
        db_session.commit()
        row = extra_gcs(db_session, case, monkeypatch, anchor=other)
    elif mode == "unanchored":
        monkeypatch.setattr(inpatient_gcs, "utcnow", lambda: case["as_of"])
        row = inpatient_gcs.create_source(
            db_session, case["doctor"], {**scope(case), "observed_at": utc_text(case["start"]), "payload": gcs_payload(case, anchor_point=None, same_exam_confirmed=False, same_exam_basis_note=None)}
        )
        db_session.commit()
        monkeypatch.setattr(inpatient_gcs, "utcnow", lambda: case["now"])
    else:
        row = extra_gcs(db_session, case, monkeypatch, observed=case["start"] - datetime.timedelta(microseconds=1))
    with pytest.raises(HTTPException) as error:
        create(db_session, case, gcs_observation={"gcs_observation_id": row.gcs_observation_id, "expected_content_hash": row.content_hash})
    assert error.value.status_code == 409


def test_pre_cutoff_different_same_anchor_gcs_components_are_explicit_conflict_but_identical_duplicates_are_not(db_session, case, monkeypatch):
    duplicate = extra_gcs(db_session, case, monkeypatch)
    row = create(db_session, case)
    data = qsofa_sources.assessment_current(db_session, row, user=case["doctor"])
    assert len(data["snapshot"]["gcs_group"]) == 2 and data["specialist_source"]["gcs"]["conflict"] is False
    components = copy.deepcopy(gcs_payload(case)["components"])
    components["eye"]["score"] = 3
    other = extra_gcs(db_session, case, monkeypatch, components=components)
    with pytest.raises(HTTPException):
        qsofa_sources.assessment_current(db_session, row, user=case["doctor"])
    fresh = create(db_session, case)
    current = qsofa_sources.assessment_current(db_session, fresh, user=case["doctor"])
    assert current["specialist_source"]["gcs"]["conflict"] is True
    assert {item["gcs_observation_id"] for item in current["snapshot"]["gcs_group"]} == {case["gcs"].gcs_observation_id, duplicate.gcs_observation_id, other.gcs_observation_id}


def test_after_cutoff_gcs_member_is_not_a_dependency_and_does_not_leak_existence(db_session, case, monkeypatch):
    row = create(db_session, case)
    before = qsofa_sources.assessment_current(db_session, row, user=case["doctor"])
    other = extra_gcs(db_session, case, monkeypatch, recorded=case["now"])
    after = qsofa_sources.assessment_current(db_session, row, user=case["doctor"])
    assert before == after and other.gcs_observation_id not in canonical_json(after)


@pytest.mark.parametrize("kind", ["selected_gcs_note", "unselected_gcs_revoke", "point_note", "profile_revoke", "doctor_identity", "assessment_revoke"])
def test_original_content_governance_and_clinical_signer_changes_invalidate_ordinary_use_preserve_super_frozen_audit(db_session, case, monkeypatch, kind):
    other = extra_gcs(db_session, case, monkeypatch)
    row = create(db_session, case)
    frozen = row.snapshot_json
    if kind == "selected_gcs_note":
        raw = json.loads(case["gcs"].payload_json)
        raw["note"] += " changed private text"
        case["gcs"].payload_json = canonical_json(raw)
    elif kind == "unselected_gcs_revoke":
        other.status, other.revision, other.revoked_at, other.revoked_by, other.revoke_reason = "revoked", 2, case["now"], case["doctor"].user_id, NOTE
    elif kind == "point_note":
        raw = json.loads(case["point"].payload_json)
        raw["note"] += " changed private text"
        case["point"].payload_json = canonical_json(raw)
    elif kind == "profile_revoke":
        ai_risk_rules.revoke_profile(case["profile"].rule_profile_id, ai_risk_rules.ProfileRevoke(expected_revision=2, reason=NOTE), db_session, case["seed"]["super_admin_user"])
    elif kind == "doctor_identity":
        signed_id = json.loads(frozen)["author_qualification"]["doctor_id"]
        db_session.get(Doctor, signed_id).user_id = case["seed"]["admin_user"].user_id
    else:
        row.status, row.revision, row.revoked_at, row.revoked_by, row.revoke_reason = "revoked", 2, case["now"], case["doctor"].user_id, NOTE
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        qsofa_sources.assessment_current(db_session, row, user=case["seed"]["super_admin_user"])
    assert error.value.status_code == 409
    ordinary = ai_qsofa.detail(db_session, case["seed"]["admin_user"], row)
    super_audit = ai_qsofa.detail(db_session, case["seed"]["super_admin_user"], row)
    assert ordinary["snapshot"] is None and ordinary["specialist_source"] is None and not ordinary["eligible"]
    assert super_audit["snapshot"] == json.loads(frozen) and super_audit["specialist_source"] is None and not super_audit["eligible"]
    assert row.snapshot_json == frozen


def test_later_author_role_change_preserves_original_qualified_signature_for_other_current_caregiver(db_session, case):
    row = create(db_session, case)
    case["doctor"].user_role = "nurse"
    db_session.commit()
    current = qsofa_sources.assessment_current(db_session, row, user=case["seed"]["super_admin_user"])
    assert current["eligible"] and current["snapshot"]["author_qualification"]["role_at_creation"] == "doctor"
    case["doctor"].user_role = "doctor"
    db_session.commit()


@pytest.mark.asyncio
async def test_current_care_lost_is_not_restored_by_assessment_authorship_and_super_history_survives(client, db_session, case, auth_headers):
    row = create(db_session, case)
    case["admission"].doctor_id = None
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        qsofa_sources.authorize_assessment(db_session, case["doctor"], case["patient_id"], case["admission_id"], row.assessment_id)
    assert error.value.status_code == 403
    response = await client.get(f"/api/ai/qsofa-assessments/{row.assessment_id}", headers=auth_headers(case["doctor"].username), params=scope(case))
    assert response.status_code == 403
    super_audit = await client.get(f"/api/ai/admin/qsofa-assessments/{row.assessment_id}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert super_audit.status_code == 200 and super_audit.json()["data"]["snapshot"]["author_qualification"]["clinical_review_signed"] is True


@pytest.mark.asyncio
async def test_assessment_creation_and_revoke_roll_back_on_actual_audit_failure(client, db_session, case, auth_headers, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic qSOFA audit failure")

    monkeypatch.setattr(ai_qsofa, "audit", fail)
    with pytest.raises(RuntimeError, match="audit failure"):
        await client.post("/api/ai/qsofa-assessments", headers=auth_headers(case["doctor"].username), json=body(case))
    assert db_session.query(AIQsofaAssessment).count() == 0
    row = create(db_session, case)
    with pytest.raises(RuntimeError, match="audit failure"):
        await client.post(f"/api/ai/qsofa-assessments/{row.assessment_id}/revoke", headers=auth_headers(case["doctor"].username), json={**scope(case), "expected_revision": 1, "reason": NOTE})
    db_session.refresh(row)
    assert row.status == "active" and row.revision == 1


@pytest.mark.parametrize("mutation", ["metadata_bool", "gcs_bool", "gcs_note", "point_bool", "review_backdate", "foreign_rule"])
def test_recomputed_outer_hash_cannot_hide_changed_frozen_original_types_notes_scope_or_review_clock(db_session, case, mutation):
    row = create(db_session, case)
    snapshot = json.loads(row.snapshot_json)
    if mutation == "metadata_bool":
        snapshot["created_by"] = True
    elif mutation == "gcs_bool":
        snapshot["gcs_observation"]["payload"]["same_exam_confirmed"] = 1
        for member in snapshot["gcs_group"]:
            if member["gcs_observation_id"] == case["gcs"].gcs_observation_id:
                member["payload"]["same_exam_confirmed"] = 1
    elif mutation == "gcs_note":
        snapshot["gcs_observation"]["payload"]["same_exam_basis_note"] += "已改变"
    elif mutation == "point_bool":
        snapshot["point"]["revision"] = True
    elif mutation == "review_backdate":
        snapshot["clinical_statements_recorded_at"] = snapshot["window_binding"]["as_of"]
    else:
        snapshot["rule_profile"]["rule_id"] = "kdigo_aki_2012"
    row.snapshot_json = canonical_json(snapshot)
    row.content_hash = qsofa_sources.hash_content(snapshot)
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        qsofa_sources.assessment_current(db_session, row, user=case["doctor"])
    assert error.value.status_code == 409


def test_three_actual_fixed_rule_profiles_publish_with_independent_identity_and_withdrawal(db_session, case):
    options = risk_rule_profiles.fixed_options()
    assert [item["rule_id"] for item in options] == ["news2_2017", "kdigo_aki_2012", "qsofa_sepsis3_2016"]
    expected = options[2]
    assert expected["recipe_digest"] == recipe_digest()
    assert expected["input_policy"] == {key: expected["recipe"][key] for key in ("source_policy", "input_precision", "review", "population", "partial_policy")}
    others = []
    for option in options[:2]:
        profile = risk_rule_profiles.create_profile(
            db_session,
            case["seed"]["super_admin_user"],
            {
                "name": "Synthetic independent " + option["rule_id"],
                "rule_id": option["rule_id"],
                "expected_recipe_digest": option["recipe_digest"],
                "evidence_reference": "Synthetic independent fixed recipe review",
                "rationale": NOTE,
            },
        )
        db_session.commit()
        ai_risk_rules.publish_profile(
            profile.rule_profile_id,
            ai_risk_rules.ProfilePublish(
                expected_revision=1,
                expected_recipe_digest=option["recipe_digest"],
                implementation_terms_confirmed=True,
                review_note=NOTE,
                review_evidence_reference="Synthetic actual independent software implementation",
            ),
            db_session,
            case["seed"]["super_admin_user"],
        )
        others.append(profile)
    assert len({row.published_key for row in [case["profile"], *others]}) == 3
    ai_risk_rules.revoke_profile(case["profile"].rule_profile_id, ai_risk_rules.ProfileRevoke(expected_revision=2, reason=NOTE), db_session, case["seed"]["super_admin_user"])
    assert all(risk_rule_profiles.profile_current(db_session, row.rule_profile_id)["eligible"] for row in others)


@pytest.mark.parametrize("relevant", [True, False])
def test_same_clock_conflicts_only_block_dependent_rr_or_sbp_and_keep_other_private_originals(db_session, case, relevant):
    measurements = (
        {"respiratory_rate": {"value": "21.99999999", "unit": "/min", "absent_reason": None}} if relevant else {"temperature": {"value": "39.12345678", "unit": "Cel", "absent_reason": None}}
    )
    point(db_session, case, observed=case["start"], payload={"measurements": measurements, "supplemental_oxygen": "yes", "note": "不同的原始氧疗/体温不阻断qSOFA呼吸或血压分项"})
    db_session.commit()
    case["window"] = observation_windows.create_window(db_session, case["doctor"], values(case))
    db_session.commit()
    row = create(db_session, case)
    source = qsofa_sources.assessment_current(db_session, row, user=case["doctor"])["specialist_source"]
    assert source["point_conflicts"] == (["respiratory_rate"] if relevant else [])
    assert source["measurements"]["systolic_bp"]["value"] == "100.00000000" and source["gcs"]["components"]["eye"]["score"] == 4


def test_complete_immutable_same_exam_group_utf8_capacity_rejects_before_source_or_audit_insertion_without_truncation(db_session, case, monkeypatch):
    monkeypatch.setattr(inpatient_gcs, "utcnow", lambda: case["as_of"])
    selected_note = case["gcs"].payload_json
    for _ in range(40):
        data = gcs_payload(case, note="合" * 1000, same_exam_basis_note="同" * 1000)
        row = inpatient_gcs.create_source(db_session, case["doctor"], {**scope(case), "observed_at": utc_text(case["start"] + datetime.timedelta(minutes=2)), "payload": data})
        db_session.add(row)
        db_session.flush()
    db_session.commit()
    monkeypatch.setattr(inpatient_gcs, "utcnow", lambda: case["now"])
    group = qsofa_sources.gcs_group(db_session, case["point"].observation_id, case["as_of"])
    assert len(group) == 41 and len(canonical_json(group).encode("utf-8")) > qsofa_sources.MAX_SNAPSHOT_BYTES
    before = (db_session.query(AIQsofaAssessment).count(), db_session.query(AIAuditEvent).count(), db_session.query(InpatientGcsObservation).count())
    with pytest.raises(HTTPException) as error:
        create(db_session, case)
    assert error.value.status_code == 422 and "262144" in str(error.value.detail)
    assert (db_session.query(AIQsofaAssessment).count(), db_session.query(AIAuditEvent).count(), db_session.query(InpatientGcsObservation).count()) == before
    assert case["gcs"].payload_json == selected_note and not db_session.new


def test_super_can_sign_only_with_actual_doctor_entity_and_original_clinical_care(db_session, case):
    supervisor = case["seed"]["super_admin_user"]
    doctor = Doctor(user_id=supervisor.user_id, name="Synthetic actual clinical reviewer", department_id=case["seed"]["department"].department_id)
    db_session.add(doctor)
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        qsofa_sources.create_assessment(db_session, supervisor, body(case))
    assert error.value.status_code == 403
    case["admission"].doctor_id = doctor.doctor_id
    db_session.commit()
    row = qsofa_sources.create_assessment(db_session, supervisor, body(case))
    db_session.commit()
    current = qsofa_sources.assessment_current(db_session, row, user=supervisor)
    assert current["eligible"] and current["snapshot"]["author_qualification"]["doctor_id"] == doctor.doctor_id
    assert current["snapshot"]["author_qualification"]["role_at_creation"] == "super_admin"
