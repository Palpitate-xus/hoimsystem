import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    Admission,
    Bed,
    DischargeSummary,
    Doctor,
    InpatientCharge,
    Patient,
)
from app.schemas import DischargeSummaryCreateRequest

router = APIRouter()


@router.post("/discharge/doDischarge")
def do_discharge(req: dict, db: Session = Depends(get_db)):
    admission_id = req.get("admission_id")
    admission = db.query(Admission).filter(Admission.admission_id == admission_id).first()
    if not admission:
        return {"code": 500, "msg": "入院记录不存在"}
    if admission.status != 1:
        return {"code": 500, "msg": "病人不在院状态，无法办理出院"}

    # 计算费用
    total_amount = (
        db.query(func.sum(InpatientCharge.total_amount))
        .filter(InpatientCharge.admission_id == admission_id, InpatientCharge.status != 2)
        .scalar()
        or 0
    )

    # 自动结算未结算费用
    charges = db.query(InpatientCharge).filter(
        InpatientCharge.admission_id == admission_id,
        InpatientCharge.status == 0,
    ).all()
    for c in charges:
        c.status = 1
        db.add(c)

    # 更新入院记录
    admission.status = 2
    admission.discharge_time = datetime.datetime.now()
    admission.discharge_diagnosis = req.get("discharge_diagnosis", admission.admission_diagnosis)
    db.add(admission)

    # 释放床位
    bed = db.query(Bed).filter(Bed.bed_id == admission.bed_id).first()
    if bed:
        bed.status = 0
        db.add(bed)

    # 创建出院小结（如果不存在）
    existing_summary = db.query(DischargeSummary).filter(DischargeSummary.admission_id == admission_id).first()
    if not existing_summary:
        hospital_days = 1
        if admission.admission_time:
            hospital_days = (datetime.datetime.now() - admission.admission_time).days + 1
        summary = DischargeSummary(
            admission_id=admission_id,
            patient_id=admission.patient_id,
            doctor_id=admission.doctor_id,
            discharge_time=datetime.datetime.now(),
            hospital_days=hospital_days,
            admission_diagnosis=admission.admission_diagnosis,
            discharge_diagnosis=req.get("discharge_diagnosis", admission.admission_diagnosis),
            treatment_summary=req.get("treatment_summary", ""),
            discharge_status=req.get("discharge_status", 0),
            discharge_instruction=req.get("discharge_instruction", ""),
            follow_up_plan=req.get("follow_up_plan", ""),
            note=req.get("note", ""),
            create_time=datetime.datetime.now(),
        )
        db.add(summary)

    db.commit()
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "total_amount": round(total_amount, 2),
            "deposit_amount": admission.deposit_amount,
            "refund_amount": round(admission.deposit_amount - total_amount, 2),
        },
    }


@router.get("/discharge/getSummary")
def get_discharge_summary(admission_id: str, db: Session = Depends(get_db)):
    summary = db.query(DischargeSummary).filter(DischargeSummary.admission_id == admission_id).first()
    if not summary:
        return {"code": 500, "msg": "出院小结不存在"}

    admission = db.query(Admission).filter(Admission.admission_id == admission_id).first()
    status_map = ["治愈", "好转", "未愈", "死亡", "转院"]
    data = {
        "summary_id": summary.summary_id,
        "admission_id": summary.admission_id,
        "admission_no": admission.admission_no if admission else "",
        "patient_id": summary.patient_id,
        "patient_name": summary.patient.name if summary.patient else "",
        "patient_identity": summary.patient.identity if summary.patient else "",
        "patient_sex": "男" if summary.patient and summary.patient.sex == 1 else "女",
        "doctor_id": summary.doctor_id,
        "doctor_name": summary.doctor.name if summary.doctor else "",
        "discharge_time": (summary.discharge_time.strftime("%Y-%m-%d %H:%M:%S") if summary.discharge_time else None) if summary.discharge_time else "",
        "hospital_days": summary.hospital_days,
        "admission_time": (admission.admission_time.strftime("%Y-%m-%d %H:%M:%S") if admission.admission_time else None) if admission else "",
        "admission_diagnosis": summary.admission_diagnosis or "",
        "discharge_diagnosis": summary.discharge_diagnosis or "",
        "treatment_summary": summary.treatment_summary or "",
        "discharge_status": summary.discharge_status,
        "discharge_status_text": status_map[summary.discharge_status] if summary.discharge_status is not None and summary.discharge_status < len(status_map) else "",
        "discharge_instruction": summary.discharge_instruction or "",
        "follow_up_plan": summary.follow_up_plan or "",
        "note": summary.note or "",
    }
    return {"code": 200, "msg": "success", "data": data}


@router.post("/discharge/updateSummary")
def update_discharge_summary(req: DischargeSummaryCreateRequest, db: Session = Depends(get_db)):
    summary = db.query(DischargeSummary).filter(DischargeSummary.admission_id == req.admission_id).first()
    if not summary:
        return {"code": 500, "msg": "出院小结不存在"}
    if req.discharge_diagnosis is not None:
        summary.discharge_diagnosis = req.discharge_diagnosis
    if req.treatment_summary is not None:
        summary.treatment_summary = req.treatment_summary
    if req.discharge_status is not None:
        summary.discharge_status = req.discharge_status
    if req.discharge_instruction is not None:
        summary.discharge_instruction = req.discharge_instruction
    if req.follow_up_plan is not None:
        summary.follow_up_plan = req.follow_up_plan
    if req.note is not None:
        summary.note = req.note
    db.add(summary)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/discharge/getDischargedList")
def get_discharged_list(
    start_date: str | None = None,
    end_date: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Admission).filter(Admission.status == 2).order_by(Admission.discharge_time.desc())
    if start_date:
        try:
            start = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(Admission.discharge_time >= start)
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)
            query = query.filter(Admission.discharge_time < end)
        except ValueError:
            pass
    records = query.all()
    data = []
    for item in records:
        # 计算总费用
        total = (
            db.query(func.sum(InpatientCharge.total_amount))
            .filter(InpatientCharge.admission_id == item.admission_id, InpatientCharge.status != 2)
            .scalar()
            or 0
        )
        data.append(
            {
                "admission_id": item.admission_id,
                "admission_no": item.admission_no,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "patient_identity": item.patient.identity if item.patient else "",
                "doctor_name": item.doctor.name if item.doctor else "",
                "department_name": item.department.name if item.department else "",
                "ward_name": item.ward.name if item.ward else "",
                "bed_no": item.bed.bed_no if item.bed else "",
                "admission_time": (item.admission_time.strftime("%Y-%m-%d %H:%M:%S") if item.admission_time else None) if item.admission_time else "",
                "discharge_time": (item.discharge_time.strftime("%Y-%m-%d %H:%M:%S") if item.discharge_time else None) if item.discharge_time else "",
                "hospital_days": (item.discharge_time - item.admission_time).days + 1 if item.discharge_time and item.admission_time else 0,
                "admission_diagnosis": item.admission_diagnosis or "",
                "discharge_diagnosis": item.discharge_diagnosis or "",
                "deposit_amount": item.deposit_amount,
                "total_amount": round(total, 2),
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}
