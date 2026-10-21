"""Actual SQL full safe capsules; hidden patient links remain opaque hashes."""

import copy
import datetime
import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai import inventory_native_collection as c
from app.models import Consumable, PharmaceuticalBatch, PharmaceuticalStockLedger, PurchaseOrder, PurchaseOrderItem

NOW = datetime.datetime(2026, 10, 21, 12, 0, 0, 123456)


@pytest.fixture
def legacy_case(db_session, seed_data, monkeypatch):
    db = db_session
    monkeypatch.setattr(c, "utcnow", lambda: NOW)
    drug = seed_data["pharmaceutical"]
    drug.stock = 19
    drug.price = "2.50"
    a = PharmaceuticalBatch(
        pharmaceutical_id=drug.pharmaceutical_id, batch_no="原实际批次甲", stock=7, status=0, expiry_date=datetime.date(2026, 10, 20), location="原地点", create_time=NOW, update_time=NOW
    )
    b = PharmaceuticalBatch(pharmaceutical_id=drug.pharmaceutical_id, batch_no="原实际批次乙", stock=5, status=1, expiry_date=None, location="原地点", create_time=NOW, update_time=NOW)
    con = Consumable(name="原无批次耗材", stock=0, unit="套", status=0)
    db.add_all([a, b, con])
    db.flush()
    ledger = PharmaceuticalStockLedger(
        batch_id=a.batch_id,
        pharmaceutical_id=drug.pharmaceutical_id,
        transaction_type="outbound",
        quantity=3,
        before_stock=10,
        after_stock=7,
        reference_type="prescription",
        reference_id="PRIVATE_PATIENT_LINK",
        operator_id=seed_data["pharmacist_user"].user_id,
        reason="PRIVATE_CLINICAL_FREE_NOTE",
        create_time=NOW,
    )
    db.add(ledger)
    order_key = uuid.uuid4().hex[:12]
    for status in (0, 1, 2, 3, 7):
        order = PurchaseOrder(
            order_no="INV-" + order_key + "-" + str(status), supplier="PRIVATE_SUPPLIER_LABEL", status=status, total_amount="8.00", create_by=seed_data["admin_user"].user_id, create_time=NOW
        )
        db.add(order)
        db.flush()
        db.add(
            PurchaseOrderItem(
                purchase_id=order.purchase_id,
                item_type="drug",
                item_id_ref=drug.pharmaceutical_id,
                item_name="PRIVATE_SOURCE_LABEL",
                quantity=4,
                unit_price="2.00",
                total_price="8.00",
                received_quantity=None,
                expiry_date=None,
            )
        )
    db.commit()
    return {"drug": drug, "consumable": con, "batch": a, "ledger": ledger}


def capture(db, case, kind="pharmaceutical"):
    row = case["drug" if kind == "pharmaceutical" else "consumable"]
    return c.capture_legacy_inventory(db, kind, row.pharmaceutical_id if kind == "pharmaceutical" else row.consumable_id)


def rehash(value):
    for row in [value["sku"], *value["batches"], *value["ledger_entries"], *value["open_purchase_items"]]:
        row["projection_hash"] = c.hash_content(row["projection"])
    value["collection_digest"] = c.hash_content(c.legacy_content(value))


def test_entire_raw_stock_batch_freeze_expiry_and_unknown_orders_preserved(db_session, legacy_case):
    result = capture(db_session, legacy_case)
    assert c.verify_legacy_capture(result)
    assert result["sku"]["projection"]["stock"] == 19
    assert sum(row["projection"]["stock"] for row in result["batches"]) == 12
    assert [row["projection"]["status"] for row in result["batches"]] == [0, 1]
    assert [row["projection"]["expiry_date"] for row in result["batches"]] == ["2026-10-20", None]
    assert [row["projection"]["order_status"] for row in result["open_purchase_items"]] == [0, 1, 7]
    assert result["row_count"] == 7 and result["sku"]["projection"]["unit"] is None
    assert result["captured_at"] == "2026-10-21T12:00:00.123456Z"


def test_safe_whole_capsules_do_not_expose_reference_patient_operator_or_free_text(db_session, legacy_case):
    result = capture(db_session, legacy_case)
    text = json.dumps(result)
    for forbidden in ["PRIVATE_PATIENT_LINK", "PRIVATE_CLINICAL_FREE_NOTE", "PRIVATE_SUPPLIER_LABEL", "PRIVATE_SOURCE_LABEL", "operator_id", "reference_id"]:
        assert forbidden not in text
    movement = result["ledger_entries"][0]
    assert movement["projection"]["quantity"] == 3 and len(movement["original_row_hash"]) == 64
    assert movement["projection"]["create_time_legacy"] == "2026-10-21T12:00:00.123456"
    assert movement["projection"]["time_basis"] == c.TIME_BASIS


