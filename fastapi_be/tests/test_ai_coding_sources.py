"""Local code candidates retain real dictionary provenance and do not create or alter diagnoses."""

import datetime
import json
import uuid

import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.coding_sources import local_icd_candidates
from app.ai.context import patient_snapshot
from app.ai.governance import encode_json
from app.ai.models import AIRun
from app.ai.runtime import describe_run
from app.models import Admission, DrgGrouping, DrgRule, HomeIcdBinding, Icd10Diagnosis, MedicalRecordHome


@pytest.fixture
def coding_case(seed_data, db_session):
    now = datetime.datetime.now()
    admission = Admission(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, status=2, admission_time=now)
    db_session.add(admission)
    db_session.flush()
    home = MedicalRecordHome(
        admission_id=admission.admission_id,
        patient_id=admission.patient_id,
        doctor_id=admission.doctor_id,
        admission_diagnosis="测试原始诊断",
        discharge_diagnosis="测试原始诊断",
        status=1,
        creator_id=seed_data["doctor_user"].user_id,
        create_time=now,
        update_time=now,
    )
    code = "T" + uuid.uuid4().hex[:6].upper()
    entry = Icd10Diagnosis(code=code, name="测试原始诊断", status=1, create_time=now, update_time=now)
    inactive = Icd10Diagnosis(code=code + "X", name="测试原始诊断停用条目", status=0, create_time=now, update_time=now)
    db_session.add_all([home, entry, inactive])
    db_session.flush()
    binding = HomeIcdBinding(home_id=home.home_id, kind="diagnosis", icd_code=code, icd_name="旧绑定名称", is_primary=1, coder_id=seed_data["doctor_user"].user_id, code_time=now)
    db_session.add(binding)
    db_session.commit()
    return admission, home, entry, inactive, binding


def test_home_and_bound_codes_are_scoped_and_inactive_dictionary_entries_are_excluded(seed_data, db_session, coding_case):
    admission, home, entry, inactive, binding = coding_case
    spec = FEATURE_BY_KEY["icd_candidates"]
    bundle = patient_snapshot(db_session, seed_data["doctor_user"], spec, admission.patient_id, admission.admission_id, {"home_id": home.home_id})
    assert bundle.data["current_confirmed_diagnoses"] == []
    assert bundle.data["home_icd_bindings"][0]["current_dictionary_state"] == "stored_name_differs"
    results, evidence = local_icd_candidates(db_session, bundle.data, {})
    codes = {item["code"] for item in results["candidates"]}
    assert entry.code in codes
    assert inactive.code not in codes
    assert results["changes_written"] == []
    assert all(item["kind"] == "dictionary" for item in evidence)
    db_session.refresh(binding)
    assert binding.icd_name == "旧绑定名称"
    assert db_session.get(MedicalRecordHome, home.home_id).status == 1


def test_drg_review_retains_current_rule_provenance_and_omits_reimbursement_incentives(seed_data, db_session, coding_case):
    admission, home, entry, _, _ = coding_case
    now = datetime.datetime.now()
    rule = DrgRule(
        payment_method="DRG",
        group_code="TEST-GROUP",
        group_name="测试规则",
        diagnosis_prefix=entry.code[:3],
        expected_amount=999,
        priority=1,
        version="current-test-version",
        status=1,
        creator_id=seed_data["super_admin_user"].user_id,
        create_time=now,
        update_time=now,
    )
    db_session.add(rule)
    db_session.flush()
    db_session.add(
        DrgGrouping(
            patient_id=admission.patient_id,
            home_id=home.home_id,
            rule_id=rule.rule_id,
            group_code="TEST-GROUP",
            diagnosis="原分组文字",
            diagnosis_codes=entry.code,
            expected_amount=999,
            actual_amount=100,
            profit=899,
            create_time=now,
        )
    )
    db_session.commit()
    bundle = patient_snapshot(db_session, seed_data["super_admin_user"], FEATURE_BY_KEY["drg_evidence_review"], admission.patient_id, admission.admission_id, {"home_id": home.home_id})
    assert bundle.data["current_linked_drg_rules"][0]["version"] == "current-test-version"
    assert "旧分组未冻结原规则版本" in bundle.data["drg_comparison_scope"]
    assert "profit" not in encode_json(bundle.data["recorded_drg_groups"])
    assert "expected_amount" not in encode_json(bundle.data["current_linked_drg_rules"])


def test_foreign_home_or_another_admission_cannot_be_loaded(seed_data, db_session, coding_case):
    admission, home, _, _, _ = coding_case
    other = Admission(patient_id=admission.patient_id, doctor_id=admission.doctor_id, department_id=admission.department_id, status=1, admission_time=admission.admission_time)
    db_session.add(other)
    db_session.commit()
    with pytest.raises(HTTPException) as mismatch:
        patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["record_home_review"], admission.patient_id, other.admission_id, {"home_id": home.home_id})
    assert mismatch.value.status_code == 422


def test_dictionary_search_escapes_sql_wildcards_and_result_payload_exposes_only_allowlisted_tools(db_session):
    candidates, _ = local_icd_candidates(db_session, {}, {"icd_query": "%_"})
    assert candidates["candidates"] == []
    run = AIRun(
        feature_key="icd_candidates",
        input_json=json.dumps(
            {"system_prompt": "private-system", "provider_snapshot": {"api_base": "private-url"}, "payload": {"tools": {"icd_candidates": candidates, "unapproved_tool": "private-data"}}}
        ),
        context_metadata_json="{}",
        result_json="{}",
        evidence_json="[]",
    )
    result = describe_run(run)
    assert result["tool_findings"] == {"icd_candidates": candidates}
    assert "private-url" not in encode_json(result)
    assert "private-system" not in encode_json(result)
    assert "private-data" not in encode_json(result)
