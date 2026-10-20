"""Two actual daily recomputations, explicit baseline assumptions and signed deltas."""

import copy
from datetime import datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from app.ai.sofa_config import SofaSettings, runtime_descriptor, runtime_from_descriptor
from app.ai.sofa_contract import SofaChangeSource, hash_content
from app.ai.sofa_model import compute_change, generation_result_for_change_analysis, validate_change_analysis_binding
from app.ai.sofa_server import create_sofa_app
from tests.test_ai_sofa_contract import binding, identifier, sha
from tests.test_ai_sofa_model import complete_source
from tests.test_ai_sofa_server import KEY


def previous_day(source):
    data = copy.deepcopy(source)

    def visit(item):
        if isinstance(item, dict):
            for key, value in list(item.items()):
                if isinstance(value, str) and value.endswith("Z") and "T" in value:
                    item[key] = (datetime.fromisoformat(value) - timedelta(days=1)).isoformat(timespec="microseconds").replace("+00:00", "Z")
                else:
                    visit(value)
            if "recorded_at" in item and "source_id" in item:
                prefix = item["source_id"].split(":", 1)[0]
                name = "previous-day-" + item["source_id"]
                item.update(**binding(prefix, name, recorded=item["recorded_at"]))
                for key in ("lab_source_id", "support_source_id", "observation_id", "gcs_observation_id", "interval_id"):
                    if key in item:
                        item[key] = identifier(name)
        elif isinstance(item, list):
            for value in item:
                visit(value)

    visit(data)
    data.update(assessment_id=identifier("baseline"), content_hash=sha("baseline"), assessment_governance_hash=sha("baseline-governance"))
    data["source_id"] = f"sofa_assessment:{data['assessment_id']}:{data['content_hash'][:12]}"
    return data


def change_source(mode="observed"):
    current = complete_source()
    baseline = (
        {"mode": "observed", "source": previous_day(current)}
        if mode == "observed"
        else {"mode": "conditional_zero", "no_known_preexisting_organ_dysfunction": True, "preinfection_baseline_assumption_confirmed": True, "basis_hash": sha("zero")}
        if mode == "conditional_zero"
        else {"mode": "unknown", "basis_hash": sha("unknown")}
    )
    cid = identifier("change")
    return {
        "schema_version": "sofa1_change_source_v1",
        "change_assessment_id": cid,
        "source_id": f"sofa_change_assessment:{cid}:{sha('change')[:12]}",
        "content_hash": sha("change"),
        "assessment_governance_hash": sha("change-governance"),
        "evaluation_at": "2026-10-20T02:00:00.000000Z",
        "current": current,
        "baseline": baseline,
        "infection": {
            **binding("infection_episode", "infection", recorded="2026-10-20T01:30:00.000000Z"),
            "schema_version": "infection_episode_v1",
            "support_source_id": identifier("infection"),
            "infection_status": "suspected",
            "clinical_scope_start_at": "2026-10-19T00:00:00.000000Z",
            "clinical_scope_end_at": None,
            "first_suspected_at": "2026-10-19T00:00:00.000000Z",
            "onset_at": "2026-10-19T00:00:00.000000Z",
            "onset_time_basis": "explicit_clinician_verified_utc",
            "current_presence": "yes",
            "current_presence_basis_hash": sha("presence"),
            "onset_review": "known",
            "onset_review_basis_hash": sha("onset"),
            "late_original_available_after_current_as_of": True,
        },
        "review": {
            "acute_change": "confirmed",
            "acute_change_basis_hash": sha("acute"),
            "attribution": "infection_related",
            "attribution_basis_hash": sha("attribution"),
            "temporal_relation": "overlapping",
            "temporal_relation_basis_hash": sha("temporal"),
        },
        "review_mode": "current_retrospective_review",
        "historical_prediction": False,
    }


def calculate(source):
    return compute_change(source, sha("Prompt"), runtime_from_descriptor(runtime_descriptor()))


