"""The actual native receipt preserves exact quantities and rejects mixed/coerced envelopes."""

import copy

import pytest
from pydantic import ValidationError

from app.ai.supply_config import runtime_descriptor
from app.ai.supply_protocol import parse_supply_envelope
from app.ai.supply_server import SupplyTask, build_response
from tests.test_ai_supply_server import task


@pytest.fixture(scope="module")
def response():
    descriptor = runtime_descriptor()
    return build_response(SupplyTask.model_validate(task(descriptor)), descriptor)


def test_actual_native_receipt_preserves_all_targets_folds_and_rational_text(response):
    result, input_tokens, output_tokens = parse_supply_envelope(response, response["model_version"])
    assert input_tokens == output_tokens == 0
    assert result["supply_analysis"] == response["supply_analysis"]
    targets = result["supply_analysis"]["targets"]
    assert len(targets) == 3 and all(len(target["models"]) == 6 for target in targets)
    assert all(len(model["rolling_origins"]) == 28 for target in targets for model in target["models"])
    assert targets[0]["models"][0]["prediction"]["values"][0] == {"numerator": "2", "denominator": "1"}


@pytest.mark.parametrize("case", ["schema", "model", "feature", "handled_int", "extra", "private_note", "missing_analysis", "missing_explanation", "usage_bool"])
def test_receipt_rejects_wrong_mode_missing_proof_and_scalar_coercion(response, case):
    value = copy.deepcopy(response)
    if case == "schema":
        value["schema_version"] = "12"
    elif case == "model":
        value["model_version"] = "supply:" + "f" * 64
    elif case == "feature":
        value["feature_key"] = "supply_replenishment"
    elif case == "handled_int":
        value["handled"] = 1
    elif case == "extra":
        value["bed_analysis"] = {}
    elif case == "private_note":
        value["result"]["patient_note"] = "never-echo-this"
    elif case == "missing_analysis":
        value.pop("supply_analysis")
    elif case == "missing_explanation":
        value["result"].pop("missing_data")
    else:
        value["usage"]["input_tokens"] = False
    with pytest.raises((ValidationError, ValueError)):
        parse_supply_envelope(value, response["model_version"])
