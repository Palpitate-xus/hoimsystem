import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, PHARMACY_ROLES, ROLE_DIRECTOR, User, get_current_user, require_roles
from app.models import AntibioticApproval, LabOrder, Pharmaceutical, PrePha, Prescription

router = APIRouter()
ANTIBIOTIC_ROLES = {*CLINICAL_ROLES, *PHARMACY_ROLES}
REVIEW_ROLES = {*ADMIN_ROLES, ROLE_DIRECTOR}


@router.get("/antibiotic/grade/list")
def get_antibiotic_grade_list(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.query(Pharmaceutical).filter(Pharmaceutical.antibiotic_level > 0).order_by(Pharmaceutical.antibiotic_level.desc(), Pharmaceutical.name).all()
    return {"code": 200, "msg": "success", "data": [{"pharmaceutical_id": item.pharmaceutical_id, "name": item.name, "level": item.antibiotic_level, "level_text": {1: "非限制级", 2: "限制级", 3: "特殊使用级"}.get(item.antibiotic_level, "未知")} for item in items]}


@router.post("/antibiotic/grade/save")
def save_antibiotic_grade(req: dict, current_user: User = Depends(require_roles(*PHARMACY_ROLES, ROLE_DIRECTOR)), db: Session = Depends(get_db)):
    item = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.get("pharmaceutical_id")).first()
    if not item:
        return {"code": 404, "msg": "药品不存在"}
    level = req.get("level")
    if level not in (0, 1, 2, 3):
        return {"code": 400, "msg": "等级必须为0至3"}
    item.antibiotic_level = level
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/antibiotic/approval/create")
def create_antibiotic_approval(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    drug = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.get("pharmaceutical_id")).first()
    if not drug or drug.antibiotic_level < 2:
        return {"code": 400, "msg": "仅限制级或特殊使用级药品需要越级审批"}
    approval = AntibioticApproval(
        pharmaceutical_id=drug.pharmaceutical_id,
        patient_id=req.get("patient_id"),
        prescription_id=req.get("prescription_id"),
        applicant_id=current_user.user_id,
        reason=req.get("reason", "").strip(),
        status=0,
        create_time=datetime.datetime.now(),
    )
    if not approval.reason:
        return {"code": 400, "msg": "审批理由不能为空"}
    db.add(approval)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"approval_id": approval.approval_id}}


def _approval_data(item: AntibioticApproval):
    return {"approval_id": item.approval_id, "drug_name": item.pharmaceutical.name if item.pharmaceutical else "", "patient_name": item.patient.name if item.patient else "", "reason": item.reason, "status": item.status, "status_text": {0: "待审批", 1: "已通过", 2: "已退回"}.get(item.status, ""), "applicant_name": item.applicant.username if item.applicant else "", "review_note": item.review_note or "", "create_time": item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else ""}


@router.get("/antibiotic/approval/list")
def get_antibiotic_approval_list(current_user: User = Depends(require_roles(*ANTIBIOTIC_ROLES)), db: Session = Depends(get_db)):
    return {"code": 200, "msg": "success", "data": [_approval_data(item) for item in db.query(AntibioticApproval).order_by(AntibioticApproval.create_time.desc()).all()]}


@router.post("/antibiotic/approval/review")
def review_antibiotic_approval(req: dict, current_user: User = Depends(require_roles(*REVIEW_ROLES)), db: Session = Depends(get_db)):
    item = db.query(AntibioticApproval).filter(AntibioticApproval.approval_id == req.get("approval_id"), AntibioticApproval.status == 0).first()
    if not item:
        return {"code": 404, "msg": "待审批记录不存在"}
    status = req.get("status")
    if status not in (1, 2):
        return {"code": 400, "msg": "审批状态必须为1(通过)或2(退回)"}
    item.status = status
    item.reviewer_id = current_user.user_id
    item.review_note = req.get("note", "")
    item.review_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "审批完成"}


@router.get("/antibiotic/ddds")
def antibiotic_ddds(start_date: str | None = None, end_date: str | None = None, current_user: User = Depends(require_roles(*ANTIBIOTIC_ROLES)), db: Session = Depends(get_db)):
    query = db.query(PrePha, Prescription).join(Prescription, PrePha.prescription_id == Prescription.prescription_id).join(Pharmaceutical, PrePha.pharmaceutical_id == Pharmaceutical.pharmaceutical_id).filter(Pharmaceutical.antibiotic_level > 0)
    if start_date:
        query = query.filter(func.date(Prescription.create_time) >= start_date)
    if end_date:
        query = query.filter(func.date(Prescription.create_time) <= end_date)
    groups = {}
    for item, prescription in query.all():
        name = item.pharmaceutical.name if item.pharmaceutical else "未知药品"
        groups.setdefault(name, {"drug_name": name, "total_units": 0, "prescription_count": 0, "patient_days": set()})
        groups[name]["total_units"] += item.number or 0
        groups[name]["patient_days"].add(prescription.patient_id)
        groups[name]["prescription_count"] += 1
    data = [{**value, "patient_days": len(value.pop("patient_days"))} for value in groups.values()]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/antibiotic/submissionRate")
def antibiotic_submission_rate(start_date: str | None = None, end_date: str | None = None, current_user: User = Depends(require_roles(*ANTIBIOTIC_ROLES)), db: Session = Depends(get_db)):
    query = db.query(PrePha, Prescription).join(Prescription, PrePha.prescription_id == Prescription.prescription_id).join(Pharmaceutical, PrePha.pharmaceutical_id == Pharmaceutical.pharmaceutical_id).filter(Pharmaceutical.antibiotic_level > 0)
    if start_date:
        query = query.filter(func.date(Prescription.create_time) >= start_date)
    if end_date:
        query = query.filter(func.date(Prescription.create_time) <= end_date)
    prescriptions = {prescription.prescription_id: prescription for _, prescription in query.all()}
    lab_patients = {row[0] for row in db.query(LabOrder.patient_id).filter(LabOrder.patient_id.in_([item.patient_id for item in prescriptions.values()])).all()}
    submitted = sum(1 for item in prescriptions.values() if item.patient_id in lab_patients)
    total = len(prescriptions)
    return {"code": 200, "msg": "success", "data": {"antibiotic_prescriptions": total, "with_lab_orders": submitted, "submission_rate": round(submitted / total * 100, 2) if total else 0}}
