"""Synthetic typed NEWS2 bindings; no clinical records or external services."""

import copy

import pytest
from pydantic import ValidationError

from app.ai.news2_contract import News2Source, recipe_digest


def make_source():
    assessment, window, point, profile = (f"00000000-0000-4000-8000-{index:012d}" for index in range(1, 5))
    return {
        "assessment_id": assessment,
        "source_id": f"news2_assessment:{assessment}:" + "a" * 12,
        "content_hash": "a" * 64,
        "source_governance_hash": "b" * 64,
        "window_id": window,
        "window_source_id": f"observation_window:{window}:" + "c" * 12,
        "window_content_hash": "c" * 64,
        "as_of": "2026-10-20T12:00:00.654321Z",
        "point_id": point,
        "point_source_id": f"inpatient_observation:{point}:" + "d" * 12,
        "observed_at": "2026-10-20T11:00:00.123456Z",
        "recorded_at": "2026-10-20T11:00:01.123456Z",
        "rule_profile_id": profile,
        "rule_profile_source_id": f"risk_rule_profile:{profile}:" + "e" * 12,
        "rule_profile_content_hash": "e" * 64,
        "rule_profile_governance_hash": "f" * 64,
        "rule_id": "news2_2017",
        "recipe_digest": recipe_digest(),
        "age_at_observation_years": 40,
        "pregnancy_status": "not_pregnant",
        "spo2_scale": 1,
        "scale2_review": None,
        "measurements": {
            "respiratory_rate": {"value": "16", "unit": "/min", "absent_reason": None},
            "spo2": {"value": "98", "unit": "%", "absent_reason": None},
            "systolic_bp": {"value": "120", "unit": "mm[Hg]", "absent_reason": None},
            "pulse_rate": {"value": "70", "unit": "/min", "absent_reason": None},
            "temperature": {"value": "37.0", "unit": "Cel", "absent_reason": None},
        },
        "supplemental_oxygen": "no",
        "consciousness": {"system": "ACVPU", "code": "alert"},
        "conflict_codes": [],
    }


def scale2_review():
    return {
        "hypercapnic_respiratory_failure_confirmed": True,
        "clinical_decision_confirmed": True,
        "target_range": "88-92",
        "blood_gas_reference_hash": "1" * 64,
        "clinical_decision_reference_hash": "2" * 64,
    }


def test_exact_projection_keeps_zero_microseconds_and_decimal_lexical_form():
    source = make_source()
    source["measurements"]["pulse_rate"]["value"] = "0.00000000"
    assert News2Source.model_validate(source).model_dump() == source


@pytest.mark.parametrize("field,value", [("patient_id", 1), ("admission_id", "opaque-hospital-scope"), ("note", "patient narrative"), ("question", "external instructions"), ("evidence", [])])
def test_no_unapproved_identifiers_or_free_text(field, value):
    source = make_source()
    source[field] = value
    with pytest.raises(ValidationError):
        News2Source.model_validate(source)


@pytest.mark.parametrize(
    "field,value",
    [
        ("age_at_observation_years", True),
        ("age_at_observation_years", "40"),
        ("age_at_observation_years", 40.5),
        ("age_at_observation_years", 131),
        ("spo2_scale", True),
        ("spo2_scale", "1"),
        ("spo2_scale", 1.0),
        ("spo2_scale", 3),
        ("source_id", "news2_assessment:wrong"),
        ("recipe_digest", "0" * 64),
        ("window_id", "not-a-uuid"),
        ("rule_profile_content_hash", "0" * 64),
        ("point_source_id", "inpatient_observation:wrong"),
        ("conflict_codes", ["oxygen_device"]),
        ("conflict_codes", ["spo2", "spo2"]),
    ],
)
def test_rejects_inexact_structural_and_numeric_bindings(field, value):
    source = make_source()
    source[field] = value
    with pytest.raises(ValidationError):
        News2Source.model_validate(source)


@pytest.mark.parametrize("value", [True, 0, 12.5, "NaN", "Infinity", "1e2", "+12", "01", "1.123456789", "-1"])
def test_measurement_values_cannot_be_coerced_or_rounded(value):
    source = make_source()
    source["measurements"]["respiratory_rate"]["value"] = value
    with pytest.raises(ValidationError):
        News2Source.model_validate(source)


@pytest.mark.parametrize("value", ["2026-10-20T11:00Z", "2026-10-20T11:00:00", "2026-10-20T11:00:00.1234567Z", "2026-W43-2T11:00:00Z", "2026-10-20T12:00:00+01:00", "2026-02-30T11:00:00Z"])
def test_clocks_preserve_explicit_utc_without_truncation(value):
    source = make_source()
    source["observed_at"] = value
    with pytest.raises(ValidationError):
        News2Source.model_validate(source)


def test_unknowns_are_explicit_and_non_news2_measurements_are_rejected():
    source = make_source()
    source["measurements"]["spo2"] = {"value": None, "unit": "%", "absent_reason": "measurement_error"}
    assert News2Source.model_validate(source).measurements["spo2"].value is None
    for mutate in (
        lambda item: item["measurements"]["spo2"].update(absent_reason=None),
        lambda item: item["measurements"].update(heart_rate={"value": "70", "unit": "/min", "absent_reason": None}),
        lambda item: item["measurements"]["pulse_rate"].update(unit="bpm"),
        lambda item: item.update(consciousness={"system": "AVPU", "code": "new_confusion"}),
        lambda item: item.update(scale2_review=scale2_review()),
        lambda item: item.update(recorded_at="2026-10-20T13:00:00Z"),
    ):
        invalid = copy.deepcopy(source)
        mutate(invalid)
        with pytest.raises(ValidationError):
            News2Source.model_validate(invalid)


@pytest.mark.parametrize(
    "field,value", [("hypercapnic_respiratory_failure_confirmed", "true"), ("clinical_decision_confirmed", 1), ("target_range", "90-94"), ("blood_gas_reference_hash", "document text")]
)
def test_scale2_review_is_explicit_typed_and_hash_only(field, value):
    source = make_source()
    source.update(spo2_scale=2, scale2_review=scale2_review())
    source["scale2_review"][field] = value
    with pytest.raises(ValidationError):
        News2Source.model_validate(source)
