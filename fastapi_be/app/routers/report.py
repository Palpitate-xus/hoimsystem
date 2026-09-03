import datetime

from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from sqlalchemy import String, case, cast, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CASHIER_ROLES, CLINICAL_ROLES, User, require_roles
from app.models import Charge, Department, Doctor, LabOrder, MedicalRecord, Pharmaceutical, PrePha, Prescription, Review

router = APIRouter()

_REPORT_ROLES = {*CLINICAL_ROLES, *CASHIER_ROLES}


def _date_range_filters(column, start_date, end_date):
    """Build sargable half-open timestamp bounds instead of wrapping columns."""
    try:
        start = datetime.date.fromisoformat(str(start_date)) if start_date else None
        end = datetime.date.fromisoformat(str(end_date)) if end_date else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="日期必须为 YYYY-MM-DD") from exc
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="开始日期不能晚于结束日期")
    filters = []
    if start:
        filters.append(column >= datetime.datetime.combine(start, datetime.time.min))
    if end:
        filters.append(column < datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min))
    return filters


@router.post("/report/outpatientVolume")
def report_outpatient_volume(req: dict, keyword: str | None = None, current_user: User = Depends(require_roles(*_REPORT_ROLES)), db: Session = Depends(get_db)):
    start_date = req.get("start_date")
    end_date = req.get("end_date")
    group_by = req.get("group_by", "day")
    if group_by not in {"day", "week", "month", "department", "doctor"}:
        raise HTTPException(status_code=422, detail="group_by 必须为 day/week/month/department/doctor")

    filters = _date_range_filters(MedicalRecord.consultation_time, start_date, end_date)
    details = []

    if group_by in {"day", "month"}:
        date_text = cast(MedicalRecord.consultation_time, String)
        label = func.substr(date_text, 1, 10 if group_by == "day" else 7)
        rows = (
            db.query(label.label("label"), func.count(MedicalRecord.medical_record_id).label("value"))
            .filter(*filters, MedicalRecord.consultation_time.isnot(None))
            .group_by(label)
            .order_by(label)
            .all()
        )
        details = [{"label": row.label, "value": row.value} for row in rows]
    elif group_by == "week":
        # ISO week formatting differs across supported databases. Stream only
        # the timestamp scalar here, avoiding full ORM rows and relationships.
        groups = {}
        timestamps = (
            db.query(MedicalRecord.consultation_time)
            .filter(*filters, MedicalRecord.consultation_time.isnot(None))
            .yield_per(1000)
        )
        for (consultation_time,) in timestamps:
            key = str(consultation_time.date().isocalendar()[1])
            groups[key] = groups.get(key, 0) + 1
        for k, v in sorted(groups.items()):
            details.append({"label": f"第{k}周", "value": v})
    elif group_by == "department":
        label = func.coalesce(Department.name, "未知科室")
        rows = (
            db.query(label.label("label"), func.count(MedicalRecord.medical_record_id).label("value"))
            .outerjoin(Doctor, MedicalRecord.doctor_id == Doctor.doctor_id)
            .outerjoin(Department, Doctor.department_id == Department.department_id)
            .filter(*filters)
            .group_by(label)
            .all()
        )
        details = [{"label": row.label, "value": row.value} for row in rows]
    elif group_by == "doctor":
        label = func.coalesce(Doctor.name, "未知医生")
        rows = (
            db.query(label.label("label"), func.count(MedicalRecord.medical_record_id).label("value"))
            .outerjoin(Doctor, MedicalRecord.doctor_id == Doctor.doctor_id)
            .filter(*filters)
            .group_by(label)
            .all()
        )
        details = [{"label": row.label, "value": row.value} for row in rows]

    total_visits = sum(item["value"] for item in details)

    if keyword:
        kw = keyword.lower()
        details = [item for item in details if any(kw in str(val).lower() for val in item.values())]

    return {"code": 200, "msg": "success", "data": {"total_visits": total_visits, "details": details}}


