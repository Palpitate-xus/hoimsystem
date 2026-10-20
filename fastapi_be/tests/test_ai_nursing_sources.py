"""Nursing AI uses explicit original admissions, unknowns and verifiable manual sums."""

import datetime
import json

import httpx
import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import authorize_patient, minimize_identifiers, patient_snapshot
from app.ai.governance import encode_json
from app.ai.models import AIPatientGrant, AIRun, utcnow
from app.ai.runtime import claim_next_run, create_run, describe_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Admission, CriticalCareRecord, IcuScoreRecord, NursingAssessment, NursingPlan, Registration
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure, successful_transport


@pytest.fixture
def nursing_sources_case(seed_data, db_session):
    now = datetime.datetime.now()
    admissions = [
        Admission(patient_id=patient.patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, status=1, admission_time=now)
        for patient in (seed_data["patient"], seed_data["patient"], seed_data["patient2"])
    ]
    db_session.add_all(admissions)
    db_session.flush()
    current, other, foreign = admissions
    registration = Registration(patient_id=current.patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=now)
    db_session.add(registration)
    values = {"admission_id": current.admission_id, "patient_id": current.patient_id, "nurse_id": seed_data["nurse_user"].user_id}
    assessment = NursingAssessment(**values, adl_score=0, fall_risk=0, status=1, entry_version="nullable_v1", note="原评估明确零值与未知项", create_time=now, update_time=now)
    plan = NursingPlan(**values, nursing_diagnosis="原护理诊断", goal="原目标", measures="原措施", status=0, create_time=now, update_time=now)
    critical = CriticalCareRecord(**values, record_time=now, time_basis="utc", entry_version="nullable_v1", consciousness=None, gcs_score=None, pulse=0, spo2=0)
    score = IcuScoreRecord(
        patient_id=current.patient_id,
        admission_id=current.admission_id,
        assessor_id=seed_data["nurse_user"].user_id,
        score_type="gcs",
        scene="icu",
        total_score=12,
        detail_json='{"eye":3,"verbal":4,"motor":5}',
        interpretation="原人工汇总说明",
        calculation_version="manual_components_v2",
        assess_time=now,
        create_time=now,
    )
    db_session.add_all([assessment, plan, critical, score])
    db_session.commit()
    return {"current": current, "other": other, "foreign": foreign, "assessment": assessment, "plan": plan, "critical": critical, "score": score, "now": now, "registration": registration}


def snapshot(db, seed, case, *, feature="handover_summary", refs=None, encounter="current", user="doctor_user", patient_id=None):
    reference = case[encounter].admission_id if encounter else None
    return patient_snapshot(db, seed[user], FEATURE_BY_KEY[feature], patient_id or case["current"].patient_id, reference, refs)


def all_refs(case):
    return {
        "nursing_assessment_id": case["assessment"].assessment_id,
        "nursing_plan_id": case["plan"].plan_id,
        "critical_care_record_id": case["critical"].record_id,
        "icu_score_id": str(case["score"].score_id),
    }


