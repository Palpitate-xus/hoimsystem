import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, NURSING_ROLES, User, require_roles
from app.models import EmergencyObservation, EmergencyRescueEvent, EmergencyTriage, Patient
from app.schemas import EmergencyObservationCreateRequest, EmergencyObservationUpdateRequest, EmergencyRescueEventCreateRequest, EmergencyTriageCreateRequest, EmergencyTriageUpdateRequest

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


@router.post("/emergency/rescue/create")
def create_rescue_event(req: EmergencyRescueEventCreateRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    triage = db.query(EmergencyTriage).filter(EmergencyTriage.triage_id == req.triage_id, EmergencyTriage.status != 3).first()
    if not triage:
        return {"code": 500, "msg": "有效分诊记录不存在"}
    try:
        event_time = datetime.datetime.strptime(req.event_time, "%Y-%m-%d %H:%M:%S") if req.event_time else datetime.datetime.now()
    except ValueError:
        return {"code": 500, "msg": "时间格式必须为 YYYY-MM-DD HH:MM:SS"}
    item = EmergencyRescueEvent(triage_id=req.triage_id, event_type=req.event_type.strip(), description=req.description.strip(), medication=req.medication.strip(), event_time=event_time, operator_id=current_user.user_id)
    db.add(item)
    if triage.status == 0:
        triage.status = 1
        triage.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": {"event_id": item.event_id}}


@router.get("/emergency/rescue/list")
def list_rescue_events(triage_id: str | None = None, current_user: User = Depends(require_roles(*(NURSING_ROLES | CLINICAL_ROLES))), db: Session = Depends(get_db)):
    query = db.query(EmergencyRescueEvent).order_by(EmergencyRescueEvent.event_time.asc())
    if triage_id:
        query = query.filter(EmergencyRescueEvent.triage_id == triage_id)
    data = []
    for item in query.all():
        data.append({"event_id": item.event_id, "triage_id": item.triage_id, "patient_name": item.triage.patient.name if item.triage and item.triage.patient else "", "event_type": item.event_type, "description": item.description, "medication": item.medication or "", "event_time": item.event_time, "operator_name": item.operator.username if item.operator else ""})
    return {"code": 200, "msg": "success", "data": data}


def _serialize_observation(item: EmergencyObservation):
    return {
        "observation_id": item.observation_id,
        "triage_id": item.triage_id,
        "patient_id": item.triage.patient_id if item.triage else None,
        "patient_name": item.triage.patient.name if item.triage and item.triage.patient else "",
        "start_time": item.start_time,
        "end_time": item.end_time,
        "condition": item.condition,
        "medical_advice": item.medical_advice or "",
        "fee_amount": round(float(item.fee_amount or 0), 2),
        "fee_status": item.fee_status,
        "fee_status_text": "已计费" if item.fee_status else "待计费",
        "status": item.status,
        "status_text": {1: "留观中", 2: "已结束", 3: "已取消"}.get(item.status, "未知"),
        "operator_name": item.operator.username if item.operator else "",
        "update_time": item.update_time,
    }


@router.post("/emergency/observation/create")
def create_observation(req: EmergencyObservationCreateRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    triage = db.query(EmergencyTriage).filter(EmergencyTriage.triage_id == req.triage_id, EmergencyTriage.status != 3).first()
    if not triage:
        return {"code": 500, "msg": "有效分诊记录不存在"}
    active = db.query(EmergencyObservation).filter(EmergencyObservation.triage_id == req.triage_id, EmergencyObservation.status == 1).first()
    if active:
        return {"code": 500, "msg": "该患者已有进行中的留观记录"}
    now = datetime.datetime.now()
    item = EmergencyObservation(triage_id=req.triage_id, start_time=now, condition=req.condition.strip(), medical_advice=req.medical_advice.strip(), fee_amount=req.fee_amount, fee_status=0, status=1, operator_id=current_user.user_id, update_time=now)
    db.add(item)
    if triage.status == 0:
        triage.status = 1
        triage.update_time = now
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize_observation(item)}


@router.get("/emergency/observation/list")
def list_observations(triage_id: str | None = None, status: int | None = None, current_user: User = Depends(require_roles(*(NURSING_ROLES | CLINICAL_ROLES))), db: Session = Depends(get_db)):
    query = db.query(EmergencyObservation).order_by(EmergencyObservation.status.asc(), EmergencyObservation.start_time.desc())
    if triage_id:
        query = query.filter(EmergencyObservation.triage_id == triage_id)
    if status is not None:
        query = query.filter(EmergencyObservation.status == status)
    return {"code": 200, "msg": "success", "data": [_serialize_observation(item) for item in query.all()]}


@router.put("/emergency/observation/update")
def update_observation(req: EmergencyObservationUpdateRequest, current_user: User = Depends(require_roles(*(NURSING_ROLES | CLINICAL_ROLES))), db: Session = Depends(get_db)):
    item = db.query(EmergencyObservation).filter(EmergencyObservation.observation_id == req.observation_id).first()
    if not item:
        return {"code": 500, "msg": "留观记录不存在"}
    if item.status in (2, 3) and req.status is not None:
        return {"code": 500, "msg": "已结束或已取消的留观记录不能再次变更状态"}
    if req.status is not None and req.status == 1 and item.status != 1:
        return {"code": 500, "msg": "留观记录状态不能恢复为进行中"}
    if req.condition is not None:
        item.condition = req.condition.strip()
    if req.medical_advice is not None:
        item.medical_advice = req.medical_advice.strip()
    if req.fee_amount is not None:
        item.fee_amount = req.fee_amount
    if req.fee_status is not None:
        item.fee_status = req.fee_status
    if req.status is not None:
        item.status = req.status
        if req.status in (2, 3):
            item.end_time = datetime.datetime.now()
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize_observation(item)}
