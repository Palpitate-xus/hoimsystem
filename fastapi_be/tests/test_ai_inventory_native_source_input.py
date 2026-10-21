"""Strict private originals preserve explicit unknowns and whole-plan identity."""

import copy
import uuid

import pytest
from pydantic import ValidationError

from app.ai.inventory_contract import day_bounds
from app.ai.inventory_native_source_input import Cost, InventoryObservation, Quantity, SourceCreate, SourceReview, SourceRevoke

NOTE = "这是独立工程合成核实依据逐项保留未知不会代替业务人员签署"
UNIT = "明确原计数包"
RID = "00000000-0000-4000-8000-000000000067"
HASH = "a" * 64


def quantity(value="0.000000", reviewed=False):
    return {"value": value, "absent_reason": "unknown" if value is None else None, "original_unit_text": UNIT, "unit_review": "confirmed" if reviewed else "unknown"}


def cost(value="0.000000", reviewed=False):
    return {
        "value": value,
        "absent_reason": "not_recorded" if value is None else None,
        "currency_text": "原明确币种",
        "original_cost_unit_text": "原明确计价元",
        "unit_review": "confirmed" if reviewed else "unknown",
    }


def base(kind):
    return {"kind": kind, "definition_basis_note": NOTE, "professional_attestation": {"status": "unknown", "signer_user_id": None, "basis_note": None}}


def lot():
    return {
        "lot_id": str(uuid.uuid4()),
        "original_lot_key": None,
        "quantity": quantity("1.000000"),
        "frozen_quantity": quantity(None),
        "valid_through": {"value": None, "absent_reason": "unknown"},
        "expiry_review": "unknown",
        "frozen_review": "unknown",
    }


def observation():
    return {
        **base("inventory_observation"),
        "method": "independent_count",
        "observed_at": "2026-10-21T01:00:00.123456Z",
        "scope_review": "unknown",
        "coverage": "unknown",
        "coverage_basis_note": NOTE,
        "lots": [lot()],
        "declared_total_quantity": quantity(None),
        "physical_reconciliation": "unknown",
        "reconciliation_basis_note": NOTE,
        "legacy_reconciliation": "unknown",
        "legacy_reconciliation_basis_note": NOTE,
        "legacy_quantity_unit_review": "unknown",
        "legacy_quantity_unit_basis_note": NOTE,
    }


def future():
    day = "2026-11-01"
    start, end = day_bounds(day, "America/New_York")
    return {
        **base("future_quantity_scenario"),
        "timezone": "America/New_York",
        "date_from": day,
        "date_to": day,
        "basis": "reviewed_operational_scenario",
        "quantity_definition": "planned_physical_stock_drawdown",
        "scope_review": "unknown",
        "coverage": "unknown",
        "coverage_basis_note": NOTE,
        "days": [{"date": day, "day_start_at": start, "day_end_at": end, "required_quantity": quantity(None)}],
    }


def candidate():
    arrival = {**lot(), "arrival_date": {"value": None, "absent_reason": "unknown"}, "unit_price": cost(None), "price_basis_review": "unknown", "price_basis_note": NOTE}
    return {
        **base("purchase_candidate_plan"),
        "timezone": "UTC",
        "date_from": "2026-11-01",
        "date_to": "2026-11-02",
        "completeness": "unknown",
        "completeness_basis_note": NOTE,
        "plan_fixed_fee": cost("0"),
        "orders": [{"order_id": str(uuid.uuid4()), "original_order_key": None, "order_fixed_fee": cost(None), "lines": [arrival]}],
    }


def request(payload=None):
    return {
        "item_kind": "pharmaceutical",
        "item_id": 67,
        "scope": "hospital_inventory",
        "unit_definition_id": None,
        "expected_unit_content_hash": None,
        "expected_unit_governance_hash": None,
        "payload": payload or observation(),
    }


@pytest.mark.parametrize("build", [observation, future, candidate])
def test_all_three_originals_preserve_explicit_unknown_raw_units_and_zero(build):
    values = request(build())
    assert SourceCreate.model_validate(values).model_dump(mode="json") == values


@pytest.mark.parametrize("value", ["0", "0.000000", "999999999999999999.999999", None])
def test_exact_original_numeric_text_never_becomes_js_or_python_float(value):
    assert Quantity.model_validate(quantity(value)).value == value
    assert Cost.model_validate(cost(value)).value == value


@pytest.mark.parametrize("value", [False, 0, 1.0, "-1", "1e2", "01", "1.0000001", "1000000000000000000"])
def test_no_numeric_coercion_or_hidden_quantity_conversion(value):
    with pytest.raises(ValidationError):
        Quantity.model_validate(quantity(value))


@pytest.mark.parametrize("value,absent", [("0", "unknown"), (None, None)])
def test_known_zero_and_null_reason_are_mutually_exclusive(value, absent):
    values = quantity(value)
    values["absent_reason"] = absent
    with pytest.raises(ValidationError):
        Quantity.model_validate(values)


@pytest.mark.parametrize("change", ["coverage", "scope", "frozen", "unit", "professional"])
def test_technical_recording_cannot_imply_actual_pharmacist_confirmation(change):
    values = request()
    p = values["payload"]
    if change == "coverage":
        p["coverage"] = "attested_complete"
    elif change == "scope":
        p["scope_review"] = "confirmed"
    elif change == "frozen":
        p["lots"][0]["frozen_review"] = "confirmed"
    elif change == "unit":
        p["lots"][0]["quantity"]["unit_review"] = "confirmed"
    else:
        p["professional_attestation"] = {"status": "confirmed", "signer_user_id": None, "basis_note": None}
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(values)


