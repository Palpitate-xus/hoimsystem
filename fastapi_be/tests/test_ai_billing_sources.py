"""Billing assistance compares original facts without charging, refunding or guessing execution."""

import datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.ai.billing_sources import billing_reconciliation
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.tools import business_tools
from app.models import Admission, InpatientCharge, InpatientOrder, OrderExecution


@pytest.fixture
def billing_case(seed_data, db_session):
    now = datetime.datetime.now()
    admission = Admission(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, status=1, admission_time=now)
    db_session.add(admission)
    db_session.flush()
    orders = [InpatientOrder(patient_id=admission.patient_id, admission_id=admission.admission_id, doctor_id=admission.doctor_id, category="service", status=2, create_time=now) for _ in range(5)]
    db_session.add_all(orders)
    db_session.flush()
    # Completed, completed-and-refunded, awaiting execution, no actual time, cancelled.
    for index, order in enumerate(orders):
        db_session.add(
            OrderExecution(order_id=order.order_id, nurse_id=seed_data["nurse_user"].user_id, planned_time=now, status=0 if index == 2 else 1, execution_time=now if index in {0, 1, 4} else None)
        )
    orders[4].status = 4
    charges = [
        InpatientCharge(
            patient_id=admission.patient_id,
            admission_id=admission.admission_id,
            item_name="已退费测试项目",
            quantity=1,
            unit_price=Decimal("10.00"),
            total_amount=Decimal("10.00"),
            status=2,
            related_order_id=orders[1].order_id,
            create_time=now,
        ),
        InpatientCharge(
            patient_id=admission.patient_id,
            admission_id=admission.admission_id,
            item_name="执行待核实测试项目",
            quantity=1.5,
            unit_price=Decimal("6.67"),
            total_amount=Decimal("10.01"),
            status=0,
            related_order_id=orders[2].order_id,
            create_time=now,
        ),
    ]
    db_session.add_all(charges)
    db_session.commit()
    return admission, orders, charges


def snapshot(db_session, seed_data, admission, **refs):
    return patient_snapshot(db_session, seed_data["super_admin_user"], FEATURE_BY_KEY["charge_reconciliation"], admission.patient_id, admission.admission_id, refs)


def test_only_executed_with_actual_time_and_without_any_charge_link_are_review_candidates(seed_data, db_session, billing_case):
    admission, orders, charges = billing_case
    bundle = snapshot(db_session, seed_data, admission)
    tools, _ = business_tools(db_session, FEATURE_BY_KEY["charge_reconciliation"], seed_data["super_admin_user"], admission.patient_id, {}, bundle)
    results = tools["billing_reconciliation"]
    assert {row["order_id"] for row in results["executed_without_charge_link"]} == {orders[0].order_id}
    assert results["changes_written"] == []
    assert "outpatient_records" not in bundle.data
    assert "reviewed_lab_results" not in bundle.data
    assert "prescriptions" not in bundle.data
    assert "current_confirmed_diagnoses" not in bundle.data
    refund = next(row for row in results["checks"] if row["charge_id"] == charges[0].charge_id)
    assert any("已记录退费" in text for text in refund["findings"])
    review = next(row for row in results["checks"] if row["charge_id"] == charges[1].charge_id)
    assert review["raw_product"] == "10.005"
    assert review["stored_amount"] == "10.01"
    assert review["amount_comparison"] == "raw_product_differs"
    assert any("关联医嘱缺少执行状态或实际执行时间" in text for text in review["findings"])
    assert all(source_id in {item["source_id"] for item in bundle.evidence} for row in results["checks"] for source_id in row["source_ids"])
    db_session.refresh(charges[0])
    db_session.refresh(charges[1])
    assert (charges[0].status, charges[1].status) == (2, 0)
    assert db_session.query(InpatientCharge).filter_by(admission_id=admission.admission_id).count() == 2


def test_selected_charge_cannot_cross_admission_and_foreign_order_contents_are_not_loaded(seed_data, db_session, billing_case):
    admission, _, charges = billing_case
    other = Admission(patient_id=admission.patient_id, doctor_id=admission.doctor_id, department_id=admission.department_id, status=1, admission_time=admission.admission_time)
    db_session.add(other)
    db_session.flush()
    foreign_order = InpatientOrder(patient_id=admission.patient_id, admission_id=other.admission_id, doctor_id=admission.doctor_id, status=2, category="foreign-category")
    db_session.add(foreign_order)
    db_session.flush()
    charges[1].related_order_id = foreign_order.order_id
    db_session.commit()
    with pytest.raises(HTTPException) as mismatch:
        snapshot(db_session, seed_data, other, inpatient_charge_id=charges[0].charge_id)
    assert mismatch.value.status_code == 422
    bundle = snapshot(db_session, seed_data, admission)
    assert all(row["order_id"] != foreign_order.order_id for row in bundle.data["billing_related_orders"])
    result = next(row for row in billing_reconciliation(bundle.data)["checks"] if row["charge_id"] == charges[1].charge_id)
    assert any("所选住院中核实" in text for text in result["findings"])


def test_selected_older_charge_survives_bounded_history_and_truncation_is_explicit(seed_data, db_session, billing_case):
    admission, _, charges = billing_case
    old = charges[0]
    db_session.add_all(
        [
            InpatientCharge(
                patient_id=admission.patient_id,
                admission_id=admission.admission_id,
                item_name="较新记录",
                quantity=1,
                unit_price=1,
                total_amount=1,
                status=0,
                create_time=old.create_time + datetime.timedelta(days=1),
            )
            for _ in range(51)
        ]
    )
    db_session.commit()
    bundle = snapshot(db_session, seed_data, admission, inpatient_charge_id=old.charge_id)
    assert len(bundle.data["inpatient_charges"]) == 50
    assert bundle.data["inpatient_charges"][0]["charge_id"] == old.charge_id
    assert any(row["source"] == "住院收费记录" for row in bundle.data["truncated_sources"])


def test_missing_financial_values_are_not_replaced_with_zero():
    results = billing_reconciliation({"inpatient_charges": [{"charge_id": "test", "source_id": "charge:test", "quantity": None, "unit_price": "0.00", "total_amount": None, "status": 0}]})
    assert results["checks"][0]["raw_product"] is None
    assert results["checks"][0]["stored_amount"] is None
    assert results["checks"][0]["amount_comparison"] == "unknown"


def test_billing_sources_are_not_added_to_unrelated_clinical_tasks(seed_data, db_session, billing_case):
    admission, _, _ = billing_case
    bundle = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["patient_summary"], admission.patient_id, admission.admission_id)
    assert "inpatient_charges" not in bundle.data
    assert "billing_related_orders" not in bundle.data
