"""Actual governed facts, complete scene capture and finite native comparison."""

import copy
import datetime
import uuid

import pytest
from fastapi import HTTPException

from app.ai import governance
from app.ai import inventory_contract as core
from app.ai import inventory_projection as projection
from app.ai import inventory_scenario_input as inputs
from app.ai import inventory_scenarios as scenes
from app.ai import supply_sources as units
from app.ai.inventory_snapshot import verify_snapshot
from app.models import Pharmaceutical, PharmaceuticalBatch, User
from tests.test_ai_inventory_native_source_input import NOTE

NOW = datetime.datetime(2026, 10, 21, 13, 0, 0, 123456)
UNIT = "原明确计数包"


def quantity(value, *, unit=UNIT, review="confirmed"):
    return {"value": value, "absent_reason": "unknown" if value is None else None, "original_unit_text": unit, "unit_review": review}


def cost(value, *, review="confirmed"):
    return {"value": value, "absent_reason": "unknown" if value is None else None, "currency_text": "工程币种", "original_cost_unit_text": "工程元", "unit_review": review}


def attestation(case, confirmed=True):
    return {"status": "confirmed" if confirmed else "unknown", "signer_user_id": case["pharmacist"].user_id if confirmed else None, "basis_note": NOTE if confirmed else None}


def source_request(case, payload, *, unit=True):
    return {
        "item_kind": "pharmaceutical",
        "item_id": case["drug"].pharmaceutical_id,
        "scope": "hospital_inventory",
        "unit_definition_id": case["unit"].unit_definition_id if unit else None,
        "expected_unit_content_hash": case["unit"].content_hash if unit else None,
        "expected_unit_governance_hash": core.hash_content(units.governance(case["unit"])) if unit else None,
        "payload": payload,
    }


def publish_source(db, case, payload, *, unit=True, actor=None):
    from app.ai import inventory_native_sources as facts

    row = facts.create_source(db, actor or case["pharmacist"], source_request(case, payload, unit=unit))
    db.commit()
    facts.review_source(db, case["super"], row.source_record_id, {"expected_revision": row.revision, "expected_content_hash": row.content_hash, "decision": "publish", "basis_note": NOTE})
    db.commit()
    return row


def observation(case):
    return {
        "kind": "inventory_observation",
        "definition_basis_note": NOTE,
        "professional_attestation": attestation(case),
        "method": "independent_count",
        "observed_at": inputs.utc_text(NOW - datetime.timedelta(hours=1)),
        "scope_review": "confirmed",
        "coverage": "attested_complete",
        "coverage_basis_note": NOTE,
        "lots": [
            {
                "lot_id": case["opening_lot_id"],
                "original_lot_key": "明确工程原批次" + str(case["batch"].batch_id),
                "quantity": quantity("10.000000"),
                "frozen_quantity": quantity(case.get("physical_frozen", "0")),
                "valid_through": {"value": "2027-12-31", "absent_reason": None},
                "expiry_review": "confirmed",
                "frozen_review": "confirmed",
            }
        ],
        "declared_total_quantity": quantity("10"),
        "physical_reconciliation": "confirmed",
        "reconciliation_basis_note": NOTE,
        "legacy_reconciliation": "confirmed",
        "legacy_reconciliation_basis_note": NOTE,
        "legacy_quantity_unit_review": "confirmed",
        "legacy_quantity_unit_basis_note": NOTE,
    }


def future(case):
    days = []
    for day, value in [("2026-11-01", "12"), ("2026-11-02", "3")]:
        start, end = core.day_bounds(day, "UTC")
        days.append({"date": day, "day_start_at": start, "day_end_at": end, "required_quantity": quantity(value)})
    return {
        "kind": "future_quantity_scenario",
        "definition_basis_note": NOTE,
        "professional_attestation": attestation(case),
        "timezone": "UTC",
        "date_from": "2026-11-01",
        "date_to": "2026-11-02",
        "basis": "reviewed_operational_scenario",
        "quantity_definition": "planned_physical_stock_drawdown",
        "scope_review": "confirmed",
        "coverage": "attested_complete",
        "coverage_basis_note": NOTE,
        "days": days,
    }


