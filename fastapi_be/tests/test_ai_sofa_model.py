"""Independent native-threshold and whole-window mathematical regression evidence."""

import copy

import pytest

from app.ai.sofa_config import runtime_descriptor, runtime_from_descriptor
from app.ai.sofa_contract import AXES, SofaSource, hash_content
from app.ai.sofa_model import compute_sofa, generation_result_for_analysis, sofa_values, validate_analysis_binding
from tests.test_ai_sofa_contract import binding, empty_source, identifier, lab, quantity, review, sha


def source_with(**values):
    data = empty_source()
    data.update(values)
    return data


def domain(data, axis):
    return next(item for item in sofa_values(data)["domains"] if item["axis"] == axis)


def map_point(value="70", name="map"):
    return {
        **binding("map_observation", name),
        "support_source_id": identifier(name),
        "observed_at": "2026-10-19T12:00:00.000000Z",
        "quantity": quantity(value, "mm[Hg]"),
        "measurement_method": "oscillometric_device",
        "review": review(),
    }


def gcs(scores=(4, 5, 6), name="gcs"):
    return {
        **binding("gcs_observation", name),
        "gcs_observation_id": identifier(name),
        "observed_at": "2026-10-19T12:00:00.000000Z",
        "components": {key: {"score": score, "absent_reason": "not_testable" if score is None else None} for key, score in zip(("eye", "verbal", "motor"), scores)},
        "interpretable": "confirmed",
        "sedation_confounding_status": "excluded",
        "other_confounding_status": "excluded",
        "confounding_basis_hash": sha("confounding"),
        "anchor": None,
        "anchor_current": True,
        "review": review(),
    }


def urine(value="500", name="urine", start="2026-10-19T00:00:00.000000Z", end="2026-10-20T00:00:00.000000Z"):
    return {
        **binding("urine_interval", name),
        "interval_id": identifier(name),
        "start_at": start,
        "end_at": end,
        "volume_ml": value,
        "absent_reason": "unknown" if value is None else None,
        "collection_completeness": "complete",
        "patient_total": True,
        "review": review(),
    }


def support(name="support"):
    return {
        **binding("respiratory_support", name),
        "support_source_id": identifier(name),
        "start_at": "2026-10-19T00:00:00.000000Z",
        "verified_until_at": "2026-10-20T00:00:00.000000Z",
        "ended_at": None,
        "delivery_mode": "noninvasive_positive_pressure",
        "continuity_confirmed": True,
        "review": review(),
    }


def respiratory(pao2="400", fio2="100", unit="mm[Hg]", qualifying="yes", name="resp"):
    item = lab("arterial_oxygen_partial_pressure", pao2, unit, name + "lab")
    return {
        "candidate_id": name,
        "pao2": item,
        "pair": {**binding("arterial_pair", name + "pair"), "support_source_id": identifier(name + "pair")},
        "fio2": {**binding("inpatient_observation", name + "fio2"), "observation_id": identifier(name + "fio2"), "observed_at": "2026-10-19T11:30:00.000000Z", "quantity": quantity(fio2, "%")},
        "support": support(name + "support"),
        "arterial_sample_confirmed": True,
        "same_sampling_state_confirmed": True,
        "fio2_applicability_confirmed": True,
        "qualifying_respiratory_support": qualifying,
        "support_qualification_basis_hash": sha(name + "qualification"),
        "review": review(),
    }


def weight(value="60", name="weight"):
    return {**binding("inpatient_observation", name), "observation_id": identifier(name), "observed_at": "2026-10-18T20:00:00.000000Z", "quantity": quantity(value, "kg"), "review": review()}


def vaso(rate="0.1", drug="norepinephrine", name="vaso", start="2026-10-19T00:00:00.000000Z", end="2026-10-19T01:00:00.000000Z", stream="stream1"):
    mapping = sha(drug + "mapping")
    return {
        **binding("vasoactive_interval", name),
        "support_source_id": identifier(name),
        "start_at": start,
        "verified_until_at": end,
        "ended_at": end,
        "stream_key": sha(stream),
        "mapping": {
            "source_id": f"vasoactive_drug_mapping:{identifier(drug + 'mapping')}:{mapping[:12]}",
            "mapping_id": identifier(drug + "mapping"),
            "content_hash": mapping,
            "governance_hash": sha(drug + "mapping-governance"),
            "drug_key": drug,
            "active_moiety_basis": "base",
        },
        "continuity_confirmed": True,
        "continuous_iv": "confirmed",
        "rate_scope": "stream_rate",
        "dose_input": {"mode": "weight_normalized", "rate": quantity(rate, "ug/kg/min")},
        "weight": None,
        "weight_applicability_confirmed": False,
        "weight_use_confirmed": False,
        "mass_basis_compatible_confirmed": True,
        "review": review(),
    }


