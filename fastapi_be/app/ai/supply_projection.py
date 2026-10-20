"""Mechanical private-to-public projection. No raw SKU, note, operator or unit text."""

import hashlib
import hmac
import uuid

from fastapi import HTTPException

from app.ai import supply_contract as core
from app.ai.supply_series_input import SeriesRequest, typed_period, validate_selections
from app.ai.supply_snapshot import verify_snapshot


def token(snapshot, namespace, value):
    return hmac.new(bytes.fromhex(snapshot["identity_secret"]), core.canonical_json([namespace, value]).encode(), hashlib.sha256).hexdigest()


def unit_token(snapshot, unit_id, text):
    return token(snapshot, "unit", {"unit_definition_id": unit_id, "original_unit_text": text})


def project_source(value, governance_hash, *, validate_current_recipe=True):
    snapshot = verify_snapshot(value)
    if validate_current_recipe and (snapshot["recipe_digest"] != core.recipe_digest() or snapshot["input_policy_digest"] != core.input_policy_digest()):
        raise HTTPException(409, "当前固定配方或输入政策已改变，须重新捕获与审核")
    req = SeriesRequest.model_validate(snapshot["request"])
    unit = validate_selections(snapshot["collection"], req)
    content_hash = core.hash_content(snapshot)
    profile_id = str(uuid.UUID(token(snapshot, "profile", snapshot["profile"])[:32]))
    manifest, observations = [], []
    reviews = {r.source_record_id: r for r in req.member_reviews if r.source_kind == "daily_quantity"}
    for record in snapshot["collection"]["source_records"]:
        source = record["source"]
        r = reviews[source["source_record_id"]]
        ref = {
            "source_record_id": source["source_record_id"],
            "source_id": source["source_id"],
            "kind": "daily_quantity",
            "content_hash": source["content_hash"],
            "governance_hash": source["governance_hash"],
        }
        manifest.append({**ref, "status": source["status"], "eligible": source["eligible"], "selection": r.selection, "selection_basis_hash": core.hash_content(r.basis_note)})
        if r.selection != "confirmed":
            continue
        p = source["payload"]
        original_unit = p["original_unit_text"]
        observations.append(
            {
                "ref": ref,
                "target": p["target"],
                "date": p["date"],
                "day_start_at": p["day_start_at"],
                "day_end_at": p["day_end_at"],
                "quantity": p["quantity"],
                "unit_token": None if original_unit is None else unit_token(snapshot, source["unit_definition_id"], original_unit),
                "original_unit_hash": core.hash_content(original_unit),
                "unit_review": p["unit_review"],
                "coverage": p["coverage"],
                "coverage_basis_hash": core.hash_content(p["coverage_basis_note"]),
                "method": p["method"],
                "original_scope_hash": token(snapshot, "original_scope", {"item_kind": source["item_kind"], "item_id": source["item_id"], "scope": source["scope"]}),
                "external_record_key_hash": None if p["external_record_key"] is None else token(snapshot, "external_record_key", p["external_record_key"]),
                "stock_constraint": p["stock_constraint"],
                "stock_constraint_basis_hash": core.hash_content(p["stock_constraint_basis_note"]),
                "observed_at": p["observed_at"],
                "recorded_at": source["recorded_at"],
                "published_at": source["reviewed_at"],
            }
        )
    manifest.sort(key=lambda r: r["source_record_id"])
    observations.sort(key=lambda r: (r["date"], r["target"], r["ref"]["source_record_id"]))
    by_id = {r["ref"]["source_record_id"]: r["ref"]["source_id"] for r in observations}
    days = []
    for day in req.days:
        start, end = core.day_bounds(day.date, req.timezone)
        days.append(
            {
                "date": day.date,
                "day_start_at": start,
                "day_end_at": end,
                "selections": [{"target": r.target, "source_id": None if r.source_record_id is None else by_id[r.source_record_id], "absent_reason": r.absent_reason} for r in day.selections],
            }
        )
    source = {
        "schema_version": "supply_source_v1",
        "series_id": snapshot["series_id"],
        "source_id": f"supply_series:{snapshot['series_id']}:{content_hash[:12]}",
        "content_hash": content_hash,
        "governance_hash": governance_hash,
        "profile_id": profile_id,
        "profile_content_hash": core.hash_content(snapshot["profile"]),
        "profile_governance_hash": governance_hash,
        "rule_id": snapshot["recipe"]["rule_id"],
        "recipe_digest": snapshot["recipe_digest"],
        "input_policy_digest": snapshot["input_policy_digest"],
        "scope": "single_sku_single_scope_single_unit",
        "item_kind": req.item_kind,
        "item_token": token(snapshot, "item", {"item_kind": req.item_kind, "item_id": req.item_id}),
        "scope_token": token(snapshot, "scope", req.scope),
        "unit_token": unit_token(snapshot, req.unit_definition_id, unit["payload"]["original_unit_text"]),
        "timezone": req.timezone,
        "date_from": req.date_from,
        "date_to": req.date_to,
        "as_of": snapshot["as_of"],
        "captured_at": snapshot["captured_at"],
        "historical_collection_digest": snapshot["collection"]["historical_collection_digest"],
        "current_membership_digest": snapshot["collection"]["current_membership_digest"],
        "member_manifest_hash": core.hash_content(manifest),
        "parameters": req.parameters.model_dump(mode="json"),
        "target_coverage": [
            {
                "target": r.target,
                "same_scope_confirmed": r.same_scope_confirmed,
                "same_definition_confirmed": r.same_definition_confirmed,
                "same_method_confirmed": r.same_method_confirmed,
                "basis_hash": core.hash_content(r.basis_note),
            }
            for r in req.target_coverage
        ],
        "days": days,
        "member_manifest": manifest,
        "observations": observations,
    }
    if validate_current_recipe:
        try:
            return core.SupplySource.model_validate(source).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(409, "完整匿名物资来源与真实原件或固定合同不符") from exc
    # Historical own-byte audit never rewrites an old recipe with today's recipe.
    # This is a deterministic projection of the stored private v1 contract only;
    # new execution separately requires the current typed native contract.
    typed_period(req)
    return source
