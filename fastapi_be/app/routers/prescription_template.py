import datetime
import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, User, require_roles
from app.models import Doctor, Pharmaceutical, PrescriptionTemplate
from app.schemas import PrescriptionTemplateCreateRequest, PrescriptionTemplateIdRequest, PrescriptionTemplateUpdateRequest

router = APIRouter()


def _doctor(current_user: User, db: Session):
    return db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()


def _normalize_items(items, db: Session):
    if not items:
        return None, "模板至少需要一项药品"
    normalized = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            return None, "药品明细格式错误"
        try:
            pharmaceutical_id = int(item.get("id", item.get("pharmaceutical_id")))
            number = int(item.get("number", 0))
        except (TypeError, ValueError):
            return None, "药品和数量必须是有效数字"
        if pharmaceutical_id in seen:
            return None, "模板中不能重复添加同一药品"
        if number <= 0:
            return None, "药品数量必须大于0"
        pharmaceutical = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == pharmaceutical_id).first()
        if not pharmaceutical:
            return None, "药品不存在"
        seen.add(pharmaceutical_id)
        normalized.append({"id": pharmaceutical_id, "number": number, "name": pharmaceutical.name})
    return normalized, None


def _serialize(item: PrescriptionTemplate):
    return {
        "id": item.template_id,
        "template_id": item.template_id,
        "name": item.name,
        "items": json.loads(item.items),
        "create_time": item.create_time,
        "update_time": item.update_time,
    }


@router.get("/prescriptionTemplate/list")
def list_prescription_templates(
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    doctor = _doctor(current_user, db)
    if not doctor:
        return {"code": 500, "msg": "医生信息不存在", "data": []}
    items = db.query(PrescriptionTemplate).filter(PrescriptionTemplate.doctor_id == doctor.doctor_id).order_by(PrescriptionTemplate.template_id.desc()).all()
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in items]}


@router.post("/prescriptionTemplate/create")
def create_prescription_template(
    req: PrescriptionTemplateCreateRequest,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    doctor = _doctor(current_user, db)
    if not doctor:
        return {"code": 500, "msg": "医生信息不存在"}
    items, error = _normalize_items(req.items, db)
    if error:
        return {"code": 500, "msg": error}
    now = datetime.datetime.now()
    template = PrescriptionTemplate(doctor_id=doctor.doctor_id, name=req.name.strip(), items=json.dumps(items, ensure_ascii=False), create_time=now, update_time=now)
    db.add(template)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(template)}


@router.put("/prescriptionTemplate/update")
def update_prescription_template(
    req: PrescriptionTemplateUpdateRequest,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    doctor = _doctor(current_user, db)
    template = db.query(PrescriptionTemplate).filter(PrescriptionTemplate.template_id == req.template_id, PrescriptionTemplate.doctor_id == doctor.doctor_id if doctor else False).first()
    if not template:
        return {"code": 404, "msg": "处方模板不存在"}
    items, error = _normalize_items(req.items, db)
    if error:
        return {"code": 500, "msg": error}
    template.name = req.name.strip()
    template.items = json.dumps(items, ensure_ascii=False)
    template.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(template)}


@router.post("/prescriptionTemplate/delete")
def delete_prescription_template(
    req: PrescriptionTemplateIdRequest,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    doctor = _doctor(current_user, db)
    template = db.query(PrescriptionTemplate).filter(PrescriptionTemplate.template_id == req.template_id, PrescriptionTemplate.doctor_id == doctor.doctor_id if doctor else False).first()
    if not template:
        return {"code": 404, "msg": "处方模板不存在"}
    db.delete(template)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/prescriptionTemplate/apply")
def apply_prescription_template(
    req: PrescriptionTemplateIdRequest,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    doctor = _doctor(current_user, db)
    template = db.query(PrescriptionTemplate).filter(PrescriptionTemplate.template_id == req.template_id, PrescriptionTemplate.doctor_id == doctor.doctor_id if doctor else False).first()
    if not template:
        return {"code": 404, "msg": "处方模板不存在"}
    return {"code": 200, "msg": "success", "data": _serialize(template)["items"]}
