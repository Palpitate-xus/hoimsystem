"""Synthetic strict qSOFA identities, real clocks and explicit original GCS."""

import copy

import pytest
from pydantic import ValidationError

from app.ai.qsofa_contract import QsofaSource, recipe_digest


def make_source():
    assessment, window, point, profile, gcs = (f"00000000-0000-4000-8000-{index:012d}" for index in range(1, 6))
    return {
        "assessment_id": assessment,
        "source_id": f"qsofa_assessment:{assessment}:" + "a" * 12,
        "content_hash": "a" * 64,
        "source_governance_hash": "b" * 64,
        "window_id": window,
        "window_source_id": f"observation_window:{window}:" + "c" * 12,
        "window_content_hash": "c" * 64,
        "start_at": "2026-10-20T10:00:00.123456Z",
        "end_at": "2026-10-20T12:00:00.123456Z",
        "as_of": "2026-10-20T12:00:01.654321Z",
        "point_id": point,
        "point_source_id": f"inpatient_observation:{point}:" + "d" * 12,
        "point_content_hash": "d" * 64,
        "point_governance_hash": "1" * 64,
        "observed_at": "2026-10-20T11:00:00.123456Z",
        "recorded_at": "2026-10-20T11:00:01.123456Z",
        "rule_profile_id": profile,
        "rule_profile_source_id": f"risk_rule_profile:{profile}:" + "e" * 12,
        "rule_profile_content_hash": "e" * 64,
        "rule_profile_governance_hash": "f" * 64,
        "rule_id": "qsofa_sepsis3_2016",
        "recipe_digest": recipe_digest(),
        "evaluation_at": "2026-10-20T13:00:00.654321Z",
        "clinical_statements_recorded_at": "2026-10-20T13:00:00.654321Z",
        "clinical_scope_applies_to": "2026-10-20T11:00:00.123456Z",
        "review_mode": "current_retrospective_review",
        "historical_prediction": False,
        "age_at_observation_years": 40,
        "care_setting": "non_icu",
        "infection_status": "suspected",
        "scope_evidence_hash": "2" * 64,
        "measurements": {
            "respiratory_rate": {"value": "16", "unit": "/min", "absent_reason": None},
            "systolic_bp": {"value": "120", "unit": "mm[Hg]", "absent_reason": None},
        },
        "point_conflicts": [],
        "gcs": {
            "gcs_observation_id": gcs,
            "source_id": f"gcs_observation:{gcs}:" + "3" * 12,
            "content_hash": "3" * 64,
            "governance_hash": "4" * 64,
            "schema_version": "inpatient_gcs_v1",
            "observed_at": "2026-10-20T11:02:00.234567Z",
            "recorded_at": "2026-10-20T11:03:00.345678Z",
            "components": {"eye": {"score": 4, "absent_reason": None}, "verbal": {"score": 5, "absent_reason": None}, "motor": {"score": 6, "absent_reason": None}},
            "anchor_point_id": point,
            "anchor_point_source_id": f"inpatient_observation:{point}:" + "d" * 12,
            "anchor_point_content_hash": "d" * 64,
            "same_exam_confirmed": True,
            "same_exam_evidence_hash": "5" * 64,
            "conflict": False,
        },
        "gcs_interpretability": "confirmed",
        "gcs_review_evidence_hash": "6" * 64,
    }


def without_gcs(source):
    source.update(gcs=None, gcs_interpretability="unknown", gcs_review_evidence_hash=None)
    return source


def test_original_values_distinct_real_exam_clocks_and_current_retrospective_review_are_preserved():
    source = make_source()
    source["measurements"]["respiratory_rate"]["value"] = "0.00000000"
    assert source["gcs"]["observed_at"] != source["observed_at"]
    assert source["evaluation_at"] > source["as_of"]
    assert QsofaSource.model_validate(source).model_dump() == source
    source["age_at_observation_years"] = None
    assert QsofaSource.model_validate(source).age_at_observation_years is None


@pytest.mark.parametrize("field,value", [("patient_id", 1), ("admission_id", "private-original-admission"), ("question", "private-instruction"), ("pregnancy_status", "not_pregnant"), ("note", "private-clinical-note")])
def test_no_extra_identifiers_or_private_narrative(field, value):
    source = make_source()
    source[field] = value
    with pytest.raises(ValidationError):
        QsofaSource.model_validate(source)


