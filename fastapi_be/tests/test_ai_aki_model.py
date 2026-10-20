"""KDIGO 2012 section 2.1/Table 2 boundaries and declared software policies."""

import copy
import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from app.ai.aki_config import runtime_descriptor, runtime_from_descriptor
from app.ai.aki_contract import CRITERION_KEYS, AkiAnalysis
from app.ai.aki_model import aki_values, generation_result_for_analysis, validate_analysis_binding, validate_runtime
from tests.test_ai_aki_contract import creatinine, make_source, urine


def criterion(result, key):
    return next(value for value in result["criteria"] if value["key"] == key)


def analysis_for(source=None):
    source = source or make_source()
    return AkiAnalysis.model_validate(
        {
            "schema_version": "1",
            "source_binding": source,
            **aki_values(source),
            "local_runtime": runtime_from_descriptor(runtime_descriptor()),
            "instructions_digest": hashlib.sha256(b"complete synthetic Prompt").hexdigest(),
        }
    )


@pytest.mark.parametrize(
    "unit,current,previous,met",
    [
        ("mg/dL", "1.29999999", "1", False),
        ("mg/dL", "1.3", "1", True),
        ("mg/dL", "1.30000000", "1.00000000", True),
        ("umol/L", "126.49999999", "100", False),
        ("umol/L", "126.5", "100", True),
        ("umol/L", "126.51999999", "100", True),
    ],
)
def test_48_hour_original_native_thresholds_without_hidden_conversion(unit, current, previous, met):
    source = make_source()
    source["index_creatinine"].update(value=current, unit=unit)
    source["comparison_48h"].update(value=previous, unit=unit, collected_at_utc="2026-10-15T00:00:00Z")
    result = criterion(aki_values(source), "creatinine_48h")
    assert (result["status"] == "met") is met
    assert result["evidence"]["elapsed_microseconds"] == 48 * 3_600_000_000
    assert result["evidence"]["threshold"] == ("0.3" if unit == "mg/dL" else "26.5")


@pytest.mark.parametrize("value,stage", [("1.49999999", None), ("1.5", 1), ("1.95", 1), ("1.99999999", 1), ("2", 2), ("2.95", 2), ("2.99999999", 2), ("3", 3), ("3.00000000", 3)])
def test_unrounded_ratio_thresholds_have_no_artificial_decimal_gap(value, stage):
    source = make_source()
    source["index_creatinine"]["value"] = value
    result = criterion(aki_values(source), "creatinine_ratio_7d")
    assert result["stage"] == stage
    assert result["status"] == ("met" if stage else "not_met_in_selected_data")


@pytest.mark.parametrize(
    "unit,value,previous,met",
    [
        ("mg/dL", "3.99999999", "3.6", False),
        ("mg/dL", "4", "3.7", True),
        ("umol/L", "353.59999999", "300", False),
        ("umol/L", "353.6", "300", True),
        ("umol/L", "353.7", "300", True),
        ("umol/L", "354", "300", True),
    ],
)
def test_table2_absolute_stage3_si_is_353_point_6_not_prose_rounding(unit, value, previous, met):
    source = make_source()
    source["index_creatinine"].update(value=value, unit=unit)
    source["comparison_48h"].update(value=previous, unit=unit)
    result = criterion(aki_values(source), "creatinine_absolute_stage3")
    assert (result["status"] == "met") is met


def test_chronic_high_creatinine_plus_urine_aki_does_not_satisfy_absolute_screatinine_stage3():
    source = make_source()
    source["index_creatinine"]["value"] = "4.1"
    source["comparison_48h"]["value"] = source["baseline_creatinine"]["value"] = "4"
    source["urine_intervals"] = [urine(start="2026-10-16T18:00:00Z", volume="100")]
    result = aki_values(source)
    assert criterion(result, "creatinine_absolute_stage3")["status"] == "not_met_in_selected_data"
    assert result["minimum_stage"] == 1 and result["stage_is_lower_bound"] is True


