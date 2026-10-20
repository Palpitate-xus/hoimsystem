"""Synthetic real HTTP/ORM explicit AKI sources; no external inference or patient data."""

import copy
import datetime
import json

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException

from app.ai import aki_sources, observation_windows, risk_rule_profiles
from app.ai.aki_contract import AkiSource, recipe_digest
from app.ai.aki_model import aki_values
from app.ai.models import AIAKIAssessment, AIAuditEvent, AINews2Assessment, AIPatientGrant, AIRiskRuleProfile
from app.database import get_db
from app.models import Doctor, InpatientUrineInterval, User
from app.routers import ai_aki, ai_risk_rules
from tests.test_ai_observation_laboratory import laboratory_case as laboratory_case
from tests.test_ai_observation_windows import observation_case as observation_case
from tests.test_ai_observation_windows import point, urine, values

NOTE = "合成核对原住院、人工年龄、真实血清肌酐角色和体重适用性，仅为工程回归而非临床验证。"


@pytest.fixture
def case(db_session, laboratory_case, monkeypatch):
    case = laboratory_case["case"]
    db_session.query(AIAKIAssessment).delete()
    db_session.query(AINews2Assessment).delete()
    db_session.query(AIRiskRuleProfile).delete()
    db_session.query(AIPatientGrant).filter_by(patient_id=case["patient_id"], category="inpatient").delete()
    for module in (aki_sources, ai_aki, risk_rule_profiles, ai_risk_rules):
        monkeypatch.setattr(module, "utcnow", lambda: case["now"])
    case["start"] = case["now"] - datetime.timedelta(hours=49)
    db_session.query(InpatientUrineInterval).delete()
    case["weight"] = point(
        db_session,
        case,
        observed=case["start"],
        payload={"measurements": {"body_weight": {"value": "70.00", "unit": "kg", "absent_reason": None}}, "supplemental_oxygen": "unknown", "note": "原体重中文备注保留，不是理想体重或自动选择。"},
    )
    case["urines"] = [
        urine(db_session, case, start=case["now"] - datetime.timedelta(hours=13), end=case["now"] - datetime.timedelta(hours=7), payload=urine_payload("100.00")),
        urine(db_session, case, start=case["now"] - datetime.timedelta(hours=7), end=case["end"], payload=urine_payload("100.00")),
    ]
    db_session.commit()
    make = laboratory_case["make"]
    case["make"] = make
    case["baseline"] = make(numeric="100.00", collected=case["start"])
    case["comparison"] = make(numeric="180.00", collected=case["now"] - datetime.timedelta(hours=2))
    case["index"] = make(numeric="200.00", collected=case["end"], report_text="合成父报告完整正文不应复制进入AKI来源。")
    profile = risk_rule_profiles.create_profile(
        db_session,
        case["seed"]["super_admin_user"],
        {
            "name": "Synthetic actual KDIGO source profile",
            "rule_id": "kdigo_aki_2012",
            "expected_recipe_digest": recipe_digest(),
            "evidence_reference": "Synthetic fixed original algorithm implementation review",
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
            review_evidence_reference="Synthetic only original recipe and implementation terms",
        ),
        db_session,
        case["seed"]["super_admin_user"],
    )
    case["profile"] = profile
    case["window"] = observation_windows.create_window(db_session, case["doctor"], values(case))
    db_session.commit()
    return case


def urine_payload(volume="0", **changes):
    return {
        "volume_ml": volume,
        "absent_reason": None if volume is not None else "not_performed",
        "collection_completeness": "complete",
        "patient_total": True,
        "collection_method": "Synthetic measured complete patient total",
        "note": "完整原尿量区间，不裁剪分摊。",
        **changes,
    }


def reference(member):
    row = member["source"]
    return {"lab_source_id": row.lab_source_id, "expected_content_hash": row.content_hash}


def scope(case):
    return {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id}


