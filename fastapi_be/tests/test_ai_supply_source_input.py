"""Private original quantities, clocks, units and professional confirmation boundaries."""

import copy

import pytest
from pydantic import ValidationError

from app.ai.supply_source_input import DailyPayload, SourceCreate, SourceReview, SourceRevoke, UnitCreate

NOTE = "合成工程原始库存计数依据，逐项确认来源口径与缺项，不表示医院真实验证或岗位执照认证。"


def daily():
    return {
        "kind": "daily_quantity",
        "target": "gross_fulfilled_issue_quantity",
        "date": "2026-10-19",
        "timezone": "Asia/Shanghai",
        "day_start_at": "2026-10-18T16:00:00.000000Z",
        "day_end_at": "2026-10-19T16:00:00.000000Z",
        "observed_at": "2026-10-19T17:00:00.123456Z",
        "quantity": {"value": "0.000000", "absent_reason": None},
        "original_unit_text": None,
        "unit_review": "unknown",
        "coverage": "unknown",
        "coverage_basis_note": NOTE,
        "definition_basis_note": NOTE,
        "method": "direct_tally",
        "external_record_key": None,
        "stock_constraint": "full",
        "stock_constraint_basis_note": NOTE,
        "professional_attestation": {"status": "unknown", "signer_user_id": None, "basis_note": None},
        "audit_refs": [],
    }


def test_preserves_zero_precision_and_independent_stock_constraint_without_invented_demand():
    value = DailyPayload.model_validate(daily())
    assert value.quantity.value == "0.000000" and value.stock_constraint == "full"
    values = daily()
    values["quantity"] = {"value": None, "absent_reason": "not_recorded"}
    assert DailyPayload.model_validate(values).quantity.value is None
    values["quantity"] = {"value": "999999999999999999.123456", "absent_reason": None}
    assert DailyPayload.model_validate(values).quantity.value.endswith(".123456")


@pytest.mark.parametrize(
    "quantity",
    [
        {"value": 0, "absent_reason": None},
        {"value": False, "absent_reason": None},
        {"value": "-1", "absent_reason": None},
        {"value": "0.0000001", "absent_reason": None},
        {"value": "1000000000000000000", "absent_reason": None},
        {"value": "0", "absent_reason": "unknown"},
        {"value": None, "absent_reason": None},
    ],
)
def test_unknown_zero_signed_delta_and_float_quantity_are_not_interchangeable(quantity):
    value = daily()
    value["quantity"] = quantity
    with pytest.raises(ValidationError):
        DailyPayload.model_validate(value)


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(day_end_at="2026-10-20T16:00:00.000000Z"),
        lambda p: p.update(observed_at="2026-10-19T15:59:59.999999Z"),
        lambda p: p.update(day_start_at="2026-10-18T16:00:00Z"),
        lambda p: p.update(coverage="attested_complete"),
        lambda p: p.update(unit_review="confirmed", original_unit_text="盒"),
        lambda p: p.update(method="external_register"),
        lambda p: p.update(external_record_key="not-a-direct-tally"),
        lambda p: p.update(coverage_basis_note=" " * 20),
    ],
)
def test_rejects_incomplete_actual_day_backfilled_clock_and_technical_confirmation(change):
    values = daily()
    change(values)
    with pytest.raises(ValidationError):
        DailyPayload.model_validate(values)


def test_explicit_reviewed_dst_23_and_25_hour_days_remain_actual_utc_intervals():
    for date, start, end in [("2026-03-08", "2026-03-08T05:00:00.000000Z", "2026-03-09T04:00:00.000000Z"), ("2026-11-01", "2026-11-01T04:00:00.000000Z", "2026-11-02T05:00:00.000000Z")]:
        values = daily()
        values.update(date=date, timezone="America/New_York", day_start_at=start, day_end_at=end, observed_at=end)
        assert DailyPayload.model_validate(values).day_end_at == end


def test_unit_preserves_exact_private_text_and_never_infers_meaning_from_drug_name():
    values = {
        "item_kind": "pharmaceutical",
        "item_id": 1,
        "scope": "hospital_inventory",
        "payload": {"original_unit_text": " 原计数包 ", "definition_basis_note": NOTE, "professional_attestation": {"status": "unknown", "signer_user_id": None, "basis_note": None}},
    }
    assert UnitCreate.model_validate(values).payload.original_unit_text == " 原计数包 "
    changed = copy.deepcopy(values)
    changed["scope"] = "department_inventory"
    with pytest.raises(ValidationError):
        UnitCreate.model_validate(changed)


def test_known_unit_requires_three_complete_explicit_binding_fields_and_same_sku_audit_kind():
    values = {
        "item_kind": "pharmaceutical",
        "item_id": 1,
        "scope": "hospital_inventory",
        "unit_definition_id": None,
        "expected_unit_content_hash": None,
        "expected_unit_governance_hash": None,
        "payload": daily(),
    }
    assert SourceCreate.model_validate(values).unit_definition_id is None
    values["expected_unit_governance_hash"] = "a" * 64
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(values)
    values["expected_unit_governance_hash"] = None
    values["payload"]["audit_refs"] = [{"kind": "consumable_trace", "ledger_id": None, "trace_id": "10000000-0000-4000-8000-000000000001"}]
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(values)


@pytest.mark.parametrize("note,valid", [("a" * 1000, True), ("a" * 1001, False), ("😀" * 1000, True), ("😀" * 1001, False)])
def test_revoke_1000_codepoints_and_4000_utf8_bytes_are_distinct_from_review(note, valid):
    values = {"expected_revision": 1, "expected_content_hash": "a" * 64, "basis_note": note}
    if valid:
        assert SourceRevoke.model_validate(values).basis_note == note
    else:
        with pytest.raises(ValidationError):
            SourceRevoke.model_validate(values)
    if len(note.encode()) <= 4000:
        assert SourceReview.model_validate({**values, "decision": "reject"}).basis_note == note
