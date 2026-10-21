"""Actual synthetic ledger originals and technical governance, no money writes."""

import copy
import datetime as dt
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text, update
from sqlalchemy.dialects import mysql

from app.ai import charge_reconciliation_contract as c
from app.ai import charge_reconciliation_sources as s
from app.ai.charge_reconciliation_models import AIChargeCaseSnapshot
from app.ai.models import AIAuditEvent, AIPatientGrant
from app.models import Admission, InpatientCharge, InpatientOrder, InpatientOrderItem, MedicationAdministration, OrderExecution

NOW = dt.datetime(2026, 10, 21, 12, 30, 0, 123456)
NOTE = "本合成完整账目仅核对原始记录，不表示真实收退款或收费资格。"
LITERAL = "原文2026-10-21T12:00:00.123456Z"


@pytest.fixture
def charge_case(db_session, seed_data, monkeypatch):
    db = db_session
    monkeypatch.setattr(s, "utcnow", lambda: NOW)
    admission = Admission(
        patient_id=seed_data["patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        department_id=seed_data["department"].department_id,
        admission_time=NOW - dt.timedelta(days=1),
        create_time=NOW - dt.timedelta(days=1),
        status=1,
        deposit_amount=Decimal("123.00"),
    )
    db.add(admission)
    db.flush()
    orders = [
        InpatientOrder(
            admission_id=admission.admission_id, patient_id=admission.patient_id, doctor_id=admission.doctor_id, category="service", order_type=0, status=status, create_time=NOW, start_time=NOW
        )
        for status in (1, 4)
    ]
    db.add_all(orders)
    db.flush()
    items = [
        InpatientOrderItem(order_id=order.order_id, item_name="原项目" + str(index), item_type="service", quantity=0, days=1, unit="次", unit_price=Decimal("0.00"), total_price=Decimal("0.00"))
        for index, order in enumerate(orders)
    ]
    executions = [OrderExecution(order_id=orders[0].order_id, status=status, planned_time=NOW, execution_time=NOW) for status in (1, 2)]
    db.add_all([*items, *executions])
    db.flush()
    administration = MedicationAdministration(
        execution_id=executions[0].execution_id,
        order_id=orders[0].order_id,
        patient_id=admission.patient_id,
        nurse_id=seed_data["nurse_user"].user_id,
        patient_barcode="private-only-patient",
        medication_barcodes_json='["private-only-drug"]',
        status=1,
        verified_at=NOW,
    )
    charges = [
        InpatientCharge(
            admission_id=admission.admission_id,
            patient_id=admission.patient_id,
            item_name=LITERAL if index == 0 else seed_data["patient"].name + "原记账项目",
            item_type="service",
            quantity=[0.0, None, -0.5, 0.1][index % 4],
            unit_price=Decimal("2.00"),
            total_amount=Decimal("4.00"),
            charge_date=NOW.date(),
            related_order_id=orders[0].order_id if index % 2 else None,
            status=[0, 1, 2, None, 17][index % 5],
            create_time=NOW,
        )
        for index in range(65)
    ]
    db.add_all([administration, *charges])
    db.commit()
    db.execute(update(InpatientCharge).where(InpatientCharge.charge_id == charges[1].charge_id).values(quantity=None, unit_price=None))
    db.commit()
    return {**seed_data, "db": db, "admission": admission, "orders": orders, "items": items, "executions": executions, "administration": administration, "charges": charges}


def request(case):
    return {"patient_id": case["patient"].patient_id, "admission_id": case["admission"].admission_id}


def cas(value):
    return {"expected_revision": value["revision"], "expected_content_hash": value["content_hash"], "expected_governance_hash": value["governance_hash"]}


def draft(case, actor=None):
    db, actor = case["db"], actor or case["super_admin_user"]
    value = s.capture_case(db, actor, request(case))
    result = s.create_case(db, actor, {"request": request(case), "expected_collection_digest": value["collection_digest"], "note": NOTE})
    db.commit()
    return result


def published(case):
    value = draft(case)
    result = s.review_case(case["db"], case["super_admin_user"], value["case_snapshot_id"], {**cas(value), "decision": "publish", "basis_note": NOTE})
    case["db"].commit()
    return result


def test_complete_originals_float_zero_null_negative_naive_time_and_no_financial_claim(charge_case):
    case, db = charge_case, charge_case["db"]
    value = s.capture_case(db, case["super_admin_user"], request(case))
    assert len(value["charges"]) == 65 and len(value["orders"]) == 2
    assert len(value["member_manifest"]) == 74 and s.verify_capture(value)
    assert {row["quantity"]["state"] for row in value["charges"]} == {"null", "finite"}
    assert any(row["quantity"]["value_text"] == "-0.5" for row in value["charges"])
    assert any(row["quantity"]["value_text"] == "0.0" for row in value["charges"])
    assert all(row["quantity"]["storage_witness"] is None for row in value["charges"])
    assert value["float_capture_basis"] == "sqlite_orm_float_only"
    assert value["captured_at"] == "2026-10-21T12:30:00.123456Z"
    assert value["charges"][0]["create_time"].endswith(".123456")
    made = published(case)
    proof = s.original_proof(db.get(AIChargeCaseSnapshot, made["case_snapshot_id"]))
    assert s.verify_original(proof)
    public = made["public_source"]
    assert public["policy"]["cash_receipt"] == public["policy"]["cash_refund"] == "not_provided"
    assert public["policy"]["billing_entitlement"] == "unknown"
    assert public["admission"]["deposit_amount"] == "123.00"
    text_ = c.canonical_json(public)
    for secret in (case["patient"].name, case["patient"].identity, case["admission"].admission_id, "private-only-patient", "private-only-drug", made["snapshot"]["identity_secret"]):
        assert secret not in text_
    assert LITERAL in text_ and "[已隐藏直接标识]" in text_
    assert all(row["order_association"] in {"recorded_same_admission", "not_recorded"} for row in public["charges"])


@pytest.mark.parametrize("change", ["add", "delete", "same_total", "rebind"])
def test_any_actual_member_change_invalidates_current_source_and_old_create_digest(charge_case, change):
    case, db = charge_case, charge_case["db"]
    original = published(case)
    old_digest = original["collection_digest"]
    if change == "add":
        db.add(InpatientCharge(admission_id=case["admission"].admission_id, patient_id=case["patient"].patient_id, item_name="新零元非赢家", quantity=0, unit_price=0, total_amount=0))
    elif change == "delete":
        db.delete(case["charges"][0])
    elif change == "same_total":
        case["charges"][0].unit_price = Decimal("3.00")
    else:
        alternate = Admission(patient_id=case["patient"].patient_id, status=1)
        db.add(alternate)
        db.flush()
        case["charges"][0].admission_id = alternate.admission_id
    db.commit()
    current = s.case_current(db, case["super_admin_user"], original["case_snapshot_id"])
    assert not current["eligible"] and current["snapshot"] is None and current["public_source"] is None
    audit = s.case_current(db, case["super_admin_user"], original["case_snapshot_id"], audit_only=True)
    assert audit["snapshot"] == original["snapshot"] and not audit["eligible"]
    count = db.query(AIChargeCaseSnapshot).count()
    with pytest.raises(HTTPException) as denied:
        s.create_case(db, case["super_admin_user"], {"request": request(case), "expected_collection_digest": old_digest, "note": NOTE})
    assert denied.value.status_code == 409 and db.query(AIChargeCaseSnapshot).count() == count


def test_emar_union_detects_cross_parent_record_even_when_order_join_would_hide_it(charge_case):
    case, db = charge_case, charge_case["db"]
    alternate = Admission(patient_id=case["patient2"].patient_id, status=1)
    db.add(alternate)
    db.flush()
    outside = InpatientOrder(admission_id=alternate.admission_id, patient_id=alternate.patient_id)
    db.add(outside)
    db.flush()
    case["administration"].order_id = outside.order_id
    db.commit()
    with pytest.raises(HTTPException) as denied:
        s.capture_case(db, case["super_admin_user"], request(case))
    assert denied.value.status_code == 409


def test_cashier_requires_current_actual_operations_grant_and_cannot_technically_publish(charge_case):
    case, db = charge_case, charge_case["db"]
    cashier = case["cashier_user"]
    statements = []

    def observed(conn, cursor, query, parameters, context, many):
        statements.append(query)

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", observed)
    try:
        with pytest.raises(HTTPException) as denied:
            s.capture_case(db, cashier, request(case))
    finally:
        event.remove(connection, "before_cursor_execute", observed)
    assert denied.value.status_code == 403
    assert not any("hoimsystem_inpatient_charge" in query for query in statements)
    grant = AIPatientGrant(
        user_id=cashier.user_id, patient_id=case["patient"].patient_id, category="operations", reason=NOTE, expires_at=NOW + dt.timedelta(days=1), created_by=case["super_admin_user"].user_id
    )
    db.add(grant)
    db.commit()
    value = draft(case, cashier)
    with pytest.raises(HTTPException) as denied:
        s.review_case(db, cashier, value["case_snapshot_id"], {**cas(value), "decision": "publish", "basis_note": NOTE})
    assert denied.value.status_code == 403
    db.refresh(grant)
    grant.revoked = 1
    db.commit()
    statements.clear()
    connection = db.connection()
    event.listen(connection, "before_cursor_execute", observed)
    try:
        with pytest.raises(HTTPException) as denied:
            s.case_current(db, cashier, value["case_snapshot_id"])
    finally:
        event.remove(connection, "before_cursor_execute", observed)
    assert denied.value.status_code == 403
    assert not any("snapshot_json" in query for query in statements)


@pytest.mark.parametrize("decision", ["publish", "reject"])
def test_exact_governance_cas_and_terminal_originals(charge_case, decision):
    case, db = charge_case, charge_case["db"]
    value = draft(case)
    changed = {**cas(value), "expected_governance_hash": "0" * 64, "decision": decision, "basis_note": NOTE}
    with pytest.raises(HTTPException) as denied:
        s.review_case(db, case["super_admin_user"], value["case_snapshot_id"], changed)
    assert denied.value.status_code == 409
    reviewed = s.review_case(db, case["super_admin_user"], value["case_snapshot_id"], {**cas(value), "decision": decision, "basis_note": NOTE})
    db.commit()
    assert reviewed["status"] == ("published" if decision == "publish" else "rejected")
    if decision == "publish":
        revoked = s.revoke_case(db, case["super_admin_user"], value["case_snapshot_id"], {**cas(reviewed), "basis_note": NOTE})
        db.commit()
        assert revoked["status"] == "revoked" and revoked["revision"] == 3 and revoked["snapshot"] == value["snapshot"]
        normal = s.case_current(db, case["super_admin_user"], value["case_snapshot_id"])
        assert normal["snapshot"] is None and normal["review_basis_note"] is None and normal["revoke_reason"] is None


@pytest.mark.parametrize("mutation", ["quantity", "unknown_field", "date", "missing_member", "scope"])
def test_full_collection_self_rehash_is_not_a_substitute_for_types_members_and_scope(charge_case, mutation):
    case, db = charge_case, charge_case["db"]
    value = copy.deepcopy(s.capture_case(db, case["super_admin_user"], request(case)))
    if mutation == "quantity":
        value["charges"][0]["quantity"]["value_text"] = "100000"
    elif mutation == "unknown_field":
        value["charges"][0]["trusted_cash_receipt"] = True
    elif mutation == "date":
        value["charges"][0]["create_time"] = "2026-02-30T12:00:00.123456"
    elif mutation == "missing_member":
        del value["orders"][0]
    else:
        value["charges"][0]["patient_id"] = case["patient2"].patient_id
    value["member_manifest"] = s.member_manifest(value)
    value["manifest_hash"] = c.digest(value["member_manifest"])
    value["collection_digest"] = c.digest(s.collection_content(value))
    assert not s.verify_capture(value)


@pytest.mark.parametrize("overflow", ["rows", "bytes"])
def test_actual_keyset_all_or_refuse_budget_has_no_silent_complete_prefix(charge_case, overflow):
    case, db = charge_case, charge_case["db"]
    baseline = db.query(AIChargeCaseSnapshot).count()
    values = [
        {
            "charge_id": str(uuid.uuid4()),
            "admission_id": case["admission"].admission_id,
            "patient_id": case["patient"].patient_id,
            "item_name": "😀" * 50 if overflow == "bytes" else "合成原件",
            "refund_reason": "😀" * 200 if overflow == "bytes" else None,
        }
        for _ in range(6000 if overflow == "bytes" else 8192)
    ]
    db.execute(InpatientCharge.__table__.insert(), values)
    db.commit()
    with pytest.raises(HTTPException) as denied:
        s.capture_case(db, case["super_admin_user"], request(case))
    assert denied.value.status_code == 409 and db.query(AIChargeCaseSnapshot).count() == baseline


@pytest.mark.parametrize("fault", ["audit", "source", "member", "token"])
def test_actual_post_audit_sql_fault_rolls_back_entire_case_and_specific_audit(charge_case, fault):
    case, db = charge_case, charge_case["db"]
    value = s.capture_case(db, case["super_admin_user"], request(case))
    baseline = db.query(AIChargeCaseSnapshot).count()
    audit_baseline = db.query(AIAuditEvent).filter_by(action="charge.case.create").count()
    effects = {
        "audit": "DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id",
        "source": "UPDATE hoimsystem_ai_charge_case_snapshot SET snapshot_json='{}' WHERE case_snapshot_id=NEW.target",
        "member": "UPDATE hoimsystem_inpatient_charge SET unit_price=99 WHERE admission_id='" + case["admission"].admission_id + "'",
        "token": "UPDATE hoimsystem_users SET token_invalid_before='2026-10-22 00:00:00' WHERE user_id=NEW.actor_id",
    }
    db.execute(text("CREATE TRIGGER charge_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='charge.case.create' BEGIN " + effects[fault] + "; END"))
    db.commit()
    try:
        with pytest.raises(HTTPException):
            s.create_case(db, case["super_admin_user"], {"request": request(case), "expected_collection_digest": value["collection_digest"], "note": NOTE})
        assert db.query(AIChargeCaseSnapshot).count() == baseline
        assert db.query(AIAuditEvent).filter_by(action="charge.case.create").count() == audit_baseline
        db.refresh(case["super_admin_user"])
        assert case["super_admin_user"].token_invalid_before is None
        db.refresh(case["charges"][0])
        assert case["charges"][0].unit_price == Decimal("2.00")
    finally:
        db.execute(text("DROP TRIGGER charge_fault"))
        db.commit()


def test_actual_mysql_expression_is_not_generic_cast_silently_removed_by_sqlalchemy():
    sql = str(s.SQLFloatPromotion(InpatientCharge.quantity).compile(dialect=mysql.dialect()))
    assert sql == "CAST(hoimsystem_inpatient_charge.quantity AS DOUBLE)"


def test_original_proof_requires_retained_publication_and_server_clock_order(charge_case):
    case = charge_case
    value = published(case)
    value = s.revoke_case(case["db"], case["super_admin_user"], value["case_snapshot_id"], {**cas(value), "basis_note": NOTE})
    case["db"].commit()
    original = {key: value[key] for key in c.CaseOriginalProof.model_fields}
    assert s.verify_original(original)
    missing = copy.deepcopy(original)
    missing["public_source"] = missing["projection_hash"] = None
    assert not s.verify_original(missing)
    early = copy.deepcopy(original)
    early["created_at"] = early["snapshot"]["created_at"] = "2026-10-20T00:00:00.000000Z"
    early["content_hash"] = c.digest(early["snapshot"])
    early["source_id"] = "charge_case:" + early["case_snapshot_id"] + ":" + early["content_hash"][:12]
    early["public_source"] = c.project_snapshot(early["snapshot"], s.published_metadata(early))
    early["projection_hash"] = c.digest(early["public_source"])
    assert not s.verify_original(early)


def test_arbitrary_legacy_category_text_is_never_promoted_to_public_enum(charge_case):
    case, db = charge_case, charge_case["db"]
    private = case["patient"].name
    db.execute(update(InpatientCharge).where(InpatientCharge.charge_id == case["charges"][0].charge_id).values(item_type=private))
    db.execute(update(InpatientOrder).where(InpatientOrder.order_id == case["orders"][0].order_id).values(category=private))
    db.commit()
    value = published(case)
    source = value["public_source"]
    charge = next(row for row in source["charges"] if row["original_item_type_hash"] == c.digest(private))
    order = next(row for row in source["orders"] if row["original_category_hash"] == c.digest(private))
    assert charge["item_type"] == order["category"] == "unknown"
    assert private not in c.canonical_json(source)


def test_internal_frozen_proof_is_distinct_from_current_execution_permission(charge_case):
    case, db = charge_case, charge_case["db"]
    value = draft(case)
    with pytest.raises(HTTPException) as denied:
        s.case_current(db, case["super_admin_user"], value["case_snapshot_id"], execution=True)
    assert denied.value.status_code == 409
    value = s.review_case(db, case["super_admin_user"], value["case_snapshot_id"], {**cas(value), "decision": "publish", "basis_note": NOTE})
    db.commit()
    assert s.case_current(db, case["super_admin_user"], value["case_snapshot_id"], execution=True)["eligible"]
    published_governance = value["governance_hash"]
    value = s.revoke_case(db, case["super_admin_user"], value["case_snapshot_id"], {**cas(value), "basis_note": NOTE})
    db.commit()
    proof = s.frozen_case_proof(db, value["case_snapshot_id"])
    assert s.verify_original(proof) and proof["status"] == "revoked"
    assert proof["public_source"]["governance_hash"] == published_governance != proof["governance_hash"]
    for options in ({"execution": True}, {"execution": True, "audit_only": True}):
        with pytest.raises(HTTPException) as denied:
            s.case_current(db, case["super_admin_user"], value["case_snapshot_id"], **options)
        assert denied.value.status_code == 409