def body(case, **changes):
    return {
        **scope(case),
        "window_id": case["window"].window_id,
        "expected_window_hash": case["window"].content_hash,
        "rule_profile_id": case["profile"].rule_profile_id,
        "expected_rule_profile_hash": case["profile"].content_hash,
        "evaluation_at": observation_windows.iso(case["end"]),
        "age_at_evaluation_years": 40,
        "age_basis_note": NOTE,
        "index_creatinine": reference(case["index"]),
        "comparison_48h": reference(case["comparison"]),
        "baseline_creatinine": reference(case["baseline"]),
        "baseline_mode": "observed_within_7d",
        "serum_creatinine_confirmed": True,
        "creatinine_review_note": NOTE,
        "baseline_rise_within_7d_confirmed": None,
        "baseline_review_note": None,
        "weight_point": {"observation_id": case["weight"].observation_id, "expected_content_hash": case["weight"].content_hash},
        "weight_applicability_confirmed": True,
        "weight_basis_note": NOTE,
        "urine_intervals": [{"interval_id": row.interval_id, "expected_content_hash": row.content_hash} for row in case["urines"]],
        "rrt_status": "unknown",
        "rrt_started_at": None,
        "rrt_acute_aki_confirmed": None,
        "rrt_basis_note": None,
        **changes,
    }


def rewindow(db, case):
    case["window"] = observation_windows.create_window(db, case["doctor"], values(case))
    db.commit()


def grant(db, case, user):
    row = AIPatientGrant(
        user_id=user.user_id,
        patient_id=case["patient_id"],
        category="inpatient",
        reason=NOTE,
        created_by=case["seed"]["super_admin_user"].user_id,
        expires_at=case["now"] + datetime.timedelta(days=1),
        revoked=0,
    )
    db.add(row)
    db.commit()
    return row


@pytest_asyncio.fixture
async def client(db_session):
    app = FastAPI()
    app.include_router(ai_aki.router, prefix="/api")
    app.include_router(ai_risk_rules.router, prefix="/api")

    def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as result:
        yield result


async def post(client, case, auth_headers, role="doctor_user", **changes):
    return await client.post("/api/ai/aki-assessments", json=body(case, **changes), headers=auth_headers(case["seed"][role].username))


