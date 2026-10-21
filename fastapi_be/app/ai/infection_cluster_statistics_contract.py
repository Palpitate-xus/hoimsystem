"""Pure finite case-set comparisons; no clinical authority or model activation.

The complete family is declared before this execution. This does not establish
that its choice was independent of already observed data or earlier analyses.
"""

import math
import re
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_projection as p

MAX_COMPARISONS = 256
MAX_WORK = 2110000
Count = Annotated[int, Field(strict=True, ge=0, le=c.MAX_ROOTS)]
NaturalText = Annotated[str, Field(strict=True, pattern=r"^(0|[1-9][0-9]{0,1279})$", max_length=1280)]
PositiveText = Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,1279}$", max_length=1280)]
RECIPE = {
    "version": "infection_case_set_fisher_v1",
    "max_records": c.MAX_ROOTS,
    "max_comparisons": MAX_COMPARISONS,
    "whole_input_and_result_bytes_each": c.MAX_BYTES,
    "work_limit": MAX_WORK,
    "work_units": "classification_visits_plus_eligible_table_visits_plus_hypergeometric_terms_plus_three_binomial_primitives_per_candidate",
    "method": "exact_integer_hypergeometric_upper_tail",
    "alternative": "greater",
    "family": "complete_declared_department_by_window_cartesian_product",
    "adjustment": "min_one_family_size_times_p",
    "duplicate_eligible_subject": "whole_inference_unavailable_without_deduplication",
    "degenerate": "exact_p_one_and_no_information",
    "selection_limitation": "not_adjusted_for_data_dependent_family_selection_or_repeated_analyses",
}
LIMITATIONS = [
    "Conditional associations concern only this finite explicit case-record set and reviewed pathogen stratum, not infection incidence, individual risk, an outbreak diagnosis, or an intervention instruction.",
    "No population denominator was supplied. Selected or observed patient counts are not a surveillance population denominator.",
    "Records not meeting the declared eligibility requirements remain individually listed, with unknown and excluded categories separated; they are not normal or negative observations.",
    "The entire declared department by window family is retained, including empty and fixed-margin comparisons. No candidate is dropped according to its observed count or p-value.",
    "Adjustment applies only to this complete declared family. It does not control undisclosed data-dependent family selection or repeated analyses.",
    "Current independent technical publication proves a declaration before this execution, not that the plan was chosen without seeing data, professional competence, or local clinical validation.",
    "Case capture, reporting practices and classification changes can change the observed pattern. These comparisons do not distinguish those mechanisms from actual changes in infection.",
    "Repeated eligible subject tokens prevent the independence assumption for this record-level method. In that case all counts remain, and the whole inference is unavailable rather than deduplicated.",
    "Stored onset calendar dates are used literally; no UTC event-time or historical availability claim is added.",
    "This pure evaluator proves mechanical bindings and arithmetic only; it does not authorize Source reads, prove Department identity, publish a Scenario, or enable clinical use.",
]


class Rational(c.StrictModel):
    numerator: NaturalText
    denominator: PositiveText

    @model_validator(mode="after")
    def reduced(self):
        if math.gcd(int(self.numerator), int(self.denominator)) != 1:
            raise ValueError("Exact fractions are reduced and never floating-point quantities")
        return self


class Probability(Rational):
    @model_validator(mode="after")
    def unit_interval(self):
        if int(self.numerator) > int(self.denominator):
            raise ValueError("An exact p-value lies in[0,1]")
        return self


def rational(value: Fraction):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def alpha_fraction(value):
    if type(value) is not str or re.fullmatch(r"0\.[0-9]{1,12}", value) is None:
        raise ValueError("Alpha must be an explicit original plain decimal string, without a default")
    fraction = Fraction(value)
    if not 0 < fraction < 1:
        raise ValueError("This method accepts explicit alpha strictly between0and1")
    return fraction


