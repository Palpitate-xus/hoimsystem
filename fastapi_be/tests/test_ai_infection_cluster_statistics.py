"""Pure declarations/independent exact enumeration; no server authority proof."""

import copy
import itertools
from fractions import Fraction

import pytest
from pydantic import ValidationError

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_projection as p
from app.ai import infection_cluster_statistics as engine
from app.ai import infection_cluster_statistics_contract as k
from tests.test_ai_infection_cluster_contract import collection, identifier, mapping, row


def input_for_table(a=6, b=2, cc=1, d=4, *, family=1):
    rows = []
    for count, department, date in [(a, 1, "2026-10-15"), (b, 2, "2026-10-15"), (cc, 1, "2026-10-05"), (d, 2, "2026-10-05")]:
        for _ in range(count):
            number = len(rows) + 1
            rows.append(row(number, patient_id=10000 + number, department_id=department, onset_date=date))
    private = collection(rows, assessment="meets_definition")
    private["patient_ids"] = [item["patient_id"] for item in rows] or [10000]
    for review, original in zip(private["reviews"], rows):
        for field in ("infection_type", "pathogen"):
            review[field] = mapping(field, original[field], True)
    source = p.project_source(private, b"S" * 32)
    department = next((item.department_token for item in source.reports if item.onset_date == "2026-10-15" and item.department_token), "e" * 64)
    # If a=0, explicitly choose the same department as c; the test's table is
    # a declared synthetic identity, not a current Department authorization.
    if a == 0 and cc:
        department = source.reports[b].department_token
    scope_window = {"date_from": "2026-10-15", "date_to": "2026-10-15", "coordinate_basis": "recorded_onset_date_inclusive_no_event_timezone"}
    plan = {
        "schema_version": "infection_comparison_plan_v1",
        "scenario_id": identifier(7900),
        "source_binding": {
            "snapshot_id": private["collection_id"],
            "source_id": source.source_id,
            "private_collection_hash": source.private_collection_hash,
            "public_source_hash": c.digest(source),
            "witness_hash": "a" * 64,
        },
        "department_tokens": [department],
        "windows": [scope_window],
        "pathogen_code": "LOCAL_PATHOGEN",
        "alpha_decimal": "0.1",
        "method": "one_sided_fisher_greater_fixed_margins",
        "family_basis": "complete_declared_department_by_window_cartesian_product",
        "declaration_basis": "declared_before_this_execution_not_proven_independent_of_observed_data",
        "no_population_denominator": "not_provided",
    }
    if family == 2:
        plan["department_tokens"].append("f" * 64)  # explicitly declared zero-record department
    return {
        "schema_version": "infection_statistics_input_v1",
        "source": source.model_dump(mode="json"),
        "scenario": plan,
        "scenario_content_hash": c.digest(plan),
        "scenario_governance_hash": "b" * 64,
        "recipe_hash": c.digest(k.RECIPE),
        "authority_basis": "pure_structure_and_arithmetic_only_server_must_verify_current_authority",
    }


def rebound(value):
    value["scenario"]["source_binding"]["public_source_hash"] = c.digest(value["source"])
    value["scenario_content_hash"] = c.digest(value["scenario"])
    return value


def test_primary_documented_example_exact_and_original_scientific_scope():
    assert engine.fisher_upper_tail(6, 2, 1, 4) == Fraction(37, 429)
    assert float(Fraction(37, 429)) == pytest.approx(0.08624708624708627)
    output = engine.evaluate(input_for_table())
    result = output.candidates[0]
    assert result.table.model_dump() == dict(window_in_department=6, window_in_other=2, window_out_department=1, window_out_other=4)
    assert result.exact_p.model_dump() == k.rational(Fraction(37, 429))
    assert result.fixed_margin_expectations.window_in_department.model_dump() == k.rational(Fraction(56, 13))
    assert result.nominal_declared_family_threshold_met is True
    assert output.denominator == "not_provided" and output.automatic_actions is False
    assert "does not control undisclosed" in " ".join(output.limitations)
    assert engine.verify_analysis_binding(input_for_table(), output)


