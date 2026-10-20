"""Synthetic immutable AKI input fixtures and strict boundary contracts."""

import copy
import uuid

import pytest
from pydantic import ValidationError

from app.ai.aki_contract import AkiSource, canonical_json, recipe_digest


def identifier(value):
    return str(uuid.UUID(int=value))


def creatinine(value="1", unit="mg/dL", time="2026-10-17T00:00:00Z", number=10):
    digest = str(number % 10) * 64
    return {
        "lab_source_id": identifier(number),
        "source_id": f"inpatient_lab:{identifier(number)}:{digest[:12]}",
        "content_hash": digest,
        "governance_hash": "a" * 64,
        "collected_at_utc": time,
        "registered_at": "2026-10-17T00:00:00Z",
        "available_at": "2026-10-17T00:00:00Z",
        "mapping_id": identifier(20),
        "mapping_content_hash": "b" * 64,
        "mapping_governance_hash": "c" * 64,
        "identity_hash": "d" * 64,
        "value": value,
        "unit": unit,
        "conflict": False,
    }


def urine(start="2026-10-16T00:00:00Z", end="2026-10-17T00:00:00Z", volume="2000", number=30):
    return {
        "interval_id": identifier(number),
        "source_id": f"urine_interval:{identifier(number)}:{'e' * 12}",
        "content_hash": "e" * 64,
        "governance_hash": "f" * 64,
        "start_at": start,
        "end_at": end,
        "recorded_at": "2026-10-17T00:00:00Z",
        "volume_ml": volume,
        "absent_reason": None if volume is not None else "not_performed",
        "collection_completeness": "complete",
        "patient_total": True,
    }


def make_source():
    return {
        "assessment_id": identifier(1),
        "source_id": f"aki_assessment:{identifier(1)}:{'a' * 12}",
        "content_hash": "a" * 64,
        "source_governance_hash": "b" * 64,
        "window_id": identifier(2),
        "window_source_id": f"observation_window:{identifier(2)}:{'c' * 12}",
        "window_content_hash": "c" * 64,
        "start_at": "2026-10-10T00:00:00Z",
        "end_at": "2026-10-17T00:00:00Z",
        "as_of": "2026-10-17T00:00:00Z",
        "evaluation_at": "2026-10-17T00:00:00Z",
        "rule_profile_id": identifier(3),
        "rule_profile_source_id": f"risk_rule_profile:{identifier(3)}:{'d' * 12}",
        "rule_profile_content_hash": "d" * 64,
        "rule_profile_governance_hash": "e" * 64,
        "rule_id": "kdigo_aki_2012",
        "recipe_digest": recipe_digest(),
        "age_at_evaluation_years": 40,
        "creatinine_review": {"serum_creatinine_confirmed": True, "evidence_hash": "f" * 64},
        "index_creatinine": creatinine(),
        "comparison_48h": creatinine(time="2026-10-16T00:00:00Z", number=11),
        "baseline_creatinine": creatinine(time="2026-10-10T00:00:00Z", number=12),
        "baseline_mode": "observed_within_7d",
        "baseline_review": None,
        "weight": {
            "point_id": identifier(4),
            "source_id": f"inpatient_observation:{identifier(4)}:{'a' * 12}",
            "content_hash": "a" * 64,
            "governance_hash": "b" * 64,
            "observed_at": "2026-10-15T00:00:00Z",
            "recorded_at": "2026-10-17T00:00:00Z",
            "value": "70",
            "unit": "kg",
            "absent_reason": None,
            "conflict": False,
        },
        "weight_applicability_confirmed": True,
        "weight_evidence_hash": "c" * 64,
        "urine_intervals": [urine()],
        "urine_coverage_issues": [],
        "rrt": {"status": "not_initiated", "started_at": None, "acute_aki_confirmed": None, "evidence_hash": "d" * 64},
    }