class SourceBinding(c.StrictModel):
    snapshot_id: c.UUID
    source_id: str = Field(pattern=r"^infection_reports:[a-f0-9]{64}:[a-f0-9]{12}$", max_length=95)
    private_collection_hash: c.SHA
    public_source_hash: c.SHA
    witness_hash: c.SHA


class ScenarioPlan(c.StrictModel):
    schema_version: Literal["infection_comparison_plan_v1"]
    scenario_id: c.UUID
    source_binding: SourceBinding
    department_tokens: list[c.SHA] = Field(min_length=1, max_length=MAX_COMPARISONS)
    windows: list[c.CalendarWindow] = Field(min_length=1, max_length=MAX_COMPARISONS)
    pathogen_code: c.Code
    alpha_decimal: str
    method: Literal["one_sided_fisher_greater_fixed_margins"]
    family_basis: Literal["complete_declared_department_by_window_cartesian_product"]
    declaration_basis: Literal["declared_before_this_execution_not_proven_independent_of_observed_data"]
    no_population_denominator: Literal["not_provided"]

    @model_validator(mode="after")
    def whole_family(self):
        alpha_fraction(self.alpha_decimal)
        if len(set(self.department_tokens)) != len(self.department_tokens):
            raise ValueError("Department candidates cannot be silently deduplicated")
        keys = [(window.date_from, window.date_to) for window in self.windows]
        if len(set(keys)) != len(keys):
            raise ValueError("Identical windows cannot silently change family size")
        if len(self.department_tokens) * len(self.windows) > MAX_COMPARISONS:
            raise ValueError("The complete Cartesian family exceeds256; no clipping is allowed")
        c.canonical(self)
        return self


class StatisticsInput(c.StrictModel):
    schema_version: Literal["infection_statistics_input_v1"]
    source: p.InfectionClusterSource
    scenario: ScenarioPlan
    scenario_content_hash: c.SHA
    scenario_governance_hash: c.SHA
    recipe_hash: c.SHA
    authority_basis: Literal["pure_structure_and_arithmetic_only_server_must_verify_current_authority"]

    @model_validator(mode="after")
    def all_bindings(self):
        binding = self.scenario.source_binding
        if binding.source_id != self.source.source_id or binding.private_collection_hash != self.source.private_collection_hash or binding.public_source_hash != c.digest(self.source):
            raise ValueError("The exact finite Source projection binding differs")
        if self.scenario_content_hash != c.digest(self.scenario) or self.recipe_hash != c.digest(RECIPE):
            raise ValueError("The full scenario/recipe hashes differ")
        scope = self.source.scope.window
        if any(window.date_from < scope.date_from or window.date_to > scope.date_to for window in self.scenario.windows):
            raise ValueError("Every whole candidate window stays in the recorded Source calendar")
        c.canonical(self)
        return self


Reason = Literal[
    "human_does_not_meet_definition",
    "human_undetermined",
    "human_not_assessed",
    "pathogen_null",
    "pathogen_empty",
    "pathogen_code_not_mapped",
    "other_reviewed_pathogen_code",
    "department_not_recorded",
]


class RecordDisposition(c.StrictModel):
    case_token: c.SHA
    patient_token: c.SHA
    original_content_hash: c.SHA
    disposition: Literal["eligible", "excluded", "unknown"]
    reasons: list[Reason] = Field(max_length=8)

    @model_validator(mode="after")
    def separate_unknown(self):
        if len(set(self.reasons)) != len(self.reasons) or (self.disposition == "eligible") != (not self.reasons):
            raise ValueError("Every noneligible original retains explicit unique reasons")
        return self


class Table(c.StrictModel):
    window_in_department: Count
    window_in_other: Count
    window_out_department: Count
    window_out_other: Count


class Expectations(c.StrictModel):
    window_in_department: Rational
    window_in_other: Rational
    window_out_department: Rational
    window_out_other: Rational
    basis: Literal["fixed_observed_case_table_margins_under_independence_null_not_population_expectation"]


