"""First Billing Gate, existing inventory/surgery gate, current actor and parents."""

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm.attributes import set_committed_value

from app.ai.charge_reconciliation_models import AIChargeWriteGate


def current_charge_rows(query, *, shared=False):
    return query.populate_existing().with_for_update(read=shared)


def _mysql_gate_statement():
    # Duplicate INSERT IGNORE takes S before our later X read and permits two
    # new callers to deadlock while upgrading. An unchanged duplicate UPDATE
    # acquires X atomically, including metadata-bootstrap databases.
    return mysql_insert(AIChargeWriteGate).values(gate_id=1, revision=1).on_duplicate_key_update(gate_id=1)


def lock_charge_gate(db):
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        statement = _mysql_gate_statement()
    elif dialect == "sqlite":
        statement = sqlite_insert(AIChargeWriteGate).values(gate_id=1, revision=1).on_conflict_do_nothing(index_elements=["gate_id"])
    else:
        raise RuntimeError("Billing gate requires an explicitly supported SQL dialect")
    with db.no_autoflush:
        db.execute(statement)
        return current_charge_rows(db.query(AIChargeWriteGate).filter_by(gate_id=1)).one()


def current_charge_actor(db, user, allowed_roles):
    from app.dependencies import VALID_USER_ROLES
    from app.models import User

    roles = frozenset(allowed_roles)
    if not roles or not roles <= VALID_USER_ROLES:
        raise ValueError("Exact original business roles required")
    state = inspect(user, raiseerr=False)
    uid = state.identity[0] if state is not None and state.identity is not None else getattr(user, "user_id", None)
    with db.no_autoflush:
        actor = current_charge_rows(db.query(User).filter_by(user_id=uid), shared=True).one_or_none()
    if actor is None or actor.user_role not in roles:
        raise HTTPException(403, "当前账户已无本项原业务权限")
    return actor


def lock_charge_admissions(db, admission_ids):
    from app.models import Admission

    ids = set(admission_ids)
    if any(type(value) is not str for value in ids):
        raise ValueError("Actual Admission identifiers required")
    # Legacy missing/noncanonical IDs retain their original business response.
    return {value: current_charge_rows(db.query(Admission).filter_by(admission_id=value)).one_or_none() for value in sorted(ids)}


def lock_charge_write(db, user, *, allowed_roles, legacy_gate=None, admission_ids=()):
    """Caller owns transaction and all original business authorization.

    Billing is always acquired before either existing gate, including a caller
    whose expired ORM actor would otherwise issue a plain RR refresh first.
    """
    with db.no_autoflush:
        lock_charge_gate(db)
        if legacy_gate == "inventory":
            from app.ai.inventory_write_guard import lock_inventory_gate

            lock_inventory_gate(db)
        elif legacy_gate == "surgery":
            from app.ai.surgery_facts import lock_write_gate

            lock_write_gate(db)
        elif legacy_gate is not None:
            raise ValueError("Unknown legacy write gate")
        actor = current_charge_actor(db, user, allowed_roles)
        lock_charge_admissions(db, admission_ids)
        return actor


def lock_charge_order(db, order_id):
    from app.models import InpatientOrder, InpatientOrderItem

    locator = current_charge_rows(db.query(InpatientOrder.admission_id).filter_by(order_id=order_id), shared=True).one_or_none()
    if locator is None:
        return None
    lock_charge_admissions(db, [locator.admission_id] if locator.admission_id is not None else [])
    row = current_charge_rows(db.query(InpatientOrder).filter_by(order_id=order_id)).one()
    items = current_charge_rows(db.query(InpatientOrderItem).filter_by(order_id=order_id)).order_by(InpatientOrderItem.item_id).all()
    set_committed_value(row, "items", items)
    return row


def lock_charge_execution(db, execution_id):
    from app.models import OrderExecution

    locator = current_charge_rows(db.query(OrderExecution.order_id).filter_by(execution_id=execution_id), shared=True).one_or_none()
    if locator is None:
        return None
    order = lock_charge_order(db, locator.order_id)
    row = current_charge_rows(db.query(OrderExecution).filter_by(execution_id=execution_id)).one()
    set_committed_value(row, "order", order)
    return row


def lock_charge_administration(db, administration_id):
    from app.models import MedicationAdministration

    locator = current_charge_rows(db.query(MedicationAdministration.order_id, MedicationAdministration.execution_id).filter_by(administration_id=administration_id), shared=True).one_or_none()
    if locator is None:
        return None
    lock_charge_order(db, locator.order_id)
    lock_charge_execution(db, locator.execution_id)
    return current_charge_rows(db.query(MedicationAdministration).filter_by(administration_id=administration_id)).one()


def lock_charge_entry(db, charge_id):
    from app.models import InpatientCharge

    locator = current_charge_rows(db.query(InpatientCharge.admission_id).filter_by(charge_id=charge_id), shared=True).one_or_none()
    if locator is None:
        return None
    lock_charge_admissions(db, [locator.admission_id] if locator.admission_id is not None else [])
    return current_charge_rows(db.query(InpatientCharge).filter_by(charge_id=charge_id)).one()
