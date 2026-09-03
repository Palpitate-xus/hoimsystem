import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CASHIER_ROLES, User, require_roles
from app.models import ChargeItem
from app.schemas import ChargeItemCreateRequest, ChargeItemIdRequest, ChargeItemUpdateRequest

router = APIRouter()


def _serialize(item: ChargeItem):
    return {"id": item.item_id, "item_id": item.item_id, "code": item.code, "name": item.name, "category": item.category, "price": item.price, "status": item.status, "status_text": "启用" if item.status else "停用", "note": item.note or "", "creator_name": item.creator.username if item.creator else "", "create_time": item.create_time, "update_time": item.update_time}


@router.get("/chargeItem/list")
def list_charge_items(current_user: User = Depends(require_roles(*CASHIER_ROLES)), db: Session = Depends(get_db)):
    items = db.query(ChargeItem).order_by(ChargeItem.status.desc(), ChargeItem.item_id.desc()).all()
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in items]}


@router.post("/chargeItem/create")
def create_charge_item(req: ChargeItemCreateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    if db.query(ChargeItem).filter(ChargeItem.code == req.code.strip()).first():
        return {"code": 500, "msg": "收费项目编码已存在"}
    now = datetime.datetime.now()
    item = ChargeItem(code=req.code.strip(), name=req.name.strip(), category=req.category.strip(), price=req.price, note=req.note.strip(), status=1, creator_id=current_user.user_id, create_time=now, update_time=now)
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.put("/chargeItem/update")
def update_charge_item(req: ChargeItemUpdateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    item = db.query(ChargeItem).filter(ChargeItem.item_id == req.item_id).first()
    if not item:
        return {"code": 500, "msg": "收费项目不存在"}
    duplicate = db.query(ChargeItem).filter(ChargeItem.code == req.code.strip(), ChargeItem.item_id != req.item_id).first()
    if duplicate:
        return {"code": 500, "msg": "收费项目编码已存在"}
    item.code = req.code.strip()
    item.name = req.name.strip()
    item.category = req.category.strip()
    item.price = req.price
    item.note = req.note.strip()
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.post("/chargeItem/toggle")
def toggle_charge_item(req: ChargeItemIdRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    item = db.query(ChargeItem).filter(ChargeItem.item_id == req.item_id).first()
    if not item:
        return {"code": 500, "msg": "收费项目不存在"}
    item.status = 0 if item.status else 1
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success"}
