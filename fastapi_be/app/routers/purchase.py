import datetime
import random

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, User, User, require_roles, ADMIN_ROLES
from app.models import Consumable, Pharmaceutical, PurchaseOrder, PurchaseOrderItem

router = APIRouter()


@router.post("/purchase/create")
def create_purchase(req: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    items = req.get("items", [])
    if not items:
        return {"code": 500, "msg": "采购明细不能为空"}
    total = 0
    for it in items:
        total += float(it.get("unit_price", 0)) * int(it.get("quantity", 0))
    order_no = "PO" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(1000, 9999))
    order = PurchaseOrder(
        order_no=order_no,
        supplier=req.get("supplier", ""),
        total_amount=total,
        status=0,
        create_by=current_user.user_id,
        create_time=datetime.datetime.now(),
    )
    db.add(order)
    db.flush()
    for it in items:
        pi = PurchaseOrderItem(
            purchase_id=order.purchase_id,
            item_type=it.get("item_type", "drug"),
            item_id_ref=it.get("item_id_ref"),
            item_name=it.get("item_name", ""),
            quantity=it.get("quantity", 0),
            unit_price=it.get("unit_price", 0),
            total_price=float(it.get("unit_price", 0)) * int(it.get("quantity", 0)),
        )
        db.add(pi)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"order_no": order_no}}


@router.get("/purchase/getList")
def get_purchase_list(status: int | None = None, current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    query = db.query(PurchaseOrder)
    if status is not None:
        query = query.filter(PurchaseOrder.status == status)
    orders = query.order_by(PurchaseOrder.create_time.desc()).all()
    data = []
    for o in orders:
        data.append(
            {
                "purchase_id": o.purchase_id,
                "order_no": o.order_no,
                "supplier": o.supplier,
                "total_amount": round(o.total_amount, 2) if o.total_amount else 0,
                "status": o.status,
                "status_text": {0: "待审批", 1: "已审批", 2: "已入库", 3: "已取消"}.get(o.status, ""),
                "create_by": o.creator.username if o.creator else "",
                "create_time": (o.create_time.strftime("%Y-%m-%d %H:%M:%S") if o.create_time else None) if o.create_time else "",
                "items": [{"item_name": i.item_name, "quantity": i.quantity, "unit_price": i.unit_price} for i in o.items],
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/purchase/approve")
def approve_purchase(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db)):
    order = db.query(PurchaseOrder).filter(PurchaseOrder.purchase_id == req.get("purchase_id")).first()
    if not order:
        return {"code": 500, "msg": "采购单不存在"}
    if order.status != 0:
        return {"code": 500, "msg": "只有待审批的采购单可以审批"}
    order.status = 1
    order.approve_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/purchase/storage")
def storage_purchase(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db)):
    order = db.query(PurchaseOrder).filter(PurchaseOrder.purchase_id == req.get("purchase_id")).first()
    if not order:
        return {"code": 500, "msg": "采购单不存在"}
    if order.status != 1:
        return {"code": 500, "msg": "只有已审批的采购单可以入库"}
    for item in order.items:
        if item.item_type == "drug":
            pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item.item_id_ref).first()
            if pha:
                pha.stock += item.quantity
                db.add(pha)
        elif item.item_type == "consumable":
            con = db.query(Consumable).filter(Consumable.consumable_id == item.item_id_ref).first()
            if con:
                con.stock += item.quantity
                db.add(con)
    order.status = 2
    order.storage_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/purchase/cancel")
def cancel_purchase(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db)):
    order = db.query(PurchaseOrder).filter(PurchaseOrder.purchase_id == req.get("purchase_id")).first()
    if not order:
        return {"code": 500, "msg": "采购单不存在"}
    if order.status == 2:
        return {"code": 500, "msg": "已入库的采购单不可取消"}
    order.status = 3
    db.commit()
    return {"code": 200, "msg": "success"}
