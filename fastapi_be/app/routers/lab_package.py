import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, LAB_ROLES, User, require_roles
from app.models import LabPackage
from app.schemas import LabPackageCreateRequest, LabPackageUpdateRequest

router = APIRouter()
LAB_VIEW_ROLES = CLINICAL_ROLES | LAB_ROLES
LAB_MAINTAIN_ROLES = ADMIN_ROLES | {"lab_technician"}


def _serialize(item: LabPackage):
    return {"package_id": item.package_id, "code": item.code, "name": item.name, "category": item.category or "", "items": item.items or "", "price": item.price, "status": item.status, "status_text": "启用" if item.status else "停用"}


@router.get("/labPackage/list")
def list_packages(keyword: str | None = None, current_user: User = Depends(require_roles(*LAB_VIEW_ROLES)), db: Session = Depends(get_db)):
    query = db.query(LabPackage).filter(LabPackage.status == 1).order_by(LabPackage.code)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter((LabPackage.code.like(like)) | (LabPackage.name.like(like)) | (LabPackage.category.like(like)))
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in query.all()]}


@router.post("/labPackage/create")
def create_package(req: LabPackageCreateRequest, current_user: User = Depends(require_roles(*LAB_MAINTAIN_ROLES)), db: Session = Depends(get_db)):
    if db.query(LabPackage).filter(LabPackage.code == req.code.strip().upper()).first():
        return {"code": 500, "msg": "套餐编码已存在"}
    now = datetime.datetime.now()
    item = LabPackage(code=req.code.strip().upper(), name=req.name.strip(), category=req.category.strip(), items=req.items.strip(), price=req.price, status=1, create_time=now, update_time=now)
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.put("/labPackage/update")
def update_package(req: LabPackageUpdateRequest, current_user: User = Depends(require_roles(*LAB_MAINTAIN_ROLES)), db: Session = Depends(get_db)):
    item = db.query(LabPackage).filter(LabPackage.package_id == req.package_id).first()
    if not item:
        return {"code": 500, "msg": "检验套餐不存在"}
    for field in ("code", "name", "category", "items", "price", "status"):
        value = getattr(req, field)
        if value is not None:
            setattr(item, field, value.strip().upper() if field == "code" else value.strip() if isinstance(value, str) else value)
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}