def test_exact_projection_retains_decimal_tail_and_nullable_qualitative_unit():
    source = make_source()
    source["index_creatinine"].update(value="1.00000000")
    source["baseline_creatinine"].update(value=None, unit=None)
    actual = AkiSource.model_validate(source).model_dump()
    assert actual == source
    assert "patient_id" not in canonical_json(actual) and "admission_id" not in canonical_json(actual)


@pytest.mark.parametrize(
    "field,value",
    [
        ("patient_id", 1),
        ("note", "private text"),
        ("age_at_evaluation_years", True),
        ("age_at_evaluation_years", "40"),
        ("age_at_evaluation_years", 131),
        ("recipe_digest", "0" * 64),
        ("rule_id", "news2_2017"),
        ("assessment_id", "01"),
        ("source_id", "wrong"),
        ("window_source_id", "wrong"),
        ("rule_profile_source_id", "wrong"),
    ],
)
def test_strict_identity_scope_and_extra_inputs_rejected(field, value):
    source = make_source()
    source[field] = value
    with pytest.raises(ValidationError):
        AkiSource.model_validate(source)


@pytest.mark.parametrize("value", [True, 1, 1.2, "NaN", "Infinity", "1e2", "01", "1.000000000", " 1", "+1"])
def test_no_numeric_coercion_or_lossy_decimal_input(value):
    source = make_source()
    source["index_creatinine"]["value"] = value
    with pytest.raises(ValidationError):
        AkiSource.model_validate(source)


@pytest.mark.parametrize(
    "value", ["2026-10-17", "2026-10-17T00:00Z", "2026-10-17T00:00:00", "2026-10-17T00:00:00.1234567Z", "2026-W42-6T00:00:00Z", "2026-10-17T00:00:00+01:00", "2026-10-17T00:00:00+00:99"]
)
def test_explicit_utc_clock_without_silent_normalization(value):
    source = make_source()
    source["as_of"] = value
    with pytest.raises(ValidationError):
        AkiSource.model_validate(source)


@pytest.mark.parametrize(
    "change", ["future_lab", "pre_window_index", "future_weight", "outside_urine", "duplicate_urine", "duplicate_issue", "unknown_issue", "future_rrt", "overlong_window", "late_evaluation"]
)
def test_time_membership_and_engineering_limits_are_fail_closed(change):
    source = make_source()
    if change == "future_lab":
        source["index_creatinine"]["available_at"] = "2026-10-17T00:00:00.000001Z"
    elif change == "pre_window_index":
        source["index_creatinine"]["collected_at_utc"] = "2026-10-09T23:59:59Z"
    elif change == "future_weight":
        source["weight"]["recorded_at"] = "2026-10-17T00:00:00.000001Z"
    elif change == "outside_urine":
        source["urine_intervals"][0]["start_at"] = "2026-10-09T23:59:59Z"
    elif change == "duplicate_urine":
        source["urine_intervals"] *= 2
    elif change == "duplicate_issue":
        source["urine_coverage_issues"] = ["gap", "gap"]
    elif change == "unknown_issue":
        source["urine_coverage_issues"] = ["normal"]
    elif change == "future_rrt":
        source["rrt"]["started_at"] = "2026-10-17T00:00:00.000001Z"
    elif change == "overlong_window":
        source["start_at"] = "2026-10-09T23:59:59.999999Z"
    elif change == "late_evaluation":
        source["evaluation_at"] = "2026-10-17T00:00:00.000001Z"
    with pytest.raises(ValidationError):
        AkiSource.model_validate(source)


def test_maximum_64_original_intervals_is_explicit_not_truncation():
    source = make_source()
    source["urine_intervals"] = [copy.deepcopy(urine(number=100 + index)) for index in range(64)]
    assert len(AkiSource.model_validate(source).urine_intervals) == 64
    source["urine_intervals"].append(urine(number=999))
    with pytest.raises(ValidationError):
        AkiSource.model_validate(source)
