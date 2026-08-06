import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, User, require_roles
from app.models import DiagnosisTemplate, Doctor
from app.schemas import DiagnosisTemplateCreateRequest, DiagnosisTemplateIdRequest, DiagnosisTemplateUpdateRequest

router = APIRouter()


def _doctor(current_user: User, db: Session):
    return db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()


def _serialize(item: DiagnosisTemplate):
    return {"id": item.template_id, "template_id": item.template_id, "code": item.code, "name": item.name, "create_time": item.create_time, "update_time": item.update_time}


@router.get("/diagnosisTemplate/list")
def list_diagnosis_templates(current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    doctor = _doctor(current_user, db)
    if not doctor:
        return {"code": 500, "msg": "医生信息不存在", "data": []}
    items = db.query(DiagnosisTemplate).filter(DiagnosisTemplate.doctor_id == doctor.doctor_id).order_by(DiagnosisTemplate.template_id.desc()).all()
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in items]}


@router.post("/diagnosisTemplate/create")
def create_diagnosis_template(req: DiagnosisTemplateCreateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    doctor = _doctor(current_user, db)
    if not doctor:
        return {"code": 500, "msg": "医生信息不存在"}
    now = datetime.datetime.now()
    item = DiagnosisTemplate(doctor_id=doctor.doctor_id, code=req.code.strip().upper(), name=req.name.strip(), create_time=now, update_time=now)
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.put("/diagnosisTemplate/update")
def update_diagnosis_template(req: DiagnosisTemplateUpdateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    doctor = _doctor(current_user, db)
    item = db.query(DiagnosisTemplate).filter(DiagnosisTemplate.template_id == req.template_id, DiagnosisTemplate.doctor_id == doctor.doctor_id if doctor else False).first()
    if not item:
        return {"code": 404, "msg": "诊断模板不存在"}
    item.code = req.code.strip().upper()
    item.name = req.name.strip()
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.post("/diagnosisTemplate/delete")
def delete_diagnosis_template(req: DiagnosisTemplateIdRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    doctor = _doctor(current_user, db)
    item = db.query(DiagnosisTemplate).filter(DiagnosisTemplate.template_id == req.template_id, DiagnosisTemplate.doctor_id == doctor.doctor_id if doctor else False).first()
    if not item:
        return {"code": 404, "msg": "诊断模板不存在"}
    db.delete(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/diagnosisTemplate/apply")
def apply_diagnosis_template(req: DiagnosisTemplateIdRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    doctor = _doctor(current_user, db)
    item = db.query(DiagnosisTemplate).filter(DiagnosisTemplate.template_id == req.template_id, DiagnosisTemplate.doctor_id == doctor.doctor_id if doctor else False).first()
    if not item:
        return {"code": 404, "msg": "诊断模板不存在"}
    return {"code": 200, "msg": "success", "data": {"code": item.code, "name": item.name}}
