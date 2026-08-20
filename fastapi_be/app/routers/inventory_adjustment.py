import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, PHARMACY_ROLES, User, require_roles
from app.models import InventoryAdjustment, Pharmaceutical
from app.schemas import InventoryAdjustmentActionRequest, InventoryAdjustmentCreateRequest

router = APIRouter()


def _serialize(item: InventoryAdjustment):
    return {
        "id": item.adjustment_id,
        "adjustment_id": item.adjustment_id,
        "pharmaceutical_id": item.pharmaceutical_id,
        "pharmaceutical_name": item.pharmaceutical.name if item.pharmaceutical else "",
        "adjustment_type": item.adjustment_type,
        "quantity": item.quantity,
        "reason": item.reason,
        "status": item.status,
        "applicant": item.applicant.username if item.applicant else "",
        "approver": item.approver.username if item.approver else "",
        "create_time": item.create_time,
        "approve_time": item.approve_time,
    }


@router.get("/pharmacy/inventoryAdjustment/list")
def list_inventory_adjustments(
    status: int | None = None,
    current_user: User = Depends(require_roles(*PHARMACY_ROLES)),
    db: Session = Depends(get_db),
):
    query = db.query(InventoryAdjustment).order_by(InventoryAdjustment.adjustment_id.desc())
    if status is not None:
        query = query.filter(InventoryAdjustment.status == status)
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in query.all()]}


@router.post("/pharmacy/inventoryAdjustment/create")
def create_inventory_adjustment(
    req: InventoryAdjustmentCreateRequest,
    current_user: User = Depends(require_roles(*PHARMACY_ROLES)),
    db: Session = Depends(get_db),
):
    if req.adjustment_type not in {"loss", "gain"}:
        return {"code": 500, "msg": "调整类型必须为报损或报溢"}
    pharmaceutical = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pharmaceutical_id).first()
    if not pharmaceutical:
        return {"code": 500, "msg": "药品不存在"}
    item = InventoryAdjustment(
        pharmaceutical_id=req.pharmaceutical_id,
        adjustment_type=req.adjustment_type,
        quantity=req.quantity,
        reason=req.reason.strip(),
        status=0,
        applicant_id=current_user.user_id,
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.post("/pharmacy/inventoryAdjustment/approve")
def approve_inventory_adjustment(
    req: InventoryAdjustmentActionRequest,
    current_user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    item = db.query(InventoryAdjustment).filter(InventoryAdjustment.adjustment_id == req.adjustment_id).first()
    if not item:
        return {"code": 404, "msg": "库存调整单不存在"}
    if item.status != 0:
        return {"code": 500, "msg": "库存调整单已处理"}
    pharmaceutical = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item.pharmaceutical_id).first()
    if not pharmaceutical:
        return {"code": 500, "msg": "药品不存在"}
    updated_adjustment = db.query(InventoryAdjustment).filter(InventoryAdjustment.adjustment_id == item.adjustment_id, InventoryAdjustment.status == 0).update(
        {InventoryAdjustment.status: 1, InventoryAdjustment.approver_id: current_user.user_id, InventoryAdjustment.approve_time: datetime.datetime.now()},
        synchronize_session=False,
    )
    if updated_adjustment != 1:
        db.rollback()
        return {"code": 500, "msg": "库存调整单已处理"}
    if item.adjustment_type == "loss":
        updated = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item.pharmaceutical_id, Pharmaceutical.stock >= item.quantity).update(
            {Pharmaceutical.stock: Pharmaceutical.stock - item.quantity}, synchronize_session=False
        )
    else:
        updated = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item.pharmaceutical_id).update(
            {Pharmaceutical.stock: Pharmaceutical.stock + item.quantity}, synchronize_session=False
        )
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "报损数量超过当前库存"}
    # 批次台账联动（§3.6 #6）：启用批次管理的药品，报损按 FEFO 冲减批次并写台账
    batch_note = ""
    if item.adjustment_type == "loss":
        from app.models import PharmaceuticalBatch, PharmaceuticalStockLedger

        remaining = item.quantity
        batches = (
            db.query(PharmaceuticalBatch)
            .filter(
                PharmaceuticalBatch.pharmaceutical_id == item.pharmaceutical_id,
                PharmaceuticalBatch.status == 0,
                PharmaceuticalBatch.stock > 0,
            )
            .order_by(
                PharmaceuticalBatch.expiry_date.is_(None),
                PharmaceuticalBatch.expiry_date.asc(),
                PharmaceuticalBatch.batch_id.asc(),
            )
            .with_for_update()
            .all()
        )
        batch_stock = sum(b.stock for b in batches)
        if batch_stock:
            if batch_stock < remaining:
                db.rollback()
                return {"code": 500, "msg": f"批次库存不足：批次合计 {batch_stock} < 报损 {remaining}"}
            deducted_batches = []
            for b in batches:
                if remaining <= 0:
                    break
                cut = min(b.stock, remaining)
                before = b.stock
                b.stock -= cut
                remaining -= cut
                db.add(b)
                db.add(PharmaceuticalStockLedger(
                    pharmaceutical_id=item.pharmaceutical_id,
                    batch_id=b.batch_id,
                    transaction_type="adjustment",
                    quantity=-cut,
                    before_stock=before,
                    after_stock=b.stock,
                    reference_type="inventory_adjustment",
                    reference_id=str(item.adjustment_id),
                    operator_id=current_user.user_id,
                    reason=f"报损审批冲减批次 {b.batch_no}",
                    create_time=datetime.datetime.now(),
                ))
                deducted_batches.append(f"{b.batch_no}×{cut}")
            batch_note = f"；批次冲减：{'、'.join(deducted_batches)}"
    db.commit()
    return {"code": 200, "msg": "success", "msg_detail": batch_note.lstrip("；") if batch_note else None}


@router.post("/pharmacy/inventoryAdjustment/reject")
def reject_inventory_adjustment(
    req: InventoryAdjustmentActionRequest,
    current_user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    item = db.query(InventoryAdjustment).filter(InventoryAdjustment.adjustment_id == req.adjustment_id).first()
    if not item:
        return {"code": 404, "msg": "库存调整单不存在"}
    updated = db.query(InventoryAdjustment).filter(InventoryAdjustment.adjustment_id == item.adjustment_id, InventoryAdjustment.status == 0).update(
        {InventoryAdjustment.status: 2, InventoryAdjustment.approver_id: current_user.user_id, InventoryAdjustment.approve_time: datetime.datetime.now()},
        synchronize_session=False,
    )
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "库存调整单已处理"}
    db.commit()
    return {"code": 200, "msg": "success"}
