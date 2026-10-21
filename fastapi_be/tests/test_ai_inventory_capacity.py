"""Actual bounded DTO/proof limits, not claims of procurement or hospital throughput."""

import copy

import pytest

from app.ai.inventory_config import runtime_descriptor, runtime_from_descriptor
from app.ai.inventory_contract import MAX_BYTES, InventorySource, canonical_json
from app.ai.inventory_model import compute_inventory
from tests.test_ai_inventory_contract import amount, candidate, lot, make_source, refresh


def maximum_source(candidate_count=1, lots=4096, days=31):
    value = make_source(days=days)
    value["observation"]["lots"] = [lot("capacity-stock:" + str(i), "0.000000", "0.000000", None) for i in range(lots)]
    for key in ("declared_total_quantity",):
        value["observation"][key] = amount("0.000000")
    value["observation"]["legacy_snapshot"]["catalog_quantity"] = amount("0.000000")
    value["observation"]["legacy_snapshot"]["batch_quantity_sum"] = amount("0.000000")
    for day in value["scenario"]["days"]:
        day["required_quantity"] = amount("0.000000")
    value["candidates"] = [candidate("capacity-plan:" + str(i), []) for i in range(candidate_count)]
    return refresh(value)


def test_actual_full_4096_opening_lots_31_days_proof_is_complete_and_bounded():
    source = InventorySource.model_validate(maximum_source())
    result = compute_inventory(source, "a" * 64, runtime_from_descriptor(runtime_descriptor()))
    assert result.best_among_declared_candidates and result.candidate_count == 1
    assert len(result.candidate_results[0].terminal_lots) == 4096
    assert len(result.candidate_results[0].daily) == 31
    assert len(canonical_json(result.model_dump()).encode()) < MAX_BYTES
    assert len(canonical_json(source.model_dump()).encode()) < MAX_BYTES


def test_actual_maximum_256_declared_candidates_keep_all_ties_without_selection():
    source = InventorySource.model_validate(maximum_source(256, 0, 1))
    result = compute_inventory(source, "a" * 64, runtime_from_descriptor(runtime_descriptor()))
    assert result.candidate_count == result.known_feasible_count == len(result.best_known_feasible_candidate_ids) == 256
    assert result.automatically_selected_candidate is None
    assert all(row.status == "feasible" and len(row.daily) == 1 for row in result.candidate_results)


def test_member_domain_overflow_rejected_without_truncation():
    value = maximum_source(lots=4096)
    value["observation"]["lots"].append(copy.deepcopy(value["observation"]["lots"][0]))
    with pytest.raises(ValueError):
        InventorySource.model_validate(value)