@pytest.mark.parametrize("key,time", [("comparison_48h", "2026-10-14T23:59:59.999999Z"), ("baseline_creatinine", "2026-10-09T23:59:59.999999Z"), ("comparison_48h", "2026-10-17T00:00:00Z")])
def test_exact_clock_edges_do_not_round_into_eligible_acute_pairs(key, time):
    source = make_source()
    source["comparison_48h"] = None if key == "baseline_creatinine" else source["comparison_48h"]
    source["index_creatinine"]["value"] = "3"
    source[key] = creatinine(time=time, number=14)
    key_name = "creatinine_48h" if key == "comparison_48h" else "creatinine_ratio_7d"
    assert criterion(aki_values(source), key_name)["status"] == "unknown"


@pytest.mark.parametrize("review", [None, {"rise_within_7d_confirmed": False, "evidence_hash": "a" * 64}, {"rise_within_7d_confirmed": True, "evidence_hash": "a" * 64}])
def test_explicit_older_actual_baseline_needs_recent_rise_attestation(review):
    source = make_source()
    source.update(baseline_mode="presumed_within_7d", baseline_review=review)
    source["baseline_creatinine"]["collected_at_utc"] = "2025-10-17T00:00:00Z"
    source["index_creatinine"]["value"] = "2"
    result = criterion(aki_values(source), "creatinine_ratio_7d")
    assert result["status"] == ("met" if review and review["rise_within_7d_confirmed"] else "unknown")


@pytest.mark.parametrize("problem", ["qualitative", "zero", "negative", "unsupported_unit", "mixed_unit", "identity", "index_conflict", "comparison_conflict", "no_serum_review"])
def test_unknown_or_incomparable_creatinine_is_never_normalized_or_zero_filled(problem):
    source = make_source()
    source["index_creatinine"]["value"] = "3"
    if problem == "qualitative":
        source["index_creatinine"].update(value=None, unit=None)
    elif problem in {"zero", "negative"}:
        source["index_creatinine"]["value"] = "0" if problem == "zero" else "-1"
    elif problem == "unsupported_unit":
        source["index_creatinine"]["unit"] = "mg/L"
    elif problem == "mixed_unit":
        source["comparison_48h"]["unit"] = "umol/L"
    elif problem == "identity":
        source["comparison_48h"]["identity_hash"] = "0" * 64
    elif problem == "index_conflict":
        source["index_creatinine"]["conflict"] = True
    elif problem == "comparison_conflict":
        source["comparison_48h"]["conflict"] = True
    else:
        source["creatinine_review"]["serum_creatinine_confirmed"] = False
    assert criterion(aki_values(source), "creatinine_48h")["status"] == "unknown"


