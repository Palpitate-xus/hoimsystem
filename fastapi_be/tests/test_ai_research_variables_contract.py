"""76 exact field/type/window/purpose boundaries; no clinical variable validation."""

import ast
import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai.research_variables_contract import BatchCapture, DictionaryCreate, VariableDefinition
from app.ai.research_variables_fields import VARIABLE_FIELDS

BASIS = "仅隔离合成原变量定义和明确记录口径，不代表真实研究方案审核或临床变量有效性。"


def definition():
    return dict(
        variable_key="recorded_symptom",
        label="原症状逐字区间",
        family="medical_records",
        field="symptom",
        value_kind="verbatim_text",
        record_window={"date_from": "2026-10-01", "date_to": "2026-10-21", "time_basis": "legacy_naive_calendar_dates_timezone_unknown"},
        temporal_policy="explicit_recorded_window_unknown_clock_separate",
        record_policy="all_recorded_candidates_no_automatic_winner",
        unit_policy="preserve_original_literal_no_conversion",
        declared_unit=None,
        missingness_policy="explicit_literal_evidence_else_unknown",
        extraction_instruction=BASIS + "\ufeff\r\n🧪保留否定与组合e\u0301。",
    )


def anchors():
    return dict(scope_id="00000000-0000-4000-8000-000000000001", scope_content_hash="a" * 64, scope_governance_hash="b" * 64)


def test_literal_definition_roundtrip_keeps_untouched_meaning_units_and_codepoints():
    raw = definition()
    assert VariableDefinition.model_validate(raw).model_dump() == raw
    assert VariableDefinition.model_validate({**raw, "declared_unit": "原文人工声明单位，未换算"}).declared_unit == "原文人工声明单位，未换算"


@pytest.mark.parametrize(
    "change",
    [
        {"field": "patient_id"},
        {"field": "doctor_id"},
        {"field": "identity"},
        {"field": "symptom;SELECT"},
        {"family": "laboratory_results"},
        {"value_kind": "normalized_numeric_value"},
        {"value_kind": "original_integer"},
        {"record_window": None},
        {"temporal_policy": "static_subject_field_without_event_clock"},
        {"record_policy": "latest"},
        {"missingness_policy": "fill_zero"},
        {"unit_policy": "convert_to_standard"},
        {"unit_policy": "preserve_original_literal_no_conversion", "declared_unit": ""},
        {"patient_id": 1},
        {"sql": "SELECT 1"},
        {"extraction_instruction": "\ud800"},
        {"variable_key": "InvalidKey"},
        {"variable_key": True},
    ],
)
def test_no_identity_sql_invented_kind_winner_missingness_or_time_coercion(change):
    with pytest.raises(ValidationError):
        VariableDefinition.model_validate({**definition(), **change})


@pytest.mark.parametrize("field,kind", [("sex", "original_integer"), ("birthday", "original_calendar_date")])
def test_static_subject_does_not_acquire_an_invented_event_clock(field, kind):
    value = {**definition(), "family": "patient_demographics", "field": field, "value_kind": kind, "record_window": None, "temporal_policy": "static_subject_field_without_event_clock"}
    assert VariableDefinition.model_validate(value).model_dump() == value
    for change in [{"declared_unit": "mg"}, {"record_window": definition()["record_window"]}]:
        with pytest.raises(ValidationError):
            VariableDefinition.model_validate({**value, **change})


@pytest.mark.parametrize(
    "variables", [[], [definition(), definition()], [{**definition(), "variable_key": "z"}, {**definition(), "variable_key": "a"}], [{**definition(), "variable_key": f"v_{n:03}"} for n in range(65)]]
)
def test_dictionary_requires_bounded_sorted_distinct_explicit_variables(variables):
    with pytest.raises(ValidationError):
        DictionaryCreate.model_validate({**anchors(), "title": "合成变量字典", "purpose": BASIS, "variables": variables, "basis_note": BASIS})


def test_dictionary_and_batch_have_separate_exact_reference_anchors_and_no_purpose_substitution():
    raw = {**anchors(), "title": "合成变量字典", "purpose": BASIS, "variables": [definition()], "basis_note": BASIS}
    assert DictionaryCreate.model_validate(raw).model_dump() == raw
    batch = {**anchors(), "variable_dictionary_id": "00000000-0000-4000-8000-000000000002", "dictionary_content_hash": "c" * 64, "dictionary_governance_hash": "d" * 64, "patient_ids": [1, 2]}
    assert BatchCapture.model_validate(batch).model_dump() == batch
    for change in [{"patient_ids": [True]}, {"patient_ids": [2, 1]}, {"patient_ids": []}, {"dictionary_content_hash": "c" * 63}, {"use": "cohort_criteria_review"}, {"source_id": "arbitrary"}]:
        with pytest.raises(ValidationError):
            BatchCapture.model_validate({**batch, **change})
    changed = copy.deepcopy(raw)
    changed["variables"][0]["record_window"]["date_to"] = "2027-10-02"
    with pytest.raises(ValidationError):
        DictionaryCreate.model_validate(changed)


def test_supported_fields_are_actual_declared_recorded_columns_without_importing_collection_sql():
    tree = ast.parse((Path(__file__).parents[1] / "app/ai/research_cohort_collection.py").read_text())
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "FAMILY_COLUMNS" for target in node.targets))
    supported = ast.literal_eval(assignment.value)
    for family, fields in VARIABLE_FIELDS.items():
        assert set(fields) <= set(supported[family])
        assert not any(key.endswith("_id") or key in {"identity", "name", "address", "phone"} for key in fields)


def test_declared_value_kind_matches_actual_legacy_sql_column_type_without_importing_models():
    tree = ast.parse((Path(__file__).parents[1] / "app/models.py").read_text())
    names = {"patient_demographics": "Patient", "registrations": "Registration", "admissions": "Admission", "medical_records": "MedicalRecord", "structured_medical_records": "StructuredMedicalRecord"}
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    kinds = {"original_integer": {"Integer", "SmallInteger", "BigInteger"}, "original_calendar_date": {"Date"}, "original_naive_clock": {"DateTime"}, "verbatim_text": {"Text", "String"}}
    for family, fields in VARIABLE_FIELDS.items():
        columns = {target.id: node.value for node in classes[names[family]].body if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}
        for field, kind in fields.items():
            column = columns[field]
            assert isinstance(column, ast.Call) and isinstance(column.func, ast.Name) and column.func.id == "Column"
            sql_type = column.args[0]
            if isinstance(sql_type, ast.Call):
                sql_type = sql_type.func
            assert isinstance(sql_type, ast.Name) and sql_type.id in kinds[kind], (family, field, kind, ast.unparse(column))
