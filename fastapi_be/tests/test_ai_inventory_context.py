"""Short scenario references and typed public payloads never export private hospital bodies."""

import copy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.inventory_context import InventoryContextBinding, _short_context, inventory_evidence, public_payload, selection
from app.ai.inventory_contract import hash_content
from tests.test_ai_inventory_contract import make_source, uid


def bundle():
    source = make_source()
    public_keys = (
        "scenario_id",
        "item_kind",
        "source_id",
        "content_hash",
        "member_manifest_hash",
        "profile_id",
        "profile_content_hash",
        "profile_governance_hash",
        "scope_token",
        "item_token",
        "quantity_unit_token",
        "cost_unit_token",
        "rule_id",
        "recipe_digest",
        "input_policy_digest",
    )
    bound = InventoryContextBinding(
        schema_version="inventory_context_binding_v1",
        **{key: source[key] for key in public_keys},
        item_id=17,
        scope="hospital_inventory",
        unit_definition_id=uid("actual unit"),
        revision=2,
        scenario_governance_hash=source["governance_hash"],
        projection_hash=hash_content(source),
        collection_digest=hash_content("entire private current collection"),
    ).model_dump(mode="json")
    return {
        "input": {"inventory_scenario_id": source["scenario_id"], "question": "院内备注never-export-private-question"},
        "context": {
            **_short_context(bound, "2026-10-20T12:00:02.123456Z"),
            "inventory_source": source,
            "inventory_scenario": {"snapshot": {"identity_secret": "never-export-secret", "name": "never-export-name"}},
        },
    }


@pytest.mark.parametrize(
    "values",
    [
        None,
        [],
        {},
        {"inventory_scenario_id": None},
        {"inventory_scenario_id": True},
        {"inventory_scenario_id": 17},
        {"inventory_scenario_id": "x"},
        {"inventory_scenario_id": "urn:uuid:" + uid("scenario")},
        {"inventory_scenario_id": uid("scenario"), "question": 2},
        {"inventory_scenario_id": uid("scenario"), "question": "字" * 12001},
        {"inventory_scenario_id": uid("scenario"), "horizon_days": 7},
        {"inventory_scenario_id": uid("scenario"), "stock": 0},
        {"inventory_scenario_id": uid("scenario"), "patient_id": 1},
        {"inventory_scenario_id": uid("scenario"), "candidate_ids": []},
    ],
)
def test_selection_only_accepts_exact_canonical_scenario_and_optional_bounded_question(values):
    with pytest.raises(HTTPException) as error:
        selection(values)
    assert error.value.status_code == 422


def test_outbound_only_contains_complete_typed_source_and_omits_all_private_context_and_question():
    data = bundle()
    before = copy.deepcopy(data)
    outgoing = public_payload(data)
    assert outgoing == {"context": {"inventory_source": data["context"]["inventory_source"]}}
    assert data == before
    assert "never-export" not in str(outgoing)
    assert outgoing["context"]["inventory_source"]["observation"]["declared_total_quantity"]["value"] == "5"
    assert outgoing["context"]["inventory_source"]["candidates"][0]["plan_fixed_fee"]["value"] == "0"


@pytest.mark.parametrize(
    "case",
    [
        "selected_scenario",
        "foreign_source_id",
        "projection",
        "governance",
        "quantity_unit",
        "cost_unit",
        "item_token",
        "scope_token",
        "profile",
        "recipe",
        "policy",
        "members",
        "original_quantity",
        "original_price",
        "private_source_field",
        "coerced_quantity",
    ],
)
def test_public_payload_rejects_original_or_projection_binding_changes(case):
    data = bundle()
    source, bound = data["context"]["inventory_source"], data["context"]["inventory_binding"]
    if case == "selected_scenario":
        data["input"]["inventory_scenario_id"] = uid("different scenario")
    elif case == "foreign_source_id":
        source["source_id"] = "inventory_scenario:" + uid("different") + ":" + source["content_hash"][:12]
    elif case == "projection":
        bound["projection_hash"] = "0" * 64
    elif case == "governance":
        bound["scenario_governance_hash"] = "0" * 64
    elif case in {"quantity_unit", "cost_unit", "item_token", "scope_token"}:
        key = {"quantity_unit": "quantity_unit_token", "cost_unit": "cost_unit_token"}.get(case, case)
        bound[key] = "0" * 64
    elif case in {"profile", "recipe", "policy", "members"}:
        key = {"profile": "profile_content_hash", "recipe": "recipe_digest", "policy": "input_policy_digest", "members": "member_manifest_hash"}[case]
        bound[key] = "0" * 64
    elif case == "original_quantity":
        source["observation"]["declared_total_quantity"]["value"] = "6"
    elif case == "original_price":
        source["candidates"][0]["orders"][0]["lines"][0]["unit_price"]["value"] = "2.00"
    elif case == "private_source_field":
        source["patient_name"] = "never-export-name"
    else:
        source["observation"]["declared_total_quantity"]["value"] = 5
    with pytest.raises((ValueError, ValidationError)):
        public_payload(data)


def test_evidence_is_exact_short_citation_without_original_bodies_or_private_governance():
    data = bundle()
    context = data["context"]
    evidence = inventory_evidence(context["inventory_binding"])
    assert evidence["source_id"] == context["inventory_source"]["source_id"]
    assert evidence["kind"] == "operational_record"
    assert "never-export" not in evidence["content"]
    assert "inventory_binding" in evidence["content"] and '"candidates"' not in evidence["content"]
    assert context["selected_sources"] == {"inventory_scenario_id": data["input"]["inventory_scenario_id"]}
    assert context["snapshot_time"] == "2026-10-20T12:00:02.123456Z"
