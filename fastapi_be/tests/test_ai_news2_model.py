"""Boundary fixtures transcribed from RCP 2017 Charts 1 and 2, not RECIPE."""

import copy
import hashlib

import pytest

from app.ai.news2_config import runtime_descriptor, runtime_from_descriptor
from app.ai.news2_contract import COMPONENT_KEYS, News2Analysis, canonical_json
from app.ai.news2_model import generation_result_for_analysis, news2_values, validate_analysis_binding, validate_runtime
from tests.test_ai_news2_contract import make_source, scale2_review


def component(result, key):
    return next(item for item in result["components"] if item["key"] == key)


def analysis_for(source=None):
    source = source or make_source()
    return News2Analysis.model_validate(
        {
            "schema_version": "1",
            "source_binding": source,
            **news2_values(source),
            "local_runtime": runtime_from_descriptor(runtime_descriptor()),
            "instructions_digest": hashlib.sha256(b"complete synthetic Prompt").hexdigest(),
        }
    )


# Source: https://www.rcp.ac.uk/media/alxev00t/news2-chart-1_the-news-scoring-system_0_0.pdf
@pytest.mark.parametrize(
    "key,value,score",
    [("respiratory_rate", str(value), score) for value, score in [(0, 3), (8, 3), (9, 1), (11, 1), (12, 0), (20, 0), (21, 2), (24, 2), (25, 3), (200, 3)]]
    + [("spo2", str(value), score) for value, score in [(0, 3), (91, 3), (92, 2), (93, 2), (94, 1), (95, 1), (96, 0), (100, 0)]]
    + [("systolic_bp", str(value), score) for value, score in [(0, 3), (90, 3), (91, 2), (100, 2), (101, 1), (110, 1), (111, 0), (219, 0), (220, 3)]]
    + [("pulse_rate", str(value), score) for value, score in [(0, 3), (40, 3), (41, 1), (50, 1), (51, 0), (90, 0), (91, 1), (110, 1), (111, 2), (130, 2), (131, 3)]]
    + [("temperature", value, score) for value, score in [("-1", 3), ("35.0", 3), ("35.1", 1), ("36.0", 1), ("36.1", 0), ("38.0", 0), ("38.1", 1), ("39.0", 1), ("39.1", 2), ("45", 2)]],
)
def test_all_primary_band_boundaries_match_official_score(key, value, score):
    source = make_source()
    source["measurements"][key]["value"] = value
    result = news2_values(source)
    assert component(result, key)["score"] == score
    assert result["total_score"] == score and result["observed_subtotal"] == score
    assert result["scored_component_count"] == 7 and result["score_is_lower_bound"] is False
    assert [item["key"] for item in result["components"]] == list(COMPONENT_KEYS)


@pytest.mark.parametrize("oxygen", ["no", "yes"])
@pytest.mark.parametrize(
    "value,low,high", [(0, 3, 3), (83, 3, 3), (84, 2, 2), (85, 2, 2), (86, 1, 1), (87, 1, 1), (88, 0, 0), (92, 0, 0), (93, 0, 1), (94, 0, 1), (95, 0, 2), (96, 0, 2), (97, 0, 3), (100, 0, 3)]
)
def test_scale2_air_and_oxygen_branches_are_distinct(value, low, high, oxygen):
    source = make_source()
    source.update(spo2_scale=2, scale2_review=scale2_review(), supplemental_oxygen=oxygen)
    source["measurements"]["spo2"]["value"] = str(value)
    result = news2_values(source)
    expected = low if oxygen == "no" else high
    assert component(result, "spo2")["score"] == expected
    assert component(result, "supplemental_oxygen")["score"] == (2 if oxygen == "yes" else 0)
    assert result["total_score"] == expected + (2 if oxygen == "yes" else 0)


@pytest.mark.parametrize(
    "key,value",
    [("respiratory_rate", "8.5"), ("respiratory_rate", "12.5"), ("spo2", "91.5"), ("systolic_bp", "100.5"), ("pulse_rate", "90.01"), ("temperature", "35.05"), ("temperature", "37.12345678")],
)
def test_no_rounding_or_unpublished_continuous_extensions(key, value):
    source = make_source()
    source["measurements"][key]["value"] = value
    result = news2_values(source)
    assert component(result, key)["raw_value"] == value
    assert component(result, key)["score"] is None and component(result, key)["status"] == "outside_precision"
    assert result["calculation_status"] == "insufficient_data" and result["total_score"] is None
    assert result["observed_subtotal"] == 0 and result["minimum_classification"] is None and result["score_is_lower_bound"] is True


