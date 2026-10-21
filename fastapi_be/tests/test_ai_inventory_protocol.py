"""Actual schema14 response preserves the whole declared-candidate physical proof."""

import copy

import pytest
from pydantic import ValidationError

from app.ai.inventory_config import runtime_descriptor
from app.ai.inventory_protocol import parse_inventory_envelope
from app.ai.inventory_server import InventoryTask, build_response
from tests.test_ai_inventory_contract import candidate, refresh
from tests.test_ai_inventory_server import task


@pytest.fixture(scope="module")
def response():
    descriptor = runtime_descriptor()
    payload = task(descriptor)
    source = payload["input"]["context"]["inventory_source"]
    source["candidates"].append(candidate("protocol-zero-baseline", []))
    refresh(source)
    return build_response(InventoryTask.model_validate(payload), descriptor)


def test_actual_native_receipt_keeps_all_candidate_ledgers_and_exact_cost(response):
    result, input_tokens, output_tokens = parse_inventory_envelope(response, response["model_version"])
    assert input_tokens == output_tokens == 0
    assert result["inventory_analysis"] == response["inventory_analysis"]
    assert result["summary"] == response["result"]["summary"]
    assert len(result["inventory_analysis"]["candidate_results"]) == 2
    assert [row["total_cost"] for row in result["inventory_analysis"]["candidate_results"]] == [{"numerator": "5", "denominator": "2"}, {"numerator": "0", "denominator": "1"}]
    assert result["inventory_analysis"]["best_among_declared_candidates"] is True
    assert all(len(candidate["daily"]) == 3 for candidate in result["inventory_analysis"]["candidate_results"] if candidate["inventory_status"] != "unknown")


@pytest.mark.parametrize("case", ["schema", "model", "feature", "handled_int", "extra", "private_note", "missing_analysis", "missing_explanation", "usage_bool", "foreign_findings"])
def test_receipt_rejects_wrong_mode_missing_proof_and_scalar_coercion(response, case):
    value = copy.deepcopy(response)
    if case == "schema":
        value["schema_version"] = "13"
    elif case == "model":
        value["model_version"] = "inventory:" + "f" * 64
    elif case == "feature":
        value["feature_key"] = "inventory_auto_purchase"
    elif case == "handled_int":
        value["handled"] = 1
    elif case == "extra":
        value["supply_analysis"] = {}
    elif case == "private_note":
        value["result"]["patient_note"] = "never-echo-this"
    elif case == "missing_analysis":
        value.pop("inventory_analysis")
    elif case == "missing_explanation":
        value["result"].pop("missing_data")
    elif case == "foreign_findings":
        value["result"]["nursing_findings"] = []
    else:
        value["usage"]["input_tokens"] = False
    with pytest.raises((ValidationError, ValueError)):
        parse_inventory_envelope(value, response["model_version"])