def candidate(case, *, zero=False):
    orders = (
        []
        if zero
        else [
            {
                "order_id": str(uuid.uuid4()),
                "original_order_key": "合成完整候选原订单",
                "order_fixed_fee": cost("0"),
                "lines": [
                    {
                        "lot_id": str(uuid.uuid4()),
                        "original_lot_key": "合成已声明未来收货",
                        "quantity": quantity("5"),
                        "frozen_quantity": quantity("0"),
                        "valid_through": {"value": "2027-12-31", "absent_reason": None},
                        "expiry_review": "confirmed",
                        "frozen_review": "confirmed",
                        "arrival_date": {"value": "2026-11-01", "absent_reason": None},
                        "unit_price": cost("2.000000"),
                        "price_basis_review": "confirmed",
                        "price_basis_note": NOTE,
                    }
                ],
            }
        ]
    )
    return {
        "kind": "purchase_candidate_plan",
        "definition_basis_note": NOTE,
        "professional_attestation": attestation(case),
        "timezone": "UTC",
        "date_from": "2026-11-01",
        "date_to": "2026-11-02",
        "completeness": "attested_complete",
        "completeness_basis_note": NOTE,
        "plan_fixed_fee": cost("0.000000"),
        "orders": orders,
    }


@pytest.fixture
def inventory_case(seed_data, db_session, monkeypatch, request):
    from app.ai import inventory_native_collection as collection
    from app.ai import inventory_native_sources as facts

    case = {
        "now": NOW,
        "pharmacist": seed_data["pharmacist_user"],
        "super": seed_data["super_admin_user"],
        "admin": seed_data["admin_user"],
        "director": seed_data["director_user"],
        "nurse": seed_data["nurse_user"],
        "opening_lot_id": str(uuid.uuid4()),
    }
    case["physical_frozen"] = "10" if getattr(request, "param", None) == "frozen_batch_matching" else "0"
    for module in (units, facts, collection, inputs, scenes):
        monkeypatch.setattr(module, "utcnow", lambda: case["now"])
    drug = Pharmaceutical(name="真实工程库存候选药品", stock=10, price="7.77", status=0, barcode="inventory-scene-" + uuid.uuid4().hex)
    db_session.add(drug)
    db_session.flush()
    batch = PharmaceuticalBatch(
        pharmaceutical_id=drug.pharmaceutical_id,
        batch_no=uuid.uuid4().hex,
        stock=10,
        status=1 if getattr(request, "param", None) in {"frozen_batch", "frozen_batch_matching"} else 0,
        expiry_date=datetime.date(2027, 12, 31),
        create_time=NOW,
        update_time=NOW,
    )
    db_session.add(batch)
    db_session.commit()
    case.update(drug=drug, batch=batch)
    unit = units.create_unit(
        db_session,
        case["pharmacist"],
        {
            "item_kind": "pharmaceutical",
            "item_id": drug.pharmaceutical_id,
            "scope": "hospital_inventory",
            "payload": {"original_unit_text": UNIT, "definition_basis_note": NOTE, "professional_attestation": attestation(case)},
        },
    )
    db_session.commit()
    units.review_source(
        db_session, case["super"], "unit", unit.unit_definition_id, {"expected_revision": unit.revision, "expected_content_hash": unit.content_hash, "decision": "publish", "basis_note": NOTE}
    )
    db_session.commit()
    case["unit"] = unit
    case["observation"] = publish_source(db_session, case, observation(case))
    case["future"] = publish_source(db_session, case, future(case))
    case["baseline"] = publish_source(db_session, case, candidate(case, zero=True))
    case["purchase"] = publish_source(db_session, case, candidate(case))
    case["now"] += datetime.timedelta(seconds=2)
    return case