@router.post("/report/finance")
def report_finance(req: dict, current_user: User = Depends(require_roles(*_REPORT_ROLES)), db: Session = Depends(get_db)):
    start_date = req.get("start_date")
    end_date = req.get("end_date")

    filters = _date_range_filters(Charge.charge_time, start_date, end_date)
    total_income, total_refund, prescription_income = db.query(
        func.coalesce(func.sum(case((Charge.status == 1, Charge.amount), else_=0)), 0),
        func.coalesce(func.sum(case((Charge.status == 2, Charge.amount), else_=0)), 0),
        func.coalesce(
            func.sum(case(((Charge.status == 1) & Charge.prescription_id.isnot(None), Charge.amount), else_=0)),
            0,
        ),
    ).filter(*filters).one()
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

    filters = _date_range_filters(Prescription.create_time, start_date, end_date)
    name = func.coalesce(Pharmaceutical.name, "未知药品")
    rows = (
        db.query(name.label("name"), func.coalesce(func.sum(PrePha.number), 0).label("total_number"))
        .join(Prescription, PrePha.prescription_id == Prescription.prescription_id)
        .outerjoin(Pharmaceutical, PrePha.pharmaceutical_id == Pharmaceutical.pharmaceutical_id)
        .filter(*filters)
        .group_by(name)
        .all()
    )
    data = [{"name": row.name, "total_number": row.total_number} for row in rows]
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]

    return {"code": 200, "msg": "success", "data": data}


@router.post("/report/doctorWorkload")
def report_doctor_workload(req: dict, keyword: str | None = None, current_user: User = Depends(require_roles(*_REPORT_ROLES)), db: Session = Depends(get_db)):
    start_date = req.get("start_date")
    end_date = req.get("end_date")
    doctor_id = req.get("doctor_id")

    mr_counts = (
        db.query(
            MedicalRecord.doctor_id.label("doctor_id"),
            func.count(MedicalRecord.medical_record_id).label("visit_count"),
        )
        .filter(*_date_range_filters(MedicalRecord.consultation_time, start_date, end_date))
        .group_by(MedicalRecord.doctor_id)
        .subquery()
    )
    prescription_counts = (
        db.query(
            Prescription.doctor_id.label("doctor_id"),
            func.count(Prescription.prescription_id).label("prescription_count"),
        )
        .filter(*_date_range_filters(Prescription.create_time, start_date, end_date))
        .group_by(Prescription.doctor_id)
        .subquery()
    )
    lab_counts = (
        db.query(
            LabOrder.doctor_id.label("doctor_id"),
            func.count(LabOrder.lab_order_id).label("lab_order_count"),
        )
        .filter(*_date_range_filters(LabOrder.create_time, start_date, end_date))
        .group_by(LabOrder.doctor_id)
        .subquery()
    )
    doctors = (
        db.query(
            Doctor.doctor_id,
            Doctor.name,
            func.coalesce(mr_counts.c.visit_count, 0),
            func.coalesce(prescription_counts.c.prescription_count, 0),
            func.coalesce(lab_counts.c.lab_order_count, 0),
        )
        .outerjoin(mr_counts, mr_counts.c.doctor_id == Doctor.doctor_id)
        .outerjoin(prescription_counts, prescription_counts.c.doctor_id == Doctor.doctor_id)
        .outerjoin(lab_counts, lab_counts.c.doctor_id == Doctor.doctor_id)
    )
    if doctor_id:
        doctors = doctors.filter(Doctor.doctor_id == doctor_id)
    data = [
        {
            "doctor_id": row[0],
            "doctor_name": row[1],
            "visit_count": row[2],
            "prescription_count": row[3],
            "lab_order_count": row[4],
        }
        for row in doctors.order_by(Doctor.doctor_id).all()
    ]

    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]

    return {"code": 200, "msg": "success", "data": data}


