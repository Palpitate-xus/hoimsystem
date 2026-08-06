import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import LAB_ROLES, User, require_roles
from app.models import LabQcRecord
from app.schemas import LabQcRecordCreateRequest

router = APIRouter()


def _serialize(item: LabQcRecord):
    return {"qc_id": item.qc_id, "qc_name": item.qc_name, "level": item.level, "target_value": item.target_value, "measured_value": item.measured_value, "unit": item.unit or "", "pass_flag": item.pass_flag, "pass_text": "通过" if item.pass_flag else "不通过", "remark": item.remark or "", "operator_name": item.operator.username if item.operator else "", "qc_time": item.qc_time}


@router.get("/labQc/list")
def list_qc(qc_name: str | None = None, current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    query = db.query(LabQcRecord).order_by(LabQcRecord.qc_time.desc())
    if qc_name:
        query = query.filter(LabQcRecord.qc_name.like(f"%{qc_name.strip()}%"))
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in query.all()]}


@router.post("/labQc/create")
def create_qc(req: LabQcRecordCreateRequest, current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    tolerance = abs(req.target_value) * 0.1 if req.target_value else 0.1
    passed = 1 if abs(req.measured_value - req.target_value) <= tolerance else 0
    item = LabQcRecord(qc_name=req.qc_name.strip(), level=req.level.strip(), target_value=req.target_value, measured_value=req.measured_value, unit=req.unit.strip(), pass_flag=passed, remark=req.remark.strip(), operator_id=current_user.user_id, qc_time=datetime.datetime.now())
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.get("/labQc/summary")
def qc_summary(current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    total = db.query(func.count(LabQcRecord.qc_id)).scalar() or 0
    failed = db.query(func.count(LabQcRecord.qc_id)).filter(LabQcRecord.pass_flag == 0).scalar() or 0
    return {"code": 200, "msg": "success", "data": {"total": total, "failed": failed, "pass_rate": round((total - failed) / total * 100, 1) if total else 0}}
