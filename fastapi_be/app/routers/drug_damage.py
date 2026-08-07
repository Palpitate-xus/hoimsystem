import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, PHARMACY_ROLES, User, require_roles
from app.models import DrugDamage, Pharmaceutical

router = APIRouter()


def _serialize(item: DrugDamage):
    return {
        "damage_id": item.damage_id,
        "pharmaceutical_id": item.pharmaceutical_id,
        "pharmaceutical_name": item.pharmaceutical.name if item.pharmaceutical else "",
        "quantity": item.quantity,
        "damage_type": item.damage_type,
        "batch_no": item.batch_no or "",
        "reason": item.reason,
        "status": item.status,
        "status_text": {0: "待审批", 1: "已通过", 2: "已驳回"}.get(item.status, ""),
        "applicant": item.applicant.username if item.applicant else "",
        "approver": item.approver.username if item.approver else "",
        "create_time": item.create_time,
        "approve_time": item.approve_time,
    }


@router.get("/pharmacy/drugDamage/list")
def list_drug_damage(status: int | None = None, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    query = db.query(DrugDamage).order_by(DrugDamage.create_time.desc())
    if status is not None:
        query = query.filter(DrugDamage.status == status)
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in query.all()]}


@router.post("/pharmacy/drugDamage/create")
def create_drug_damage(req: dict, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    pharmaceutical = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.get("pharmaceutical_id"), Pharmaceutical.status == 0).first()
    if not pharmaceutical:
        return {"code": 404, "msg": "药品不存在或已停用"}
    try:
        quantity = int(req.get("quantity", 0))
    except (TypeError, ValueError):
        quantity = 0
    if quantity <= 0:
        return {"code": 400, "msg": "报损数量必须大于0"}
    if quantity > pharmaceutical.stock:
        return {"code": 400, "msg": "报损数量不能超过库存"}
    damage_type = req.get("damage_type", "other")
    if damage_type not in {"expired", "broken", "contaminated", "other"}:
        return {"code": 400, "msg": "报损类型不合法"}
    reason = str(req.get("reason", "")).strip()
    if not reason:
        return {"code": 400, "msg": "报损原因不能为空"}
    item = DrugDamage(
        pharmaceutical_id=pharmaceutical.pharmaceutical_id,
        quantity=quantity,
        damage_type=damage_type,
        batch_no=str(req.get("batch_no", "")).strip()[:60],
        reason=reason[:300],
        applicant_id=current_user.user_id,
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "报损申请已提交", "data": _serialize(item)}


@router.post("/pharmacy/drugDamage/approve")
def approve_drug_damage(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    item = db.query(DrugDamage).filter(DrugDamage.damage_id == req.get("damage_id"), DrugDamage.status == 0).first()
    if not item:
        return {"code": 404, "msg": "待审批报损记录不存在"}
    updated = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item.pharmaceutical_id, Pharmaceutical.stock >= item.quantity).update({Pharmaceutical.stock: Pharmaceutical.stock - item.quantity}, synchronize_session=False)
    if updated != 1:
        db.rollback()
        return {"code": 400, "msg": "当前库存不足，无法审批"}
    item.status = 1
    item.approver_id = current_user.user_id
    item.approve_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "报损已审批", "data": _serialize(item)}


@router.post("/pharmacy/drugDamage/reject")
def reject_drug_damage(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    item = db.query(DrugDamage).filter(DrugDamage.damage_id == req.get("damage_id"), DrugDamage.status == 0).first()
    if not item:
        return {"code": 404, "msg": "待审批报损记录不存在"}
    item.status = 2
    item.approver_id = current_user.user_id
    item.approve_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "报损已驳回", "data": _serialize(item)}