def test_hidden_column_changes_invalidate_complete_current_digest_without_revealing_text(db_session, legacy_case):
    before = capture(db_session, legacy_case)
    legacy_case["ledger"].reason = "ANOTHER_PRIVATE_NOTE"
    db_session.commit()
    after = capture(db_session, legacy_case)
    assert before["collection_digest"] != after["collection_digest"]
    assert before["ledger_entries"][0]["projection_hash"] == after["ledger_entries"][0]["projection_hash"]
    assert before["ledger_entries"][0]["original_row_hash"] != after["ledger_entries"][0]["original_row_hash"]
    assert "ANOTHER_PRIVATE_NOTE" not in json.dumps(after)


def test_actual_capture_clock_does_not_change_unchanged_inventory_content_digest(db_session, legacy_case, monkeypatch):
    before = capture(db_session, legacy_case)
    monkeypatch.setattr(c, "utcnow", lambda: NOW + datetime.timedelta(microseconds=1))
    after = capture(db_session, legacy_case)
    assert before["captured_at"] != after["captured_at"]
    assert before["collection_digest"] == after["collection_digest"]


def test_consumable_never_invents_legacy_batches_expiry_or_stock_unit_confirmation(db_session, legacy_case):
    result = capture(db_session, legacy_case, "consumable")
    assert c.verify_legacy_capture(result) and result["batches"] == result["ledger_entries"] == []
    assert result["sku"]["projection"]["stock"] == 0 and result["sku"]["projection"]["unit"] == "套"
    assert result["sku"]["projection"]["expiry_date"] is None
    assert "unit_review" not in result["sku"]["projection"]


def test_signed_and_null_legacy_stock_are_retained_not_clamped_to_zero(db_session, legacy_case):
    for value in (-7, None):
        legacy_case["drug"].stock = value
        db_session.commit()
        assert capture(db_session, legacy_case)["sku"]["projection"]["stock"] == value


def test_keyset_reads_all_more_than32_actual_batches_without_loading_truncated_winner(db_session, legacy_case):
    for number in range(35):
        db_session.add(
            PharmaceuticalBatch(
                pharmaceutical_id=legacy_case["drug"].pharmaceutical_id, batch_no=f"原完整批次{number}", stock=0, status=0, expiry_date=None, location="", create_time=NOW, update_time=NOW
            )
        )
    db_session.commit()
    sql = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "hoimsystem_pharmaceutical_batch" in statement and statement.lstrip().startswith("SELECT"):
            sql.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", observe)
    try:
        result = capture(db_session, legacy_case)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", observe)
    assert len(result["batches"]) == 37
    ids_only = [s for s in sql if " LIMIT " in " ".join(s.split())]
    assert len(ids_only) == 3 and all(".stock" not in s.split("FROM")[0] for s in ids_only)


@pytest.mark.parametrize("bound,value", [("MAX_LEGACY_ROWS", 2), ("MAX_LEGACY_BYTES", 100)])
def test_whole_capture_limits_refuse_not_truncate(db_session, legacy_case, monkeypatch, bound, value):
    monkeypatch.setattr(c, bound, value)
    with pytest.raises(HTTPException) as error:
        capture(db_session, legacy_case)
    assert error.value.status_code == 409


@pytest.mark.parametrize("change", ["boolean_stock", "foreign_scope", "duplicate", "raw_reference", "utc_invented", "row_count", "closed_order", "foreign_batch", "extra_root"])
def test_rehashing_safe_capsules_cannot_justify_wrong_scope_or_types(db_session, legacy_case, change):
    result = copy.deepcopy(capture(db_session, legacy_case))
    if change == "boolean_stock":
        result["sku"]["projection"]["stock"] = True
    elif change == "foreign_scope":
        result["sku"]["item_id"] += 1
    elif change == "duplicate":
        result["batches"].append(copy.deepcopy(result["batches"][0]))
    elif change == "raw_reference":
        result["ledger_entries"][0]["projection"]["reference_id"] = "private"
    elif change == "utc_invented":
        result["ledger_entries"][0]["projection"]["create_time_legacy"] += "Z"
    elif change == "row_count":
        result["row_count"] += 1
    elif change == "closed_order":
        result["open_purchase_items"][0]["projection"]["order_status"] = 2
    elif change == "foreign_batch":
        result["batches"][0]["projection"]["pharmaceutical_id"] += 1
    else:
        result["injected_patient"] = {"id": 1}
    rehash(result)
    assert not c.verify_legacy_capture(result)