@pytest.mark.parametrize(
    "field,value",
    [
        ("age_at_observation_years", True), ("age_at_observation_years", "40"), ("age_at_observation_years", 40.5), ("age_at_observation_years", 131),
        ("source_id", "news2_assessment:wrong"), ("recipe_digest", "0" * 64), ("window_id", "not-a-uuid"),
        ("point_content_hash", "0" * 64), ("point_governance_hash", "not-a-hash"), ("point_conflicts", ["temperature"]), ("point_conflicts", ["systolic_bp", "systolic_bp"]),
        ("historical_prediction", True), ("historical_prediction", 0), ("review_mode", "historical_prediction"),
        ("clinical_statements_recorded_at", "2026-10-20T12:00:00Z"), ("clinical_scope_applies_to", "2026-10-20T11:01:00Z"),
        ("evaluation_at", "2026-10-20T11:00:00Z"), ("recorded_at", "2026-10-20T13:00:00Z"),
    ],
)
def test_invalid_identity_scope_and_time_bindings_fail(field, value):
    source = make_source()
    source[field] = value
    with pytest.raises(ValidationError):
        QsofaSource.model_validate(source)


@pytest.mark.parametrize("value", [True, 0, 12.5, "NaN", "Infinity", "1e2", "+12", "01", "1.123456789", "-1"])
def test_original_decimal_values_not_coerced_or_rounded(value):
    source = make_source()
    source["measurements"]["respiratory_rate"]["value"] = value
    with pytest.raises(ValidationError):
        QsofaSource.model_validate(source)


@pytest.mark.parametrize("value", ["2026-10-20T11:00Z", "2026-10-20T11:00:00", "2026-10-20T11:00:00.1234567Z", "2026-W43-2T11:00:00Z", "2026-10-20T12:00:00+01:00", "2026-02-30T11:00:00Z"])
def test_clock_format_never_truncates_or_infers_utc(value):
    source = make_source()
    source["observed_at"] = value
    with pytest.raises(ValidationError):
        QsofaSource.model_validate(source)


@pytest.mark.parametrize("field,value", [("same_exam_confirmed", 1), ("same_exam_confirmed", False), ("anchor_point_id", "00000000-0000-4000-8000-999999999999"), ("anchor_point_content_hash", "0" * 64), ("observed_at", "2026-10-20T09:59:59Z"), ("observed_at", "2026-10-20T12:00:01Z"), ("recorded_at", "2026-10-20T13:00:00Z"), ("conflict", 0)])
def test_gcs_original_anchor_clocks_and_boolean_confirmation_are_required(field, value):
    source = make_source()
    source["gcs"][field] = value
    with pytest.raises(ValidationError):
        QsofaSource.model_validate(source)


@pytest.mark.parametrize("component,value", [("eye", 0), ("eye", 5), ("verbal", 6), ("motor", 7), ("motor", True), ("motor", "6"), ("eye", 4.0)])
def test_gcs_component_ranges_and_types_are_not_inferred(component, value):
    source = make_source()
    source["gcs"]["components"][component]["score"] = value
    with pytest.raises(ValidationError):
        QsofaSource.model_validate(source)


def test_explicit_nt_missing_measurement_and_no_gcs_remain_distinct():
    source = make_source()
    source["gcs"]["components"]["verbal"] = {"score": None, "absent_reason": "not_testable"}
    source["measurements"]["systolic_bp"] = {"value": None, "unit": "mm[Hg]", "absent_reason": "measurement_error"}
    assert QsofaSource.model_validate(source).model_dump() == source
    assert QsofaSource.model_validate(without_gcs(copy.deepcopy(source))).gcs is None
    invalid = copy.deepcopy(source)
    invalid["gcs"]["components"]["verbal"]["score"] = 1
    with pytest.raises(ValidationError):
        QsofaSource.model_validate(invalid)
    invalid = without_gcs(copy.deepcopy(source))
    invalid["gcs_interpretability"] = "confirmed"
    with pytest.raises(ValidationError):
        QsofaSource.model_validate(invalid)


@pytest.mark.parametrize("change", ["both_absent", "both_present", "wrong_unit", "unknown_metric", "gcs_without_review"])
def test_exact_original_quantity_and_review_presence(change):
    source = make_source()
    if change == "both_absent":
        source["measurements"]["systolic_bp"]["value"] = None
    elif change == "both_present":
        source["measurements"]["systolic_bp"]["absent_reason"] = "unknown"
    elif change == "wrong_unit":
        source["measurements"]["systolic_bp"]["unit"] = "kPa"
    elif change == "unknown_metric":
        source["measurements"]["avpu"] = {"value": "15", "unit": "score", "absent_reason": None}
    else:
        source["gcs_review_evidence_hash"] = None
    with pytest.raises(ValidationError):
        QsofaSource.model_validate(source)
