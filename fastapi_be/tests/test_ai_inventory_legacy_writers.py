"""Real synthetic SQL regressions for the legacy inventory transaction boundary."""

import datetime
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.models import Consumable, PharmaceuticalStockLedger, PurchaseOrder, PurchaseOrderItem
from app.routers import consumable, doctor, emar, purchase

WRITERS = [
    (purchase.create_purchase, "admin_user"),
    (purchase.approve_purchase, "admin_user"),
    (purchase.storage_purchase, "admin_user"),
    (purchase.cancel_purchase, "admin_user"),
    (consumable.create_consumable, "pharmacist_user"),
    (consumable.update_consumable, "pharmacist_user"),
    (consumable.delete_consumable, "pharmacist_user"),
    (doctor.pharmaceutical_register, "pharmacist_user"),
    (doctor.update_pharmaceutical, "pharmacist_user"),
    (doctor.delete_pharmaceutical, "pharmacist_user"),
    (doctor.restore_pharmaceutical, "pharmacist_user"),
    (emar.set_medication_barcode, "admin_user"),
]


@pytest.mark.parametrize("writer,actor_key", WRITERS, ids=[fn.__name__ for fn, _ in WRITERS])
def test_each_writer_rechecks_actual_role_before_request_or_business_reads(db_session, seed_data, writer, actor_key):
    actor = seed_data[actor_key]
    original_role = actor.user_role
    db_session.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:pk"), {"pk": actor.user_id})
    assert actor.user_role == original_role  # Deliberately stale ORM identity.
    with pytest.raises(HTTPException) as error:
        writer(SimpleNamespace(), current_user=actor, db=db_session)
    assert error.value.status_code == 403
    assert actor.user_role == "patient"
    db_session.rollback()


def declared_order(db, actor, sku, *, quantity=5):
    order = PurchaseOrder(order_no=uuid.uuid4().hex, create_by=actor.user_id, status=1, create_time=datetime.datetime.now())
    db.add(order)
    db.flush()
    line = PurchaseOrderItem(purchase_id=order.purchase_id, item_type="consumable", item_id_ref=sku.consumable_id, item_name="synthetic", quantity=quantity)
    db.add(line)
    db.commit()
    assert order.items == [line]
    return order, line


def test_storage_refreshes_cached_order_state_before_stock_change(db_session, seed_data):
    db = db_session
    sku = Consumable(name="synthetic cancelled", stock=9, status=0)
    db.add(sku)
    db.commit()
    order, line = declared_order(db, seed_data["admin_user"], sku)
    assert order.status == 1
    db.execute(text("UPDATE hoimsystem_purchase_order SET status=3 WHERE purchase_id=:pk"), {"pk": order.purchase_id})
    assert order.status == 1
    response = purchase.storage_purchase({"purchase_id": order.purchase_id}, current_user=seed_data["admin_user"], db=db)
    assert response["code"] == 500
    assert order.status == 3 and sku.stock == 9 and line.received_quantity is None
    db.rollback()


def test_storage_refreshes_whole_cached_child_collection_and_stock(db_session, seed_data):
    db = db_session
    sku = Consumable(name="synthetic receipt", stock=9, status=0)
    db.add(sku)
    db.commit()
    order, line = declared_order(db, seed_data["admin_user"], sku)
    db.execute(text("UPDATE hoimsystem_purchase_order_item SET quantity=2 WHERE item_id=:pk"), {"pk": line.item_id})
    db.execute(text("UPDATE hoimsystem_consumable SET stock=30 WHERE consumable_id=:pk"), {"pk": sku.consumable_id})
    assert line.quantity == 5 and sku.stock == 9
    second = PurchaseOrderItem(purchase_id=order.purchase_id, item_type="consumable", item_id_ref=sku.consumable_id, item_name="synthetic later child", quantity=3)
    db.add(second)
    db.flush()
    assert order.items == [line]  # Deliberately cached incomplete collection.
    response = purchase.storage_purchase({"purchase_id": order.purchase_id}, current_user=seed_data["admin_user"], db=db)
    assert response["code"] == 200
    db.refresh(sku)
    db.refresh(line)
    db.refresh(second)
    assert sku.stock == 35 and line.received_quantity == 2 and second.received_quantity == 3
    assert order.status == 2 and db.query(PharmaceuticalStockLedger).count() == 0


def test_soft_restore_refreshes_disabled_state_instead_of_accepting_cached_active(db_session, seed_data):
    db, drug = db_session, seed_data["pharmaceutical"]
    assert drug.status == 0
    db.execute(text("UPDATE hoimsystem_pharmaceutical SET status=1 WHERE pharmaceutical_id=:pk"), {"pk": drug.pharmaceutical_id})
    assert drug.status == 0
    response = doctor.restore_pharmaceutical(SimpleNamespace(pharmaceutical_id=drug.pharmaceutical_id), current_user=seed_data["pharmacist_user"], db=db)
    assert response == {"code": 200, "msg": "药品已启用"}
    db.refresh(drug)
    assert drug.status == 0