def test_selected_original_rows_survive_bounds_and_preserve_unknown_zero_and_time(seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    for index in range(7):
        now = case["now"] + datetime.timedelta(days=index + 1)
        db_session.add(
            NursingAssessment(
                admission_id=case["current"].admission_id, patient_id=case["current"].patient_id, nurse_id=seed_data["nurse_user"].user_id, adl_score=100, status=1, create_time=now, update_time=now
            )
        )
    db_session.add(
        NursingAssessment(
            admission_id=case["other"].admission_id,
            patient_id=case["other"].patient_id,
            nurse_id=seed_data["nurse_user"].user_id,
            adl_score=99,
            status=1,
            note="其他住院不能加载",
            create_time=case["now"],
            update_time=case["now"],
        )
    )
    db_session.commit()
    bundle = snapshot(db_session, seed_data, case, refs=all_refs(case))
    review = bundle.data["nursing_source_review"]
    chosen = review["assessments"][0]
    assert chosen["explicitly_selected"] is True and len(review["assessments"]) == 3
    assert chosen["adl_score"] == chosen["fall_risk"] == 0
    assert chosen["pressure_ulcer_risk"] is None
    assert chosen["missing_fields"] == ["pressure_ulcer_risk", "consciousness", "nutrition_risk"]
    assert chosen["assessment_time_basis"] == "not_recorded" and chosen["assessed_at"] is None
    assert chosen["standard_scale_validated"] is False and chosen["legacy_defaults_possible"] is False
    assert next(item for item in bundle.evidence if item["source_id"] == chosen["source_id"])["observed_at"] is None
    assert any(item["source"] == "completed_nursing_assessments" for item in bundle.data["truncated_sources"])
    assert "其他住院不能加载" not in encode_json(bundle.data)
    assert review["critical_records"][0]["gcs_score"] is None
    assert review["critical_records"][0]["pulse"] == review["critical_records"][0]["spo2"] == 0
    assert review["scores"][0]["component_check"]["state"] == "manual_sum_matches"
    assert review["scores"][0]["assessment_time_basis"] == "not_recorded"
    assert review["plans"][0]["explicitly_selected"] is True


@pytest.mark.parametrize(("key", "field"), [("nursing_assessment_id", "assessment"), ("nursing_plan_id", "plan"), ("critical_care_record_id", "critical"), ("icu_score_id", "score")])
@pytest.mark.parametrize(("encounter", "expected"), [(None, 422), ("other", 409)])
def test_each_reference_requires_its_actual_selected_admission(key, field, encounter, expected, seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    with pytest.raises(HTTPException) as rejected:
        snapshot(db_session, seed_data, case, refs={key: all_refs(case)[key]}, encounter=encounter)
    assert rejected.value.status_code == expected


@pytest.mark.parametrize("key", ["nursing_assessment_id", "nursing_plan_id", "critical_care_record_id", "icu_score_id"])
def test_foreign_patient_and_unrelated_feature_cannot_select_internal_rows(key, seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    with pytest.raises(HTTPException) as rejected:
        snapshot(db_session, seed_data, case, refs={key: all_refs(case)[key]}, encounter="foreign", patient_id=case["foreign"].patient_id)
    assert rejected.value.status_code == 404
    with pytest.raises(HTTPException) as unrelated:
        snapshot(db_session, seed_data, case, feature="patient_summary", refs={key: all_refs(case)[key]})
    assert unrelated.value.status_code == 422


def test_draft_assessment_rejected_while_completed_original_remains_read_only(seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    case["assessment"].status = 0
    db_session.commit()
    with pytest.raises(HTTPException) as rejected:
        snapshot(db_session, seed_data, case, refs={"nursing_assessment_id": case["assessment"].assessment_id})
    assert rejected.value.status_code == 409
    assert snapshot(db_session, seed_data, case).data["completed_nursing_assessments"] == []


@pytest.mark.parametrize(
    ("change", "state"), [("legacy", "legacy_unverified"), ("missing", "invalid_components"), ("extra", "invalid_components"), ("mismatch", "total_mismatch"), ("json", "invalid_components")]
)
def test_score_integrity_is_not_inferred_from_a_saved_total(change, state, seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    row = case["score"]
    if change == "legacy":
        row.calculation_version = "legacy_unverified"
        row.detail_json = "{}"
        row.interpretation = "旧系统原说明，不能重新验证"
    elif change == "missing":
        row.detail_json = '{"eye":3,"motor":5}'
    elif change == "extra":
        row.detail_json = '{"eye":3,"verbal":4,"motor":5,"other_score":0}'
    elif change == "mismatch":
        row.total_score = 15
    else:
        row.detail_json = "invalid-json"
    db_session.commit()
    before = (row.total_score, row.detail_json, row.interpretation, row.calculation_version)
    review = snapshot(db_session, seed_data, case, refs={"icu_score_id": str(row.score_id)}).data["nursing_source_review"]
    checked = review["scores"][0]["component_check"]
    assert checked["state"] == state and checked["clinical_validation"] == "not_provided"
    db_session.refresh(row)
    assert (row.total_score, row.detail_json, row.interpretation, row.calculation_version) == before


def test_old_nursing_values_are_not_upgraded_by_presence_or_completion(seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    case["assessment"].entry_version = "legacy_unverified"
    case["assessment"].pressure_ulcer_risk = 0
    case["critical"].entry_version = "legacy_unverified"
    case["critical"].consciousness = 0
    case["critical"].gcs_score = 15
    db_session.commit()
    review = snapshot(db_session, seed_data, case).data["nursing_source_review"]
    assert review["assessments"][0]["legacy_defaults_possible"] is True
    assert review["assessments"][0]["pressure_ulcer_risk"] == 0
    assert review["critical_records"][0]["legacy_defaults_possible"] is True
    assert review["critical_records"][0]["gcs_score"] == 15


def test_nurse_historical_care_does_not_grant_a_different_admission(seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    # The nurse authored the current case's source records, but none in 'other'.
    assert snapshot(db_session, seed_data, case, user="nurse_user").data["nursing_source_review"]
    with pytest.raises(HTTPException) as rejected:
        snapshot(db_session, seed_data, case, user="nurse_user", encounter="other")
    assert rejected.value.status_code == 403
    with pytest.raises(HTTPException) as outpatient:
        authorize_patient(db_session, seed_data["nurse_user"], case["current"].patient_id, "inpatient", case["registration"].registration_uuid)
    assert outpatient.value.status_code == 403


@pytest.mark.asyncio
async def test_encounter_directory_and_preview_follow_nurse_current_admission(async_client, auth_headers, seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    headers = auth_headers(seed_data["nurse_user"].username)
    options = await async_client.get("/api/ai/encounters", headers=headers, params={"feature_key": "handover_summary", "patient_id": case["current"].patient_id})
    assert options.status_code == 200, options.text
    offered = {item["encounter_ref"] for item in options.json()["data"]}
    assert case["current"].admission_id in offered
    assert case["other"].admission_id not in offered
    assert case["registration"].registration_uuid not in offered
    body = {"feature_key": "handover_summary", "patient_id": case["current"].patient_id, "encounter_ref": case["current"].admission_id, "source_refs": all_refs(case)}
    inspected = await async_client.post("/api/ai/context", headers=headers, json=body)
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["data"]["context"]["selected_sources"] == all_refs(case)
    assert db_session.query(AIRun).count() == 0


@pytest.mark.asyncio
async def test_worker_freezes_manual_sources_and_never_writes_nursing_or_score_records(async_client, auth_headers, seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    configure(db_session, seed_data, "handover_summary")
    before = [(model.__tablename__, db_session.query(model).count()) for model in (NursingAssessment, NursingPlan, CriticalCareRecord, IcuScoreRecord)]
    request = RunRequest(feature_key="handover_summary", patient_id=case["current"].patient_id, encounter_ref=case["current"].admission_id, input=all_refs(case))
    run = create_run(db_session, seed_data["nurse_user"], request)
    claim = claim_next_run(db_session)
    sent = []
    await execute_claimed(*claim, transport=successful_transport(sent))
    db_session.refresh(run)
    assert run.status == "succeeded", run.error_message
    response = await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(seed_data["nurse_user"].username))
    assert response.status_code == 200, response.text
    findings = response.json()["data"]["nursing_findings"]
    assert findings["selected_sources"] == all_refs(case)
    assert findings["scores"][0]["component_check"]["state"] == "manual_sum_matches"
    assert findings["assessments"][0]["missing_fields"] == ["pressure_ulcer_risk", "consciousness", "nutrition_risk"]
    assert before == [(model.__tablename__, db_session.query(model).count()) for model in (NursingAssessment, NursingPlan, CriticalCareRecord, IcuScoreRecord)]
    db_session.refresh(case["assessment"])
    assert case["assessment"].pressure_ulcer_risk is None
    assert json.loads(run.input_json)["payload"]["context"]["selected_sources"] == all_refs(case)
    assert len(sent) == 1 and "不得" in json.loads(run.input_json)["system_prompt"]
    assert describe_run(run, include_result=False).get("nursing_findings") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("in_flight", [False, True])
async def test_changed_selected_source_stops_queued_or_inflight_results(in_flight, seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    configure(db_session, seed_data, "handover_summary")
    run = create_run(
        db_session,
        seed_data["doctor_user"],
        RunRequest(feature_key="handover_summary", patient_id=case["current"].patient_id, encounter_ref=case["current"].admission_id, input={"icu_score_id": str(case["score"].score_id)}),
    )
    claim = claim_next_run(db_session)
    calls = []

    def change():
        case["score"].detail_json = '{"eye":1,"verbal":1,"motor":1}'
        db_session.commit()

    if not in_flight:
        change()

    def handle(request):
        calls.append(request)
        change()
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"summary": "隔离测试旧候选", "sections": [], "warnings": [], "missing_data": []})}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
        )

    await execute_claimed(*claim, transport=httpx.MockTransport(handle))
    db_session.refresh(run)
    assert run.status == "failed" and run.result_json == "{}"
    assert len(calls) == int(in_flight)
    assert run.error_code in {"TASK_CONTEXT_CHANGED", "TASK_NO_LONGER_AUTHORIZED"}


def test_explicit_expiring_grant_can_override_missing_nursing_care_without_rebinding_sources(seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    grant = AIPatientGrant(
        user_id=seed_data["nurse_user"].user_id,
        patient_id=case["current"].patient_id,
        category="inpatient",
        reason="隔离测试临时授权",
        expires_at=utcnow() + datetime.timedelta(hours=1),
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(grant)
    db_session.commit()
    assert snapshot(db_session, seed_data, case, user="nurse_user", encounter="other").data["inpatient_source_scope"]["admission_id"] == case["other"].admission_id
    with pytest.raises(HTTPException) as rejected:
        snapshot(db_session, seed_data, case, user="nurse_user", encounter="other", refs={"nursing_assessment_id": case["assessment"].assessment_id})
    assert rejected.value.status_code == 409


@pytest.mark.parametrize("kind", ["leading_zero", "decimal", "plus", "scientific", "whitespace", "unicode", "zero", "negative", "overflow", "number"])
def test_integer_score_reference_requires_a_single_canonical_identifier(kind, seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    original = case["score"].score_id
    reference = {
        "leading_zero": "0" + str(original),
        "decimal": f"{original}.0",
        "plus": f"+{original}",
        "scientific": f"{original}e0",
        "whitespace": f" {original}",
        "unicode": "١",
        "zero": "0",
        "negative": "-1",
        "overflow": "2147483648",
        "number": original,
    }[kind]
    with pytest.raises(HTTPException) as rejected:
        snapshot(db_session, seed_data, case, refs={"icu_score_id": reference})
    assert rejected.value.status_code == 422


@pytest.mark.parametrize("basis", ["utc", "unspecified", "recorded_at_only"])
def test_critical_evidence_does_not_promote_recording_time_to_observation(basis, seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    case["critical"].time_basis = basis
    db_session.commit()
    bundle = snapshot(db_session, seed_data, case, refs={"critical_care_record_id": case["critical"].record_id})
    record = bundle.data["critical_care_records"][0]
    original = next(item for item in bundle.evidence if item["source_id"] == record["source_id"])
    assert record["record_time"]
    assert bool(original["observed_at"]) is (basis == "utc")


@pytest.mark.asyncio
@pytest.mark.parametrize(("key", "row_key"), [("nursing_assessment_id", "assessment"), ("nursing_plan_id", "plan"), ("critical_care_record_id", "critical"), ("icu_score_id", "score")])
@pytest.mark.parametrize("change", ["delete", "patient", "admission", "content"])
async def test_completed_results_recheck_each_selected_original_and_keep_super_audit(change, key, row_key, async_client, auth_headers, seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    configure(db_session, seed_data, "handover_summary")
    run = create_run(
        db_session,
        seed_data["doctor_user"],
        RunRequest(feature_key="handover_summary", patient_id=case["current"].patient_id, encounter_ref=case["current"].admission_id, input={key: all_refs(case)[key]}),
    )
    await execute_claimed(*claim_next_run(db_session), transport=successful_transport([]))
    db_session.refresh(run)
    assert run.status == "succeeded", run.error_message
    frozen_input, frozen_result = run.input_json, run.result_json
    row = case[row_key]
    if change == "delete":
        db_session.delete(row)
    elif change == "patient":
        row.patient_id = case["foreign"].patient_id
    elif change == "admission":
        row.admission_id = case["other"].admission_id
    elif row_key == "score":
        row.detail_json = '{"eye":1,"verbal":1,"motor":1}'
    elif row_key == "plan":
        row.measures = "原措施已变更"
    else:
        row.note = "原记录已变更"
    db_session.commit()
    denied = await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(seed_data["doctor_user"].username))
    assert denied.status_code == 403, denied.text
    audit = await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(seed_data["super_admin_user"].username))
    assert audit.status_code == 200, audit.text
    assert audit.json()["data"]["nursing_findings"]["selected_sources"] == {key: all_refs(case)[key]}
    db_session.refresh(run)
    assert (run.input_json, run.result_json) == (frozen_input, frozen_result)


@pytest.mark.asyncio
async def test_super_frozen_nursing_audit_survives_original_admission_removal(async_client, auth_headers, seed_data, db_session, nursing_sources_case):
    case = nursing_sources_case
    configure(db_session, seed_data, "handover_summary")
    run = create_run(
        db_session,
        seed_data["doctor_user"],
        RunRequest(feature_key="handover_summary", patient_id=case["current"].patient_id, encounter_ref=case["current"].admission_id, input={"icu_score_id": str(case["score"].score_id)}),
    )
    original_input = run.input_json
    db_session.delete(case["current"])
    db_session.commit()
    allowed = await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(seed_data["super_admin_user"].username))
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["data"]["nursing_findings"]["selected_sources"] == {"icu_score_id": str(case["score"].score_id)}
    assert (await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(seed_data["doctor_user"].username))).status_code in {403, 404}
    db_session.refresh(run)
    assert run.input_json == original_input


def test_canonical_admission_uuid_is_not_mistaken_for_a_phone_number():
    reference = "12345678-1234-4234-8234-13123456789a"
    cleaned = minimize_identifiers({"admission_id": reference, "note": "原备注手机号13123456789"})
    assert cleaned["admission_id"] == reference
    assert "13123456789" not in cleaned["note"]
