"""Independent boundary fixtures from final Sepsis-3 criteria, not RECIPE."""

import copy
import hashlib
import itertools

import pytest

from app.ai.qsofa_config import runtime_descriptor, runtime_from_descriptor
from app.ai.qsofa_contract import CRITERION_KEYS, QsofaAnalysis, canonical_json
from app.ai.qsofa_model import generation_result_for_analysis, qsofa_values, validate_analysis_binding, validate_runtime
from tests.test_ai_qsofa_contract import make_source, without_gcs


def criterion(result, key):
    return next(item for item in result["criteria"] if item["key"] == key)


def analysis_for(source=None):
    source = source or make_source()
    return QsofaAnalysis.model_validate({"schema_version": "1", "source_binding": source, **qsofa_values(source), "local_runtime": runtime_from_descriptor(runtime_descriptor()), "instructions_digest": hashlib.sha256(b"complete synthetic qSOFA Prompt").hexdigest()})


# Final Singer consensus: RR >=22/min, SBP <=100 mmHg; no integer rounding.
@pytest.mark.parametrize("key,value,expected", [("respiratory_rate", value, score) for value, score in [("0", 0), ("21.99999999", 0), ("22", 1), ("22.00000001", 1), ("200.00000000", 1)]] + [("systolic_bp", value, score) for value, score in [("0.00000000", 1), ("99.99999999", 1), ("100", 1), ("100.00000001", 0), ("220", 0)]])
def test_exact_thresholds_do_not_round_original_precision_or_drop_zero(key, value, expected):
    source = make_source()
    source["measurements"][key]["value"] = value
    result = qsofa_values(source)
    assert criterion(result, key)["score"] == expected
    assert criterion(result, key)["raw_value"] == value
    assert result["total_score"] == result["observed_subtotal"] == expected
    assert result["scored_count"] == 3 and not result["score_is_lower_bound"]
    assert [item["key"] for item in result["criteria"]] == list(CRITERION_KEYS)


@pytest.mark.parametrize("eye,verbal,motor", list(itertools.product(range(1, 5), range(1, 6), range(1, 7))))
def test_all_120_actual_gcs_combinations_use_final_less_than_15_not_derivation_less_than_14(eye, verbal, motor):
    source = make_source()
    for key, value in zip(("eye", "verbal", "motor"), (eye, verbal, motor), strict=True):
        source["gcs"]["components"][key]["score"] = value
    result = qsofa_values(source)
    total = eye + verbal + motor
    assert criterion(result, "mentation")["raw_value"] == str(total)
    assert criterion(result, "mentation")["score"] == (0 if total == 15 else 1)
    assert result["total_score"] == (0 if total == 15 else 1)


@pytest.mark.parametrize("gcs_total,verbal,expected", [(15, 5, 0), (14, 4, 1), (13, 3, 1)])
def test_final_14_is_positive_with_original_distinct_exam_clock_preserved(gcs_total, verbal, expected):
    source = make_source()
    source["gcs"]["components"]["verbal"]["score"] = verbal
    result = qsofa_values(source)
    item = criterion(result, "mentation")
    assert item["raw_value"] == str(gcs_total) and item["score"] == expected
    assert item["observed_at"] == source["gcs"]["observed_at"] != source["observed_at"]


@pytest.mark.parametrize("state", ["none", "nt", "not_recorded", "limited", "unknown", "conflict"])
def test_two_known_positive_criteria_retain_threshold_when_mentation_is_unknown(state):
    source = make_source()
    source["measurements"]["respiratory_rate"]["value"] = "22.00000000"
    source["measurements"]["systolic_bp"]["value"] = "100.00000000"
    if state == "none":
        without_gcs(source)
    elif state in {"nt", "not_recorded"}:
        source["gcs"]["components"]["verbal"] = {"score": None, "absent_reason": "not_testable" if state == "nt" else "not_recorded"}
    elif state == "conflict":
        source["gcs"]["conflict"] = True
    else:
        source["gcs_interpretability"] = state
    result = qsofa_values(source)
    assert result["total_score"] is None and result["observed_subtotal"] == 2
    assert result["scored_count"] == 2 and result["score_is_lower_bound"] is True
    assert result["threshold_status"] == "at_least_two"
    assert criterion(result, "mentation")["score"] is None
    assert result["diagnosis_provided"] is result["probability_provided"] is False
    assert "已达到" in generation_result_for_analysis(analysis_for(source))["summary"]


@pytest.mark.parametrize("known_score", [0, 1])
def test_partial_below_two_never_becomes_complete_negative_threshold(known_score):
    source = without_gcs(make_source())
    source["measurements"].pop("systolic_bp")
    source["measurements"]["respiratory_rate"]["value"] = "22" if known_score else "16"
    result = qsofa_values(source)
    assert result["observed_subtotal"] == known_score and result["scored_count"] == 1
    assert result["total_score"] is None and result["score_is_lower_bound"] is True
    assert result["threshold_status"] == "unknown"
    assert "不能据此排除" in generation_result_for_analysis(analysis_for(source))["summary"]


def test_no_scored_criteria_has_null_subtotal_instead_of_false_zero():
    source = without_gcs(make_source())
    source["measurements"] = {}
    result = qsofa_values(source)
    assert result["scored_count"] == 0
    assert result["observed_subtotal"] is result["total_score"] is None
    assert result["threshold_status"] == "unknown" and result["score_is_lower_bound"] is False


