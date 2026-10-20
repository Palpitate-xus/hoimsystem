"""Actual typed maximum roots/history and explicit early exact-computation refusal."""

import uuid
from fractions import Fraction

import pytest

from app.ai.supply_config import runtime_descriptor, runtime_from_descriptor
from app.ai.supply_contract import MAX_BYTES, MAX_MEMBERS, SupplySource, canonical_json, hash_content, rational
from app.ai.supply_model import Budget, compute_supply, forecast_target
from tests.test_ai_supply_contract import make_source, refresh_manifest


def maximum_source(denominator=10):
    values = [str((index * 37) % 11) if index % 3 == 0 else "0" for index in range(366)]
    value = make_source(values=values)
    for key in value["parameters"]:
        value["parameters"][key] = rational(Fraction(1, denominator))
    while len(value["member_manifest"]) < MAX_MEMBERS:
        index = len(value["member_manifest"])
        identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, "supply-unselected:" + str(index)))
        digest = hash_content([identifier, "draft"])
        value["member_manifest"].append(
            {
                "source_record_id": identifier,
                "source_id": f"supply_day:{identifier}:{digest[:12]}",
                "kind": "daily_quantity",
                "content_hash": digest,
                "governance_hash": hash_content([identifier, "rev1"]),
                "status": "draft",
                "eligible": False,
                "selection": "excluded",
                "selection_basis_hash": hash_content("actual whole original not selected"),
            }
        )
    return refresh_manifest(value)


def test_actual_366_days_three_targets_4096_root_source_and_exact_native_complete():
    source = SupplySource.model_validate(maximum_source())
    assert len(source.days) == 366 and len(source.observations) == 1098 and len(source.member_manifest) == 4096
    assert len(canonical_json(source.model_dump()).encode()) < MAX_BYTES
    result = compute_supply(source, 14, "a" * 64, runtime_from_descriptor(runtime_descriptor()))
    assert all(target.status == "complete" for target in result.targets)
    assert all(model.eligible_pair_count == 392 for target in result.targets for model in target.models)
    assert len(canonical_json(result.model_dump()).encode()) < MAX_BYTES


def test_extreme_legal_parameters_refuse_whole_calculation_at_explicit_budget():
    source = SupplySource.model_validate(maximum_source(997))
    with pytest.raises(ValueError, match="budget|UTF8 bound"):
        compute_supply(source, 14, "a" * 64, runtime_from_descriptor(runtime_descriptor()))


def test_individual_large_prediction_evidence_is_bounded_before_next_record():
    value = maximum_source(997)
    values = [row["quantity"]["value"] for row in value["observations"] if row["target"] == "recorded_request_quantity"]
    dates = [row["date"] for row in value["days"]]
    budget = Budget(max_bytes=500000)
    with pytest.raises(ValueError, match="proof construction"):
        forecast_target(values, dates, 14, value["parameters"], budget)
    # One bounded record may trigger refusal; there is no whole-result list first.
    assert 500000 < budget.bytes < 2 * 500000