@pytest.mark.parametrize(
    "hours,volume,key,met",
    [
        (6, "210", "urine_6h", False),
        (6, "209.99999999", "urine_6h", True),
        (12, "420", "urine_12h", False),
        (12, "419.99999999", "urine_12h", True),
        (24, "504", "urine_24h", False),
        (24, "503.99999999", "urine_24h", True),
        (12, "0", "anuria_12h", True),
        (12, "0.00000001", "anuria_12h", False),
    ],
)
def test_original_urine_thresholds_are_strict_with_inclusive_duration(hours, volume, key, met):
    source = make_source()
    source["urine_intervals"] = [urine(start=(datetime(2026, 10, 17, tzinfo=UTC) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z"), volume=volume)]
    result = criterion(aki_values(source), key)
    assert (result["status"] == "met") is met
    assert result["evidence"]["elapsed_microseconds"] == hours * 3_600_000_000


def test_no_proration_of_11_hour_59_minute_59_point_999999_second_zero_interval():
    source = make_source()
    source["urine_intervals"] = [urine(start="2026-10-16T12:00:00.000001Z", volume="0")]
    assert criterion(aki_values(source), "anuria_12h")["status"] == "unknown"
    assert criterion(aki_values(source), "urine_12h")["status"] == "unknown"


def test_whole_boundary_subchain_detected_without_claiming_hourly_persistence():
    source = make_source()
    source["urine_intervals"] = [
        urine(start="2026-10-16T00:00:00Z", end="2026-10-16T06:00:00Z", volume="0", number=31),
        urine(start="2026-10-16T06:00:00Z", end="2026-10-16T12:00:00Z", volume="0", number=32),
        urine(start="2026-10-16T12:00:00Z", volume="2000", number=33),
    ]
    result = aki_values(source)
    assert criterion(result, "anuria_12h")["stage"] == 3
    assert criterion(result, "anuria_12h")["evidence"]["interval_end_at"] == "2026-10-16T12:00:00Z"
    assert criterion(result, "urine_24h")["status"] == "not_met_in_selected_data"


@pytest.mark.parametrize("problem", ["not_selected", "zero", "unknown", "conflict", "unattested", "missing_evidence", "late_weight"])
def test_anuria_does_not_depend_on_weight_but_per_kg_criteria_do(problem):
    source = make_source()
    source["urine_intervals"] = [urine(volume="0")]
    if problem == "not_selected":
        source["weight"] = None
    elif problem == "zero":
        source["weight"]["value"] = "0"
    elif problem == "unknown":
        source["weight"].update(value=None, absent_reason="not_performed")
    elif problem == "conflict":
        source["weight"]["conflict"] = True
    elif problem == "unattested":
        source["weight_applicability_confirmed"] = False
    elif problem == "missing_evidence":
        source["weight_evidence_hash"] = None
    else:
        source["weight"]["observed_at"] = "2026-10-16T00:00:00.000001Z"
    result = aki_values(source)
    assert criterion(result, "anuria_12h")["stage"] == result["minimum_stage"] == 3
    assert criterion(result, "urine_24h")["status"] == "unknown"


@pytest.mark.parametrize(
    "problem",
    [
        "unselected_active_interval",
        "gap",
        "overlap",
        "partial_collection",
        "unknown_volume",
        "not_patient_total",
        "actual_gap",
        "actual_overlap",
        "actual_partial",
        "actual_unknown",
        "actual_not_total",
    ],
)
def test_bad_urine_axis_preserves_independent_positive_creatinine(problem):
    source = make_source()
    source["index_creatinine"]["value"] = "2"
    source["urine_intervals"] = [urine(volume="0")]
    if problem.startswith("actual_"):
        if problem in {"actual_gap", "actual_overlap"}:
            source["urine_intervals"] = [
                urine(end="2026-10-16T12:00:00Z", volume="500", number=31),
                urine(start="2026-10-16T12:00:00.000001Z" if problem == "actual_gap" else "2026-10-16T11:59:59.999999Z", volume="500", number=32),
            ]
        elif problem == "actual_partial":
            source["urine_intervals"][0]["collection_completeness"] = "partial"
        elif problem == "actual_unknown":
            source["urine_intervals"][0].update(volume_ml=None, absent_reason="unknown")
        else:
            source["urine_intervals"][0]["patient_total"] = None
    else:
        source["urine_coverage_issues"] = [problem]
    result = aki_values(source)
    assert result["minimum_stage"] == 2 and result["detection"] == "met"
    assert all(criterion(result, key)["status"] == "unknown" for key in ("urine_6h", "urine_12h", "urine_24h", "anuria_12h"))


@pytest.mark.parametrize("problem", ["partial_suffix", "unknown_prefix", "not_total_suffix", "gap_after_positive"])
def test_complete_zero_12h_witness_survives_locatable_missing_other_intervals(problem):
    source = make_source()
    first = urine(end="2026-10-16T12:00:00Z", volume="0", number=31)
    second = urine(start="2026-10-16T12:00:00Z", volume="0", number=32)
    expected_id = first["source_id"]
    if problem == "partial_suffix":
        second["collection_completeness"] = "partial"
    elif problem == "unknown_prefix":
        first.update(volume_ml=None, absent_reason="not_performed")
        expected_id = second["source_id"]
    elif problem == "not_total_suffix":
        second["patient_total"] = False
    else:
        second.update(start_at="2026-10-16T12:00:00.000001Z", volume_ml="500")
    source["urine_intervals"] = [first, second]
    source["weight"] = None
    result = aki_values(source)
    item = criterion(result, "anuria_12h")
    assert result["minimum_stage"] == item["stage"] == 3 and item["status"] == "met"
    assert item["evidence"]["interval_source_ids"] == [expected_id] and item["source_ids"] == [expected_id]
    assert item["evidence"]["coverage_issues"]
    assert criterion(result, "urine_24h")["status"] == "unknown"


def test_separate_four_hour_zero_blocks_cannot_be_joined_across_four_hour_gap():
    source = make_source()
    source["urine_intervals"] = [
        urine(start="2026-10-16T00:00:00Z", end="2026-10-16T04:00:00Z", volume="0", number=31),
        urine(start="2026-10-16T08:00:00Z", end="2026-10-16T12:00:00Z", volume="0", number=32),
    ]
    result = aki_values(source)
    assert result["minimum_stage"] is None
    assert all(criterion(result, key)["status"] == "unknown" for key in ("urine_6h", "urine_12h", "urine_24h", "anuria_12h"))
    assert criterion(result, "urine_6h")["evidence"]["coverage_issues"] == ["gap"]


@pytest.mark.parametrize("problem", ["unselected_active_interval", "overlap"])
def test_hidden_omission_or_overlap_cannot_preserve_potentially_conflicted_zero_witness(problem):
    source = make_source()
    source["urine_intervals"] = [urine(volume="0")]
    source["urine_coverage_issues"] = [problem]
    result = aki_values(source)
    assert criterion(result, "anuria_12h")["status"] == "unknown" and result["minimum_stage"] is None


def test_per_kg_positive_complete_subchain_is_preserved_but_negative_with_gap_is_unknown():
    source = make_source()
    source["urine_intervals"] = [urine(end="2026-10-16T06:00:00Z", volume="100", number=31), urine(start="2026-10-16T12:00:00Z", volume="1000", number=32)]
    result = aki_values(source)
    assert criterion(result, "urine_6h")["stage"] == result["minimum_stage"] == 1
    assert criterion(result, "urine_6h")["evidence"]["interval_source_ids"] == [source["urine_intervals"][0]["source_id"]]
    assert criterion(result, "urine_12h")["status"] == "unknown"
    assert criterion(result, "anuria_12h")["status"] == "unknown"


def test_huge_exact_decimal_and_microsecond_arithmetic_does_not_use_float_or_decimal_default_precision():
    source = make_source()
    source["weight"]["value"] = "9999999999999999.99999999"
    source["urine_intervals"] = [urine(start="2026-10-16T18:00:00Z", volume="9999999999999999.99999999")]
    result = criterion(aki_values(source), "urine_6h")
    assert result["status"] == "met" and result["evidence"]["rate_numerator"] == "1" and result["evidence"]["rate_denominator"] == "6"


def test_64_real_consecutive_intervals_preserve_all_original_boundaries_and_zero_anuria():
    source = make_source()
    start = datetime(2026, 10, 16, tzinfo=UTC)
    source["urine_intervals"] = [
        urine(
            start=(start + timedelta(minutes=22.5 * index)).isoformat().replace("+00:00", "Z"),
            end=(start + timedelta(minutes=22.5 * (index + 1))).isoformat().replace("+00:00", "Z"),
            volume="0",
            number=100 + index,
        )
        for index in range(64)
    ]
    result = aki_values(source)
    assert result["minimum_stage"] == 3
    assert len(criterion(result, "urine_24h")["evidence"]["interval_source_ids"]) == 64
    assert len(criterion(result, "anuria_12h")["evidence"]["interval_source_ids"]) == 32


def test_full_collection_average_can_be_low_despite_unobserved_hourly_pattern():
    source = make_source()
    source["urine_intervals"] = [urine(start="2026-10-16T18:00:00Z", volume="100")]
    item = criterion(aki_values(source), "urine_6h")
    assert item["status"] == "met" and item["reason_code"] == "whole_original_interval_average_not_hourly_persistence"
    assert item["evidence"]["interval_source_ids"] == [source["urine_intervals"][0]["source_id"]]


@pytest.mark.parametrize("change,met", [("complete", True), ("missing_time", False), ("unconfirmed", False), ("missing_evidence", False), ("unknown", False)])
def test_acute_rrt_is_actual_confirmed_initiation_not_an_order_or_assumed_dialysis(change, met):
    source = make_source()
    source["rrt"] = {"status": "acute_initiated_for_aki", "started_at": "2026-10-16T10:00:00Z", "acute_aki_confirmed": True, "evidence_hash": "a" * 64}
    if change == "missing_time":
        source["rrt"]["started_at"] = None
    elif change == "unconfirmed":
        source["rrt"]["acute_aki_confirmed"] = False
    elif change == "missing_evidence":
        source["rrt"]["evidence_hash"] = None
    elif change == "unknown":
        source["rrt"]["status"] = "unknown"
    result = aki_values(source)
    assert (criterion(result, "acute_rrt")["status"] == "met") is met
    if met:
        assert result["minimum_stage"] == 3


@pytest.mark.parametrize("change", ["child", "maintenance"])
def test_outside_scope_does_not_supply_adult_stages(change):
    source = make_source()
    source["index_creatinine"]["value"] = "10"
    if change == "child":
        source["age_at_evaluation_years"] = 17
    else:
        source["rrt"]["status"] = "maintenance"
    result = aki_values(source)
    assert result["detection"] == "outside_scope" and result["minimum_stage"] is None
    assert all(item["status"] == "outside_scope" and item["stage"] is None for item in result["criteria"])


def test_complete_selected_negative_never_becomes_stage_zero_or_aki_excluded():
    result = aki_values(make_source())
    assert result["detection"] == "not_met_in_selected_data" and result["calculation_status"] == "computed"
    assert result["minimum_stage"] is None and result["aki_excluded"] is False
    assert [item["key"] for item in result["criteria"]] == list(CRITERION_KEYS)


@pytest.mark.parametrize("field", ["minimum_stage", "stage_is_lower_bound", "detection", "criterion_status", "criterion_evidence", "source_binding", "warnings", "instructions_digest", "attribution"])
def test_full_analysis_recalculation_rejects_forged_stage_evidence_and_text(field):
    analysis = analysis_for()
    value = analysis.model_dump()
    if field == "criterion_status":
        value["criteria"][0]["status"] = "met"
    elif field == "criterion_evidence":
        value["criteria"][0]["evidence"]["absolute_change"] = "100"
    elif field == "source_binding":
        value["source_binding"]["age_at_evaluation_years"] = 41
    elif field == "minimum_stage":
        value[field] = 3
    elif field == "stage_is_lower_bound":
        value[field] = True
    elif field == "detection":
        value[field] = "met"
    elif field == "warnings":
        value[field] = []
    elif field == "instructions_digest":
        value[field] = "0" * 64
    else:
        value[field] = "claimed endorsement"
    with pytest.raises(ValueError):
        validate_analysis_binding(value, make_source(), analysis.instructions_digest, analysis.local_runtime.model_version)


def test_runtime_accepts_truthful_other_python_version_but_binds_all_four_source_hashes():
    analysis = analysis_for()
    runtime = analysis.local_runtime.model_dump()
    runtime["python_version"] = "3.12.13"
    identity = {key: value for key, value in runtime.items() if key not in {"runtime_digest", "model_version"}}
    from app.ai.aki_contract import canonical_json

    digest = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    runtime.update(runtime_digest=digest, model_version="aki:" + digest)
    validate_runtime(runtime)
    changed = copy.deepcopy(runtime)
    changed["implementation"]["aki_model.py"] = "0" * 64
    with pytest.raises(ValueError):
        validate_runtime(changed)
    assert len(generation_result_for_analysis(analysis)["sections"][0]["source_ids"]) <= 30
