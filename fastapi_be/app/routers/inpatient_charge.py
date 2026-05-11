import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Admission, InpatientCharge, Patient

router = APIRouter()


@router.get("/inpatientCharge/getList")
def get_inpatient_charge_list(
    admission_id: str | None = None,
    patient_id: int | None = None,
    charge_date: str | None = None,
    status: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(InpatientCharge).order_by(InpatientCharge.charge_date.desc(), InpatientCharge.create_time.desc())
    if admission_id:
        query = query.filter(InpatientCharge.admission_id == admission_id)
    if patient_id:
        query = query.filter(InpatientCharge.patient_id == patient_id)
    if charge_date:
        try:
            from datetime import date as dt_date
            d = dt_date.fromisoformat(charge_date)
            query = query.filter(InpatientCharge.charge_date == d)
        except ValueError:
            pass
    if status is not None:
        query = query.filter(InpatientCharge.status == status)
    charges = query.all()

    status_map = ["未结算", "已结算", "已退费"]
    data = []
    for item in charges:
        data.append(
            {
                "charge_id": item.charge_id,
                "admission_id": item.admission_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "item_name": item.item_name,
                "item_type": item.item_type,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total_amount": item.total_amount,
                "charge_date": str(item.charge_date) if item.charge_date else "",
                "status": item.status,
                "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
                "create_time": str(item.create_time) if item.create_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.get("/inpatientCharge/getDailyBill")
def get_daily_bill(admission_id: str, db: Session = Depends(get_db)):
    admission = db.query(Admission).filter(Admission.admission_id == admission_id).first()
    if not admission:
        return {"code": 500, "msg": "入院记录不存在"}

    # 按日期汇总费用
    daily = (
        db.query(
            InpatientCharge.charge_date,
            func.sum(InpatientCharge.total_amount).label("daily_total"),
        )
        .filter(InpatientCharge.admission_id == admission_id, InpatientCharge.status != 2)
        .group_by(InpatientCharge.charge_date)
        .order_by(InpatientCharge.charge_date)
        .all()
    )

    total_amount = (
        db.query(func.sum(InpatientCharge.total_amount))
        .filter(InpatientCharge.admission_id == admission_id, InpatientCharge.status != 2)
        .scalar()
        or 0
    )

    settled_amount = (
        db.query(func.sum(InpatientCharge.total_amount))
        .filter(InpatientCharge.admission_id == admission_id, InpatientCharge.status == 1)
        .scalar()
        or 0
    )

    data = {
        "admission_id": admission_id,
        "patient_name": admission.patient.name if admission.patient else "",
        "admission_no": admission.admission_no,
        "deposit_amount": admission.deposit_amount,
        "total_amount": round(total_amount, 2),
        "settled_amount": round(settled_amount, 2),
        "unsettled_amount": round(total_amount - settled_amount, 2),
        "balance": round(admission.deposit_amount - total_amount, 2),
        "daily_list": [
            {"charge_date": str(d.charge_date), "amount": round(d.daily_total, 2)} for d in daily
        ],
    }
    return {"code": 200, "msg": "success", "data": data}


@router.post("/inpatientCharge/settle")
def settle_charges(req: dict, db: Session = Depends(get_db)):
    admission_id = req.get("admission_id")
    admission = db.query(Admission).filter(Admission.admission_id == admission_id).first()
    if not admission:
        return {"code": 500, "msg": "入院记录不存在"}

    # 结算所有未结算的费用
    charges = db.query(InpatientCharge).filter(
        InpatientCharge.admission_id == admission_id,
        InpatientCharge.status == 0,
    ).all()
    for c in charges:
        c.status = 1
        db.add(c)

    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/inpatientCharge/refund")
def refund_charge(req: dict, db: Session = Depends(get_db)):
    charge_id = req.get("charge_id")
    charge = db.query(InpatientCharge).filter(InpatientCharge.charge_id == charge_id).first()
    if not charge:
        return {"code": 500, "msg": "费用记录不存在"}
    if charge.status == 2:
        return {"code": 500, "msg": "该费用已退费"}
    charge.status = 2
    db.add(charge)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/inpatientCharge/getSummary")
def get_charge_summary(db: Session = Depends(get_db)):
    today = datetime.datetime.now().date()

    today_income = (
        db.query(func.sum(InpatientCharge.total_amount))
        .filter(InpatientCharge.charge_date == today, InpatientCharge.status != 2)
        .scalar()
        or 0
    )

    total_inpatient = db.query(Admission).filter(Admission.status == 1).count()

    total_deposit = (
        db.query(func.sum(Admission.deposit_amount))
        .filter(Admission.status == 1)
        .scalar()
        or 0
    )

    return {
        "code": 200,
        "msg": "success",
        "data": {
            "today_income": round(today_income, 2),
            "total_inpatient": total_inpatient,
            "total_deposit": round(total_deposit, 2),
        },
    }