def vaso_group(intervals, relation="single_stream", drug=None):
    return {
        "drug_key": drug or intervals[0]["mapping"]["drug_key"],
        "relation": relation,
        "relation_confirmed": True,
        "dose_basis_consistency_confirmed": True,
        "basis_hash": sha("group"),
        "intervals": intervals,
    }


def with_vaso(intervals, relation="single_stream"):
    return source_with(
        vasoactive_groups=[vaso_group(intervals, relation)], circulation_review={"drug_exposure": "reviewed_intervals", "no_other_unrepresented_exposure_confirmed": True, "basis_hash": sha("circ")}
    )


@pytest.mark.parametrize(
    "analyte,unit,values",
    [
        ("platelet_count", "10^9/L", [("150", 0), ("149.99999999", 1), ("100", 1), ("99.99999999", 2), ("50", 2), ("49.99999999", 3), ("20", 3), ("19.99999999", 4), ("0", 4)]),
        ("total_bilirubin", "mg/dL", [("1.19999999", 0), ("1.2", 1), ("1.99999999", 1), ("2", 2), ("5.99999999", 2), ("6", 3), ("11.99999999", 3), ("12", 4)]),
        ("total_bilirubin", "umol/L", [("19.99999999", 0), ("20", 1), ("32.99999999", 1), ("33", 2), ("101.99999999", 2), ("102", 3), ("203.99999999", 3), ("204", 4)]),
        ("creatinine", "mg/dL", [("1.19999999", 0), ("1.2", 1), ("1.99999999", 1), ("2", 2), ("3.49999999", 2), ("3.5", 3), ("4.99999999", 3), ("5", 4)]),
        ("creatinine", "umol/L", [("109.99999999", 0), ("110", 1), ("170.99999999", 1), ("171", 2), ("299.99999999", 2), ("300", 3), ("440", 3), ("440.00000001", 4)]),
    ],
)
def test_all_native_continuous_edges(analyte, unit, values):
    axis = {"platelet_count": "coagulation", "total_bilirubin": "liver", "creatinine": "renal"}[analyte]
    for value, score in values:
        actual = domain(source_with(lab_observations=[lab(analyte, value, unit)]), axis)
        assert actual["observed_max_score"] == score, (analyte, value, actual)


@pytest.mark.parametrize(
    "unit,raw,expected",
    [
        ("mm[Hg]", "400", 0),
        ("mm[Hg]", "399.99999999", 1),
        ("mm[Hg]", "300", 1),
        ("mm[Hg]", "299.99999999", 2),
        ("mm[Hg]", "200", 2),
        ("mm[Hg]", "199.99999999", 3),
        ("mm[Hg]", "100", 3),
        ("mm[Hg]", "99.99999999", 4),
        ("kPa", "53.3", 0),
        ("kPa", "53.29999999", 1),
        ("kPa", "40", 1),
        ("kPa", "39.99999999", 2),
        ("kPa", "26.7", 2),
        ("kPa", "26.69999999", 3),
        ("kPa", "13.3", 3),
        ("kPa", "13.29999999", 4),
    ],
)
def test_native_pao2_branches_no_approximate_conversion(unit, raw, expected):
    result = domain(source_with(respiratory_observations=[respiratory(raw, unit=unit)]), "respiratory")
    assert result["observed_max_score"] == expected
    assert result["protocol_complete"]


@pytest.mark.parametrize("raw,qualifying,bounds", [("99", "unknown", (2, 4)), ("150", "unknown", (2, 3)), ("99", "no", (2, 2)), ("250", "unknown", (2, 2)), ("99", "yes", (4, 4))])
def test_support_review_separate_from_actual_device_mode(raw, qualifying, bounds):
    result = domain(source_with(respiratory_observations=[respiratory(raw, qualifying=qualifying)]), "respiratory")
    assert (result["lower_bound"], result["upper_bound"]) == bounds


def test_pf_exact_rational_no_rounding_and_raw_zero_distinct_null():
    original = respiratory("100", "33")
    result = domain(source_with(respiratory_observations=[original]), "respiratory")
    assert result["candidates"][0]["calculations"][0]["exact"] == {"numerator": "10000", "denominator": "33", "unit": "mm[Hg]"}
    zero = domain(source_with(respiratory_observations=[respiratory("0")]), "respiratory")
    missing = domain(source_with(respiratory_observations=[respiratory(None)]), "respiratory")
    assert zero["observed_max_score"] == 4 and missing["observed_max_score"] is None