def period(case):
    return {
        "item_kind": "pharmaceutical",
        "item_id": case["drug"].pharmaceutical_id,
        "scope": "hospital_inventory",
        "timezone": "UTC",
        "date_from": "2026-11-01",
        "date_to": "2026-11-02",
        "as_of": case.get("as_of", inputs.utc_text(NOW + datetime.timedelta(seconds=1))),
    }


def original_ref(row):
    from app.ai import inventory_native_sources as facts

    return {"source_record_id": row.source_record_id, "expected_content_hash": row.content_hash, "expected_governance_hash": core.hash_content(facts.governance(row))}


def create_request(db, case):
    capture = inputs.preview_input(db, case["admin"], period(case))
    selected = {case[key].source_record_id for key in ("observation", "future", "baseline", "purchase")}
    unit = case["unit"]
    body = {
        **period(case),
        "unit_definition_id": unit.unit_definition_id,
        "expected_unit_content_hash": unit.content_hash,
        "expected_unit_governance_hash": core.hash_content(units.governance(unit)),
        "observation": original_ref(case["observation"]),
        "future_quantity_scenario": original_ref(case["future"]),
        "candidates": [original_ref(case["baseline"]), original_ref(case["purchase"])],
        "member_reviews": [
            {
                "source_record_id": source["source_record_id"],
                "source_kind": source["source_kind"],
                "expected_content_hash": source["content_hash"],
                "expected_governance_hash": source["governance_hash"],
                "use": "confirmed" if source["source_record_id"] in selected or source["source_record_id"] == unit.unit_definition_id else "excluded",
                "basis_note": NOTE,
            }
            for record in capture["unit_definitions"] + capture["source_records"]
            for source in [record["source"]]
        ],
        "daily_constraints": [
            {"date": date, "minimum_end_usable": {"mode": "known", "amount": quantity("0")}, "maximum_end_total": {"mode": "not_applicable", "amount": None}} for date in ("2026-11-01", "2026-11-02")
        ],
        "shared_budget": {"mode": "known", "amount": cost("100")},
        "cost_unit": {"currency_text": "工程币种", "original_cost_unit_text": "工程元", "review": "confirmed", "basis_note": NOTE},
        "policy_review": "confirmed",
        "policy_basis_note": NOTE,
        "assumptions": {"opening_carry_forward": "confirmed", "no_other_inventory_changes": "confirmed", "frozen_quantities_unchanged": "confirmed", "basis_note": NOTE},
        "candidate_set_review": "confirmed",
        "candidate_set_basis_note": NOTE,
    }
    return {"request": body, "expected_collection_digest": capture["collection_digest"]}


def review_request(row, *, decision="publish"):
    return {"expected_revision": row.revision, "expected_content_hash": row.content_hash, "decision": decision, "basis_note": NOTE}


def draft(db, case):
    row = scenes.create_scenario(db, case["admin"], create_request(db, case))
    db.commit()
    return row


def published(db, case):
    row = draft(db, case)
    scenes.review_scenario(db, case["super"], row.scenario_id, review_request(row))
    db.commit()
    return row


def test_actual_complete_sources_to_native_proven_best_without_changing_stock_or_orders(db_session, inventory_case):
    from app.ai.inventory_config import runtime_descriptor, runtime_from_descriptor
    from app.ai.inventory_model import compute_inventory

    case = inventory_case
    row = published(db_session, case)
    detail = scenes.scenario_current(db_session, case["admin"], row.scenario_id)
    assert detail["eligible"] and detail["snapshot"] and detail["public_source"]
    source = core.InventorySource.model_validate(detail["public_source"])
    assert len(source.candidates) == 2 and len(source.member_manifest) == 4
    assert source.observation.legacy_snapshot.catalog_quantity.original_unit_hash == projection.token(detail["snapshot"], "original_quantity_unit", None)
    assert source.observation.legacy_snapshot.catalog_quantity.unit_token == source.quantity_unit_token
    assert source.observation.legacy_snapshot.catalog_quantity.value == "10"
    result = compute_inventory(source.model_dump(mode="json"), "a" * 64, runtime_from_descriptor(runtime_descriptor()))
    assert result.status == "complete_comparison" and result.best_among_declared_candidates
    assert len(result.best_known_feasible_candidate_ids) == 1
    text = core.canonical_json(source.model_dump(mode="json"))
    for raw in (case["drug"].name, UNIT, "工程币种", "工程元", NOTE, detail["snapshot"]["identity_secret"]):
        assert raw not in text
    assert case["drug"].stock == case["batch"].stock == 10
    assert scenes.authorize_scenario(db_session, case["pharmacist"], row.scenario_id)[0].scenario_id == row.scenario_id


