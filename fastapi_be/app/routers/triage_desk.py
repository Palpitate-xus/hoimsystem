import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Patient, TriageRecord, User

router = APIRouter()


@router.post("/triageDesk/create")
def create_triage_record(req: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """创建分诊记录"""
    identity = req.get("identity")
    patient = db.query(Patient).filter(Patient.identity == identity).first()
    if not patient:
        return {"code": 500, "msg": "病人信息不存在，请先注册"}

    record = TriageRecord(
        patient_id=patient.patient_id,
        nurse_id=current_user.user_id,
        symptom=req.get("symptom", ""),
        level=req.get("level", 3),
        department_id=req.get("department_id"),
        temperature=req.get("temperature"),
        blood_pressure_systolic=req.get("blood_pressure_systolic"),
        blood_pressure_diastolic=req.get("blood_pressure_diastolic"),
        pulse=req.get("pulse"),
        status=0,
        note=req.get("note", ""),
        create_time=datetime.datetime.now(),
    )
    db.add(record)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"triage_record_id": record.triage_record_id}}


@router.get("/triageDesk/getList")
def get_triage_list(level: int | None = None, status: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """分诊记录列表，按级别排序（危急优先）"""
    query = db.query(TriageRecord)
    if level:
        query = query.filter(TriageRecord.level == level)
    if status is not None:
        query = query.filter(TriageRecord.status == status)
    records = query.order_by(TriageRecord.level.asc(), TriageRecord.create_time.asc()).all()
    data = []
    for item in records:
        data.append(
            {
                "triage_record_id": item.triage_record_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "patient_identity": item.patient.identity if item.patient else "",
                "nurse_name": item.nurse.username if item.nurse else "",
                "symptom": item.symptom,
                "level": item.level,
                "level_text": {1: "危急", 2: "急症", 3: "普通", 4: "非急"}.get(item.level, "未知"),
                "department_id": item.department_id,
                "department_name": item.department.name if item.department else "",
                "temperature": item.temperature,
                "blood_pressure": f"{item.blood_pressure_systolic}/{item.blood_pressure_diastolic}" if item.blood_pressure_systolic else "",
                "pulse": item.pulse,
                "status": item.status,
                "status_text": {0: "待就诊", 1: "已就诊", 2: "已转诊", 3: "已取消"}.get(item.status, ""),
                "note": item.note,
                "create_time": str(item.create_time),
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/triageDesk/updateStatus")
def update_triage_status(req: dict, db: Session = Depends(get_db)):
    """更新分诊状态"""
    record = db.query(TriageRecord).filter(TriageRecord.triage_record_id == req.get("triage_record_id")).first()
    if not record:
        return {"code": 500, "msg": "分诊记录不存在"}
    record.status = req.get("status")
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/triageDesk/update")
def update_triage_record(req: dict, db: Session = Depends(get_db)):
    """修改分诊记录"""
    record = db.query(TriageRecord).filter(TriageRecord.triage_record_id == req.get("triage_record_id")).first()
    if not record:
        return {"code": 500, "msg": "分诊记录不存在"}
    if "symptom" in req:
        record.symptom = req["symptom"]
    if "level" in req:
        record.level = req["level"]
    if "department_id" in req:
        record.department_id = req["department_id"]
    if "temperature" in req:
        record.temperature = req["temperature"]
    if "blood_pressure_systolic" in req:
        record.blood_pressure_systolic = req["blood_pressure_systolic"]
    if "blood_pressure_diastolic" in req:
        record.blood_pressure_diastolic = req["blood_pressure_diastolic"]
    if "pulse" in req:
        record.pulse = req["pulse"]
    if "note" in req:
        record.note = req["note"]
    db.commit()
    return {"code": 200, "msg": "success"}