@pytest.mark.parametrize("scores,expected", [((4, 5, 6), 0), ((3, 4, 6), 1), ((3, 3, 6), 2), ((2, 2, 5), 3), ((1, 1, 3), 4)])
def test_actual_full_gcs(scores, expected):
    assert domain(source_with(gcs_observations=[gcs(scores)]), "cns")["observed_max_score"] == expected


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item.update(sedation_confounding_status="present"),
        lambda item: item.update(other_confounding_status="unknown"),
        lambda item: item.update(interpretable="limited"),
        lambda item: item["components"]["verbal"].update(score=None, absent_reason="not_testable"),
    ],
)
def test_gcs_unknown_or_confounded_never_nt_one_or_default_normal(mutation):
    original = gcs()
    mutation(original)
    result = domain(source_with(gcs_observations=[original]), "cns")
    assert result["observed_max_score"] is None and result["upper_bound"] == 4


@pytest.mark.parametrize(
    "drug,rate,score",
    [
        ("dopamine", "0", 0),
        ("dopamine", "0.00000001", 2),
        ("dopamine", "5", 2),
        ("dopamine", "5.00000001", 3),
        ("dopamine", "15", 3),
        ("dopamine", "15.00000001", 4),
        ("dobutamine", "0", 0),
        ("dobutamine", "0.00000001", 2),
        ("norepinephrine", "0", 0),
        ("norepinephrine", "0.1", 3),
        ("norepinephrine", "0.10000001", 4),
        ("epinephrine", "0.00000001", 3),
    ],
)
def test_positive_dose_guard_and_native_drug_edges(drug, rate, score):
    result = domain(with_vaso([vaso(rate, drug)]), "cardiovascular")
    assert result["observed_max_score"] == score
    assert result["lower_bound"] == score
    assert result["upper_bound"] == max(1, score)  # unknown MAP branch preserved.


@pytest.mark.parametrize(
    "mode,raw,expected",
    [
        ("absolute", quantity("3.6", "mg/h"), ("1", "1")),
        ("absolute", quantity("20", "ug/min"), ("1", "3")),
        ("pump", (quantity("0.3", "mg/mL"), quantity("12", "mL/h")), ("1", "1")),
        ("pump", (quantity("300", "ug/mL"), quantity("12", "mL/h")), ("1", "1")),
    ],
)
def test_original_dose_union_exact_fraction(mode, raw, expected):
    item = vaso()
    item.update(weight=weight(), weight_applicability_confirmed=True, weight_use_confirmed=True)
    item["dose_input"] = {"mode": mode, "rate": raw} if mode == "absolute" else {"mode": "pump", "concentration": raw[0], "pump_rate": raw[1]}
    result = domain(with_vaso([item]), "cardiovascular")
    exact = result["candidates"][0]["calculations"][0]["exact"]
    assert (exact["numerator"], exact["denominator"]) == expected


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item.update(continuous_iv="unknown"),
        lambda item: item.update(continuity_confirmed=False),
        lambda item: item.update(mass_basis_compatible_confirmed=False),
        lambda item: item["mapping"].update(active_moiety_basis="salt"),
        lambda item: item["mapping"].update(active_moiety_basis="unknown"),
        lambda item: item.update(rate_scope="unknown"),
    ],
)
def test_raw_or_review_uncertainty_not_overridden_by_a_known_rate(mutation):
    item = vaso("1")
    mutation(item)
    result = domain(with_vaso([item]), "cardiovascular")
    assert result["observed_max_score"] is None and (result["lower_bound"], result["upper_bound"]) == (0, 4)


@pytest.mark.parametrize("kg,original_applicability,use_confirmed", [("0", True, True), ("60", False, True), ("60", True, False), (None, True, True)])
def test_invalid_weight_not_defaulted_or_divided(kg, original_applicability, use_confirmed):
    item = vaso()
    item.update(weight=weight(kg), weight_applicability_confirmed=original_applicability, weight_use_confirmed=use_confirmed, dose_input={"mode": "absolute", "rate": quantity("20", "ug/min")})
    result = domain(with_vaso([item]), "cardiovascular")
    assert result["upper_bound"] == 4 and result["observed_max_score"] is None


def test_direct_normalized_rate_never_divided_by_optional_weight_again():
    item = vaso("0.1")
    item["weight"] = weight("0")
    assert domain(with_vaso([item]), "cardiovascular")["lower_bound"] == 3


@pytest.mark.parametrize("end,expected", [("2026-10-19T00:59:59.999999Z", 0), ("2026-10-19T01:00:00.000000Z", 4)])
def test_actual_one_hour_duration_boundary(end, expected):
    result = domain(with_vaso([vaso("1", end=end)]), "cardiovascular")
    assert result["observed_max_score"] == expected


