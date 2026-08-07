import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, NURSING_ROLES, User, require_roles
from app.models import Patient, PatientAllergy
from app.schemas import PatientAllergyCreateRequest, PatientAllergyIdRequest, PatientAllergyUpdateRequest

router = APIRouter()


def _serialize(item: PatientAllergy):
    return {
        "id": item.allergy_id,
        "allergy_id": item.allergy_id,
        "patient_id": item.patient_id,
        "patient_name": item.patient.name if item.patient else "",
        "allergen": item.allergen,
        "reaction": item.reaction,
        "severity": item.severity,
        "severity_text": {1: "轻度", 2: "中度", 3: "重度"}.get(item.severity, "未知"),
        "note": item.note or "",
        "status": item.status,
        "status_text": "有效" if item.status else "已停用",
        "reporter_name": item.reporter.username if item.reporter else "",
        "create_time": item.create_time,
        "update_time": item.update_time,
    }


def _sync_patient_history(patient: Patient, db: Session):
    active = db.query(PatientAllergy).filter(PatientAllergy.patient_id == patient.patient_id, PatientAllergy.status == 1).order_by(PatientAllergy.allergy_id).all()
    structured = [f"{item.allergen}: {item.reaction}" for item in active]
    patient.allergy_history = "；".join(structured)[:200]


@router.get("/allergy/list")
def list_allergies(patient_id: int | None = None, current_user: User = Depends(require_roles(*(CLINICAL_ROLES | NURSING_ROLES))), db: Session = Depends(get_db)):
    query = db.query(PatientAllergy).order_by(PatientAllergy.status.desc(), PatientAllergy.update_time.desc())
    if patient_id:
        query = query.filter(PatientAllergy.patient_id == patient_id)
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in query.all()]}


@router.post("/allergy/create")
def create_allergy(req: PatientAllergyCreateRequest, current_user: User = Depends(require_roles(*(CLINICAL_ROLES | NURSING_ROLES))), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.patient_id).first()
    if not patient:
        return {"code": 500, "msg": "患者不存在"}
    now = datetime.datetime.now()
    item = PatientAllergy(patient_id=req.patient_id, allergen=req.allergen.strip(), reaction=req.reaction.strip(), severity=req.severity, note=req.note.strip(), status=1, reporter_id=current_user.user_id, create_time=now, update_time=now)
    db.add(item)
    db.flush()
    _sync_patient_history(patient, db)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.put("/allergy/update")
def update_allergy(req: PatientAllergyUpdateRequest, current_user: User = Depends(require_roles(*(CLINICAL_ROLES | NURSING_ROLES))), db: Session = Depends(get_db)):
    item = db.query(PatientAllergy).filter(PatientAllergy.allergy_id == req.allergy_id).first()
    if not item:
        return {"code": 500, "msg": "过敏标识不存在"}
    if item.patient_id != req.patient_id:
        return {"code": 500, "msg": "不允许变更过敏标识所属患者"}
    item.allergen = req.allergen.strip()
    item.reaction = req.reaction.strip()
    item.severity = req.severity
    item.note = req.note.strip()
    item.update_time = datetime.datetime.now()
    _sync_patient_history(item.patient, db)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.post("/allergy/disable")
def disable_allergy(req: PatientAllergyIdRequest, current_user: User = Depends(require_roles(*(CLINICAL_ROLES | NURSING_ROLES))), db: Session = Depends(get_db)):
    item = db.query(PatientAllergy).filter(PatientAllergy.allergy_id == req.allergy_id, PatientAllergy.status == 1).first()
    if not item:
        return {"code": 500, "msg": "有效过敏标识不存在"}
    item.status = 0
    item.update_time = datetime.datetime.now()
    db.flush()
    _sync_patient_history(item.patient, db)
    db.commit()
    return {"code": 200, "msg": "success"}