def test_mathematically_equal_trailing_zero_precision_is_preserved():
    source = make_source()
    source["measurements"]["pulse_rate"]["value"] = "90.00000000"
    source["measurements"]["temperature"]["value"] = "37.10000000"
    result = news2_values(source)
    assert result["total_score"] == 0
    assert component(result, "pulse_rate")["raw_value"] == "90.00000000"
    assert component(result, "temperature")["raw_value"] == "37.10000000"


@pytest.mark.parametrize(
    "system,code,score",
    [
        ("ACVPU", "alert", 0),
        ("ACVPU", "new_confusion", 3),
        ("ACVPU", "voice", 3),
        ("ACVPU", "pain", 3),
        ("ACVPU", "unresponsive", 3),
        ("AVPU", "alert", None),
        ("AVPU", "voice", 3),
        ("AVPU", "pain", 3),
        ("AVPU", "unresponsive", 3),
    ],
)
def test_avpu_alert_does_not_silently_exclude_new_confusion(system, code, score):
    source = make_source()
    source["consciousness"] = {"system": system, "code": code}
    result = news2_values(source)
    assert component(result, "consciousness")["score"] == score
    assert result["total_score"] == score


@pytest.mark.parametrize("review", [None, {**scale2_review(), "hypercapnic_respiratory_failure_confirmed": False}, {**scale2_review(), "clinical_decision_confirmed": False}])
def test_scale2_requires_both_documented_decision_and_confirmed_hypercapnia(review):
    source = make_source()
    source.update(spo2_scale=2, scale2_review=review)
    result = news2_values(source)
    assert component(result, "spo2")["status"] == "requires_review"
    assert result["total_score"] is None


@pytest.mark.parametrize("value,blocked", [(92, False), (93, True)])
@pytest.mark.parametrize("problem", ["unknown", "conflict"])
def test_scale2_spo2_depends_on_unknown_or_conflicting_oxygen_only_above_92(value, blocked, problem):
    source = make_source()
    source.update(spo2_scale=2, scale2_review=scale2_review())
    source["measurements"]["spo2"]["value"] = str(value)
    source.update(supplemental_oxygen="unknown" if problem == "unknown" else "yes", conflict_codes=["supplemental_oxygen"] if problem == "conflict" else [])
    result = news2_values(source)
    assert (component(result, "spo2")["score"] is None) == blocked
    assert component(result, "supplemental_oxygen")["score"] is None
    assert result["total_score"] is None


@pytest.mark.parametrize("key", COMPONENT_KEYS)
def test_each_relevant_same_time_conflict_blocks_aggregate(key):
    source = make_source()
    source["conflict_codes"] = [key]
    result = news2_values(source)
    assert component(result, key)["score"] is None and component(result, key)["status"] == "conflict"
    assert result["total_score"] is None and result["scored_component_count"] == 6


@pytest.mark.parametrize(
    "age,pregnancy,status,scope",
    [
        (15, "not_applicable", "outside_scope", "outside_scope"),
        (0, "not_pregnant", "outside_scope", "outside_scope"),
        (40, "pregnant", "outside_scope", "outside_scope"),
        (40, "unknown", "insufficient_data", "unknown"),
        (16, "not_pregnant", "computed", "within_declared_scope"),
        (130, "not_applicable", "computed", "within_declared_scope"),
    ],
)
def test_population_scope_never_becomes_an_assumed_adult_nonpregnant_status(age, pregnancy, status, scope):
    source = make_source()
    source.update(age_at_observation_years=age, pregnancy_status=pregnancy)
    result = news2_values(source)
    assert result["calculation_status"] == status and result["scope_status"] == scope
    if scope != "within_declared_scope":
        assert all(item["score"] is None for item in result["components"])
        assert result["observed_subtotal"] is result["total_score"] is result["minimum_classification"] is None
        assert result["scored_component_count"] == 0 and result["score_is_lower_bound"] is False


@pytest.mark.parametrize(
    "values,expected",
    [
        ({}, "zero"),
        ({"pulse_rate": "91"}, "low"),
        ({"respiratory_rate": "25"}, "single_red"),
        ({"respiratory_rate": "25", "pulse_rate": "91"}, "single_red"),
        ({"respiratory_rate": "25", "spo2": "92"}, "medium"),
        ({"respiratory_rate": "25", "spo2": "91"}, "medium"),
        ({"respiratory_rate": "25", "spo2": "91", "temperature": "36.0"}, "high"),
    ],
)
def test_complete_total_categories_and_single_three_priority(values, expected):
    source = make_source()
    for key, value in values.items():
        source["measurements"][key]["value"] = value
    result = news2_values(source)
    assert result["classification"] == result["minimum_classification"] == expected


