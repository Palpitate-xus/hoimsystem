"""Fourteen real writer entry points reject a stale cached authorized role."""

import ast
import datetime
import inspect as python_inspect

import pytest
from fastapi import HTTPException
from sqlalchemy import event, update

from app.ai.charge_reconciliation_write_guard import lock_charge_execution, lock_charge_write
from app.dependencies import ADMIN_ROLES
from app.models import Admission, InpatientOrder, InpatientOrderItem, OrderExecution, User
from app.routers import admission, discharge, emar, inpatient_charge, inpatient_order, surgery

WRITERS = (
    inpatient_order.create_inpatient_order,
    inpatient_order.audit_inpatient_order,
    inpatient_order.stop_inpatient_order,
    inpatient_order.cancel_inpatient_order,
    inpatient_order.execute_order,
    inpatient_charge.settle_charges,
    inpatient_charge.refund_charge,
    inpatient_charge.deposit_recharge,
    admission.update_admission,
    discharge.do_discharge,
    emar.verify_medication,
    emar.administer_medication,
    surgery.complete_surgery,
    surgery.create_anesthesia_record,
)


@pytest.mark.parametrize("writer", WRITERS, ids=lambda writer: writer.__name__)
def test_actual_writer_current_demotion_is_denied_before_request_or_private_business_read(db_session, seed_data, writer):
    db, actor = db_session, seed_data["super_admin_user"]
    uid = actor.user_id
    db.execute(update(User).where(User.user_id == uid).values(user_role="patient"), execution_options={"synchronize_session": False})
    db.flush()
    assert actor.user_role == "super_admin"
    statements = []

    def observe(conn, cursor, query, parameters, context, many):
        statements.append(query)

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", observe)
    try:
        with pytest.raises(HTTPException) as denied:
            writer(req=None, current_user=actor, db=db, **({"background_tasks": None} if writer == emar.administer_medication else {}))
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    assert denied.value.status_code == 403
    assert "hoimsystem_ai_charge_write_gate" in statements[0]
    assert not any("hoimsystem_admission" in query or "hoimsystem_inpatient_charge" in query or "hoimsystem_order_execution" in query for query in statements)
    first = ast.parse(python_inspect.getsource(writer)).body[0].body[0]
    assert isinstance(first, ast.Assign) and isinstance(first.value, ast.Call) and first.value.func.id == "lock_charge_write"


def test_current_execution_scope_refreshes_entire_cached_order_item_collection(db_session, seed_data):
    db, actor = db_session, seed_data["super_admin_user"]
    parent = Admission(patient_id=seed_data["patient"].patient_id, status=1)
    db.add(parent)
    db.flush()
    order = InpatientOrder(admission_id=parent.admission_id, patient_id=parent.patient_id, status=1)
    db.add(order)
    db.flush()
    execution = OrderExecution(order_id=order.order_id, status=0, planned_time=datetime.datetime(2026, 10, 21))
    db.add(execution)
    db.commit()
    assert order.items == []
    db.execute(InpatientOrderItem.__table__.insert().values(order_id=order.order_id, item_name="实际后加项目", item_type="service", quantity=2, days=1))
    db.flush()
    assert order.items == []
    lock_charge_write(db, actor, allowed_roles=ADMIN_ROLES)
    current = lock_charge_execution(db, execution.execution_id)
    assert current.order.admission_id == parent.admission_id
    assert len(current.order.items) == 1 and current.order.items[0].quantity == 2