@pytest.mark.asyncio
async def test_real_source_binds_raw_decimal_roles_original_times_and_minimized_projection(client, case, db_session, auth_headers):
    response = await post(client, case, auth_headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    row = db_session.get(AIAKIAssessment, data["assessment_id"])
    assert data["eligible"] is True and data["specialist_source"] == AkiSource.model_validate(data["specialist_source"]).model_dump(mode="json")
    source, frozen = data["specialist_source"], data["snapshot"]
    assert source["index_creatinine"]["value"] == json.loads(case["index"]["source"].snapshot_json)["original"]["observation"]["value_num"]
    assert source["baseline_creatinine"]["value"] == json.loads(case["baseline"]["source"].snapshot_json)["original"]["observation"]["value_num"]
    assert source["weight"]["value"] == "70.00" and source["urine_intervals"][0]["volume_ml"] == "100.00"
    assert source["urine_coverage_issues"] == [] and source["index_creatinine"]["conflict"] is False
    assert all(value not in json.dumps(source, ensure_ascii=False) for value in ("patient_id", "admission_id", NOTE, "原体重中文备注", "合成父报告完整正文"))
    assert "result" not in frozen["index_creatinine"]["snapshot"]["original"]["report"]
    assert frozen["index_creatinine"]["assessment_projection"] == "aki_lab_projection_v1"
    assert frozen["attestation"]["age_basis_note"] == NOTE and "原体重中文备注" in frozen["weight_point"]["payload"]["note"]
    assert frozen["index_creatinine"]["snapshot"]["original"]["observation"]["time_basis"] == "unknown"
    assert row.content_hash == aki_sources.hash_content(frozen)
    assert row.created_at == case["now"] and row.evaluation_at == case["end"]
    assert (
        aki_sources.authorize_assessment(db_session, case["doctor"], case["patient_id"], case["admission"].admission_id, row.assessment_id, window_id=case["window"].window_id)["specialist_source"]
        == source
    )
    result = aki_values(source)
    assert result["minimum_stage"] == 2 and result["stage_is_lower_bound"] is True and result["aki_excluded"] is False
    event = db_session.query(AIAuditEvent).filter_by(action="aki_assessment.create", target=row.assessment_id).one()
    assert json.loads(event.detail_json)["content_hash"] == row.content_hash and NOTE not in event.detail_json


@pytest.mark.asyncio
async def test_candidates_only_current_scope_and_explicit_authorized_baseline_directory(client, case, auth_headers):
    headers = auth_headers(case["doctor"].username)
    response = await client.get("/api/ai/aki-assessments/candidates", params={**scope(case), "window_id": case["window"].window_id}, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["window"]["content_hash"] == case["window"].content_hash and data["can_sign_clinical"] is True
    assert {item["lab_source_id"] for item in data["creatinine_sources"]} == {case[key]["source"].lab_source_id for key in ("index", "comparison", "baseline")}
    assert data["baseline_admission_id"] == case["admission"].admission_id and data["baseline_total"] == 3
    assert len(data["weight_points"]) == 1 and len(data["urine_intervals"]) == 2
    assert {item["rule_id"] for item in data["rule_profiles"]} == {"kdigo_aki_2012"}


@pytest.mark.parametrize("role", ["nurse_user", "admin_user", "super_admin_user"])
@pytest.mark.asyncio
async def test_screatinine_and_nonunknown_rrt_require_actual_doctor_original_care(role, client, case, db_session, auth_headers):
    if role == "nurse_user":
        grant(db_session, case, case["seed"][role])
    before = db_session.query(AIAKIAssessment).count(), db_session.query(AIAuditEvent).count()
    response = await post(client, case, auth_headers, role=role)
    assert response.status_code == 403
    assert (db_session.query(AIAKIAssessment).count(), db_session.query(AIAuditEvent).count()) == before


@pytest.mark.asyncio
async def test_nurse_can_create_urine_only_with_explicit_unknown_rrt_and_reuse_doctor_source(client, case, db_session, auth_headers):
    nurse = case["seed"]["nurse_user"]
    grant(db_session, case, nurse)
    response = await post(
        client,
        case,
        auth_headers,
        role="nurse_user",
        index_creatinine=None,
        comparison_48h=None,
        baseline_creatinine=None,
        baseline_mode="unknown",
        serum_creatinine_confirmed=False,
        creatinine_review_note=None,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["snapshot"]["author_qualification"]["doctor_id"] is None and data["specialist_source"]["rrt"]["status"] == "unknown"
    result = aki_values(data["specialist_source"])
    assert result["minimum_stage"] == 2 and result["detection"] == "met" and result["calculation_status"] == "insufficient_data"
    doctor = await post(client, case, auth_headers)
    assert doctor.status_code == 200
    assert aki_sources.authorize_assessment(db_session, nurse, case["patient_id"], case["admission"].admission_id, doctor.json()["data"]["assessment_id"])["eligible"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("age_at_evaluation_years", True),
        ("age_at_evaluation_years", "40"),
        ("age_at_evaluation_years", None),
        ("serum_creatinine_confirmed", 1),
        ("weight_applicability_confirmed", "true"),
        ("extra_values", {"creatinine": "900"}),
        ("age_basis_note", " " * 30),
        ("evaluation_at", "2026-10-20T12:00:00"),
        ("evaluation_at", "0001-01-01T00:00:00+23:59"),
    ],
)
@pytest.mark.asyncio
async def test_strict_declarations_reject_coercion_unknown_keys_and_invalid_clocks(field, value, client, case, auth_headers):
    response = await post(client, case, auth_headers, **{field: value})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_explicit_presumed_baseline_preserves_other_original_admission_and_needs_its_authorization(client, case, db_session, auth_headers):
    older = case["make"](numeric="50.00", collected=case["now"] - datetime.timedelta(days=200), admission=case["other"])
    response = await post(client, case, auth_headers, baseline_creatinine=reference(older), baseline_mode="presumed_within_7d", baseline_rise_within_7d_confirmed=True, baseline_review_note=NOTE)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["snapshot"]["baseline_creatinine"]["admission_id"] == case["other"].admission_id
    assert data["specialist_source"]["baseline_creatinine"]["collected_at_utc"] == observation_windows.iso(case["now"] - datetime.timedelta(days=200))
    assert aki_values(data["specialist_source"])["minimum_stage"] == 3
    case["other"].doctor_id = case["seed"]["director_doctor"].doctor_id
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        aki_sources.authorize_assessment(db_session, case["doctor"], case["patient_id"], case["admission"].admission_id, data["assessment_id"])
    assert caught.value.status_code == 409
    denied = await post(client, case, auth_headers, baseline_creatinine=reference(older), baseline_mode="presumed_within_7d", baseline_rise_within_7d_confirmed=True, baseline_review_note=NOTE)
    assert denied.status_code == 403


@pytest.mark.parametrize("mode", ["unknown", "observed_within_7d"])
@pytest.mark.asyncio
async def test_unconfirmed_external_baseline_never_silently_moved_into_current_window(mode, client, case, auth_headers):
    older = case["make"](numeric="50", collected=case["now"] - datetime.timedelta(days=20), admission=case["other"])
    response = await post(client, case, auth_headers, baseline_creatinine=reference(older), baseline_mode=mode)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_baseline_registered_after_cutoff_rejected_even_with_old_sampling_time(client, case, auth_headers):
    late = case["make"](numeric="50", collected=case["now"] - datetime.timedelta(days=20), admission=case["other"], registered=case["as_of"] + datetime.timedelta(microseconds=1))
    response = await post(client, case, auth_headers, baseline_creatinine=reference(late), baseline_mode="presumed_within_7d", baseline_rise_within_7d_confirmed=True, baseline_review_note=NOTE)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_unselected_overlap_blocks_urine_axis_without_hiding_creatinine_positive(client, case, db_session, auth_headers):
    urine(db_session, case, start=case["urines"][0].start_at, end=case["urines"][0].end_at, payload=urine_payload(None, collection_completeness="unknown", patient_total=None))
    db_session.commit()
    rewindow(db_session, case)
    response = await post(client, case, auth_headers)
    assert response.status_code == 200, response.text
    source = response.json()["data"]["specialist_source"]
    assert {"unselected_active_interval", "overlap", "partial_collection", "unknown_volume", "not_patient_total"} <= set(source["urine_coverage_issues"])
    result = aki_values(source)
    assert result["minimum_stage"] == 2 and result["detection"] == "met"
    assert all(item["status"] == "unknown" for item in result["criteria"] if item["key"].startswith("urine_") or item["key"] == "anuria_12h")


@pytest.mark.asyncio
async def test_same_time_original_identity_creatinine_conflict_keeps_source_but_blocks_pair(client, case, db_session, auth_headers):
    case["make"](numeric="999", collected=case["end"])
    rewindow(db_session, case)
    response = await post(client, case, auth_headers, urine_intervals=[])
    assert response.status_code == 200, response.text
    source = response.json()["data"]["specialist_source"]
    assert source["index_creatinine"]["conflict"] is True
    result = aki_values(source)
    assert result["minimum_stage"] is None and result["detection"] == "insufficient_data"


@pytest.mark.asyncio
async def test_same_analyte_different_original_identity_not_implicitly_compared(client, case, db_session, auth_headers):
    other = case["make"](numeric="1", collected=case["start"], method="another-original-method")
    rewindow(db_session, case)
    response = await post(client, case, auth_headers, baseline_creatinine=reference(other), urine_intervals=[])
    assert response.status_code == 200, response.text
    source = response.json()["data"]["specialist_source"]
    assert source["index_creatinine"]["identity_hash"] != source["baseline_creatinine"]["identity_hash"]
    ratio = next(item for item in aki_values(source)["criteria"] if item["key"] == "creatinine_ratio_7d")
    assert ratio["status"] == "unknown"


@pytest.mark.parametrize("change", ["profile", "window", "lab", "weight", "urine", "recipe"])
@pytest.mark.asyncio
async def test_revalidated_governance_stops_current_source_and_preserves_super_frozen_audit(change, client, case, db_session, auth_headers, monkeypatch):
    response = await post(client, case, auth_headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    if change == "profile":
        ai_risk_rules.revoke_profile(case["profile"].rule_profile_id, ai_risk_rules.ProfileRevoke(expected_revision=2, reason=NOTE), db_session, case["seed"]["super_admin_user"])
    elif change == "window":
        row = case["window"]
        row.status, row.revision, row.revoked_at, row.revoked_by, row.revoke_reason = "revoked", 2, case["now"], case["doctor"].user_id, NOTE
    elif change == "lab":
        case["index"]["observation"].value_num = 123
    elif change == "weight":
        case["weight"].payload_json = "{}"
    elif change == "urine":
        case["urines"][0].payload_json = "{}"
    else:
        from app.ai import aki_contract

        modified = copy.deepcopy(aki_contract.RECIPE)
        modified["version"] += "-changed"
        monkeypatch.setattr(aki_contract, "RECIPE", modified)
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        aki_sources.authorize_assessment(db_session, case["doctor"], case["patient_id"], case["admission"].admission_id, data["assessment_id"])
    assert caught.value.status_code == 409
    headers = auth_headers(case["doctor"].username)
    ordinary = await client.get(f"/api/ai/aki-assessments/{data['assessment_id']}", params=scope(case), headers=headers)
    assert ordinary.status_code == 200 and ordinary.json()["data"]["snapshot"] is None and ordinary.json()["data"]["specialist_source"] is None
    audit = await client.get(f"/api/ai/admin/aki-assessments/{data['assessment_id']}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert audit.status_code == 200 and audit.json()["data"]["snapshot"] == data["snapshot"] and not audit.json()["data"]["eligible"]
    withdrawn = await client.post(
        f"/api/ai/aki-assessments/{data['assessment_id']}/revoke", json={**scope(case), "expected_revision": 1, "reason": NOTE}, headers=auth_headers(case["seed"]["super_admin_user"].username)
    )
    assert withdrawn.status_code == 200 and withdrawn.json()["data"]["revision"] == 2


@pytest.mark.asyncio
async def test_clinical_signer_later_role_change_preserved_but_doctor_reassignment_detected(client, case, db_session, auth_headers):
    response = await post(client, case, auth_headers)
    assert response.status_code == 200, response.text
    identifier = response.json()["data"]["assessment_id"]
    db_session.query(User).filter_by(user_id=case["doctor"].user_id).update({"user_role": "nurse"})
    db_session.commit()
    supervisor = case["seed"]["super_admin_user"]
    assert aki_sources.assessment_current(db_session, identifier, user=supervisor)["eligible"]
    signed_doctor_id = response.json()["data"]["snapshot"]["author_qualification"]["doctor_id"]
    db_session.query(Doctor).filter_by(doctor_id=signed_doctor_id).update({"user_id": supervisor.user_id})
    db_session.commit()
    current = aki_sources.assessment_current(db_session, identifier, allow_revoked=True, user=supervisor)
    assert not current["eligible"] and "clinical_signer_relationship_changed" in current["exclusion_reasons"]


@pytest.mark.asyncio
async def test_owner_current_care_and_cas_revoke_and_audit_failure_are_atomic(client, case, db_session, auth_headers, monkeypatch):
    response = await post(client, case, auth_headers)
    assert response.status_code == 200, response.text
    identifier = response.json()["data"]["assessment_id"]
    before = db_session.query(AIAKIAssessment).count()

    def invalid_audit(db, actor, *args):
        db.add(AIAuditEvent(actor_id=actor, action=None, target="synthetic-invalid-audit", detail_json="{}"))

    endpoint = f"/api/ai/aki-assessments/{identifier}/revoke"
    headers = auth_headers(case["doctor"].username)
    revoke = {**scope(case), "expected_revision": 1, "reason": NOTE}
    with monkeypatch.context() as patch:
        patch.setattr(ai_aki, "audit", invalid_audit)
        failed = await post(client, case, auth_headers)
        assert failed.status_code == 409 and db_session.query(AIAKIAssessment).count() == before
        failed = await client.post(endpoint, json=revoke, headers=headers)
        assert failed.status_code == 409 and db_session.get(AIAKIAssessment, identifier).status == "active"
    assert (await client.post(endpoint, json={**revoke, "expected_revision": 2}, headers=headers)).status_code == 409
    assert (await client.post(endpoint, json=revoke, headers=auth_headers(case["seed"]["admin_user"].username))).status_code == 403
    success = await client.post(endpoint, json=revoke, headers=headers)
    assert success.status_code == 200 and success.json()["data"]["content_hash"] == response.json()["data"]["content_hash"]
    assert (await client.post(endpoint, json=revoke, headers=headers)).status_code == 409
    for method in ("PUT", "PATCH", "DELETE"):
        assert (await client.request(method, endpoint.rsplit("/", 1)[0], headers=headers)).status_code == 405


@pytest.mark.parametrize("status", ["not_initiated", "acute_initiated_for_aki", "maintenance"])
@pytest.mark.asyncio
async def test_actual_doctor_signs_explicit_rrt_without_using_administrator_authority(status, client, case, db_session, auth_headers):
    changes = {
        "index_creatinine": None,
        "comparison_48h": None,
        "baseline_creatinine": None,
        "baseline_mode": "unknown",
        "serum_creatinine_confirmed": False,
        "creatinine_review_note": None,
        "urine_intervals": [],
        "rrt_status": status,
        "rrt_started_at": observation_windows.iso(case["end"]) if status == "acute_initiated_for_aki" else None,
        "rrt_acute_aki_confirmed": True if status == "acute_initiated_for_aki" else None,
        "rrt_basis_note": NOTE,
    }
    response = await post(client, case, auth_headers, **changes)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["snapshot"]["author_qualification"]["clinical_review_signed"] is True
    result = aki_values(data["specialist_source"])
    if status == "acute_initiated_for_aki":
        assert result["minimum_stage"] == 3 and result["detection"] == "met"
    elif status == "maintenance":
        assert result["scope_status"] == "outside_scope" and result["minimum_stage"] is None
    else:
        assert next(item for item in result["criteria"] if item["key"] == "acute_rrt")["status"] == "not_met_in_selected_data"
    grant(db_session, case, case["seed"]["nurse_user"])
    denied = await post(client, case, auth_headers, role="nurse_user", **changes)
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_super_with_doctor_row_still_needs_actual_original_admission_clinical_care(client, case, db_session, auth_headers):
    supervisor = case["seed"]["super_admin_user"]
    qualified = Doctor(user_id=supervisor.user_id, name="Synthetic unrelated clinical principal")
    db_session.add(qualified)
    db_session.commit()
    response = await post(client, case, auth_headers, role="super_admin_user")
    assert response.status_code == 403
    case["admission"].doctor_id = qualified.doctor_id
    db_session.commit()
    response = await post(client, case, auth_headers, role="super_admin_user")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["snapshot"]["author_qualification"]["doctor_user_id"] == supervisor.user_id


@pytest.mark.asyncio
async def test_empty_measurement_axes_stay_unknown_and_do_not_invent_normal_or_stage_zero(client, case, db_session, auth_headers):
    grant(db_session, case, case["seed"]["nurse_user"])
    response = await post(
        client,
        case,
        auth_headers,
        role="nurse_user",
        index_creatinine=None,
        comparison_48h=None,
        baseline_creatinine=None,
        baseline_mode="unknown",
        serum_creatinine_confirmed=False,
        creatinine_review_note=None,
        weight_point=None,
        weight_applicability_confirmed=False,
        weight_basis_note=None,
        urine_intervals=[],
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    result = aki_values(data["specialist_source"])
    assert data["eligible"] and result["detection"] == "insufficient_data" and result["minimum_stage"] is None and result["aki_excluded"] is False
    assert all(item["status"] == "unknown" for item in result["criteria"])
    with pytest.raises(HTTPException) as caught:
        aki_sources.assessment_current(db_session, data["assessment_id"])
    assert caught.value.status_code == 422


@pytest.mark.parametrize("numeric", ["0", "-1.00"])
@pytest.mark.asyncio
async def test_nonpositive_original_creatinine_remains_exact_and_unknown(numeric, client, case, db_session, auth_headers):
    member = case["make"](numeric=numeric, collected=case["end"] - datetime.timedelta(minutes=1))
    rewindow(db_session, case)
    response = await post(client, case, auth_headers, index_creatinine=reference(member), urine_intervals=[])
    assert response.status_code == 200, response.text
    source = response.json()["data"]["specialist_source"]
    assert source["index_creatinine"]["value"] == json.loads(member["source"].snapshot_json)["original"]["observation"]["value_num"]
    result = aki_values(source)
    assert result["minimum_stage"] is None and result["detection"] == "insufficient_data"


@pytest.mark.asyncio
async def test_known_complete_zero_twelve_hours_survives_other_unknown_collection_without_weight(client, case, db_session, auth_headers):
    db_session.query(InpatientUrineInterval).delete()
    unknown = urine(
        db_session,
        case,
        start=case["now"] - datetime.timedelta(hours=20),
        end=case["now"] - datetime.timedelta(hours=14),
        payload=urine_payload(None, collection_completeness="partial", patient_total=None),
    )
    zero = urine(db_session, case, start=case["now"] - datetime.timedelta(hours=13), end=case["end"], payload=urine_payload("0.00"))
    case["urines"] = [unknown, zero]
    db_session.commit()
    rewindow(db_session, case)
    response = await post(
        client,
        case,
        auth_headers,
        index_creatinine=None,
        comparison_48h=None,
        baseline_creatinine=None,
        baseline_mode="unknown",
        serum_creatinine_confirmed=False,
        creatinine_review_note=None,
        weight_point=None,
        weight_applicability_confirmed=False,
        weight_basis_note=None,
    )
    assert response.status_code == 200, response.text
    source = response.json()["data"]["specialist_source"]
    assert {"gap", "partial_collection", "unknown_volume", "not_patient_total"} <= set(source["urine_coverage_issues"])
    result = aki_values(source)
    witness = next(item for item in result["criteria"] if item["key"] == "anuria_12h")
    assert witness["status"] == "met" and result["minimum_stage"] == 3 and result["aki_excluded"] is False
    assert witness["evidence"]["interval_source_ids"] == [f"urine_interval:{zero.interval_id}:{zero.content_hash[:12]}"]


@pytest.mark.asyncio
async def test_original_urine_crossing_window_is_not_clipped_or_prorated(client, case, db_session, auth_headers):
    original = urine(db_session, case, start=case["start"] - datetime.timedelta(hours=1), end=case["start"] + datetime.timedelta(hours=1))
    db_session.commit()
    rewindow(db_session, case)
    response = await post(client, case, auth_headers, urine_intervals=[{"interval_id": original.interval_id, "expected_content_hash": original.content_hash}])
    assert response.status_code == 422


@pytest.mark.parametrize("count", [2, 65])
@pytest.mark.asyncio
async def test_duplicate_or_oversize_interval_selection_is_rejected_instead_of_truncated(count, client, case, auth_headers):
    ref = {"interval_id": case["urines"][0].interval_id, "expected_content_hash": case["urines"][0].content_hash}
    response = await post(client, case, auth_headers, urine_intervals=[ref] * count)
    assert response.status_code == 422


def test_full_unicode_budget_checked_before_revalidating_any_selected_original(db_session, case, monkeypatch):
    row = aki_sources.create_assessment(db_session, case["doctor"], body(case))
    db_session.commit()
    raw = json.loads(row.snapshot_json)
    raw["synthetic_utf8_boundary"] = "中" * 88000
    row.snapshot_json = aki_sources.canonical_json(raw)
    row.content_hash = aki_sources.hash_content(raw)
    db_session.commit()
    assert len(raw["synthetic_utf8_boundary"]) < aki_sources.MAX_SNAPSHOT_BYTES < len(row.snapshot_json.encode("utf-8"))

    def must_not_load(*args, **kwargs):
        raise AssertionError("Oversized body must fail before source/window lookup")

    monkeypatch.setattr(observation_windows, "snapshot_current", must_not_load)
    with pytest.raises(HTTPException) as caught:
        aki_sources.assessment_current(db_session, row, allow_revoked=True, user=case["doctor"])
    assert caught.value.status_code == 409


@pytest.mark.asyncio
async def test_author_record_does_not_grant_care_and_care_loss_blocks_current_read_and_revoke(client, case, db_session, auth_headers):
    response = await post(client, case, auth_headers)
    assert response.status_code == 200
    identifier = response.json()["data"]["assessment_id"]
    case["admission"].doctor_id = case["seed"]["director_doctor"].doctor_id
    db_session.commit()
    endpoint = f"/api/ai/aki-assessments/{identifier}"
    headers = auth_headers(case["doctor"].username)
    assert (await client.get(endpoint, params=scope(case), headers=headers)).status_code == 403
    assert (await client.post(endpoint + "/revoke", json={**scope(case), "expected_revision": 1, "reason": NOTE}, headers=headers)).status_code == 403
    audit = await client.get(f"/api/ai/admin/aki-assessments/{identifier}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert audit.status_code == 200 and audit.json()["data"]["snapshot"] is not None
