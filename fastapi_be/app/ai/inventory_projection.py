"""One mechanical scene-local HMAC projection; no SKU labels or free basis leaves."""

import hashlib
import hmac
import uuid

from fastapi import HTTPException

from app.ai import inventory_contract as core
from app.ai.inventory_scenario_input import ScenarioRequest, legacy_frozen_conflict, observation_conflicts, validate_selections
from app.ai.inventory_snapshot import verify_snapshot


def token(snapshot, namespace, value):
    return hmac.new(bytes.fromhex(snapshot["identity_secret"]), core.canonical_json([namespace, value]).encode(), hashlib.sha256).hexdigest()


def opaque_uuid(snapshot, namespace, value):
    return str(uuid.UUID(token(snapshot, namespace, value)[:32]))


def quantity_unit_token(snapshot, unit_id, original_text):
    return token(snapshot, "quantity_unit", {"unit_definition_id": unit_id, "original_unit_text": original_text})


def quantity(snapshot, original, unit_id):
    return {
        "value": original["value"],
        "absent_reason": original["absent_reason"],
        "unit_token": None if original["original_unit_text"] is None else quantity_unit_token(snapshot, unit_id, original["original_unit_text"]),
        "original_unit_hash": token(snapshot, "original_quantity_unit", original["original_unit_text"]),
        "unit_review": original["unit_review"],
    }


def cost_unit_token(snapshot, original):
    return token(snapshot, "cost_unit", {key: original[key] for key in ("currency_text", "original_cost_unit_text")})


def cost(snapshot, original):
    return {
        "value": original["value"],
        "absent_reason": original["absent_reason"],
        "unit_token": None if original["currency_text"] is None or original["original_cost_unit_text"] is None else cost_unit_token(snapshot, original),
        "original_unit_hash": token(snapshot, "original_cost_unit", {key: original[key] for key in ("currency_text", "original_cost_unit_text")}),
        "unit_review": original["unit_review"],
    }


def public_ref(snapshot, row):
    identifier = opaque_uuid(snapshot, "fact", row["source_record_id"])
    return {
        "source_record_id": identifier,
        "source_id": f"inventory_fact:{identifier}:{row['content_hash'][:12]}",
        "kind": row["source_kind"],
        "content_hash": row["content_hash"],
        "governance_hash": row["governance_hash"],
        "recorded_at": row["recorded_at"],
        "published_at": row["reviewed_at"],
    }


def lot(snapshot, original, unit_id):
    return {
        "lot_id": opaque_uuid(snapshot, "lot", original["lot_id"]),
        "quantity": quantity(snapshot, original["quantity"], unit_id),
        "frozen_quantity": quantity(snapshot, original["frozen_quantity"], unit_id),
        "valid_through": original["valid_through"],
        "expiry_review": original["expiry_review"],
        "frozen_review": original["frozen_review"],
    }


def legacy_amount(snapshot, value, original_unit, unit_id, *, review, mapped_unit=None):
    return {
        "value": None if value is None else str(value),
        "absent_reason": "unknown" if value is None else None,
        "unit_token": None if original_unit is None and mapped_unit is None else quantity_unit_token(snapshot, unit_id, original_unit if original_unit is not None else mapped_unit),
        "original_unit_hash": token(snapshot, "original_quantity_unit", original_unit),
        "unit_review": review,
    }


