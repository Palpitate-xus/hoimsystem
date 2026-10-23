"""Real typed/JSON4096×256 pure boundary; no SQL or epidemiologic validation."""

import datetime as dt
from fractions import Fraction

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_projection as p
from app.ai import infection_cluster_statistics as engine
from app.ai import infection_cluster_statistics_contract as k
from tests.test_ai_infection_cluster_contract import collection, identifier, row


def maximal_input():
    rows = []
    for number in range(4096):
        inside = number == 0 or number >= 2048
        rows.append(
            row(number + 1, patient_id=number + 1, department_id=1 if number < 2048 else 2, onset_date="2026-10-15" if inside else "2026-01-01", infection_type="i", pathogen="p", description=None)
        )
    private = collection(rows, assessment="meets_definition")
    private["patient_ids"] = list(range(1, 4097))
    private["window"]["date_from"] = "2026-01-01"
    private["definition"]["payload"].update(version_label="v1", definition_text="synthetic-local-declaration", infection_type_codes=["I"], pathogen_codes=["P"])
    private["definition"]["content_hash"] = c.digest(private["definition"]["payload"])
    private["definition"]["governance"]["definition_content_hash"] = private["definition"]["content_hash"]
    private["definition"]["governance_hash"] = c.digest(private["definition"]["governance"])
    stamp = {"reviewed_by": 7, "reviewed_at": "2026-10-21T11:00:00.123456Z", "basis_note": "b", "basis_hash": c.text_digest("b")}
    for proposal, raw in zip(private["reviews"], rows):
        proposal["definition_content_hash"] = private["definition"]["content_hash"]
        proposal["definition_governance_hash"] = private["definition"]["governance_hash"]
        proposal["review"] = dict(stamp)
        for field, code in [("infection_type", "I"), ("pathogen", "P")]:
            proposal[field].update(assessment="mapped", reviewed_code=code, review=dict(stamp))
    # Mechanical private Source parsing/HMAC projection is real; these are still
    # synthetic declaration fixtures, without server publication authority.
    source = p.project_source(c.verify_private_collection(private), b"C" * 32)
    department = source.reports[0].department_token
    windows = [
        {"date_from": (dt.date(2026, 1, 2) + dt.timedelta(days=index)).isoformat(), "date_to": "2026-10-15", "coordinate_basis": "recorded_onset_date_inclusive_no_event_timezone"}
        for index in range(256)
    ]
    plan = {
        "schema_version": "infection_comparison_plan_v1",
        "scenario_id": identifier(7901),
        "source_binding": {
            "snapshot_id": private["collection_id"],
            "source_id": source.source_id,
            "private_collection_hash": source.private_collection_hash,
            "public_source_hash": c.digest(source),
            "witness_hash": "a" * 64,
        },
        "department_tokens": [department],
        "windows": windows,
        "pathogen_code": "P",
        "alpha_decimal": "0.0100",
        "method": "one_sided_fisher_greater_fixed_margins",
        "family_basis": "complete_declared_department_by_window_cartesian_product",
        "declaration_basis": "declared_before_this_execution_not_proven_independent_of_observed_data",
        "no_population_denominator": "not_provided",
    }
    return {
        "schema_version": "infection_statistics_input_v1",
        "source": source.model_dump(mode="json"),
        "scenario": plan,
        "scenario_content_hash": c.digest(plan),
        "scenario_governance_hash": "b" * 64,
        "recipe_hash": c.digest(k.RECIPE),
        "authority_basis": "pure_structure_and_arithmetic_only_server_must_verify_current_authority",
    }


def test_actual_typed_full_256_by_4096_and_long_hypergeometric_tails(record_property):
    value = maximal_input()
    raw = c.utf8(c.canonical(value))
    output = engine.evaluate(raw)
    assert output.eligible_records == 4096 and output.family_size == 256
    assert len(output.record_dispositions) == 4096 and len(output.candidates) == 256
    assert output.preflight_work_upper_bound == 2102272 <= k.MAX_WORK
    for item in output.candidates:
        assert item.table.model_dump() == dict(window_in_department=1, window_in_other=2048, window_out_department=2047, window_out_other=0)
        assert item.status == "evaluated"  # fixed margins are not degenerate
        assert item.exact_p.model_dump() == k.rational(Fraction(1))
        assert item.bonferroni_p.model_dump() == k.rational(Fraction(1))
        assert item.nominal_declared_family_threshold_met is False
    result_raw = c.utf8(c.canonical(output))
    assert len(raw) <= c.MAX_BYTES and len(result_raw) <= c.MAX_BYTES
    record_property("typed_full_input_bytes", len(raw))
    record_property("whole_result_bytes", len(result_raw))
    record_property("full_candidate_table_record_visits", 4096 * 256)
    record_property("actual_hypergeometric_tail_terms", 2048 * 256)