@pytest.mark.parametrize("key", ["respiratory_rate", "systolic_bp"])
def test_same_time_point_conflict_blocks_only_dependent_criterion(key):
    source = make_source()
    source["point_conflicts"] = [key]
    result = qsofa_values(source)
    assert criterion(result, key)["score"] is None and criterion(result, key)["status"] == "conflict"
    assert result["scored_count"] == 2 and result["total_score"] is None
    assert criterion(result, "mentation")["score"] == 0


@pytest.mark.parametrize("age,setting,infection,scope", [(None, "non_icu", "suspected", "unknown"), (17, "non_icu", "suspected", "outside_scope"), (0, "unknown", "unknown", "outside_scope"), (40, "icu", "unknown", "outside_scope"), (None, "icu", "suspected", "outside_scope"), (40, "non_icu", "not_suspected", "outside_scope"), (40, "unknown", "suspected", "unknown"), (40, "non_icu", "unknown", "unknown"), (18, "non_icu", "documented", "confirmed"), (130, "non_icu", "suspected", "confirmed")])
def test_explicit_scope_and_definite_outside_precedence_never_assume_adult_infection(age, setting, infection, scope):
    source = make_source()
    source.update(age_at_observation_years=age, care_setting=setting, infection_status=infection)
    result = qsofa_values(source)
    assert result["scope_status"] == scope
    if scope == "confirmed":
        assert result["total_score"] == 0 and result["threshold_status"] == "below_two_in_complete_data"
    else:
        assert result["scored_count"] == 0 and not result["score_is_lower_bound"]
        assert result["total_score"] is result["observed_subtotal"] is None
        assert all(item["score"] is None for item in result["criteria"])
        assert criterion(result, "respiratory_rate")["raw_value"] == "16"
        assert result["threshold_status"] == "unknown"


@pytest.mark.parametrize("respiratory,systolic,verbal,total", [("16", "120", 5, 0), ("22", "120", 5, 1), ("22", "100", 5, 2), ("22", "100", 4, 3)])
def test_all_complete_totals_and_thresholds(respiratory, systolic, verbal, total):
    source = make_source()
    source["measurements"]["respiratory_rate"]["value"] = respiratory
    source["measurements"]["systolic_bp"]["value"] = systolic
    source["gcs"]["components"]["verbal"]["score"] = verbal
    analysis = analysis_for(source)
    assert analysis.total_score == total and analysis.threshold_status == ("at_least_two" if total >= 2 else "below_two_in_complete_data")
    text = generation_result_for_analysis(analysis)["summary"]
    if total < 2:
        assert "不能排除" in text
    assert "唯一" in text and "低风险" not in text and "正常" not in text


def test_zero_respiratory_rate_retained_as_not_meeting_threshold_not_normal():
    source = make_source()
    source["measurements"]["respiratory_rate"]["value"] = "0.00000000"
    analysis = analysis_for(source)
    item = analysis.criteria[0]
    assert item.score == 0 and item.raw_value == "0.00000000" and "not_proof_of_normality" in item.reason
    assert any("不证明" in warning for warning in analysis.warnings)
    assert "不能排除" in generation_result_for_analysis(analysis)["summary"]


@pytest.mark.parametrize("part", ["criterion", "raw_value", "clock", "subtotal", "total", "threshold", "scope", "count", "lower_bound", "diagnosis", "prompt", "warnings", "source", "references"])
def test_recomputed_binding_rejects_all_score_scope_provenance_and_explanation_mutations(part):
    source, analysis = make_source(), analysis_for().model_dump()
    if part == "criterion":
        analysis["criteria"][0]["score"] = 1
    elif part == "raw_value":
        analysis["criteria"][0]["raw_value"] = "22"
    elif part == "clock":
        analysis["criteria"][2]["observed_at"] = source["observed_at"]
    elif part == "subtotal":
        analysis["observed_subtotal"] = 1
    elif part == "total":
        analysis["total_score"] = 1
    elif part == "threshold":
        analysis["threshold_status"] = "at_least_two"
    elif part == "scope":
        analysis["scope_status"] = "unknown"
    elif part == "count":
        analysis["scored_count"] = 2
    elif part == "lower_bound":
        analysis["score_is_lower_bound"] = True
    elif part == "diagnosis":
        analysis["diagnosis_provided"] = True
    elif part == "prompt":
        analysis["instructions_digest"] = "0" * 64
    elif part == "warnings":
        analysis["warnings"] = ["低风险，可以排除感染"]
    elif part == "source":
        analysis["source_binding"]["gcs"]["components"]["verbal"]["score"] = 4
    else:
        analysis["rule_references"][0] = "https://unapproved.example/claim"
    with pytest.raises(ValueError):
        validate_analysis_binding(analysis, source, analysis_for().instructions_digest, runtime_descriptor()["model_version"])


def test_actual_runtime_sources_versions_and_identity_are_bound():
    descriptor = runtime_descriptor()
    runtime = runtime_from_descriptor(descriptor)
    validate_runtime(runtime)
    validate_analysis_binding(analysis_for(), make_source(), analysis_for().instructions_digest, descriptor["model_version"])
    assert set(runtime["implementation"]) == {"qsofa_contract.py", "qsofa_model.py", "qsofa_config.py", "qsofa_server.py"}
    assert len(canonical_json(descriptor).encode()) < 16384
    for part in ("implementation", "runtime_digest", "engine_versions", "model_version"):
        tampered = copy.deepcopy(runtime)
        if part == "implementation":
            tampered[part]["qsofa_model.py"] = "0" * 64
        elif part == "engine_versions":
            tampered[part]["pydantic"] = "not-a-version"
        else:
            tampered[part] = "qsofa:" + "0" * 64 if part == "model_version" else "0" * 64
        with pytest.raises(ValueError):
            validate_runtime(tampered)
