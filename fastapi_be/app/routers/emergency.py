import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, NURSING_ROLES, User, require_roles
from app.models import EmergencyTriage, Patient
from app.schemas import EmergencyTriageCreateRequest, EmergencyTriageUpdateRequest

router = APIRouter()


def _serialize(item: EmergencyTriage):
    return {
        "id": item.triage_id,
        "triage_id": item.triage_id,
        "patient_id": item.patient_id,
        "patient_name": item.patient.name if item.patient else "",
        "triage_level": item.triage_level,
        "triage_level_text": {1: "一级·立即", 2: "二级·紧急", 3: "三级·一般", 4: "四级·非急"}.get(item.triage_level, "未知"),
        "chief_complaint": item.chief_complaint,
        "vital_signs": item.vital_signs or "",
        "green_channel": item.green_channel,
        "status": item.status,
        "status_text": {0: "待分诊", 1: "处理中", 2: "已完成", 3: "已取消"}.get(item.status, "未知"),
        "nurse_name": item.nurse.username if item.nurse else "",
        "create_time": item.create_time,
        "update_time": item.update_time,
    }


@router.post("/emergency/triage/create")
def create_triage(req: EmergencyTriageCreateRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    if not db.query(Patient).filter(Patient.patient_id == req.patient_id).first():
        return {"code": 500, "msg": "患者不存在"}
    now = datetime.datetime.now()
    item = EmergencyTriage(patient_id=req.patient_id, triage_level=req.triage_level, chief_complaint=req.chief_complaint.strip(), vital_signs=req.vital_signs.strip(), green_channel=req.green_channel, status=0, nurse_id=current_user.user_id, create_time=now, update_time=now)
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.get("/emergency/triage/list")
def list_triage(current_user: User = Depends(require_roles(*(NURSING_ROLES | CLINICAL_ROLES))), db: Session = Depends(get_db)):
    items = db.query(EmergencyTriage).order_by(EmergencyTriage.triage_level.asc(), EmergencyTriage.create_time.asc()).all()
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in items]}


@router.put("/emergency/triage/update")
def update_triage(req: EmergencyTriageUpdateRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    item = db.query(EmergencyTriage).filter(EmergencyTriage.triage_id == req.triage_id).first()
    if not item:
        return {"code": 500, "msg": "分诊记录不存在"}
    if req.triage_level is not None:
        item.triage_level = req.triage_level
    if req.green_channel is not None:
        item.green_channel = req.green_channel
    if req.status is not None:
        item.status = req.status
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}
