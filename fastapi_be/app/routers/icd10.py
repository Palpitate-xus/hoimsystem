import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, User, require_roles
from app.models import Icd10Diagnosis, Icd10Operation
from app.schemas import Icd10CreateRequest, Icd10UpdateRequest

router = APIRouter()
MAINTAIN_ROLES = {"admin", "super_admin", "director"}


def _list(model, keyword: str | None, db: Session):
    query = db.query(model).filter(model.status == 1).order_by(model.code)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter((model.code.like(like)) | (model.name.like(like)) | (model.category.like(like)))
    return [{"id": item.diagnosis_id if isinstance(item, Icd10Diagnosis) else item.operation_id, "code": item.code, "name": item.name, "category": item.category or "", "status": item.status} for item in query.all()]


def _create(model, req: Icd10CreateRequest, db: Session):
    if db.query(model).filter(model.code == req.code.strip()).first():
        return {"code": 500, "msg": "编码已存在"}
    now = datetime.datetime.now()
    item = model(code=req.code.strip().upper(), name=req.name.strip(), category=req.category.strip(), status=1, create_time=now, update_time=now)
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"id": item.diagnosis_id if isinstance(item, Icd10Diagnosis) else item.operation_id, "code": item.code, "name": item.name, "category": item.category or "", "status": item.status}}


def _update(model, req: Icd10UpdateRequest, db: Session):
    id_field = model.diagnosis_id if model is Icd10Diagnosis else model.operation_id
    item = db.query(model).filter(id_field == req.id).first()
    if not item:
        return {"code": 500, "msg": "编码不存在"}
    for field in ("code", "name", "category", "status"):
        value = getattr(req, field)
        if value is not None:
            new_val = value.strip().upper() if field == "code" else value.strip() if isinstance(value, str) else value
            if field == "code" and new_val != item.code:
                dup = db.query(model).filter(model.code == new_val).first()
                if dup:
                    return {"code": 500, "msg": f"编码 {new_val} 已存在"}
            setattr(item, field, new_val)
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/icd10/diagnosis/list")
def list_diagnosis(keyword: str | None = None, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    return {"code": 200, "msg": "success", "data": _list(Icd10Diagnosis, keyword, db)}


@router.post("/icd10/diagnosis/create")
def create_diagnosis(req: Icd10CreateRequest, current_user: User = Depends(require_roles(*MAINTAIN_ROLES)), db: Session = Depends(get_db)):
    return _create(Icd10Diagnosis, req, db)


@router.put("/icd10/diagnosis/update")
def update_diagnosis(req: Icd10UpdateRequest, current_user: User = Depends(require_roles(*MAINTAIN_ROLES)), db: Session = Depends(get_db)):
    return _update(Icd10Diagnosis, req, db)


@router.get("/icd10/operation/list")
def list_operation(keyword: str | None = None, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    return {"code": 200, "msg": "success", "data": _list(Icd10Operation, keyword, db)}


@router.post("/icd10/operation/create")
def create_operation(req: Icd10CreateRequest, current_user: User = Depends(require_roles(*MAINTAIN_ROLES)), db: Session = Depends(get_db)):
    return _create(Icd10Operation, req, db)


@router.put("/icd10/operation/update")
def update_operation(req: Icd10UpdateRequest, current_user: User = Depends(require_roles(*MAINTAIN_ROLES)), db: Session = Depends(get_db)):
    return _update(Icd10Operation, req, db)
