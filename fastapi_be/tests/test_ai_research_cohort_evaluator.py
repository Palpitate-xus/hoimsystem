"""Pure three-valued recorded predicate edge cases, independent of DB access."""

import copy

import pytest

from app.ai.research_cohort_evaluator import evaluate_criteria


def source(records, families=None):
    return {"scope_original": {"payload": {"data_families": families or ["medical_records"], "patient_ids": [1]}}, "records": records}


def record(value=None, *, parent="patient_bound", window="recorded_calendar_in_scope"):
    return {"patient_id": 1, "family": "medical_records", "record_id": "local-test", "original": {"symptom": value}, "parent_binding": {"status": parent}, "window_status": window}


def atom(literal="否认", quantifier="any_record"):
    return dict(op="recorded_text_contains", family="medical_records", field="symptom", literal=literal, quantifier=quantifier)


def evaluate(records, root):
    return evaluate_criteria(source(records), {"schema_version": "research_recorded_criteria_v1", "root": root})["outcomes"][0]


@pytest.mark.parametrize("quantifier", ["any_record", "every_record"])
def test_missing_family_is_unknown_even_empty_universal(quantifier):
    assert evaluate([], atom(quantifier=quantifier))["truth"] == "unknown"


def test_literal_bom_crlf_astral_codepoint_offsets_and_negative_text_not_diagnosis():
    text = "\ufeff🧪原文\r\n否认胸痛"
    value = evaluate([record(text)], atom("否认胸痛"))
    proof = value["leaves"][0]["evidence"][0]
    assert value["truth"] == "true" and text[proof["start"] : proof["end"]] == proof["quote"] == "否认胸痛"
    assert proof["start"] == 6 and proof["recorded_value"] is None
    assert evaluate([record(text)], atom("明确诊断肺炎"))["truth"] == "false"
    assert value["interpretation"] == "recorded_criteria_only_not_clinical_eligibility"


@pytest.mark.parametrize("kwargs", [{"parent": "patient_mismatch"}, {"window": "unknown_clock"}, {"parent": "missing_parent"}])
def test_known_text_in_unresolved_scope_or_parent_does_not_make_known_match(kwargs):
    assert evaluate([record("否认", **kwargs)], atom())["truth"] == "unknown"


def test_kleene_and_or_not_keep_null_and_true_false_evidence_separate():
    values = [record("明确原文"), record(None)]
    no = atom("不存在的字符串", "every_record")
    yes = atom("明确原文")
    unknown = atom("不存在的字符串")
    assert evaluate(values, no)["truth"] == "false"
    assert evaluate(values, yes)["truth"] == "true"
    assert evaluate(values, unknown)["truth"] == "unknown"
    assert evaluate(values, {"op": "not", "child": unknown})["truth"] == "unknown"
    assert evaluate(values, {"op": "all", "children": [yes, unknown]})["truth"] == "unknown"
    assert evaluate(values, {"op": "all", "children": [no, unknown]})["truth"] == "false"
    assert evaluate(values, {"op": "any", "children": [yes, unknown]})["truth"] == "true"


def test_unsupported_family_scope_does_not_silently_grow_and_inputs_are_unchanged():
    value = source([record("原文")], ["patient_demographics"])
    before = copy.deepcopy(value)
    with pytest.raises(ValueError):
        evaluate_criteria(value, {"schema_version": "research_recorded_criteria_v1", "root": atom()})
    assert value == before


def test_evidence_construction_refuses_before_whole_repeated_output_exceeds_budget():
    from fastapi import HTTPException

    records = [record("原" * 2000) for _ in range(128)]
    root = {"op": "all", "children": [atom("原" * 2000) for _ in range(63)]}
    with pytest.raises(HTTPException) as error:
        evaluate(records, root)
    assert error.value.status_code == 413