class Candidate(c.StrictModel):
    candidate_id: c.SHA
    department_token: c.SHA
    window: c.CalendarWindow
    table: Table
    fixed_margin_expectations: Expectations | None
    status: Literal["evaluated", "no_information", "inference_unavailable"]
    exact_p: Probability | None
    bonferroni_p: Probability | None
    nominal_declared_family_threshold_met: bool | None
    comparison_basis: Literal["case_set_department_time_association_not_risk_or_diagnosis"]

    @model_validator(mode="after")
    def no_false_inference(self):
        values = (self.exact_p, self.bonferroni_p, self.nominal_declared_family_threshold_met)
        if self.status == "inference_unavailable":
            if any(value is not None for value in values) or self.fixed_margin_expectations is not None:
                raise ValueError("Unavailable inference cannot retain p-values or modeled expectations")
        elif any(value is None for value in values):
            raise ValueError("Evaluated/degenerate comparisons retain their exact p-values")
        if self.status == "no_information" and (
            self.exact_p.numerator,
            self.exact_p.denominator,
            self.bonferroni_p.numerator,
            self.bonferroni_p.denominator,
            self.nominal_declared_family_threshold_met,
        ) != ("1", "1", "1", "1", False):
            raise ValueError("Degenerate p=1 is no information, never a normal/negative result")
        return self


class Analysis(c.StrictModel):
    schema_version: Literal["infection_statistics_analysis_v1"]
    source_binding: SourceBinding
    scenario_content_hash: c.SHA
    scenario_governance_hash: c.SHA
    recipe_hash: c.SHA
    status: Literal["evaluated_in_declared_case_set", "inference_unavailable_repeated_eligible_subject"]
    family_size: Annotated[int, Field(strict=True, ge=1, le=MAX_COMPARISONS)]
    eligible_records: Count
    excluded_records: Count
    unknown_records: Count
    repeated_eligible_subject_tokens: list[c.SHA] = Field(max_length=c.MAX_ROOTS)
    record_dispositions: list[RecordDisposition] = Field(max_length=c.MAX_ROOTS)
    candidates: list[Candidate] = Field(min_length=1, max_length=MAX_COMPARISONS)
    preflight_work_upper_bound: Annotated[int, Field(strict=True, ge=0, le=MAX_WORK)]
    arithmetic_basis: Literal["exact_integer_hypergeometric_tail_and_rational_bonferroni"]
    denominator: Literal["not_provided"]
    automatic_actions: bool = Field(strict=True)
    limitations: list[str] = Field(min_length=len(LIMITATIONS), max_length=len(LIMITATIONS))

    @model_validator(mode="after")
    def complete_counts(self):
        from collections import Counter

        counts = Counter(item.disposition for item in self.record_dispositions)
        if (
            self.limitations != LIMITATIONS
            or len(self.candidates) != self.family_size
            or len({item.case_token for item in self.record_dispositions}) != len(self.record_dispositions)
            or len({item.candidate_id for item in self.candidates}) != self.family_size
        ):
            raise ValueError("The full record ledger and declared family remain complete")
        if (self.eligible_records, self.excluded_records, self.unknown_records) != (counts["eligible"], counts["excluded"], counts["unknown"]):
            raise ValueError("All original records retain their exact disposition counts")
        duplicates = Counter(item.patient_token for item in self.record_dispositions if item.disposition == "eligible")
        actual = sorted(token for token, count in duplicates.items() if count > 1)
        if self.repeated_eligible_subject_tokens != actual or (self.status == "inference_unavailable_repeated_eligible_subject") != bool(actual):
            raise ValueError("Repeated eligible subjects cannot be silently merged or ignored")
        for candidate in self.candidates:
            if sum(candidate.table.model_dump().values()) != self.eligible_records or (candidate.status == "inference_unavailable") != bool(actual):
                raise ValueError("Every complete table uses the same eligible finite records")
        c.canonical(self)
        return self
