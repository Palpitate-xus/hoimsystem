"""Actual declared-window SQL columns and whole literal collection, no AI model."""

import copy
import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import research_variables_collection as collection
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_variables_dictionary import create_dictionary, review_dictionary
from app.models import MedicalRecord
from tests.test_ai_research_cohort_collection import clinical_case
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import anchors
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401
from tests.test_ai_research_variables_dictionary import definition_review, technical_review
from tests.test_ai_research_variables_dictionary import variable_dictionary_case as variable_dictionary_case  # noqa: F401


@pytest.fixture
def variable_capture_case(db_session, variable_dictionary_case):
    case, scope, permission, dictionary_request = variable_dictionary_case
    early, late = copy.deepcopy(dictionary_request["variables"][0]), copy.deepcopy(dictionary_request["variables"][0])
    early.update(variable_key="early_symptom", label="早窗原症状")
    early["record_window"]["date_to"] = "2026-10-10"
    late.update(variable_key="late_result", label="晚窗原结论", field="result")
    late["record_window"]["date_from"] = "2026-10-11"
    dictionary_request["variables"] = [early, late]
    made = create_dictionary(db_session, case["admin_user"], dictionary_request)
    review_dictionary(db_session, case["reviewer"], made["dictionary_id"], definition_review(made), definition=True)
    published = review_dictionary(db_session, case["super_admin_user"], made["dictionary_id"], technical_review())
    _, records = clinical_case(db_session, case)
    early_record = MedicalRecord(
        medical_record_id=str(uuid.uuid4()),
        patient_id=case["patient"].patient_id,
        doctor_id=case["doctor"].doctor_id,
        consultation_time=dt.datetime(2026, 10, 5),
        symptom="\ufeff否认既往原症状\r\n🧪e\u0301逐字",
        result="早窗未声明的结论列不得读取",
        status=0,
    )
    db_session.add(early_record)
    db_session.commit()
    request = {
        **anchors(scope),
        "variable_dictionary_id": made["dictionary_id"],
        "dictionary_content_hash": published["content_hash"],
        "dictionary_governance_hash": published["governance_hash"],
        "patient_ids": [case["patient"].patient_id],
    }
    return case, permission, request, records, early_record


def test_actual_per_record_columns_keep_all_literal_candidates_null_and_unknown_clock_without_reading_outside_variable_window(db_session, variable_capture_case):
    case, _, request, records, early = variable_capture_case
    late_id, early_id = records[0].medical_record_id, early.medical_record_id
    # Shared seed_data already contains another real clinical row. Enumerate
    # the full independent ID/clock set rather than treating our three new
    # rows as the complete hospital fixture and hiding a pre-existing member.
    ids_and_clocks = db_session.query(MedicalRecord.medical_record_id, MedicalRecord.consultation_time).filter_by(patient_id=request["patient_ids"][0]).all()
    expected_ids = {identifier for identifier, clock in ids_and_clocks if clock is None or dt.datetime(2026, 10, 1) <= clock < dt.datetime(2026, 10, 22)}
    statements = []

    def record(conn, cursor, statement, params, context, many):
        statements.append((statement, params))

    event.listen(db_session.bind, "before_cursor_execute", record)
    try:
        value = collection.capture_variable_sources(db_session, case["admin_user"], request)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)
    actual = {row["record_id"]: row for row in value["records"]}
    assert set(actual) == expected_ids
    assert {late_id, early_id, records[1].medical_record_id}.issubset(actual)
    assert records[2].medical_record_id not in actual
    assert [(v["variable_key"], v["literal"]) for v in actual[late_id]["variables"]] == [("late_result", None)]
    assert [(v["variable_key"], v["literal"]) for v in actual[early_id]["variables"]] == [("early_symptom", early.symptom)]
    unknown = actual[records[1].medical_record_id]
    assert unknown["window_status"] == "unknown_record_clock" and unknown["recorded_clock"] is None
    assert [v["variable_key"] for v in unknown["variables"]] == ["early_symptom", "late_result"]
    assert actual[early_id]["lifecycle_original"]["status"] == 0
    assert value["privacy_basis"].endswith("not_anonymous")
    bodies = [(sql, params) for sql, params in statements if "FROM hoimsystem_medical_record" in sql and "hoimsystem_medical_record.medical_record_id =" in sql]
    assert bodies
    assert any("hoimsystem_medical_record.result" in sql for sql, params in bodies if late_id in params)
    assert not any("hoimsystem_medical_record.symptom" in sql for sql, params in bodies if late_id in params)
    assert not any("hoimsystem_medical_record.result" in sql for sql, params in bodies if early_id in params)


def test_same_count_literal_mutation_changes_full_collection_digest_without_inventing_a_new_window_winner(db_session, variable_capture_case):
    case, _, request, _, early = variable_capture_case
    first = collection.capture_variable_sources(db_session, case["admin_user"], request)
    second = collection.capture_variable_sources(db_session, case["admin_user"], request)
    assert first["captured_at"] != second["captured_at"] and first["collection_digest"] == second["collection_digest"]
    db_session.execute(text("UPDATE hoimsystem_medical_record SET symptom=:body WHERE medical_record_id=:id"), {"body": "新原文、相同记录数，保持未知和否定。", "id": early.medical_record_id})
    db_session.commit()
    third = collection.capture_variable_sources(db_session, case["admin_user"], request)
    assert len(first["records"]) == len(third["records"]) and first["collection_digest"] != third["collection_digest"]
    assert first["member_manifest_hash"] != third["member_manifest_hash"]


@pytest.mark.parametrize("actor_name", ["admin_user", "super_admin_user"])
def test_patient_withdrawal_prevents_first_clinical_column_even_super(db_session, variable_capture_case, actor_name):
    case, permission, request, _, _ = variable_capture_case
    review_registry_original(db_session, case["super_admin_user"], "authorization", permission["source_record_id"], dict(expected_revision=2, basis_note=BASIS), revoke=True)
    statements = []

    def record(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", record)
    try:
        with pytest.raises(HTTPException) as error:
            collection.capture_variable_sources(db_session, case[actor_name], request)
        assert error.value.status_code == 403
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)
    assert not any("hoimsystem_medical_record.symptom" in sql or "hoimsystem_medical_record.result" in sql or "hoimsystem_ai_research_variable_dictionary.dictionary_json" in sql for sql in statements)


@pytest.mark.parametrize("field", ["dictionary_content_hash", "dictionary_governance_hash", "scope_content_hash"])
def test_original_expected_anchors_cannot_adopt_new_dictionary_or_project(db_session, variable_capture_case, field):
    case, _, request, _, _ = variable_capture_case
    with pytest.raises(HTTPException) as error:
        collection.capture_variable_sources(db_session, case["admin_user"], {**request, field: "f" * 64})
    assert error.value.status_code == 409


def test_real_whole_utf8_budget_and_root_bound_refuse_instead_of_clipping(db_session, variable_capture_case, monkeypatch):
    case, _, request, _, early = variable_capture_case
    monkeypatch.setattr(collection, "MAX_ROOTS", 1)
    with pytest.raises(HTTPException) as error:
        collection.capture_variable_sources(db_session, case["admin_user"], request)
    assert error.value.status_code == 413
    monkeypatch.setattr(collection, "MAX_ROOTS", 8192)
    db_session.execute(text("UPDATE hoimsystem_medical_record SET symptom=:body WHERE medical_record_id=:id"), {"body": "汉" * 2796203, "id": early.medical_record_id})
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        collection.capture_variable_sources(db_session, case["admin_user"], request)
    assert error.value.status_code == 413
