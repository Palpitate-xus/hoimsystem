import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, User, require_roles
from app.models import Admission, Doctor, InpatientCharge, MedicalRecordHome
from app.schemas import MedicalRecordHomeCreateRequest, MedicalRecordHomeUpdateRequest

router = APIRouter()


def _total_fee(db: Session, admission_id: str) -> float:
    total = db.query(func.sum(InpatientCharge.total_amount)).filter(InpatientCharge.admission_id == admission_id, InpatientCharge.status != 2).scalar() or 0
    return round(float(total), 2)


def _serialize(item: MedicalRecordHome):
    return {
        "home_id": item.home_id,
        "admission_id": item.admission_id,
        "admission_no": item.admission.admission_no if item.admission else "",
        "patient_id": item.patient_id,
        "patient_name": item.patient.name if item.patient else "",
        "doctor_name": item.doctor.name if item.doctor else "",
        "admission_diagnosis": item.admission_diagnosis,
        "discharge_diagnosis": item.discharge_diagnosis or "",
        "other_diagnosis": item.other_diagnosis or "",
        "operation_summary": item.operation_summary or "",
        "complication": item.complication or "",
        "discharge_status": item.discharge_status,
        "discharge_status_text": ["治愈", "好转", "未愈", "死亡", "转院"][item.discharge_status] if item.discharge_status is not None and 0 <= item.discharge_status <= 4 else "",
        "total_fee": round(float(item.total_fee or 0), 2),
        "status": item.status,
        "status_text": {0: "草稿", 1: "已提交", 2: "已归档"}.get(item.status, "未知"),
        "create_time": item.create_time,
        "update_time": item.update_time,
        "submit_time": item.submit_time,
    }


def _owns(item: MedicalRecordHome, current_user: User, db: Session) -> bool:
    if current_user.user_role in ADMIN_ROLES:
        return True
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id, Doctor.doctor_id == item.doctor_id).first()
    return doctor is not None


@router.get("/medicalRecordHome/admissions")
def list_medical_record_admissions(current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    query = (
        db.query(Admission, MedicalRecordHome)
        .outerjoin(MedicalRecordHome, MedicalRecordHome.admission_id == Admission.admission_id)
        .options(joinedload(Admission.patient), joinedload(Admission.doctor))
        .filter(Admission.status.in_([1, 2]))
        .order_by(Admission.create_time.desc())
    )
    if current_user.user_role not in ADMIN_ROLES:
        doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
        query = query.filter(Admission.doctor_id == (doctor.doctor_id if doctor else -1))
    data = []
    for item, existing in query.all():
        data.append({
            "admission_id": item.admission_id,
            "admission_no": item.admission_no,
            "patient_id": item.patient_id,
            "patient_name": item.patient.name if item.patient else "",
            "doctor_name": item.doctor.name if item.doctor else "",
            "admission_diagnosis": item.admission_diagnosis or "",
            "status": item.status,
            "status_text": "在院" if item.status == 1 else "已出院",
            "home_id": existing.home_id if existing else None,
            "home_status": existing.status if existing else None,
        })
    return {"code": 200, "msg": "success", "data": data}


@router.get("/medicalRecordHome/list")
def list_medical_record_homes(admission_id: str | None = None, status: int | None = None, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    query = db.query(MedicalRecordHome).options(
        joinedload(MedicalRecordHome.admission),
        joinedload(MedicalRecordHome.patient),
        joinedload(MedicalRecordHome.doctor),
    ).order_by(MedicalRecordHome.update_time.desc())
    if admission_id:
        query = query.filter(MedicalRecordHome.admission_id == admission_id)
    if status is not None:
        query = query.filter(MedicalRecordHome.status == status)
    if current_user.user_role not in ADMIN_ROLES:
        doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
        query = query.filter(MedicalRecordHome.doctor_id == (doctor.doctor_id if doctor else -1))
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in query.all()]}


@router.post("/medicalRecordHome/create")
def create_medical_record_home(req: MedicalRecordHomeCreateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    admission = db.query(Admission).filter(Admission.admission_id == req.admission_id).first()
    if not admission:
        return {"code": 500, "msg": "入院记录不存在"}
    if db.query(MedicalRecordHome).filter(MedicalRecordHome.admission_id == req.admission_id).first():
        return {"code": 500, "msg": "该住院患者已有病案首页"}
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    now = datetime.datetime.now()
    item = MedicalRecordHome(admission_id=req.admission_id, patient_id=admission.patient_id, doctor_id=doctor.doctor_id if doctor else admission.doctor_id, admission_diagnosis=req.admission_diagnosis.strip(), discharge_diagnosis=req.discharge_diagnosis.strip(), other_diagnosis=req.other_diagnosis.strip(), operation_summary=req.operation_summary.strip(), complication=req.complication.strip(), discharge_status=req.discharge_status, total_fee=_total_fee(db, req.admission_id), status=0, creator_id=current_user.user_id, create_time=now, update_time=now)
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.put("/medicalRecordHome/update")
def update_medical_record_home(req: MedicalRecordHomeUpdateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    item = db.query(MedicalRecordHome).filter(MedicalRecordHome.home_id == req.home_id).first()
    if not item:
        return {"code": 500, "msg": "病案首页不存在"}
    if not _owns(item, current_user, db):
        return {"code": 403, "msg": "无权修改该病案首页"}
    if item.status != 0:
        return {"code": 403, "msg": "已提交或已归档病案首页不可修改"}
    for field in ("admission_diagnosis", "discharge_diagnosis", "other_diagnosis", "operation_summary", "complication", "discharge_status"):
        value = getattr(req, field)
        if value is not None:
            setattr(item, field, value.strip() if isinstance(value, str) else value)
    item.total_fee = _total_fee(db, item.admission_id)
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.post("/medicalRecordHome/submit")
def submit_medical_record_home(req: MedicalRecordHomeUpdateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    item = db.query(MedicalRecordHome).filter(MedicalRecordHome.home_id == req.home_id).first()
    if not item:
        return {"code": 500, "msg": "病案首页不存在"}
    if not _owns(item, current_user, db):
        return {"code": 403, "msg": "无权提交该病案首页"}
    if item.status != 0:
        return {"code": 500, "msg": "当前病案首页不能重复提交"}
    if not item.discharge_diagnosis.strip():
        return {"code": 500, "msg": "请先填写出院诊断"}
    now = datetime.datetime.now()
    item.status = 1
    item.submit_time = now
    item.update_time = now
    item.total_fee = _total_fee(db, item.admission_id)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}