def test_small_tables_by_independent_enumeration_of_labeled_fixed_margin_assignments(record_property):
    checked = 0
    for a, b, cc, d in itertools.product(range(4), repeat=4):
        total = a + b + cc + d
        if total > 10:
            continue
        n, department = a + b, a + cc
        assignments = list(itertools.combinations(range(total), n))
        expected = Fraction(sum(sum(index < department for index in chosen) >= a for chosen in assignments), len(assignments))
        assert engine.fisher_upper_tail(a, b, cc, d) == expected, (a, b, cc, d)
        checked += 1
    assert checked == 251
    record_property("independent_labeled_assignments_tables", checked)


def test_scipy_only_independent_test_oracle_not_runtime_dependency(record_property):
    from scipy.stats import fisher_exact

    checked = 0
    for cells in itertools.product(range(6), repeat=4):
        actual = engine.fisher_upper_tail(*cells)
        expected = fisher_exact([cells[:2], cells[2:]], alternative="greater").pvalue
        assert float(actual) == pytest.approx(expected, abs=2e-15), cells
        checked += 1
    assert checked == 1296
    record_property("independent_scipy_small_tables", checked)


def test_full_family_adjustment_retains_zero_candidate_and_family_size():
    output = engine.evaluate(input_for_table(family=2))
    assert output.family_size == len(output.candidates) == 2
    assert output.candidates[0].bonferroni_p.model_dump() == k.rational(Fraction(74, 429))
    assert output.candidates[0].nominal_declared_family_threshold_met is False
    zero = output.candidates[1]
    assert zero.status == "no_information" and zero.table.window_in_department == zero.table.window_out_department == 0
    assert zero.exact_p.model_dump() == zero.bonferroni_p.model_dump() == k.rational(Fraction(1))
    assert zero.nominal_declared_family_threshold_met is False


@pytest.mark.parametrize("cells", [(0, 0, 0, 0), (0, 3, 0, 4), (3, 0, 4, 0), (3, 4, 0, 0)])
def test_empty_and_fixed_margins_are_informationless_not_negative(cells):
    output = engine.evaluate(input_for_table(*cells))
    candidate = output.candidates[0]
    assert candidate.status == "no_information"
    assert candidate.exact_p.model_dump() == k.rational(Fraction(1))
    assert candidate.nominal_declared_family_threshold_met is False
    if sum(cells) == 0:
        assert candidate.fixed_margin_expectations is None


def test_repeated_eligible_subject_refuses_entire_family_and_preserves_records_counts():
    value = input_for_table(family=2)
    reports = value["source"]["reports"]
    reports[1]["patient_token"] = reports[0]["patient_token"]
    value["source"]["counts"]["distinct_subjects_with_records"] -= 1
    rebound(value)
    output = engine.evaluate(value)
    assert output.status == "inference_unavailable_repeated_eligible_subject"
    assert len(output.record_dispositions) == output.eligible_records == 13
    assert len(output.repeated_eligible_subject_tokens) == 1
    assert all(item.status == "inference_unavailable" and item.exact_p is item.bonferroni_p is item.fixed_margin_expectations is None for item in output.candidates)
    assert sum(output.candidates[0].table.model_dump().values()) == 13


def test_unknown_excluded_other_reviewed_code_and_workflow_are_not_normal():
    value = input_for_table()
    reports = value["source"]["reports"]
    reports[0]["human_assessment"] = "does_not_meet"
    reports[1]["human_assessment"] = "undetermined"
    reports[2]["human_assessment"] = "not_assessed"
    reports[3]["pathogen"].update(original_state="null", assessment="not_mapped", reviewed_code=None)
    reports[4]["pathogen"]["reviewed_code"] = "OTHER_REVIEWED_CODE"
    reports[5]["department_token"] = None
    reports[6].update(recorded_status=-7, recorded_status_meaning="unknown")
    value["source"]["counts"].update(meets_definition=10, does_not_meet=1, undetermined=1, not_assessed=1)
    output = engine.evaluate(rebound(value))
    assert (output.eligible_records, output.excluded_records, output.unknown_records) == (7, 2, 4)
    ledger = output.record_dispositions
    assert ledger[0].reasons == ["human_does_not_meet_definition"] and ledger[0].disposition == "excluded"
    assert ledger[1].disposition == ledger[2].disposition == ledger[3].disposition == ledger[5].disposition == "unknown"
    assert ledger[4].reasons == ["other_reviewed_pathogen_code"] and ledger[4].disposition == "excluded"
    assert ledger[6].disposition == "eligible"  # workflow status is not clinical eligibility
    assert len(ledger) == 13