def project_source(value, governance_hash, *, validate_current_recipe=True):
    snapshot = verify_snapshot(value)
    if validate_current_recipe and (snapshot["recipe_digest"] != core.recipe_digest() or snapshot["input_policy_digest"] != core.input_policy_digest()):
        raise HTTPException(409, "固定库存配方或输入政策已改变，须重新捕获和独立审核")
    req = ScenarioRequest.model_validate(snapshot["request"])
    unit, originals, reviews = validate_selections(snapshot["collection"], req)
    observation, future, *candidates = originals
    op, fp = observation["payload"], future["payload"]
    # The stock quantities are from the observation's own server-captured parent,
    # never the current Scene capture or an invented historical balance.
    legacy = observation["parent_binding"]["legacy_snapshot"]
    legacy_unit = legacy["sku"]["projection"]["unit"]
    legacy_review = op["legacy_quantity_unit_review"]
    original_unit_proof = observation["parent_binding"]["unit_definition"]
    mapped_unit = original_unit_proof["payload"]["original_unit_text"] if legacy_review == "confirmed" and original_unit_proof is not None else None
    stock = legacy["sku"]["projection"]["stock"]
    batches = sum(row["projection"]["stock"] for row in legacy["batches"]) if req.item_kind == "pharmaceutical" else None
    public_observation = {
        "ref": public_ref(snapshot, observation),
        "observed_at": op["observed_at"],
        "method": op["method"],
        "professional_review": observation["professional_status"],
        "scope_review": op["scope_review"],
        "coverage": op["coverage"],
        "coverage_basis_hash": token(snapshot, "observation_coverage_basis", op["coverage_basis_note"]),
        "lots": [lot(snapshot, row, observation["unit_definition_id"]) for row in op["lots"]],
        "declared_total_quantity": quantity(snapshot, op["declared_total_quantity"], observation["unit_definition_id"]),
        "physical_reconciliation": op["physical_reconciliation"],
        "reconciliation_basis_hash": token(snapshot, "physical_reconciliation_basis", op["reconciliation_basis_note"]),
        "legacy_snapshot": {
            "captured_at": legacy["captured_at"],
            "collection_digest": legacy["collection_digest"],
            "catalog_quantity": legacy_amount(snapshot, stock, legacy_unit, observation["unit_definition_id"], review=legacy_review, mapped_unit=mapped_unit),
            "batch_quantity_sum": None
            if req.item_kind != "pharmaceutical"
            else legacy_amount(snapshot, batches, legacy_unit, observation["unit_definition_id"], review=legacy_review, mapped_unit=mapped_unit),
            "batch_applicability": "applicable" if req.item_kind == "pharmaceutical" else "not_applicable",
            "reconciliation": op["legacy_reconciliation"],
            "basis_hash": token(
                snapshot,
                "legacy_reconciliation_basis",
                {
                    "reconciliation_basis_note": op["legacy_reconciliation_basis_note"],
                    "quantity_unit_review": op["legacy_quantity_unit_review"],
                    "quantity_unit_basis_note": op["legacy_quantity_unit_basis_note"],
                },
            ),
        },
    }
    constraints = {row.date: row for row in req.daily_constraints}
    conflicting_counts = observation_conflicts(snapshot["collection"], req, observation)
    frozen_conflict = legacy_frozen_conflict(observation)
    public_future = {
        "ref": public_ref(snapshot, future),
        "basis": fp["basis"],
        "quantity_definition": fp["quantity_definition"],
        "scope_review": fp["scope_review"],
        "coverage": fp["coverage"],
        "days": [
            {
                "date": day["date"],
                "required_quantity": quantity(snapshot, day["required_quantity"], future["unit_definition_id"]),
                **{
                    key: {
                        "mode": getattr(constraints[day["date"]], key).mode,
                        "amount": None
                        if getattr(constraints[day["date"]], key).amount is None
                        else quantity(snapshot, getattr(constraints[day["date"]], key).amount.model_dump(mode="json"), req.unit_definition_id),
                    }
                    for key in ("minimum_end_usable", "maximum_end_total")
                },
            }
            for day in fp["days"]
        ],
        "budget": {"mode": req.shared_budget.mode, "amount": None if req.shared_budget.amount is None else cost(snapshot, req.shared_budget.amount.model_dump(mode="json"))},
        "policy": {
            "event_order": "expire_then_receive_then_fefo_draw_then_check_v1",
            "expiry_semantics": "valid_through_inclusive",
            "allocation": "fefo_expiry_then_lot_id",
            "stockout": "all_reviewed_daily_quantities_must_be_met",
            "frozen_policy": "frozen_quantity_unavailable_until_expiry",
            "policy_review": req.policy_review,
            "basis_hash": token(snapshot, "policy_basis", req.policy_basis_note),
        },
        "assumptions": {
            **{key: getattr(req.assumptions, key) for key in ("opening_carry_forward", "no_other_inventory_changes", "frozen_quantities_unchanged")},
            "opening_carry_forward": "unknown" if conflicting_counts else req.assumptions.opening_carry_forward,
            "frozen_quantities_unchanged": "unknown" if frozen_conflict is not None else req.assumptions.frozen_quantities_unchanged,
            "basis_hash": token(snapshot, "assumptions_basis", {"basis_note": req.assumptions.basis_note, "conflicting_counts": conflicting_counts, "legacy_frozen_conflict": frozen_conflict}),
        },
    }
    public_candidates = []
    for original in candidates:
        payload = original["payload"]
        public_candidates.append(
            {
                "ref": public_ref(snapshot, original),
                "candidate_id": opaque_uuid(snapshot, "candidate", original["source_record_id"]),
                "completeness": payload["completeness"],
                "completeness_basis_hash": token(snapshot, "candidate_completeness_basis", payload["completeness_basis_note"]),
                "plan_fixed_fee": cost(snapshot, payload["plan_fixed_fee"]),
                "orders": [
                    {
                        "order_id": opaque_uuid(snapshot, "order", order["order_id"]),
                        "order_fixed_fee": cost(snapshot, order["order_fixed_fee"]),
                        "lines": [
                            {
                                **lot(snapshot, line, original["unit_definition_id"]),
                                "arrival_date": line["arrival_date"],
                                "unit_price": cost(snapshot, line["unit_price"]),
                                "price_basis_review": line["price_basis_review"],
                            }
                            for line in order["lines"]
                        ],
                    }
                    for order in payload["orders"]
                ],
            }
        )
    manifest = [public_observation["ref"], public_future["ref"], *(row["ref"] for row in public_candidates)]
    all_confirmed = all(reviews[(row["source_kind"], row["source_record_id"])].use == "confirmed" and row["eligible"] and row["professional_status"] == "confirmed" for row in [unit, *originals])
    content_hash = core.hash_content(snapshot)
    profile = snapshot["profile"]
    public_profile_hash = token(snapshot, "profile_content", profile)
    source = {
        "schema_version": "inventory_source_v1",
        "scenario_id": snapshot["scenario_id"],
        "source_id": f"inventory_scenario:{snapshot['scenario_id']}:{content_hash[:12]}",
        "content_hash": content_hash,
        "governance_hash": governance_hash,
        "profile_id": opaque_uuid(snapshot, "profile", profile),
        "profile_content_hash": public_profile_hash,
        "profile_governance_hash": governance_hash,
        "rule_id": snapshot["recipe"]["rule_id"],
        "recipe_digest": snapshot["recipe_digest"],
        "input_policy_digest": snapshot["input_policy_digest"],
        "scope": "single_sku_single_physical_scope_single_quantity_and_cost_unit",
        "item_kind": req.item_kind,
        "item_token": token(snapshot, "item", {"item_kind": req.item_kind, "item_id": req.item_id}),
        "scope_token": token(snapshot, "scope", req.scope),
        "quantity_unit_token": quantity_unit_token(snapshot, req.unit_definition_id, unit["payload"]["original_unit_text"]),
        "cost_unit_token": cost_unit_token(snapshot, req.cost_unit.model_dump(mode="json")),
        "timezone": req.timezone,
        "as_of": snapshot["as_of"],
        "captured_at": snapshot["captured_at"],
        "date_from": req.date_from,
        "date_to": req.date_to,
        "declared_candidate_ids": [row["candidate_id"] for row in public_candidates],
        "candidate_set_review": req.candidate_set_review if all_confirmed and req.cost_unit.review == "confirmed" else "unknown",
        "candidate_set_basis_hash": token(
            snapshot,
            "candidate_set_basis",
            {"basis_note": req.candidate_set_basis_note, "member_reviews": [row.model_dump(mode="json") for row in req.member_reviews], "cost_unit_review": req.cost_unit.review},
        ),
        "member_manifest": manifest,
        "member_manifest_hash": core.hash_content(manifest),
        "observation": public_observation,
        "scenario": public_future,
        "candidates": public_candidates,
    }
    if validate_current_recipe:
        try:
            return core.InventorySource.model_validate(source).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(409, "库存场景公开原量与固定严格合同不一致") from exc
    return source
