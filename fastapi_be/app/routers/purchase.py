import datetime
import random
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, User, get_current_user, require_roles
from app.models import (
    Consumable,
    Pharmaceutical,
    PharmaceuticalBatch,
    PharmaceuticalStockLedger,
    PurchaseOrder,
    PurchaseOrderItem,
)

router = APIRouter()


def _parse_expiry(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError("效期必须使用 YYYY-MM-DD 格式")


@router.post("/purchase/create")
def create_purchase(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    items = req.get("items", [])
    if not items:
        return {"code": 500, "msg": "采购明细不能为空"}
    total = Decimal("0.00")
    normalized_items = []
    try:
        for it in items:
            if not isinstance(it, dict):
                return {"code": 500, "msg": "采购明细格式错误"}
            quantity = int(it.get("quantity", 0))
            if quantity <= 0:
                return {"code": 500, "msg": "采购数量必须大于0"}
            unit_price = Decimal(str(it.get("unit_price", it.get("price", 0))))
            if unit_price < 0:
                return {"code": 500, "msg": "采购单价不能为负数"}
            expiry_date = _parse_expiry(it.get("expiry_date", it.get("expireddate")))
            if expiry_date and expiry_date < datetime.date.today():
                return {"code": 500, "msg": "采购药品效期不能早于当前日期"}
            item_type = it.get("item_type", "drug")
            item_id_ref = it.get("item_id_ref", it.get("pharmaceutical_id"))
            if item_type == "drug" and item_id_ref is None:
                return {"code": 500, "msg": "药品采购明细缺少药品ID"}
            normalized = {
                "item_type": item_type,
                "item_id_ref": item_id_ref,
                "item_name": it.get("item_name", ""),
                "quantity": quantity,
                "unit_price": unit_price.quantize(Decimal("0.01")),
                "batch_no": (str(it.get("batch_no")).strip() if it.get("batch_no") else None),
                "expiry_date": expiry_date,
                "location": (str(it.get("location", "")).strip()),
            }
            total += normalized["unit_price"] * quantity
            normalized_items.append(normalized)
    except (InvalidOperation, TypeError, ValueError) as exc:
        return {"code": 500, "msg": str(exc) or "采购明细格式错误"}
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
    for it in normalized_items:
        pi = PurchaseOrderItem(
            purchase_id=order.purchase_id,
            item_type=it["item_type"],
            item_id_ref=it["item_id_ref"],
            item_name=it["item_name"],
            quantity=it["quantity"],
            unit_price=it["unit_price"],
            total_price=it["unit_price"] * it["quantity"],
            batch_no=it["batch_no"],
            expiry_date=it["expiry_date"],
            location=it["location"] or None,
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
                "items": [
                    {
                        "item_name": i.item_name,
                        "quantity": i.quantity,
                        "unit_price": i.unit_price,
                        "batch_no": i.batch_no,
                        "expiry_date": i.expiry_date,
                        "location": i.location or "",
                    }
                    for i in o.items
                ],
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
    now = datetime.datetime.now()
    batch_inputs = []
    for item in order.items:
        if item.quantity <= 0:
            db.rollback()
            return {"code": 500, "msg": "采购数量必须大于0"}
        if item.item_type != "drug":
            continue
        pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item.item_id_ref).first()
        if not pha:
            db.rollback()
            return {"code": 500, "msg": f"药品不存在：{item.item_id_ref}"}
        batch_no = item.batch_no or f"{order.order_no}-{item.item_id}"
        expiry_date = item.expiry_date or pha.expireddate
        if expiry_date and expiry_date < datetime.date.today():
            db.rollback()
            return {"code": 500, "msg": f"药品 {pha.name} 批次已过期，不能入库"}
        batch = db.query(PharmaceuticalBatch).filter(
            PharmaceuticalBatch.pharmaceutical_id == pha.pharmaceutical_id,
            PharmaceuticalBatch.batch_no == batch_no,
        ).first()
        if batch and batch.status != 0:
            db.rollback()
            return {"code": 500, "msg": f"药品 {pha.name} 批次 {batch_no} 已冻结"}
        if batch and batch.expiry_date and expiry_date and batch.expiry_date != expiry_date:
            db.rollback()
            return {"code": 500, "msg": f"药品 {pha.name} 批次效期不一致"}
        batch_inputs.append((item, pha, batch, batch_no, expiry_date))

    for item in order.items:
        if item.item_type == "drug":
            _, pha, batch, batch_no, expiry_date = next(entry for entry in batch_inputs if entry[0] is item)
            if batch is None:
                batch = PharmaceuticalBatch(
                    pharmaceutical_id=pha.pharmaceutical_id,
                    batch_no=batch_no,
                    expiry_date=expiry_date,
                    stock=0,
                    location=item.location or "",
                    status=0,
                    create_time=now,
                    update_time=now,
                )
                db.add(batch)
                db.flush()
            item.batch_no = batch_no
            item.expiry_date = expiry_date
            before_stock = batch.stock or 0
            batch.stock = before_stock + item.quantity
            batch.update_time = now
            pha.stock = (pha.stock or 0) + item.quantity
            if expiry_date and (not pha.expireddate or expiry_date < pha.expireddate):
                pha.expireddate = expiry_date
            db.add(PharmaceuticalStockLedger(
                batch_id=batch.batch_id,
                pharmaceutical_id=pha.pharmaceutical_id,
                transaction_type="inbound",
                quantity=item.quantity,
                before_stock=before_stock,
                after_stock=batch.stock,
                reference_type="purchase",
                reference_id=str(order.purchase_id),
                operator_id=current_user.user_id,
                reason=f"采购入库 {order.order_no}",
                create_time=now,
            ))
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
