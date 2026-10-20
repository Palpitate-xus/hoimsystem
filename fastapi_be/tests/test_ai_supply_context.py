"""Supply selection, exact short references, and public-only native serialization."""

import copy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.supply_context import SupplyContextBinding, _short_context, public_payload, selection, supply_evidence
from app.ai.supply_contract import canonical_json, hash_content
from tests.test_ai_supply_contract import make_source, uid


def binding_for_source(source, horizon=7):
    fields = (
        "series_id",
        "item_kind",
        "source_id",
        "content_hash",
        "profile_id",
        "profile_content_hash",
        "profile_governance_hash",
        "scope_token",
        "item_token",
        "unit_token",
        "rule_id",
        "recipe_digest",
        "input_policy_digest",
        "historical_collection_digest",
        "current_membership_digest",
        "member_manifest_hash",
    )
    return SupplyContextBinding(
        schema_version="supply_context_binding_v1",
        item_id=71,
        scope="hospital_inventory",
        unit_definition_id=uid("unit-private"),
        revision=2,
        series_governance_hash=source["governance_hash"],
        projection_hash=hash_content(source),
        collection_digest=hash_content("all private original roots"),
        horizon_days=horizon,
        **{key: source[key] for key in fields},
    ).model_dump(mode="json")


@pytest.mark.parametrize("horizon", [7, 14])
def test_only_complete_typed_public_quantities_and_horizon_are_sent(horizon):
    source = make_source()
    binding = binding_for_source(source, horizon)
    context = _short_context(binding, source["captured_at"])
    context.update(supply_source=source, supply_series={"snapshot": {"private_operator_note": "never-echo-this", "raw_unit": "私有单位"}})
    payload = public_payload({"input": {"supply_series_id": source["series_id"], "horizon_days": horizon, "question": "patient_name_private"}, "context": context})
    assert payload == {"context": {"supply_source": source}, "horizon_days": horizon}
    serialized = canonical_json(payload)
    assert all(text not in serialized for text in ("never-echo-this", "私有单位", "patient_name_private", uid("unit-private"), '"item_id"'))
    assert supply_evidence(binding)["content"] == canonical_json({"supply_binding": binding})


@pytest.mark.parametrize(
    "case",
    [
        "bool",
        "float",
        "string",
        "eight",
        "missing_series",
        "missing_horizon",
        "extra_quantity",
        "unit_override",
        "params_override",
        "non_uuid",
        "uppercase_uuid",
        "empty_question",
        "long_question",
        "wrong_question_type",
    ],
)
def test_selection_accepts_only_exact_reference_horizon_and_bounded_local_question(case):
    value = {"supply_series_id": uid("series"), "horizon_days": 7}
    if case in {"bool", "float", "string", "eight"}:
        value["horizon_days"] = {"bool": True, "float": 7.0, "string": "7", "eight": 8}[case]
    elif case == "missing_series":
        value.pop("supply_series_id")
    elif case == "missing_horizon":
        value.pop("horizon_days")
    elif case in {"extra_quantity", "unit_override", "params_override"}:
        value[{"extra_quantity": "quantity", "unit_override": "unit_token", "params_override": "parameters"}[case]] = 1
    elif case == "non_uuid":
        value["supply_series_id"] = 71
    elif case == "uppercase_uuid":
        value["supply_series_id"] = value["supply_series_id"].upper()
    elif case == "empty_question":
        value["question"] = ""
        assert selection(value) == (uid("series"), 7)
        return
    elif case == "long_question":
        value["question"] = "药" * 12001
    else:
        value["question"] = False
    with pytest.raises(HTTPException) as error:
        selection(value)
    assert error.value.status_code == 422


@pytest.mark.parametrize("field", ["series_id", "content_hash", "governance_hash", "unit_token", "profile_content_hash", "historical_collection_digest"])
def test_public_quantities_must_match_exact_frozen_original_and_profile(field):
    source = make_source()
    bound = binding_for_source(source)
    altered = copy.deepcopy(source)
    altered[field] = uid("other") if field == "series_id" else "f" * 64
    with pytest.raises((ValueError, ValidationError)):
        public_payload({"input": {"supply_series_id": source["series_id"], "horizon_days": 7}, "context": {"supply_binding": bound, "supply_source": altered}})