def test_same_tier_continues_but_high_tier_does_not_borrow_low_tier_time():
    one = vaso("0.09", name="first", end="2026-10-19T00:30:00.000000Z")
    two = vaso("0.11", name="second", start=one["verified_until_at"])
    result = domain(with_vaso([one, two]), "cardiovascular")
    assert result["observed_max_score"] == 3
    proofs = result["candidates"][0]["calculations"]
    assert any(p["kind"] == "continuous_tier" and p["tier"] == 3 and p["duration_microseconds"] == 3_600_000_000 and p["meets_minimum"] for p in proofs)
    assert not any(p["kind"] == "continuous_tier" and p["tier"] == 4 and p["meets_minimum"] for p in proofs)


def test_one_microsecond_gap_breaks_continuity():
    one = vaso("1", name="first", end="2026-10-19T00:30:00.000000Z")
    two = vaso("1", name="second", start="2026-10-19T00:30:00.000001Z")
    assert domain(with_vaso([one, two]), "cardiovascular")["observed_max_score"] == 0


def test_parallel_explicit_streams_sum_same_agent_exactly():
    one = vaso("0.06", name="first", stream="one")
    two = vaso("0.06", name="second", stream="two")
    result = domain(with_vaso([one, two], "distinct_parallel_streams"), "cardiovascular")
    assert result["lower_bound"] == 4
    assert any(p["kind"] == "dose_rate" and p["mode"] == "parallel_sum" and p["exact"]["numerator"] == "3" and p["exact"]["denominator"] == "25" for p in result["candidates"][0]["calculations"])


def test_same_physical_stream_overlap_not_double_counted_or_max_picked():
    one = vaso("0.06", name="first", stream="one")
    two = vaso("0.06", name="second", stream="one")
    result = domain(with_vaso([one, two], "distinct_parallel_streams"), "cardiovascular")
    assert (result["lower_bound"], result["upper_bound"]) == (0, 4)
    assert "overlapping_same_stream" in result["coverage_issues"]


def test_known_positive_continuity_retained_outside_independent_conflict():
    one = vaso("1", name="first", end="2026-10-19T02:00:00.000000Z")
    overlap = vaso("0.06", name="second", stream="stream1", start="2026-10-19T01:30:00.000000Z", end=one["verified_until_at"])
    result = domain(with_vaso([one, overlap]), "cardiovascular")
    assert result["lower_bound"] == result["upper_bound"] == 4 and not result["protocol_complete"]


def test_prefix_completion_and_end_of_day_completion_are_valid_no_future_fill():
    item = vaso("1", start="2026-10-18T23:30:00.000000Z", end="2026-10-19T00:30:00.000000Z")
    assert domain(with_vaso([item]), "cardiovascular")["lower_bound"] == 4
    item = vaso("1", start="2026-10-19T23:00:00.000000Z", end="2026-10-20T00:00:00.000000Z")
    assert domain(with_vaso([item]), "cardiovascular")["lower_bound"] == 4
    item = vaso("1", start="2026-10-18T23:00:00.000000Z", end="2026-10-19T00:00:00.000000Z")
    assert domain(with_vaso([item]), "cardiovascular")["lower_bound"] == 0


@pytest.mark.parametrize("volume,expected", [("0", 4), ("199.99999999", 4), ("200", 3), ("499.99999999", 3), ("500", 0)])
def test_whole_original_24h_urine_native_edges(volume, expected):
    result = domain(source_with(urine_intervals=[urine(volume)]), "renal")
    assert result["observed_max_score"] == expected
    assert not result["protocol_complete"]  # Cr still unknown, even urine >=500.


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item.update(start_at="2026-10-18T23:59:59.999999Z"),
        lambda item: item.update(start_at="2026-10-19T00:00:00.000001Z"),
        lambda item: item.update(volume_ml=None, absent_reason="unknown"),
        lambda item: item.update(collection_completeness="partial"),
        lambda item: item.update(patient_total=None),
    ],
)
def test_partial_crossing_or_unknown_urine_not_rescaled_to_a_day(mutation):
    item = urine("0")
    mutation(item)
    result = domain(source_with(urine_intervals=[item]), "renal")
    assert result["observed_max_score"] is None and result["upper_bound"] == 4