@pytest.mark.parametrize("role", ["admin", "director", "pharmacist"])
def test_ordinary_roles_cannot_independently_publish_or_audit_frozen_scene(db_session, inventory_case, role):
    row = draft(db_session, inventory_case)
    with pytest.raises(HTTPException) as caught:
        scenes.review_scenario(db_session, inventory_case[role], row.scenario_id, review_request(row))
    assert caught.value.status_code == 403
    assert scenes.scenario_row(db_session, row.scenario_id).status == "draft"
    with pytest.raises(HTTPException) as caught:
        scenes.scenario_current(db_session, inventory_case[role], row.scenario_id, audit_only=True)
    assert caught.value.status_code == 403


def test_rehashed_false_public_quantity_and_private_profile_do_not_pass_own_proof(db_session, inventory_case):
    row = published(db_session, inventory_case)
    snapshot, source = scenes.scenario_proof(row)
    original = row.projection_json
    forged = copy.deepcopy(source)
    forged["scenario"]["days"][0]["required_quantity"]["value"] = "0"
    row.projection_json = core.canonical_json(forged)
    row.projection_hash = core.hash_content(forged)
    with pytest.raises(HTTPException):
        scenes.scenario_proof(row)
    row.projection_json = original
    row.projection_hash = core.hash_content(source)
    forged = copy.deepcopy(snapshot)
    forged["profile"]["shared_budget"]["amount"]["value"] = "999"
    with pytest.raises(HTTPException):
        verify_snapshot(forged)
    db_session.rollback()


def test_super_cas_revoke_preserves_frozen_proof_and_redacts_ordinary_private_view(db_session, inventory_case):
    case = inventory_case
    row = published(db_session, case)
    before = row.content_hash
    scenes.revoke_scenario(db_session, case["super"], row.scenario_id, {key: value for key, value in review_request(row).items() if key != "decision"})
    db_session.commit()
    assert row.status == "revoked" and row.revision == 3 and row.content_hash == before
    audit = scenes.scenario_current(db_session, case["super"], row.scenario_id, audit_only=True)
    assert audit["snapshot"] and audit["public_source"] and not audit["eligible"]
    ordinary = scenes.scenario_current(db_session, case["admin"], row.scenario_id)
    assert ordinary["snapshot"] is ordinary["public_source"] is ordinary["local_resolution"] is None
    with pytest.raises(HTTPException) as caught:
        scenes.authorize_scenario(db_session, case["super"], row.scenario_id)
    assert caught.value.status_code == 409


def test_actual_inventory_change_invalidates_new_use_but_super_keeps_own_frozen_piece(db_session, inventory_case):
    case = inventory_case
    row = published(db_session, case)
    case["drug"].stock += 1
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        scenes.authorize_scenario(db_session, case["admin"], row.scenario_id)
    assert caught.value.status_code == 409
    assert scenes.scenario_current(db_session, case["admin"], row.scenario_id)["snapshot"] is None
    assert scenes.scenario_current(db_session, case["super"], row.scenario_id, audit_only=True)["snapshot"]