@router.post("/report/departmentStats")
def report_department_stats(req: dict, keyword: str | None = None, current_user: User = Depends(require_roles(*_REPORT_ROLES)), db: Session = Depends(get_db)):
    """汇总科室工作量、已收收入和患者满意度，供管理人员按日期查看。"""
    start_date = req.get("start_date")
    end_date = req.get("end_date")
    department_id = req.get("department_id")

    visit_counts = (
        db.query(
            Doctor.department_id.label("department_id"),
            func.count(MedicalRecord.medical_record_id).label("visit_count"),
        )
        .join(MedicalRecord, MedicalRecord.doctor_id == Doctor.doctor_id)
        .filter(*_date_range_filters(MedicalRecord.consultation_time, start_date, end_date))
        .group_by(Doctor.department_id)
        .subquery()
    )
    prescription_counts = (
        db.query(
            Doctor.department_id.label("department_id"),
            func.count(Prescription.prescription_id).label("prescription_count"),
        )
        .join(Prescription, Prescription.doctor_id == Doctor.doctor_id)
        .filter(*_date_range_filters(Prescription.create_time, start_date, end_date))
        .group_by(Doctor.department_id)
        .subquery()
    )
    lab_counts = (
        db.query(
            Doctor.department_id.label("department_id"),
            func.count(LabOrder.lab_order_id).label("lab_order_count"),
        )
        .join(LabOrder, LabOrder.doctor_id == Doctor.doctor_id)
        .filter(*_date_range_filters(LabOrder.create_time, start_date, end_date))
        .group_by(Doctor.department_id)
        .subquery()
    )
    income_totals = (
        db.query(
            Doctor.department_id.label("department_id"),
            func.coalesce(func.sum(Charge.amount), 0).label("income"),
        )
        .join(Prescription, Charge.prescription_id == Prescription.prescription_id)
        .join(Doctor, Prescription.doctor_id == Doctor.doctor_id)
        .filter(
            Charge.status == 1,
            *_date_range_filters(Charge.charge_time, start_date, end_date),
        )
        .group_by(Doctor.department_id)
        .subquery()
    )
    review_totals = (
        db.query(
            Doctor.department_id.label("department_id"),
            func.count(Review.review_id).label("review_count"),
            func.avg(Review.score).label("satisfaction_score"),
        )
        .join(Review, Review.doctor_id == Doctor.doctor_id)
        .filter(
            Review.score.isnot(None),
            *_date_range_filters(Review.review_time, start_date, end_date),
        )
        .group_by(Doctor.department_id)
        .subquery()
    )
    departments_query = (
        db.query(
            Department.department_id,
            Department.name,
            func.coalesce(visit_counts.c.visit_count, 0),
            func.coalesce(prescription_counts.c.prescription_count, 0),
            func.coalesce(lab_counts.c.lab_order_count, 0),
            func.coalesce(income_totals.c.income, 0),
            func.coalesce(review_totals.c.review_count, 0),
            review_totals.c.satisfaction_score,
        )
        .outerjoin(visit_counts, visit_counts.c.department_id == Department.department_id)
        .outerjoin(prescription_counts, prescription_counts.c.department_id == Department.department_id)
        .outerjoin(lab_counts, lab_counts.c.department_id == Department.department_id)
        .outerjoin(income_totals, income_totals.c.department_id == Department.department_id)
        .outerjoin(review_totals, review_totals.c.department_id == Department.department_id)
    )
    if department_id:
        departments_query = departments_query.filter(Department.department_id == department_id)
    rows = departments_query.order_by(Department.department_id).all()
    data = [
        {
            "department_id": row[0],
            "department_name": row[1] or "未命名科室",
            "visit_count": row[2],
            "prescription_count": row[3],
            "lab_order_count": row[4],
            "income": round(float(row[5]), 2),
            "review_count": row[6],
            "satisfaction_score": round(float(row[7]), 2) if row[7] is not None else None,
        }
        for row in rows
    ]
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if kw in str(item["department_name"]).lower()]

    totals = {
        "visit_count": sum(item["visit_count"] for item in data),
        "prescription_count": sum(item["prescription_count"] for item in data),
        "lab_order_count": sum(item["lab_order_count"] for item in data),
        "income": round(sum(item["income"] for item in data), 2),
        "review_count": sum(item["review_count"] for item in data),
    }
    weighted_score_total = sum(
        item["satisfaction_score"] * item["review_count"]
        for item in data
        if item["satisfaction_score"] is not None
    )
    if totals["review_count"]:
        totals["satisfaction_score"] = round(weighted_score_total / totals["review_count"], 2)
    else:
        totals["satisfaction_score"] = None

    return {"code": 200, "msg": "success", "data": {"items": data, "totals": totals}}
