from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, CASHIER_ROLES, User, require_roles
from app.models import Charge, Doctor, LabOrder, MedicalRecord, PrePha, Prescription

router = APIRouter()

_REPORT_ROLES = {*CLINICAL_ROLES, *CASHIER_ROLES}


@router.post("/report/outpatientVolume")
def report_outpatient_volume(req: dict, keyword: str | None = None, current_user: User = Depends(require_roles(*_REPORT_ROLES)), db: Session = Depends(get_db)):
    start_date = req.get("start_date")
    end_date = req.get("end_date")
    group_by = req.get("group_by", "day")

    query = db.query(MedicalRecord)
    if start_date:
        query = query.filter(func.date(MedicalRecord.consultation_time) >= start_date)
    if end_date:
        query = query.filter(func.date(MedicalRecord.consultation_time) <= end_date)

    records = query.all()
    total_visits = len(records)
    details = []

    if group_by == "day":
        groups = {}
        for r in records:
            key = str(r.consultation_time.date()) if r.consultation_time else ""
            groups[key] = groups.get(key, 0) + 1
        for k, v in sorted(groups.items()):
            details.append({"label": k, "value": v})
    elif group_by == "week":
        groups = {}
        for r in records:
            key = str(r.consultation_time.date().isocalendar()[1]) if r.consultation_time else ""
            groups[key] = groups.get(key, 0) + 1
        for k, v in sorted(groups.items()):
            details.append({"label": f"第{k}周", "value": v})
    elif group_by == "month":
        groups = {}
        for r in records:
            key = str(r.consultation_time.date())[:7] if r.consultation_time else ""
            groups[key] = groups.get(key, 0) + 1
        for k, v in sorted(groups.items()):
            details.append({"label": k, "value": v})
    elif group_by == "department":
        groups = {}
        for r in records:
            key = r.doctor.department.name if r.doctor and r.doctor.department else "未知科室"
            groups[key] = groups.get(key, 0) + 1
        for k, v in groups.items():
            details.append({"label": k, "value": v})
    elif group_by == "doctor":
        groups = {}
        for r in records:
            key = r.doctor.name if r.doctor else "未知医生"
            groups[key] = groups.get(key, 0) + 1
        for k, v in groups.items():
            details.append({"label": k, "value": v})

    if keyword:
        kw = keyword.lower()
        details = [item for item in details if any(kw in str(val).lower() for val in item.values())]

    return {"code": 200, "msg": "success", "data": {"total_visits": total_visits, "details": details}}


@router.post("/report/finance")
def report_finance(req: dict, current_user: User = Depends(require_roles(*_REPORT_ROLES)), db: Session = Depends(get_db)):
    start_date = req.get("start_date")
    end_date = req.get("end_date")

    query = db.query(Charge)
    if start_date:
        query = query.filter(func.date(Charge.charge_time) >= start_date)
    if end_date:
        query = query.filter(func.date(Charge.charge_time) <= end_date)

    charges = query.all()
    total_income = sum(c.amount for c in charges if c.status == 1)
    total_refund = sum(c.amount for c in charges if c.status == 2)
    prescription_income = sum(c.amount for c in charges if c.status == 1 and c.prescription_id)
    lab_income = 0

    return {
        "code": 200,
        "msg": "success",
        "data": {
            "total_income": round(total_income, 2),
            "total_refund": round(total_refund, 2),
            "prescription_income": round(prescription_income, 2),
            "lab_income": round(lab_income, 2),
        },
    }


@router.post("/report/pharmaceutical")
def report_pharmaceutical(req: dict, keyword: str | None = None, current_user: User = Depends(require_roles(*_REPORT_ROLES)), db: Session = Depends(get_db)):
    start_date = req.get("start_date")
    end_date = req.get("end_date")

    query = db.query(PrePha, Prescription).join(Prescription, PrePha.prescription_id == Prescription.prescription_id)
    if start_date:
        query = query.filter(func.date(Prescription.create_time) >= start_date)
    if end_date:
        query = query.filter(func.date(Prescription.create_time) <= end_date)

    results = query.all()
    groups = {}
    for pp, pre in results:
        name = pp.pharmaceutical.name if pp.pharmaceutical else "未知药品"
        groups[name] = groups.get(name, {"name": name, "total_number": 0})
        groups[name]["total_number"] += pp.number

    data = list(groups.values())
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]

    return {"code": 200, "msg": "success", "data": data}


@router.post("/report/doctorWorkload")
def report_doctor_workload(req: dict, keyword: str | None = None, current_user: User = Depends(require_roles(*_REPORT_ROLES)), db: Session = Depends(get_db)):
    start_date = req.get("start_date")
    end_date = req.get("end_date")
    doctor_id = req.get("doctor_id")

    doctors = db.query(Doctor)
    if doctor_id:
        doctors = doctors.filter(Doctor.doctor_id == doctor_id)
    doctors = doctors.all()

    data = []
    for doc in doctors:
        mr_query = db.query(MedicalRecord).filter(MedicalRecord.doctor_id == doc.doctor_id)
        pre_query = db.query(Prescription).filter(Prescription.doctor_id == doc.doctor_id)
        lab_query = db.query(LabOrder).filter(LabOrder.doctor_id == doc.doctor_id)
        if start_date:
            mr_query = mr_query.filter(func.date(MedicalRecord.consultation_time) >= start_date)
            pre_query = pre_query.filter(func.date(Prescription.create_time) >= start_date)
            lab_query = lab_query.filter(func.date(LabOrder.create_time) >= start_date)
        if end_date:
            mr_query = mr_query.filter(func.date(MedicalRecord.consultation_time) <= end_date)
            pre_query = pre_query.filter(func.date(Prescription.create_time) <= end_date)
            lab_query = lab_query.filter(func.date(LabOrder.create_time) <= end_date)

        data.append(
            {
                "doctor_id": doc.doctor_id,
                "doctor_name": doc.name,
                "visit_count": mr_query.count(),
                "prescription_count": pre_query.count(),
                "lab_order_count": lab_query.count(),
            }
        )

    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]

    return {"code": 200, "msg": "success", "data": data}
