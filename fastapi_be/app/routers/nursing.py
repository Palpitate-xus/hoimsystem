import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import NURSING_ROLES, get_current_user, require_roles
from app.models import (
    Admission,
    NursingAssessment,
    NursingRecord,
    Patient,
    TemperatureRecord,
    User,
)
from app.schemas import NursingAssessmentCreateRequest, NursingAssessmentUpdateRequest, NursingRecordCreateRequest, TemperatureRecordCreateRequest

router = APIRouter()


def _serialize_assessment(item: NursingAssessment):
    return {"assessment_id": item.assessment_id, "admission_id": item.admission_id, "patient_id": item.patient_id, "patient_name": item.patient.name if item.patient else "", "adl_score": item.adl_score, "pressure_ulcer_risk": item.pressure_ulcer_risk, "fall_risk": item.fall_risk, "consciousness": item.consciousness, "nutrition_risk": item.nutrition_risk, "note": item.note or "", "status": item.status, "status_text": "已完成" if item.status else "草稿", "nurse_name": item.nurse.username if item.nurse else "", "create_time": item.create_time, "update_time": item.update_time}


@router.get("/nursingAssessment/list")
def list_nursing_assessments(admission_id: str | None = None, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    query = db.query(NursingAssessment).order_by(NursingAssessment.create_time.desc())
    if admission_id:
        query = query.filter(NursingAssessment.admission_id == admission_id)
    return {"code": 200, "msg": "success", "data": [_serialize_assessment(item) for item in query.all()]}


@router.post("/nursingAssessment/create")
def create_nursing_assessment(req: NursingAssessmentCreateRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    admission = db.query(Admission).filter(Admission.admission_id == req.admission_id, Admission.patient_id == req.patient_id).first()
    if not admission:
        return {"code": 500, "msg": "在院记录不存在或患者不匹配"}
    active = db.query(NursingAssessment).filter(NursingAssessment.admission_id == req.admission_id, NursingAssessment.status == 0).first()
    if active:
        return {"code": 500, "msg": "该住院患者已有未完成的护理评估"}
    now = datetime.datetime.now()
    item = NursingAssessment(admission_id=req.admission_id, patient_id=req.patient_id, nurse_id=current_user.user_id, adl_score=req.adl_score, pressure_ulcer_risk=req.pressure_ulcer_risk, fall_risk=req.fall_risk, consciousness=req.consciousness, nutrition_risk=req.nutrition_risk, note=req.note.strip(), status=0, create_time=now, update_time=now)
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize_assessment(item)}


@router.put("/nursingAssessment/update")
def update_nursing_assessment(req: NursingAssessmentUpdateRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    item = db.query(NursingAssessment).filter(NursingAssessment.assessment_id == req.assessment_id).first()
    if not item:
        return {"code": 500, "msg": "护理评估不存在"}
    if item.status:
        return {"code": 403, "msg": "已完成护理评估不可修改"}
    if current_user.user_role not in {"admin", "super_admin"} and item.nurse_id != current_user.user_id:
        return {"code": 403, "msg": "无权修改他人的护理评估"}
    for field in ("adl_score", "pressure_ulcer_risk", "fall_risk", "consciousness", "nutrition_risk", "note"):
        value = getattr(req, field)
        if value is not None:
            setattr(item, field, value.strip() if field == "note" else value)
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize_assessment(item)}


@router.post("/nursingAssessment/complete")
def complete_nursing_assessment(req: NursingAssessmentUpdateRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    item = db.query(NursingAssessment).filter(NursingAssessment.assessment_id == req.assessment_id).first()
    if not item:
        return {"code": 500, "msg": "护理评估不存在"}
    if current_user.user_role not in {"admin", "super_admin"} and item.nurse_id != current_user.user_id:
        return {"code": 403, "msg": "无权完成他人的护理评估"}
    if item.status:
        return {"code": 500, "msg": "护理评估已完成"}
    item.status = 1
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize_assessment(item)}


@router.get("/nursingRecord/getList")
def get_nursing_record_list(
    admission_id: str | None = None,
    patient_id: int | None = None,
    current_user: User = Depends(require_roles(*NURSING_ROLES)),
    db: Session = Depends(get_db),
):
    query = db.query(NursingRecord).order_by(NursingRecord.record_time.desc())
    if admission_id:
        query = query.filter(NursingRecord.admission_id == admission_id)
    if patient_id:
        query = query.filter(NursingRecord.patient_id == patient_id)
    records = query.all()
    data = []
    for item in records:
        data.append(
            {
                "record_id": item.record_id,
                "admission_id": item.admission_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "nurse_id": item.nurse_id,
                "nurse_name": item.nurse.name if item.nurse else "",
                "record_time": (item.record_time.strftime("%Y-%m-%d %H:%M:%S") if item.record_time else None) if item.record_time else "",
                "consciousness": item.consciousness or "",
                "temperature": item.temperature,
                "pulse": item.pulse,
                "respiration": item.respiration,
                "blood_pressure": item.blood_pressure or "",
                "spo2": item.spo2,
                "intake": item.intake or "",
                "output": item.output or "",
                "skin_condition": item.skin_condition or "",
                "drainage": item.drainage or "",
                "note": item.note or "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/nursingRecord/create")
def create_nursing_record(
    req: NursingRecordCreateRequest,
    current_user: User = Depends(require_roles(*NURSING_ROLES)),
    db: Session = Depends(get_db),
):
    admission = db.query(Admission).filter(Admission.admission_id == req.admission_id).first()
    if not admission:
        return {"code": 500, "msg": "入院记录不存在"}
    try:
        record_time = datetime.datetime.strptime(req.record_time, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        record_time = datetime.datetime.now()

    record = NursingRecord(
        admission_id=req.admission_id,
        patient_id=req.patient_id,
        nurse_id=current_user.user_id,
        record_time=record_time,
        consciousness=req.consciousness,
        temperature=req.temperature,
        pulse=req.pulse,
        respiration=req.respiration,
        blood_pressure=req.blood_pressure,
        spo2=req.spo2,
        intake=req.intake,
        output=req.output,
        skin_condition=req.skin_condition,
        drainage=req.drainage,
        note=req.note,
        create_time=datetime.datetime.now(),
    )
    db.add(record)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/nursingRecord/delete")
def delete_nursing_record(req: dict, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    record = db.query(NursingRecord).filter(NursingRecord.record_id == req.get("record_id")).first()
    if not record:
        return {"code": 500, "msg": "记录不存在"}
    db.delete(record)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/temperatureRecord/getList")
def get_temperature_record_list(
    admission_id: str | None = None,
    record_date: str | None = None,
    current_user: User = Depends(require_roles(*NURSING_ROLES)),
    db: Session = Depends(get_db),
):
    query = db.query(TemperatureRecord).order_by(TemperatureRecord.record_date.desc(), TemperatureRecord.time_point)
    if admission_id:
        query = query.filter(TemperatureRecord.admission_id == admission_id)
    if record_date:
        try:
            from datetime import date as dt_date

            d = dt_date.fromisoformat(record_date)
            query = query.filter(TemperatureRecord.record_date == d)
        except ValueError:
            pass
    records = query.all()
    data = []
    for item in records:
        data.append(
            {
                "temp_id": item.temp_id,
                "admission_id": item.admission_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "record_date": str(item.record_date) if item.record_date else "",
                "time_point": item.time_point,
                "temperature": item.temperature,
                "pulse": item.pulse,
                "respiration": item.respiration,
                "blood_pressure": item.blood_pressure or "",
                "stool_count": item.stool_count,
                "weight": item.weight,
                "intake": item.intake,
                "output": item.output,
                "note": item.note or "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/temperatureRecord/create")
def create_temperature_record(
    req: TemperatureRecordCreateRequest,
    current_user: User = Depends(require_roles(*NURSING_ROLES)),
    db: Session = Depends(get_db),
):
    admission = db.query(Admission).filter(Admission.admission_id == req.admission_id).first()
    if not admission:
        return {"code": 500, "msg": "入院记录不存在"}
    try:
        from datetime import date as dt_date

        record_date = dt_date.fromisoformat(req.record_date)
    except ValueError:
        return {"code": 500, "msg": "日期格式不正确"}

    # 检查是否已存在同一时间点的记录
    existing = (
        db.query(TemperatureRecord)
        .filter(
            TemperatureRecord.admission_id == req.admission_id,
            TemperatureRecord.record_date == record_date,
            TemperatureRecord.time_point == req.time_point,
        )
        .first()
    )
    if existing:
        # 更新现有记录
        existing.temperature = req.temperature
        existing.pulse = req.pulse
        existing.respiration = req.respiration
        existing.blood_pressure = req.blood_pressure
        existing.stool_count = req.stool_count
        existing.weight = req.weight
        existing.intake = req.intake
        existing.output = req.output
        existing.note = req.note
        db.add(existing)
    else:
        record = TemperatureRecord(
            admission_id=req.admission_id,
            patient_id=req.patient_id,
            record_date=record_date,
            time_point=req.time_point,
            temperature=req.temperature,
            pulse=req.pulse,
            respiration=req.respiration,
            blood_pressure=req.blood_pressure,
            stool_count=req.stool_count,
            weight=req.weight,
            intake=req.intake,
            output=req.output,
            note=req.note,
        )
        db.add(record)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/temperatureRecord/delete")
def delete_temperature_record(req: dict, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    record = db.query(TemperatureRecord).filter(TemperatureRecord.temp_id == req.get("temp_id")).first()
    if not record:
        return {"code": 500, "msg": "记录不存在"}
    db.delete(record)
    db.commit()
    return {"code": 200, "msg": "success"}
