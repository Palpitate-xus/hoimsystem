"""Consultation source links, department mapping and clinical certainty remain distinct."""

import datetime
import json

import httpx
import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.consultation_sources import department_references
from app.ai.context import patient_snapshot
from app.ai.governance import encode_json
from app.ai.knowledge import retrieval_query
from app.ai.models import AIFeatureConfig, AIFeedback, AIProvider, AIRun
from app.ai.runtime import claim_next_run, create_run, describe_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import AdverseReaction, MdtCase, Referral


@pytest.fixture
def consultation_case(db_session, seed_data):
    for model in (AIFeedback, AIRun, AIFeatureConfig, AIProvider, MdtCase, Referral):
        db_session.query(model).delete()
    now = datetime.datetime.now()
    department = seed_data["department"].department_id
    referral = Referral(
        patient_id=seed_data["patient"].patient_id,
        from_department_id=department,
        to_department_id=99999999,
        referral_type="legacy-unknown",
        status=1,
        reason=seed_data["patient"].name + "需要心脏专科评估",
        create_time=now,
        review_time=now,
        reviewer_id=seed_data["super_admin_user"].user_id,
    )
    case = MdtCase(
        patient_id=seed_data["patient"].patient_id,
        diagnosis="所选复杂病种",
        department_ids=f'[{department}, "{department}", "科室123", 99999999, true]',
        status=3,
        result="已退回病例仍有结果文字",
        create_time=now,
    )
    foreign = MdtCase(patient_id=seed_data["patient2"].patient_id, diagnosis="外部患者诊断不得读取", department_ids=str(department), status=2, create_time=now)
    db_session.add_all([referral, case, foreign])
    db_session.commit()
    return referral, case, foreign


def snapshot(db_session, seed_data, key="referral_mdt", **references):
    return patient_snapshot(db_session, seed_data["super_admin_user"], FEATURE_BY_KEY[key], seed_data["patient"].patient_id, source_refs=references)


def test_original_approval_and_draft_result_do_not_become_arrival_or_confirmed_diagnosis(seed_data, db_session, consultation_case):
    referral, case, _ = consultation_case
    bundle = snapshot(db_session, seed_data, referral_id=str(referral.referral_id), mdt_id=str(case.mdt_id))
    source = bundle.data["consultation_sources"]
    assert source["encounter_assignment"] == "not_recorded"
    actual = source["referrals"][0]
    assert actual["recorded_status"] == 1 and actual["review_identity_recorded"] is True
    assert actual["recorded_type"] == "legacy-unknown"
    assert actual["to_department"]["name"] is None and actual["to_department"]["exists_in_current_directory"] is False
    mdt = source["mdt_cases"][0]
    assert mdt["recorded_status_meaning"] == "已退回" and mdt["recorded_result"] and mdt["result_on_completed_case"] is False
    assert mdt["unparsed_department_tokens"] == 2 and mdt["missing_department_count"] == 1
    assert len(mdt["participating_departments"]) == 2
    assert bundle.data["current_confirmed_diagnoses"] == []
    serialized = encode_json({"context": bundle.data, "evidence": bundle.evidence})
    assert seed_data["patient"].name not in serialized and "外部患者诊断" not in serialized and "科室123" not in serialized
    assert any(item["source_id"] == "mdt:" + str(case.mdt_id) for item in bundle.evidence)


def test_selected_older_case_is_retained_and_truncation_is_explicit(seed_data, db_session, consultation_case):
    _, selected, _ = consultation_case
    for index in range(8):
        db_session.add(MdtCase(patient_id=selected.patient_id, diagnosis="其他旧诊断" + str(index), create_time=selected.create_time + datetime.timedelta(days=index + 1), status=2))
    db_session.commit()
    bundle = snapshot(db_session, seed_data, mdt_id=str(selected.mdt_id))
    rows = bundle.data["consultation_sources"]["mdt_cases"]
    assert len(rows) == 6 and rows[0]["mdt_id"] == selected.mdt_id and rows[0]["explicitly_selected"] is True
    assert any(item["source"] == "MDT记录" for item in bundle.data["truncated_sources"])
    query = retrieval_query(FEATURE_BY_KEY["referral_mdt"], {"mdt_id": str(selected.mdt_id)}, bundle.data)
    assert "所选复杂病种" in query and "其他旧诊断" not in query


def test_foreign_integer_references_are_rejected_and_malformed_ids_are_bounded(seed_data, db_session, consultation_case):
    foreign = consultation_case[2]
    with pytest.raises(HTTPException) as error:
        snapshot(db_session, seed_data, mdt_id=str(foreign.mdt_id))
    assert error.value.status_code == 404
    for value in (True, 1, "01", "-1", "1" * 5000, "1.0", "２"):
        with pytest.raises(HTTPException) as error:
            snapshot(db_session, seed_data, referral_id=value)
        assert error.value.status_code == 422
    for model, key in ((Referral, "referral_id"), (AdverseReaction, "reaction_id")):
        row = model(patient_id=seed_data["patient2"].patient_id)
        db_session.add(row)
        db_session.commit()
        with pytest.raises(HTTPException) as error:
            snapshot(db_session, seed_data, **{key: str(getattr(row, key))})
        assert error.value.status_code == 404


def test_department_parser_does_not_extract_identifiers_from_prose_or_coerce_boolean():
    assert department_references("1,2,2") == ([1, 2], 0)
    assert department_references('[1, "2", true, "科室3", "01"]') == ([1, 2], 3)
    assert department_references("[1, 2") == ([], 1)
    assert department_references("[" + "1," * 1000 + "1]") == ([], 1)
    assert department_references("科室123") == ([], 1)


def test_consultation_diagnosis_never_satisfies_treatment_confirmation_and_patient_cannot_load_staff_sources(seed_data, db_session, consultation_case):
    _, case, _ = consultation_case
    case.status, case.result = 2, "原会诊已记录方案"
    db_session.commit()
    bundle = snapshot(db_session, seed_data, key="treatment_pathway", mdt_id=str(case.mdt_id))
    assert bundle.data["current_confirmed_diagnoses"] == []
    with pytest.raises(HTTPException) as error:
        patient_snapshot(db_session, seed_data["patient_user"], FEATURE_BY_KEY["patient_report_explanation"], case.patient_id, source_refs={"mdt_id": str(case.mdt_id)})
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_changed_consultation_result_stops_queued_inference_and_retains_original_findings(seed_data, db_session, consultation_case):
    key = "patient_summary"
    provider = AIProvider(
        name="consultation-isolated", kind="chat", api_base="http://localhost:11434/v1", model="isolated", enabled=1, allows_patient_data=1, created_by=seed_data["super_admin_user"].user_id
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key=key,
            enabled=1,
            provider_id=provider.provider_id,
            validation_status="validated",
            allowed_roles_json=encode_json(FEATURE_BY_KEY[key].default_roles),
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    case = consultation_case[1]
    run = create_run(db_session, seed_data["super_admin_user"], RunRequest(feature_key=key, patient_id=case.patient_id, input={"mdt_id": str(case.mdt_id)}))
    frozen = json.loads(run.input_json)
    case.result = "后来更改的会诊意见"
    db_session.commit()
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(lambda request: (calls.append(request), httpx.Response(500))[1]))
    db_session.refresh(run)
    assert not calls and run.error_code == "TASK_CONTEXT_CHANGED"
    assert describe_run(run)["consultation_findings"] == frozen["payload"]["context"]["consultation_sources"]