@pytest.mark.parametrize("value", [None, 0.05, "0", "1", "0.0", "0.0000000000000", "5e-2", "0.5 "])
def test_no_default_or_normalized_alpha(value):
    data = input_for_table()
    data["scenario"]["alpha_decimal"] = value
    rebound(data)
    with pytest.raises((ValueError, TypeError)):
        engine.evaluate(data)


@pytest.mark.parametrize("mutation", ["extra", "family_duplicate", "window_duplicate", "window_outside", "257", "source_hash", "scenario_hash", "recipe", "foreign_method"])
def test_complete_closed_plan_and_full_binding_refuse_mutations(mutation):
    value = input_for_table()
    if mutation == "extra":
        value["scenario"]["automatic_enable"] = True
    elif mutation == "family_duplicate":
        value["scenario"]["department_tokens"] *= 2
    elif mutation == "window_duplicate":
        value["scenario"]["windows"] *= 2
    elif mutation == "window_outside":
        value["scenario"]["windows"][0]["date_from"] = "2025-01-01"
    elif mutation == "257":
        value["scenario"]["department_tokens"] = [c.text_digest(str(i)) for i in range(257)]
    elif mutation == "source_hash":
        value["scenario"]["source_binding"]["public_source_hash"] = "f" * 64
    elif mutation == "scenario_hash":
        value["scenario_content_hash"] = "f" * 64
    elif mutation == "recipe":
        value["recipe_hash"] = "f" * 64
    elif mutation == "foreign_method":
        value["scenario"]["method"] = "old_count_three_in_thirty_days"
    if mutation not in {"source_hash", "scenario_hash", "recipe"}:
        value["scenario_content_hash"] = c.digest(value["scenario"])
    with pytest.raises((ValueError, ValidationError)):
        engine.evaluate(value)


@pytest.mark.parametrize("body", [b'{"source":1,"source":2}', b'{"a":NaN}', b'{"a":"\xff"}', b'{"a":"\\ud800"}'])
def test_raw_whole_input_rejects_duplicate_nonfinite_invalid_utf8_or_surrogate(body):
    with pytest.raises((ValueError, UnicodeError)):
        engine.evaluate(body)


@pytest.mark.parametrize("mutation", ["count", "fraction", "threshold", "drop_candidate", "drop_record", "source_ref", "automatic_actions"])
def test_self_rehash_is_not_a_binding_proof(mutation):
    value = input_for_table(family=2)
    output = engine.evaluate(value).model_dump(mode="json")
    forged = copy.deepcopy(output)
    if mutation == "count":
        forged["candidates"][0]["table"]["window_in_department"] += 1
    elif mutation == "fraction":
        forged["candidates"][0]["exact_p"] = {"numerator": "0", "denominator": "1"}
    elif mutation == "threshold":
        forged["candidates"][0]["nominal_declared_family_threshold_met"] = True
    elif mutation == "drop_candidate":
        forged["candidates"].pop()
    elif mutation == "drop_record":
        forged["record_dispositions"].pop()
    elif mutation == "source_ref":
        forged["source_binding"]["witness_hash"] = "f" * 64
    elif mutation == "automatic_actions":
        forged["automatic_actions"] = 0
    assert not engine.verify_analysis_binding(value, forged)


def test_exact_rational_rejects_nonreduced_and_float_values():
    for body in [{"numerator": "2", "denominator": "4"}, {"numerator": 1, "denominator": "2"}, {"numerator": "1", "denominator": "0"}, {"numerator": "3", "denominator": "2"}]:
        with pytest.raises(ValueError):
            k.Probability.model_validate(body)
    assert k.alpha_fraction("0.0500") == Fraction(1, 20)  # original text remains on the plan


def test_whole_bytes_and_depth_budgets_are_checked_before_schema_parsing():
    with pytest.raises(ValueError, match="8MiB"):
        engine.parse_input(b" " * (c.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="nesting"):
        engine.parse_input("[" * 33 + "0" + "]" * 33)


def test_runtime_modules_have_no_database_settings_scipy_or_network_imports():
    import pathlib
    import subprocess
    import sys

    script = "import sys;from app.ai import infection_cluster_statistics;assert 'app.database' not in sys.modules;assert 'app.config' not in sys.modules;assert 'scipy' not in sys.modules;assert 'httpx' not in sys.modules;assert 'sqlalchemy' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", script], cwd=pathlib.Path(__file__).parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
