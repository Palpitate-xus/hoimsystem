"""Own complete immutable proofs, separate from current authorization and freshness."""

from typing import Any, Literal

from fastapi import HTTPException
from pydantic import Field

from app.ai import supply_contract as core
from app.ai.supply_series_input import SeriesRequest, bounded_json, instant, typed_period, validate_selections
from app.ai.supply_source_input import ItemKind, Positive, Scope


class PrivateSnapshot(core.StrictModel):
    schema_version: Literal["supply_series_private_v1"]
    series_id: core.UUID
    item_kind: ItemKind
    item_id: Positive
    scope: Scope
    created_by: Positive
    as_of: core.UtcText
    captured_at: core.UtcText
    identity_secret: str = Field(pattern=r"^[a-f0-9]{64}$")
    request: SeriesRequest
    collection: dict[str, Any]
    collection_digest: core.SHA256
    recipe: dict[str, Any]
    input_policy: dict[str, Any]
    recipe_digest: core.SHA256
    input_policy_digest: core.SHA256
    profile: dict[str, Any]


def verify_snapshot(value):
    from app.ai.supply_collection import verify_capture

    try:
        bounded_json(value)
        snapshot = PrivateSnapshot.model_validate(value).model_dump(mode="json")
        if core.canonical_json(snapshot) != core.canonical_json(value):
            raise ValueError("Noncanonical closed snapshot")
        req = SeriesRequest.model_validate(snapshot["request"])
        collection = snapshot["collection"]
        if not verify_capture(collection):
            raise ValueError("Complete collection proof differs")
        if (
            any(snapshot[k] != getattr(req, k) for k in ("item_kind", "item_id", "scope", "as_of"))
            or collection["request"] != typed_period(req).model_dump(mode="json")
            or collection["as_of"] != snapshot["as_of"]
            or collection["captured_at"] != snapshot["captured_at"]
            or collection["collection_digest"] != snapshot["collection_digest"]
            or instant(snapshot["as_of"]) > instant(snapshot["captured_at"])
        ):
            raise ValueError("Frozen identity, period and collection differ")
        if (
            core.hash_content(snapshot["recipe"]) != snapshot["recipe_digest"]
            or core.hash_content(snapshot["input_policy"]) != snapshot["input_policy_digest"]
            or snapshot["recipe"].get("input_policy") != snapshot["input_policy"]
            or snapshot["recipe"].get("rule_id") != core.RULE_ID
        ):
            raise ValueError("Frozen recipe/policy originals differ")
        profile = {"parameters": req.parameters.model_dump(mode="json"), "recipe_digest": snapshot["recipe_digest"], "input_policy_digest": snapshot["input_policy_digest"]}
        if snapshot["profile"] != profile:
            raise ValueError("Exact reviewed parameters differ from frozen profile")
        validate_selections(collection, req)
        return snapshot
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, HTTPException) as exc:
        raise HTTPException(409, "完整物资序列身份、原件全集、配方或参数快照不一致") from exc


def local_resolution(snapshot):
    snapshot = verify_snapshot(snapshot)
    return {
        "schema_version": "supply_local_resolution_v1",
        "series_id": snapshot["series_id"],
        "source_content_hash": core.hash_content(snapshot),
        "item_kind": snapshot["item_kind"],
        "item_id": snapshot["item_id"],
        "scope": snapshot["scope"],
        "sku_binding": snapshot["collection"]["sku_binding"],
        "unit_definition_id": snapshot["request"]["unit_definition_id"],
        "original_unit_text": next(
            r["source"]["payload"]["original_unit_text"] for r in snapshot["collection"]["unit_definitions"] if r["source"]["source_record_id"] == snapshot["request"]["unit_definition_id"]
        ),
    }