def cr_score_four(source):
    item = next(item for item in source["lab_observations"] if item["analyte"] == "creatinine")
    item["quantity"]["value"] = "5"


def test_two_actual_daily_recomputations_and_compact_binding_zero():
    source = change_source()
    analysis = calculate(source)
    assert analysis.current_analysis.complete_total_score == analysis.baseline_analysis.analysis.complete_total_score == 0
    assert analysis.complete_delta == analysis.exact_numeric_delta == analysis.delta_lower_bound == analysis.delta_upper_bound == 0
    assert analysis.delta_threshold_status == "below_two"
    assert analysis.source_binding.projection_hash == hash_content(SofaChangeSource.model_validate(source).model_dump())
    assert "current" not in analysis.source_binding.model_dump()


@pytest.mark.parametrize("mode", ["observed", "conditional_zero"])
def test_positive_change_and_explicit_conditional_zero_attribution_not_auto_diagnosis(mode):
    source = change_source(mode)
    cr_score_four(source["current"])
    analysis = calculate(source)
    assert analysis.complete_delta == 4 and analysis.delta_threshold_status == "at_least_two"
    assert analysis.diagnosis_provided is False and analysis.treatment_provided is False
    if mode == "conditional_zero":
        assert analysis.baseline_analysis.assumed_total_score == 0 and analysis.baseline_analysis.assumptions_confirmed
        assert "条件性零基线假设" in generation_result_for_change_analysis(analysis)["summary"]


def test_observed_negative_delta_is_not_clamped():
    source = change_source()
    cr_score_four(source["baseline"]["source"])
    analysis = calculate(source)
    assert analysis.complete_delta == -4 and analysis.delta_lower_bound == analysis.delta_upper_bound == -4


def test_unknown_baseline_not_zero_and_no_subtotal_subtraction():
    source = change_source("unknown")
    cr_score_four(source["current"])
    analysis = calculate(source)
    assert analysis.current_analysis.complete_total_score == 4
    assert (analysis.delta_lower_bound, analysis.delta_upper_bound) == (-20, 4)
    assert analysis.complete_delta is None and analysis.delta_threshold_status == "indeterminate"


@pytest.mark.parametrize("field", ["no_known_preexisting_organ_dysfunction", "preinfection_baseline_assumption_confirmed"])
def test_conditional_zero_false_is_preserved_as_unknown_bounds(field):
    source = change_source("conditional_zero")
    source["baseline"][field] = False
    cr_score_four(source["current"])
    analysis = calculate(source)
    assert not analysis.baseline_analysis.assumptions_confirmed
    assert analysis.baseline_analysis.assumed_total_score is None and analysis.baseline_analysis.upper_bound == 24
    assert (analysis.delta_lower_bound, analysis.delta_upper_bound) == (-20, 4)


def test_ceiling_numerical_delta_can_be_exact_without_complete_period_protocol():
    source = change_source()
    cr_score_four(source["current"])
    cr_score_four(source["baseline"]["source"])
    source["baseline"]["source"]["urine_intervals"] = []
    analysis = calculate(source)
    assert analysis.baseline_analysis.analysis.exact_numeric_total == 4
    assert analysis.exact_numeric_delta == 0 and analysis.complete_delta is None
    assert analysis.calculation_status == "partial"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s["infection"].update(late_original_available_after_current_as_of=False),
        lambda s: s["infection"].update(recorded_at="2026-10-20T02:00:00.000001Z"),
        lambda s: s["infection"].update(onset_at=None, onset_time_basis="unknown", onset_review="known"),
        lambda s: s["infection"].update(onset_at="2026-10-18T23:59:59.999999Z"),
        lambda s: s["baseline"].update(source=s["current"]),
        lambda s: s["baseline"]["source"].update(as_of="2026-10-20T00:00:00.000001Z", evaluation_at="2026-10-20T00:00:00.000001Z"),
        lambda s: s.update(evaluation_at="2026-10-20T00:30:00.000000Z"),
        lambda s: s.update(historical_prediction=0),
        lambda s: s["infection"].update(onset_review="known", onset_at=None),
    ],
)
def test_actual_onset_availability_and_period_order_binding(mutation):
    data = change_source()
    mutation(data)
    with pytest.raises(ValidationError):
        SofaChangeSource.model_validate(data)


