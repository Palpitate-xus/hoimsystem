import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import PHARMACY_ROLES, User, get_current_user, require_roles
from app.models import Consumable
from app.pagination import paginate

router = APIRouter()


@router.get("/consumable/getList")
def get_consumable_list(keyword: str | None = None, page: int | None = None, page_size: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Consumable)
    items, total = paginate(query, page, page_size)
    data = []
    for item in items:
        data.append(
            {
                "consumable_id": item.consumable_id,
                "name": item.name,
                "category": item.category,
                "stock": item.stock,
                "unit": item.unit,
                "price": round(item.price, 2) if item.price else 0,
                "supplier": item.supplier,
                "remark": item.remark,
                "status": item.status,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/consumable/create")
def create_consumable(req: dict, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    c = Consumable(
        name=req.get("name", ""),
        category=req.get("category", ""),
        stock=req.get("stock", 0),
        unit=req.get("unit", ""),
        price=req.get("price", 0),
        supplier=req.get("supplier", ""),
        remark=req.get("remark", ""),
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(c)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/consumable/update")
def update_consumable(req: dict, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    c = db.query(Consumable).filter(Consumable.consumable_id == req.get("consumable_id")).first()
    if not c:
        return {"code": 500, "msg": "耗材不存在"}
    c.name = req.get("name", c.name)
    c.category = req.get("category", c.category)
    c.stock = req.get("stock", c.stock)
    c.unit = req.get("unit", c.unit)
    c.price = req.get("price", c.price)
    c.supplier = req.get("supplier", c.supplier)
    c.remark = req.get("remark", c.remark)
    c.status = req.get("status", c.status)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/consumable/delete")
def delete_consumable(req: dict, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    c = db.query(Consumable).filter(Consumable.consumable_id == req.get("consumable_id")).first()
    if not c:
        return {"code": 500, "msg": "耗材不存在"}
    db.delete(c)
    db.commit()
    return {"code": 200, "msg": "success"}