def test_urine_exact_tile_and_overlap_no_silent_drop():
    one = urine("100", name="one", end="2026-10-19T12:00:00.000000Z")
    two = urine("100", name="two", start=one["end_at"])
    result = domain(source_with(urine_intervals=[one, two]), "renal")
    assert result["observed_max_score"] == 3
    duplicate = copy.deepcopy(one)
    duplicate.update(**binding("urine_interval", "duplicate"), interval_id=identifier("duplicate"))
    assert domain(source_with(urine_intervals=[one, two, duplicate]), "renal")["observed_max_score"] is None


def test_ceiling_numeric_exact_does_not_claim_protocol_complete():
    result = domain(source_with(lab_observations=[lab("creatinine", "5", "mg/dL")]), "renal")
    assert result["lower_bound"] == result["upper_bound"] == result["exact_numeric_score"] == 4
    assert not result["protocol_complete"]


def complete_source():
    return source_with(
        lab_observations=[lab("platelet_count", "150", "10^9/L"), lab("total_bilirubin", "1", "mg/dL"), lab("creatinine", "1", "mg/dL")],
        respiratory_observations=[respiratory()],
        map_observations=[map_point()],
        gcs_observations=[gcs()],
        urine_intervals=[urine()],
    )


def test_real_six_axis_recomputation_complete_zero_preserved():
    actual = sofa_values(complete_source())
    assert [d["axis"] for d in actual["domains"]] == list(AXES)
    assert actual["complete_total_score"] == actual["known_subtotal"] == actual["exact_numeric_total"] == 0
    assert actual["protocol_complete_domain_count"] == 6


def test_no_measurements_and_unknown_exposure_empty_subtotal_is_null():
    data = empty_source()
    data["circulation_review"]["drug_exposure"] = "unknown"
    actual = sofa_values(data)
    assert actual["known_subtotal"] is None and (actual["lower_bound"], actual["upper_bound"]) == (0, 24)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda p: p.update(age_at_period_years=17, adult="no"), "outside_scope"),
        (lambda p: p.update(adult="unknown"), "unknown"),
        (lambda p: p.update(care_setting="unknown"), "unknown"),
        (lambda p: p.update(applicability_confirmed=False), "unknown"),
    ],
)
def test_scope_unknown_separate_from_explicit_outside(mutation, expected):
    data = complete_source()
    mutation(data["population"])
    actual = sofa_values(data)
    assert actual["scope_status"] == expected and actual["complete_total_score"] is None and actual["known_subtotal"] is None


def test_full_analysis_binding_recomputes_not_just_total_or_digest():
    source = complete_source()
    runtime = runtime_from_descriptor(runtime_descriptor())
    analysis = compute_sofa(source, sha("prompt"), runtime)
    validate_analysis_binding(analysis, source, sha("prompt"), runtime["model_version"])
    assert analysis.source_binding.projection_hash == hash_content(SofaSource.model_validate(source).model_dump())
    assert "population" not in analysis.source_binding.model_dump()
    for mutate in [
        lambda x: x["domains"][0]["candidates"][0]["calculations"][0]["exact"].update(numerator="401"),
        lambda x: x["domains"][0].update(deciding_source_ids=[]),
        lambda x: x.update(missing_data=["invented"]),
        lambda x: x.update(warnings=["invented"]),
        lambda x: x["source_binding"].update(projection_hash=sha("forged")),
    ]:
        tampered = analysis.model_dump()
        mutate(tampered)
        with pytest.raises(ValueError):
            validate_analysis_binding(tampered, source, sha("prompt"), runtime["model_version"])
    assert generation_result_for_analysis(analysis)["summary"].startswith("所选完整24小时原资料SOFA-1六轴总分为0/24")


def test_lab_signed_and_qualitative_originals_retained_without_scoring():
    negative = lab("creatinine", "-0.1", "mg/dL")
    qualitative = lab("creatinine", None, "mg/dL")
    qualitative["quantity"]["value_kind"] = "qualitative"
    for raw in [negative, qualitative]:
        typed = SofaSource.model_validate(source_with(lab_observations=[raw]))
        assert typed.lab_observations[0].quantity.model_dump() == raw["quantity"]
        result = domain(typed, "renal")
        assert result["observed_max_score"] is None and result["upper_bound"] == 4
    assert "unsupported_value" in domain(source_with(lab_observations=[negative]), "renal")["coverage_issues"]


def test_real_pair_clocks_not_forced_equal_or_automatic_nearest():
    pair = respiratory("99")
    pair["fio2"]["observed_at"] = "2026-10-19T12:15:00.000000Z"
    result = domain(source_with(respiratory_observations=[pair]), "respiratory")
    assert result["lower_bound"] == 4
    pair["same_sampling_state_confirmed"] = False
    assert domain(source_with(respiratory_observations=[pair]), "respiratory")["observed_max_score"] is None