def test_unknown_original_onset_never_given_a_new_inferred_time():
    source = change_source()
    source["infection"].update(onset_at=None, onset_time_basis="unknown", onset_review="unknown")
    analysis = calculate(source)
    assert "infection_onset_unknown_or_not_currently_reviewed" in analysis.missing_data
    assert analysis.complete_delta == 0  # arithmetic remains independent from clinical attribution certainty.


@pytest.mark.parametrize(
    "field,value",
    [("acute_change", "unknown"), ("acute_change", "not_confirmed"), ("attribution", "uncertain"), ("attribution", "not_related"), ("temporal_relation", "before"), ("temporal_relation", "unknown")],
)
def test_current_clinical_review_not_inferred_from_delta(field, value):
    source = change_source()
    cr_score_four(source["current"])
    source["review"][field] = value
    analysis = calculate(source)
    assert getattr(analysis, field) == value and analysis.delta_threshold_status == "at_least_two"
    assert analysis.diagnosis_provided is False and analysis.missing_data


def test_whole_two_period_recomputation_rejects_nonscore_or_proof_tampering():
    source = change_source()
    analysis = calculate(source)
    validate_change_analysis_binding(analysis, source, sha("Prompt"), analysis.local_runtime.model_version)
    for mutation in [
        lambda x: x["baseline_analysis"]["analysis"]["domains"][0]["candidates"][0]["calculations"][0]["exact"].update(numerator="401"),
        lambda x: x.update(acute_change="unknown"),
        lambda x: x.update(delta_threshold_status="at_least_two"),
        lambda x: x.update(warnings=[]),
        lambda x: x["source_binding"].update(baseline_projection_hash=sha("wrong")),
    ]:
        data = analysis.model_dump()
        mutation(data)
        with pytest.raises(ValueError):
            validate_change_analysis_binding(data, source, sha("Prompt"), analysis.local_runtime.model_version)


@pytest.mark.asyncio
async def test_actual_change_service_uses_exclusive_top_level_native_analysis():
    config = SofaSettings(AI_PROVIDER_LOCAL_SOFA_API_KEY=KEY)
    app = create_sofa_app(config)
    descriptor = runtime_descriptor(config)
    task = {
        "schema_version": "9",
        "feature_key": "sepsis_risk",
        "engine": "prediction",
        "model": descriptor["model_version"],
        "instructions": "Prompt",
        "store": False,
        "input": {"context": {"sofa_change_source": change_source()}},
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://sofa") as client:
        response = await client.post("/tasks", json=task, headers={"Authorization": "Bearer " + KEY})
        assert response.status_code == 200, response.text
        data = response.json()
        assert "sofa_change_analysis" in data and "sofa_analysis" not in data and "sofa_change_analysis" not in data["result"]
        task["input"]["context"]["sofa_source"] = complete_source()
        assert (await client.post("/tasks", json=task, headers={"Authorization": "Bearer " + KEY})).status_code == 422
        task["input"]["context"] = {}
        assert (await client.post("/tasks", json=task, headers={"Authorization": "Bearer " + KEY})).status_code == 422


@pytest.mark.parametrize("value", [False, 0.0, "0"])
def test_assumed_zero_is_an_integer_not_false_or_coercion(value):
    from app.ai.sofa_contract import SofaConditionalZeroBaselineAnalysis

    with pytest.raises(ValidationError):
        SofaConditionalZeroBaselineAnalysis.model_validate(
            {"mode": "conditional_zero", "assumptions_confirmed": True, "lower_bound": 0, "upper_bound": 0, "assumed_total_score": value, "basis_hash": sha("basis")}
        )