def test_real_sql_role_mutation_after_audit_rolls_back_publication_and_the_mutation(db_session, inventory_case, monkeypatch):
    case = inventory_case
    row = draft(db_session, case)
    identifier = row.scenario_id
    original = governance.audit

    def demote(db, actor_id, *args, **kwargs):
        result = original(db, actor_id, *args, **kwargs)
        db.query(User).filter_by(user_id=actor_id).update({"user_role": "admin"}, synchronize_session=False)
        db.flush()
        return result

    monkeypatch.setattr(governance, "audit", demote)
    with pytest.raises(HTTPException) as caught:
        scenes.review_scenario(db_session, case["super"], identifier, review_request(row))
    assert caught.value.status_code == 403
    assert scenes.scenario_row(db_session, identifier).status == "draft"
    assert db_session.query(User).filter_by(user_id=case["super"].user_id).one().user_role == "super_admin"


def test_exact_binding_rejects_unknown_fields_and_false_scope_types(db_session, inventory_case):
    case = inventory_case
    row = published(db_session, case)
    _, source = scenes.scenario_proof(row)
    binding = scenes.binding_for(row, source)
    assert scenes.authorize_scenario(db_session, case["admin"], row.scenario_id, binding={**binding, "schema_version": "inventory_context_binding_v1"})
    for mutation in [{"horizon_days": 7}, {"revision": True}, {"item_id": str(row.item_id)}, {"projection_hash": "0" * 64}]:
        with pytest.raises(HTTPException) as caught:
            scenes.authorize_scenario(db_session, case["admin"], row.scenario_id, binding={**binding, **mutation})
        assert caught.value.status_code == 409


def test_actual_source_case_contains_reviewed_stock_future_and_whole_zero_order_baseline(db_session, inventory_case):
    from app.ai import inventory_native_sources as facts

    case = inventory_case
    for key in ("observation", "future", "baseline", "purchase"):
        wrapper = facts.source_current(db_session, case["admin"], case[key].source_record_id)
        assert wrapper["eligible"] and wrapper["professional_status"] == "confirmed"
    baseline = facts.source_proof(case["baseline"])
    assert baseline["payload"]["orders"] == [] and baseline["payload"]["plan_fixed_fee"]["value"] == "0.000000"
    original = facts.source_proof(case["observation"])
    assert original["parent_binding"]["legacy_snapshot"]["sku"]["projection"]["unit"] is None
    assert original["payload"]["legacy_quantity_unit_review"] == "confirmed"
    assert case["drug"].stock == case["batch"].stock == 10


def refresh_cutoff(case):
    case["as_of"] = inputs.utc_text(case["now"] + datetime.timedelta(seconds=1))
    case["now"] += datetime.timedelta(seconds=2)


def add_candidate_to_request(db, case, extra):
    values = create_request(db, case)
    values["request"]["candidates"].append(original_ref(extra))
    next(row for row in values["request"]["member_reviews"] if row["source_record_id"] == extra.source_record_id)["use"] = "confirmed"
    return values


def test_missing_or_excluded_adverse_whole_candidate_cannot_prove_a_closed_set(db_session, inventory_case):
    case = inventory_case
    values = create_request(db_session, case)
    values["request"]["candidates"] = [original_ref(case["purchase"])]
    for row in values["request"]["member_reviews"]:
        if row["source_record_id"] == case["baseline"].source_record_id:
            row["use"] = "excluded"
    with pytest.raises(HTTPException) as caught:
        scenes.create_scenario(db_session, case["admin"], values)
    assert caught.value.status_code == 409 and "全部已发布候选" in caught.value.detail


