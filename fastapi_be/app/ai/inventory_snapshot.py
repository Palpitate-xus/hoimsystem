"""Frozen scene proofs; own-byte audit never substitutes today's inventory or recipe."""

from typing import Any, Literal

from fastapi import HTTPException
from pydantic import Field

from app.ai import inventory_contract as core
from app.ai.inventory_native_source_input import ItemKind, Positive
from app.ai.inventory_scenario_input import ScenarioRequest, bounded_json, instant, profile_for, typed_period, validate_selections


class PrivateSnapshot(core.StrictModel):
    schema_version: Literal["inventory_scenario_private_v1"]
    scenario_id: core.UUID
    item_kind: ItemKind
    item_id: Positive
    scope: Literal["hospital_inventory"]
    created_by: Positive
    as_of: core.UtcText
    captured_at: core.UtcText
    identity_secret: str = Field(pattern=r"^[a-f0-9]{64}$")
    request: ScenarioRequest
    collection: dict[str, Any]
    collection_digest: core.SHA256
    recipe: dict[str, Any]
    input_policy: dict[str, Any]
    recipe_digest: core.SHA256
    input_policy_digest: core.SHA256
    profile: dict[str, Any]


def verify_snapshot(value):
    from app.ai.inventory_native_collection import verify_capture

    try:
        bounded_json(value)
        snapshot = PrivateSnapshot.model_validate(value).model_dump(mode="json")
        if core.canonical_json(snapshot) != core.canonical_json(value):
            raise ValueError("Closed private scene must retain its actual values and types")
        req = ScenarioRequest.model_validate(snapshot["request"])
        collection = snapshot["collection"]
        if not verify_capture(collection):
            raise ValueError("Whole current capture proof differs")
        if (
            any(snapshot[key] != getattr(req, key) for key in ("item_kind", "item_id", "scope", "as_of"))
            or collection["request"] != typed_period(req).model_dump(mode="json")
            or collection["as_of"] != snapshot["as_of"]
            or collection["captured_at"] != snapshot["captured_at"]
            or collection["collection_digest"] != snapshot["collection_digest"]
            or instant(snapshot["as_of"]) > instant(snapshot["captured_at"])
        ):
            raise ValueError("Frozen item, scope, cutoff and captured collection differ")
        if (
            core.hash_content(snapshot["recipe"]) != snapshot["recipe_digest"]
            or core.hash_content(snapshot["input_policy"]) != snapshot["input_policy_digest"]
            or snapshot["recipe"].get("input_policy") != snapshot["input_policy"]
            or snapshot["recipe"].get("rule_id") != core.RULE_ID
            or snapshot["profile"] != profile_for(req, snapshot["recipe_digest"], snapshot["input_policy_digest"])
        ):
            raise ValueError("Own original recipe, input policy or common profile differs")
        validate_selections(collection, req)
        return snapshot
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "库存场景完整身份、来源全集、政策或共同约束原件不一致") from exc


def local_resolution(value):
    snapshot = verify_snapshot(value)
    req = ScenarioRequest.model_validate(snapshot["request"])
    unit, selected, _ = validate_selections(snapshot["collection"], req)
    from app.ai.inventory_projection import opaque_uuid

    return {
        "schema_version": "inventory_local_resolution_v1",
        "scenario_id": snapshot["scenario_id"],
        "source_content_hash": core.hash_content(snapshot),
        "item_kind": snapshot["item_kind"],
        "item_id": snapshot["item_id"],
        "scope": snapshot["scope"],
        "sku_binding": snapshot["collection"]["sku_binding"],
        "unit_definition_id": req.unit_definition_id,
        "original_unit_text": unit["payload"]["original_unit_text"],
        "currency_text": req.cost_unit.currency_text,
        "original_cost_unit_text": req.cost_unit.original_cost_unit_text,
        "facts": [
            {"source_record_id": row["source_record_id"], "public_fact_id": opaque_uuid(snapshot, "fact", row["source_record_id"]), "source_kind": row["source_kind"], "source_id": row["source_id"]}
            for row in selected
        ],
        "candidates": [{"source_record_id": row["source_record_id"], "candidate_id": opaque_uuid(snapshot, "candidate", row["source_record_id"])} for row in selected[2:]],
    }