def test_all_seven_items_can_reach_twenty_without_oxygen_counted_twice():
    source = make_source()
    for key, value in {"respiratory_rate": "25", "spo2": "91", "systolic_bp": "90", "pulse_rate": "131", "temperature": "35.0"}.items():
        source["measurements"][key]["value"] = value
    source.update(supplemental_oxygen="yes", consciousness={"system": "ACVPU", "code": "new_confusion"})
    result = news2_values(source)
    assert result["total_score"] == 20 and result["classification"] == "high"
    assert len(result["red_flag_components"]) == 6 and "supplemental_oxygen" not in result["red_flag_components"]


def test_known_subtotal_six_with_missing_component_remains_visible_as_lower_bound():
    source = make_source()
    source["measurements"]["respiratory_rate"]["value"] = "25"
    source["measurements"]["spo2"]["value"] = "91"
    source["measurements"].pop("temperature")
    result = news2_values(source)
    assert result["total_score"] is result["classification"] is None
    assert result["observed_subtotal"] == 6 and result["scored_component_count"] == 6
    assert result["minimum_classification"] == "medium" and result["score_is_lower_bound"] is True
    assert result["red_flag_components"] == ["respiratory_rate", "spo2"]


@pytest.mark.parametrize("absent_reason", ["unknown", "not_performed", "measurement_error"])
def test_explicit_missing_reason_preserved_instead_of_normal_zero(absent_reason):
    source = make_source()
    source["measurements"]["temperature"].update(value=None, absent_reason=absent_reason)
    result = news2_values(source)
    assert component(result, "temperature")["score"] is None
    assert component(result, "temperature")["reason"] == "absent_" + absent_reason


def test_all_missing_is_not_a_complete_zero_score_or_low_risk():
    source = make_source()
    source.update(measurements={}, supplemental_oxygen="unknown", consciousness=None)
    result = news2_values(source)
    assert result["calculation_status"] == "insufficient_data" and result["scored_component_count"] == 0
    assert result["observed_subtotal"] == 0 and result["minimum_classification"] is None and result["total_score"] is None


@pytest.mark.parametrize(
    "field",
    [
        "total_score",
        "observed_subtotal",
        "scored_component_count",
        "minimum_classification",
        "classification",
        "red_flag_components",
        "source_binding",
        "component_score",
        "component_value",
        "component_time",
        "instructions_digest",
        "warnings",
        "attribution",
    ],
)
def test_binding_recomputes_all_numbers_original_values_and_provenance(field):
    source = make_source()
    original = analysis_for(source)
    changed = copy.deepcopy(original.model_dump())
    if field in {"total_score", "observed_subtotal"}:
        changed[field] = 19
    elif field == "scored_component_count":
        changed[field] = 6
    elif field in {"minimum_classification", "classification"}:
        changed[field] = "high"
    elif field == "red_flag_components":
        changed[field] = ["respiratory_rate"]
    elif field == "source_binding":
        changed[field]["source_governance_hash"] = "0" * 64
    elif field == "component_score":
        changed["components"][0]["score"] = 3
    elif field == "component_value":
        changed["components"][0]["raw_value"] = "25"
    elif field == "component_time":
        changed["components"][0]["observed_at"] = "2026-10-20T11:00:01Z"
    elif field == "instructions_digest":
        changed[field] = "0" * 64
    elif field == "warnings":
        changed[field] = []
    else:
        changed[field] = "RCP certified"
    with pytest.raises(ValueError):
        validate_analysis_binding(changed, source, original.instructions_digest, original.local_runtime.model_version)


def test_different_reported_deployment_versions_are_hashed_without_requiring_hospital_versions():
    runtime = analysis_for().local_runtime.model_dump()
    runtime.update(python_version="3.12.9", engine_versions={"fastapi": "0.136.1", "pydantic": "2.12.4"})
    identity = {key: value for key, value in runtime.items() if key not in {"runtime_digest", "model_version"}}
    runtime["runtime_digest"] = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    runtime["model_version"] = "news2:" + runtime["runtime_digest"]
    validate_runtime(runtime)
    runtime["implementation"]["news2_model.py"] = "0" * 64
    with pytest.raises(ValueError):
        validate_runtime(runtime)


def test_prompt_changes_provenance_not_arithmetic_and_template_is_deterministic():
    source = make_source()
    analysis = analysis_for(source)
    validate_analysis_binding(analysis, source, analysis.instructions_digest, analysis.local_runtime.model_version)
    result = generation_result_for_analysis(analysis)
    assert result["sections"][0]["source_ids"] == [source["source_id"], source["point_source_id"], source["rule_profile_source_id"]]
    assert "0分" in result["summary"] and result["warnings"] == analysis.warnings
    assert "未提供" not in result["summary"]