def test_real_governed_zero_order_source_is_required_not_fabricated_by_scene(db_session, inventory_case):
    from app.ai import inventory_native_sources as facts

    case = inventory_case
    baseline = case["baseline"]
    facts.review_source(db_session, case["super"], baseline.source_record_id, {"expected_revision": baseline.revision, "expected_content_hash": baseline.content_hash, "basis_note": NOTE}, revoke=True)
    db_session.commit()
    refresh_cutoff(case)
    values = create_request(db_session, case)
    values["request"]["candidates"] = [original_ref(case["purchase"])]
    next(row for row in values["request"]["member_reviews"] if row["source_record_id"] == baseline.source_record_id)["use"] = "excluded"
    with pytest.raises(HTTPException) as caught:
        scenes.create_scenario(db_session, case["admin"], values)
    assert caught.value.status_code == 409 and "基线原件" in caught.value.detail


def test_added_current_root_invalidates_unchanged_winner_and_old_cutoff_without_leaking_root(db_session, inventory_case):
    case = inventory_case
    row = published(db_session, case)
    extra = publish_source(db_session, case, candidate(case))
    with pytest.raises(HTTPException) as caught:
        scenes.authorize_scenario(db_session, case["admin"], row.scenario_id)
    assert caught.value.status_code == 409
    assert extra.source_record_id not in str(caught.value.detail)
    assert scenes.scenario_current(db_session, case["admin"], row.scenario_id)["snapshot"] is None
    assert scenes.scenario_current(db_session, case["super"], row.scenario_id, audit_only=True)["snapshot"]


def test_unknown_original_unit_candidate_stays_in_whole_set_and_blocks_best_proof(db_session, inventory_case):
    from app.ai.inventory_config import runtime_descriptor, runtime_from_descriptor
    from app.ai.inventory_model import compute_inventory

    case = inventory_case
    payload = candidate(case)
    for order in payload["orders"]:
        for line in order["lines"]:
            line["quantity"]["unit_review"] = line["frozen_quantity"]["unit_review"] = "unknown"
    extra = publish_source(db_session, case, payload, unit=False)
    refresh_cutoff(case)
    # A missing UnitDefinition is uncertainty, not evidence to omit this plan.
    values = add_candidate_to_request(db_session, case, extra)
    row = scenes.create_scenario(db_session, case["admin"], values)
    db_session.commit()
    scenes.review_scenario(db_session, case["super"], row.scenario_id, review_request(row))
    db_session.commit()
    _, source = scenes.scenario_proof(row)
    result = compute_inventory(source, "a" * 64, runtime_from_descriptor(runtime_descriptor()))
    assert result.candidate_count == 3 and result.unknown_count == 1 and result.known_feasible_count == 1
    assert not result.best_among_declared_candidates and not result.all_declared_candidates_proven_infeasible
    assert source["candidates"][2]["orders"][0]["lines"][0]["quantity"]["unit_review"] == "unknown"


@pytest.mark.parametrize("offset,conflicted", [(0, True), (30, True), (-30, False)])
def test_current_same_or_later_count_conflicts_cannot_be_overridden_by_carry_forward(db_session, inventory_case, offset, conflicted):
    from app.ai.inventory_config import runtime_descriptor, runtime_from_descriptor
    from app.ai.inventory_model import compute_inventory

    case = inventory_case
    payload = observation(case)
    payload["observed_at"] = inputs.utc_text(NOW - datetime.timedelta(hours=1) + datetime.timedelta(minutes=offset))
    payload["lots"][0]["quantity"]["value"] = "11"
    payload["declared_total_quantity"]["value"] = "11"
    other = publish_source(db_session, case, payload)
    refresh_cutoff(case)
    row = published(db_session, case)
    snapshot, source = scenes.scenario_proof(row)
    assert snapshot["request"]["assumptions"]["opening_carry_forward"] == "confirmed"
    assert source["scenario"]["assumptions"]["opening_carry_forward"] == ("unknown" if conflicted else "confirmed")
    assert source["observation"]["declared_total_quantity"]["value"] == "10"
    assert any(r["source"]["source_record_id"] == other.source_record_id for r in snapshot["collection"]["source_records"])
    result = compute_inventory(source, "a" * 64, runtime_from_descriptor(runtime_descriptor()))
    assert result.best_among_declared_candidates is (not conflicted)