def test_current_database_capture_cannot_be_relabelled_as_physical_observation():
    p = observation()
    p["method"] = "legacy_current_capture"
    with pytest.raises(ValidationError):
        InventoryObservation.model_validate(p)
    p["observed_at"] = None
    assert InventoryObservation.model_validate(p).observed_at is None
    p["method"] = "independent_count"
    with pytest.raises(ValidationError):
        InventoryObservation.model_validate(p)


def test_numeric_conflicts_are_preserved_as_originals_not_repaired():
    p = observation()
    p["declared_total_quantity"] = quantity("7")
    p["lots"][0]["quantity"] = quantity("1")
    p["lots"][0]["frozen_quantity"] = quantity("9")
    result = SourceCreate.model_validate(request(p)).model_dump(mode="json")["payload"]
    assert [result["declared_total_quantity"]["value"], result["lots"][0]["quantity"]["value"], result["lots"][0]["frozen_quantity"]["value"]] == ["7", "1", "9"]


def test_actual25hour_iana_day_preserved_and_fake24hour_bounds_rejected():
    values = request(future())
    assert values["payload"]["days"][0]["day_start_at"] == "2026-11-01T04:00:00.000000Z"
    assert values["payload"]["days"][0]["day_end_at"] == "2026-11-02T05:00:00.000000Z"
    values["payload"]["days"][0]["day_end_at"] = "2026-11-02T04:00:00.000000Z"
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(values)


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown_zone", "too_long", "leap"])
def test_future_calendar_is_a_whole_explicit_bounded_original(change):
    values = request(future())
    p = values["payload"]
    if change == "missing":
        p["days"] = []
    elif change == "duplicate":
        p["days"].append(copy.deepcopy(p["days"][0]))
    elif change == "unknown_zone":
        p["timezone"] = "Unknown/DoesNotExist"
    elif change == "too_long":
        p["date_to"] = "2026-12-02"
    else:
        p["date_from"] = "2026-02-29"
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(values)


@pytest.mark.parametrize("change", ["duplicate_order", "duplicate_lot", "outside_arrival", "arrival_not_applicable"])
def test_complete_candidate_order_lines_cannot_be_duplicated_or_silently_cropped(change):
    values = request(candidate())
    p = values["payload"]
    if change == "duplicate_order":
        p["orders"].append(copy.deepcopy(p["orders"][0]))
    elif change == "duplicate_lot":
        p["orders"][0]["lines"].append(copy.deepcopy(p["orders"][0]["lines"][0]))
    elif change == "outside_arrival":
        p["orders"][0]["lines"][0]["arrival_date"] = {"value": "2026-11-03", "absent_reason": None}
    else:
        p["orders"][0]["lines"][0]["arrival_date"] = {"value": None, "absent_reason": "not_applicable"}
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(values)


def test_explicit_zero_order_plan_is_preserved_not_a_default_purchase():
    p = candidate()
    p["orders"] = []
    assert SourceCreate.model_validate(request(p)).payload.orders == []


@pytest.mark.parametrize("change", ["one_hash", "mixed_scope", "automatic_policy"])
def test_private_source_does_not_accept_partial_unit_or_scenario_policy_injection(change):
    values = request()
    if change == "one_hash":
        values["unit_definition_id"] = RID
    elif change == "mixed_scope":
        values["scope"] = "department_inventory"
    else:
        values["payload"]["policy"] = {"event_order": "default"}
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(values)


def test_confirmed_quantity_requires_complete_governed_unit_reference():
    values = request()
    values["payload"]["professional_attestation"] = {"status": "confirmed", "signer_user_id": 67, "basis_note": NOTE}
    values["payload"]["lots"][0]["quantity"]["unit_review"] = "confirmed"
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(values)
    values.update(unit_definition_id=RID, expected_unit_content_hash=HASH, expected_unit_governance_hash=HASH)
    assert SourceCreate.model_validate(values).unit_definition_id == RID


def test_legacy_numeric_count_unit_requires_its_own_actual_pharmacist_claim_and_unit_closure():
    values = request()
    values["payload"]["legacy_quantity_unit_review"] = "confirmed"
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(values)
    values["payload"]["professional_attestation"] = {"status": "confirmed", "signer_user_id": 67, "basis_note": NOTE}
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(values)
    values.update(unit_definition_id=RID, expected_unit_content_hash=HASH, expected_unit_governance_hash=HASH)
    assert SourceCreate.model_validate(values).payload.legacy_quantity_unit_review == "confirmed"


def test_general_reconciliation_does_not_implicitly_confirm_legacy_quantity_unit():
    values = request()
    values["payload"]["professional_attestation"] = {"status": "confirmed", "signer_user_id": 67, "basis_note": NOTE}
    values["payload"]["legacy_reconciliation"] = "confirmed"
    assert SourceCreate.model_validate(values).payload.legacy_quantity_unit_review == "unknown"


def test_governance_notes_preserve_unicode_codepoints_and_utf8_distinction():
    values = {"expected_revision": 1, "expected_content_hash": HASH, "basis_note": "😀" * 1000}
    assert SourceRevoke.model_validate(values).basis_note == values["basis_note"]
    with pytest.raises(ValidationError):
        SourceRevoke.model_validate({**values, "basis_note": "a" * 1001})
    with pytest.raises(ValidationError):
        SourceReview.model_validate({**values, "decision": "publish", "basis_note": "中" * 1334})
