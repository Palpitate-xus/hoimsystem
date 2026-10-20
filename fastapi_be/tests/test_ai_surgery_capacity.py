"""Actual typed construction budgets; synthetic counts are engineering probes."""

import copy
from datetime import UTC, datetime, timedelta

import pytest

from app.ai.surgery_config import runtime_descriptor, runtime_from_descriptor
from app.ai.surgery_contract import MAX_BYTES, SurgerySource, canonical_json, hash_content
from app.ai.surgery_model import check_candidate, compute_surgery
from tests.test_ai_surgery_contract import H, amount, source_dict, uid
from tests.test_ai_surgery_model import assignment


def amplified_source_dict():
    body = source_dict()
    while len(body["manifest"]) < 8192:
        item = copy.deepcopy(body["manifest"][-1])
        item["fact_id"] = uid(10000 + len(body["manifest"]))
        body["manifest"].append(item)
    body["collection"]["manifest_digest"] = hash_content(body["manifest"])
    case = body["cases"][0]
    case["roles"], case["equipment"] = [], []
    case["ref_ids"] = sorted(item["fact_id"] for item in body["manifest"])
    case["timing"]["segments"] = [
        {"segment_id": f"stage_{index:04}", "start_offset_us": amount(str(2 * index)), "end_offset_us": amount(str(2 * index + 1)), "ref_ids": [uid(3)]} for index in range(8192)
    ]
    ids = [item["segment_id"] for item in case["timing"]["segments"]]
    case["room"]["occupation"]["segment_ids"] = ids
    case["patient_presence"]["segment_ids"] = ids
    return body


def maximum_source_dict():
    body = source_dict()
    original = copy.deepcopy(body["cases"][0])
    cases = []
    for index in range(256):
        case = copy.deepcopy(original)
        case["case_id"], case["patient_conflict_token"] = uid(20000 + index), uid(30000 + index)
        case["starts"][0]["start_at"] = (datetime(2026, 10, 21, 8, tzinfo=UTC) + timedelta(microseconds=2 * index + 1)).isoformat(timespec="microseconds").replace("+00:00", "Z")
        case["timing"]["segments"][0]["end_offset_us"] = amount("1")
        refs = []
        for offset, kind in enumerate(("case_requirements", "case_duration_estimate")):
            fact = copy.deepcopy(body["manifest"][0])
            fact.update(fact_id=uid(40000 + 2 * index + offset), kind=kind)
            body["manifest"].append(fact)
            refs.append(fact["fact_id"])
        case["ref_ids"] = [refs[0]]
        case["timing"]["segments"][0]["ref_ids"] = [refs[1]]
        cases.append(case)
    body["cases"] = cases
    body["collection"]["manifest_digest"] = hash_content(body["manifest"])
    return body


def test_typed_source_with_repeated_large_provenance_is_rejected_during_check_construction():
    body = amplified_source_dict()
    assert len(canonical_json(body).encode()) < MAX_BYTES
    source = SurgerySource.model_validate(body)
    assert len(source.manifest) == len(source.cases[0].timing.segments) == 8192
    # Passing constraints also carry provenance; never stream gigabytes before
    # reaching the selected occupancy result's later 8MiB capacity guard.
    with pytest.raises(ValueError, match="canonical check stream.*construction capacity"):
        check_candidate(source, [assignment(body["cases"][0])], [])


def test_actual_maximum_case_count_solves_every_required_resource_under_fixed_budgets():
    source = SurgerySource.model_validate(maximum_source_dict())
    analysis = compute_surgery(source, H, runtime_from_descriptor(runtime_descriptor()))
    assert analysis.solve_status == "optimal_proven"
    assert analysis.solution.scheduled_count == 256
    assert len(analysis.solution.occupancies) == 1024
    assert analysis.feasible_incumbent_objective.penalty_points == "0"
    assert analysis.definite_search.primitive_operations <= analysis.definite_search.work_limits.operation_limit