def test_independent_legacy_unit_mapping_is_required_even_after_generic_reconciliation(db_session, inventory_case):
    from app.ai.inventory_config import runtime_descriptor, runtime_from_descriptor
    from app.ai.inventory_model import compute_inventory

    case = inventory_case
    payload = observation(case)
    payload["observed_at"] = inputs.utc_text(NOW - datetime.timedelta(minutes=30))
    payload["legacy_quantity_unit_review"] = "unknown"
    case["observation"] = publish_source(db_session, case, payload)
    refresh_cutoff(case)
    row = published(db_session, case)
    _, source = scenes.scenario_proof(row)
    legacy = source["observation"]["legacy_snapshot"]
    assert legacy["reconciliation"] == "confirmed" and legacy["catalog_quantity"]["unit_review"] == "unknown" and legacy["catalog_quantity"]["unit_token"] is None
    result = compute_inventory(source, "a" * 64, runtime_from_descriptor(runtime_descriptor()))
    assert result.unknown_count == 2 and not result.best_among_declared_candidates


def test_database_capture_never_becomes_an_independent_stock_count(db_session, inventory_case):
    from app.ai.inventory_config import runtime_descriptor, runtime_from_descriptor
    from app.ai.inventory_model import compute_inventory

    case = inventory_case
    payload = observation(case)
    payload.update(method="legacy_current_capture", observed_at=None)
    case["observation"] = publish_source(db_session, case, payload)
    refresh_cutoff(case)
    row = published(db_session, case)
    _, source = scenes.scenario_proof(row)
    result = compute_inventory(source, "a" * 64, runtime_from_descriptor(runtime_descriptor()))
    assert source["observation"]["observed_at"] is None and result.unknown_count == 2 and not result.best_among_declared_candidates


def test_expired_future_window_stays_own_historical_readable_but_cannot_execute(db_session, inventory_case):
    case = inventory_case
    row = published(db_session, case)
    original = row.snapshot_json
    case["now"] = datetime.datetime(2026, 11, 3, 13)
    detail = scenes.scenario_current(db_session, case["admin"], row.scenario_id)
    assert detail["source_current"] and not detail["eligible"] and detail["snapshot"] and row.snapshot_json == original
    assert scenes.authorize_scenario(db_session, case["admin"], row.scenario_id, execution=False)
    with pytest.raises(HTTPException) as caught:
        scenes.authorize_scenario(db_session, case["admin"], row.scenario_id, execution=True)
    assert caught.value.status_code == 409


@pytest.mark.parametrize("inventory_case,conflicted", [("frozen_batch", True), ("frozen_batch_matching", False)], indirect=["inventory_case"])
def test_known_legacy_frozen_conflict_cannot_be_hidden_by_professional_or_continuation_checkbox(db_session, inventory_case, conflicted):
    from app.ai.inventory_config import runtime_descriptor, runtime_from_descriptor
    from app.ai.inventory_model import compute_inventory

    case = inventory_case
    row = published(db_session, case)
    snapshot, source = scenes.scenario_proof(row)
    original = next(record["source"] for record in snapshot["collection"]["source_records"] if record["source"]["source_record_id"] == case["observation"].source_record_id)
    assert original["parent_binding"]["legacy_snapshot"]["batches"][0]["projection"]["status"] == 1
    assert snapshot["request"]["assumptions"]["frozen_quantities_unchanged"] == "confirmed"
    assert source["scenario"]["assumptions"]["frozen_quantities_unchanged"] == ("unknown" if conflicted else "confirmed")
    assert source["observation"]["lots"][0]["frozen_quantity"]["value"] == ("0" if conflicted else "10")
    result = compute_inventory(source, "a" * 64, runtime_from_descriptor(runtime_descriptor()))
    if conflicted:
        assert result.unknown_count == 2 and not result.best_among_declared_candidates
    else:
        assert result.unknown_count == 0 and result.all_declared_candidates_proven_infeasible
