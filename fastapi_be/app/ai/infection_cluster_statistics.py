"""Exact bounded integer arithmetic for one finite declared comparison family.

Pure functions grant no Source, Department, publication or clinical authority.
No SciPy/numpy dependency, external model, random simulation, or retries.
"""

import json
import math
from collections import Counter
from fractions import Fraction

from pydantic import BaseModel

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_statistics_contract as k


def parse_input(value):
    if isinstance(value, (str, bytes)):
        if isinstance(value, bytes):
            if not 0 < len(value) <= c.MAX_BYTES:
                raise ValueError("Whole statistics input exceeds8MiB")
            value = value.decode("utf-8", errors="strict")
        if not 0 < len(c.utf8(value)) <= c.MAX_BYTES:
            raise ValueError("Whole statistics input exceeds8MiB")
        c._lexical_budget(value)
        value = json.loads(value, object_pairs_hook=c._pairs, parse_constant=c._nonfinite)
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    c.canonical(value)
    return k.StatisticsInput.model_validate(value, strict=True)


def fisher_upper_tail(a, b, cc, d):
    """P[X>=a] for fixed n=a+b,K=a+cc,N=a+b+cc+d, with exact integers."""
    values = (a, b, cc, d)
    if any(type(value) is not int or value < 0 for value in values) or sum(values) > c.MAX_ROOTS:
        raise ValueError("Actual nonnegative integer case counts within4096 are required")
    total, window, department = sum(values), a + b, a + cc
    if total == 0:
        return Fraction(1)
    last = min(window, department)
    weight = math.comb(department, a) * math.comb(total - department, window - a)
    numerator = weight
    for x in range(a, last):
        numerator_factor = weight * (department - x) * (window - x)
        denominator_factor = (x + 1) * (total - department - window + x + 1)
        weight, remainder = divmod(numerator_factor, denominator_factor)
        if remainder:
            raise ArithmeticError("Exact hypergeometric recurrence was not integral")
        numerator += weight
    return Fraction(numerator, math.comb(total, window))


def dispositions(source, code):
    result, eligible = [], []
    for report in source.reports:
        reasons = []
        if report.human_assessment != "meets_definition":
            reasons.append({"does_not_meet": "human_does_not_meet_definition", "undetermined": "human_undetermined", "not_assessed": "human_not_assessed"}[report.human_assessment])
        if report.pathogen.original_state in {"null", "empty"}:
            reasons.append("pathogen_" + report.pathogen.original_state)
        if report.pathogen.assessment != "mapped":
            reasons.append("pathogen_code_not_mapped")
        elif report.pathogen.reviewed_code != code:
            reasons.append("other_reviewed_pathogen_code")
        if report.department_token is None:
            reasons.append("department_not_recorded")
        if not reasons:
            state = "eligible"
            eligible.append(report)
        elif "human_does_not_meet_definition" in reasons or "other_reviewed_pathogen_code" in reasons:
            state = "excluded"
        else:
            state = "unknown"
        result.append(k.RecordDisposition(case_token=report.case_token, patient_token=report.patient_token, original_content_hash=report.original_content_hash, disposition=state, reasons=reasons))
    return result, eligible


def fixed_expectations(a, b, cc, d):
    total, window, department = a + b + cc + d, a + b, a + cc
    if total == 0:
        return None
    return k.Expectations(
        window_in_department=k.rational(Fraction(window * department, total)),
        window_in_other=k.rational(Fraction(window * (total - department), total)),
        window_out_department=k.rational(Fraction((total - window) * department, total)),
        window_out_other=k.rational(Fraction((total - window) * (total - department), total)),
        basis="fixed_observed_case_table_margins_under_independence_null_not_population_expectation",
    )


def evaluate(value):
    data = parse_input(value)
    source, plan = data.source, data.scenario
    family_size = len(plan.department_tokens) * len(plan.windows)
    count = len(source.reports)
    # Before table visits or large combinatorial arithmetic, bound the whole
    # computation, including classification, all rows and all possible tails.
    work_upper = count + family_size * (count + count + 1 + 3)
    if work_upper > k.MAX_WORK:
        raise ValueError("The whole declared computation exceeds its fixed work budget")
    ledger, eligible = dispositions(source, plan.pathogen_code)
    subjects = Counter(report.patient_token for report in eligible)
    repeated = sorted(token for token, number in subjects.items() if number > 1)
    counts = Counter(item.disposition for item in ledger)
    alpha = k.alpha_fraction(plan.alpha_decimal)
    comparisons = []
    for department in plan.department_tokens:
        for window in plan.windows:
            table = [0, 0, 0, 0]
            for report in eligible:
                inside = window.date_from <= report.onset_date <= window.date_to
                same_department = report.department_token == department
                table[(0 if inside else 2) + (0 if same_department else 1)] += 1
            a, b, cc, d = table
            degenerate = not eligible or a + b in {0, len(eligible)} or a + cc in {0, len(eligible)}
            if repeated:
                status, raw, adjusted, threshold, expected = "inference_unavailable", None, None, None, None
            else:
                status = "no_information" if degenerate else "evaluated"
                raw = fisher_upper_tail(a, b, cc, d)
                adjusted = min(Fraction(1), family_size * raw)
                threshold = False if degenerate else adjusted <= alpha
                expected = fixed_expectations(a, b, cc, d)
            comparisons.append(
                k.Candidate(
                    candidate_id=c.digest({"department_token": department, "window": window.model_dump(mode="json")}),
                    department_token=department,
                    window=window,
                    table=k.Table(window_in_department=a, window_in_other=b, window_out_department=cc, window_out_other=d),
                    fixed_margin_expectations=expected,
                    status=status,
                    exact_p=None if raw is None else k.rational(raw),
                    bonferroni_p=None if adjusted is None else k.rational(adjusted),
                    nominal_declared_family_threshold_met=threshold,
                    comparison_basis="case_set_department_time_association_not_risk_or_diagnosis",
                )
            )
    result = k.Analysis(
        schema_version="infection_statistics_analysis_v1",
        source_binding=plan.source_binding,
        scenario_content_hash=data.scenario_content_hash,
        scenario_governance_hash=data.scenario_governance_hash,
        recipe_hash=data.recipe_hash,
        status="inference_unavailable_repeated_eligible_subject" if repeated else "evaluated_in_declared_case_set",
        family_size=family_size,
        eligible_records=counts["eligible"],
        excluded_records=counts["excluded"],
        unknown_records=counts["unknown"],
        repeated_eligible_subject_tokens=repeated,
        record_dispositions=ledger,
        candidates=comparisons,
        preflight_work_upper_bound=work_upper,
        arithmetic_basis="exact_integer_hypergeometric_tail_and_rational_bonferroni",
        denominator="not_provided",
        automatic_actions=False,
        limitations=k.LIMITATIONS,
    )
    c.canonical(result)
    return result


def verify_analysis_binding(value, analysis):
    """Recompute every record/table/exact result; a self-rehash is not a proof."""
    try:
        expected = evaluate(value)
        actual = k.Analysis.model_validate(analysis.model_dump(mode="json") if isinstance(analysis, BaseModel) else analysis, strict=True)
        return c.canonical(actual) == c.canonical(expected)
    except (ValueError, TypeError, KeyError):
        return False
