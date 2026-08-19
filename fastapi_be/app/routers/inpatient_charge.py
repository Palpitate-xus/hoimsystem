import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CASHIER_ROLES, NURSING_ROLES, User, require_roles
from app.models import Admission, InpatientCharge

router = APIRouter()
INPATIENT_FINANCE_ROLES = CASHIER_ROLES | NURSING_ROLES


@router.get("/inpatientCharge/getList")
def get_inpatient_charge_list(
    admission_id: str | None = None,
    patient_id: int | None = None,
    charge_date: str | None = None,
    status: int | None = None,
    current_user: User = Depends(require_roles(*INPATIENT_FINANCE_ROLES)),
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
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.get("/inpatientCharge/getDailyBill")
def get_daily_bill(admission_id: str, current_user: User = Depends(require_roles(*INPATIENT_FINANCE_ROLES)),
    db: Session = Depends(get_db)):
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
def settle_charges(req: dict, current_user: User = Depends(require_roles(*CASHIER_ROLES)),
    db: Session = Depends(get_db)):
    admission_id = req.get("admission_id")
    admission = db.query(Admission).filter(Admission.admission_id == admission_id).first()
    if not admission:
        return {"code": 500, "msg": "入院记录不存在"}

    # 结算所有未结算的费用，并记录实际操作人和时间；重复结算保持幂等。
    charges = db.query(InpatientCharge).filter(
        InpatientCharge.admission_id == admission_id,
        InpatientCharge.status == 0,
    ).all()
    settled_time = datetime.datetime.now()
    for c in charges:
        c.status = 1
        c.settled_by = current_user.user_id
        c.settled_time = settled_time
        db.add(c)

    db.commit()
    return {"code": 200, "msg": "success", "data": {"settled_count": len(charges)}}


@router.post("/inpatientCharge/refund")
def refund_charge(req: dict, current_user: User = Depends(require_roles(*CASHIER_ROLES)),
    db: Session = Depends(get_db)):
    charge_id = req.get("charge_id")
    charge = db.query(InpatientCharge).filter(InpatientCharge.charge_id == charge_id).first()
    if not charge:
        return {"code": 500, "msg": "费用记录不存在"}
    if charge.status == 2:
        return {"code": 500, "msg": "该费用已退费"}
    if charge.status != 1:
        return {"code": 500, "msg": "未结算费用不可退费"}
    reason = str(req.get("reason") or "").strip()
    if not reason:
        return {"code": 500, "msg": "退费原因不能为空"}
    updated = db.query(InpatientCharge).filter(
        InpatientCharge.charge_id == charge_id,
        InpatientCharge.status == 1,
    ).update(
        {
            InpatientCharge.status: 2,
            InpatientCharge.refunded_by: current_user.user_id,
            InpatientCharge.refunded_time: datetime.datetime.now(),
            InpatientCharge.refund_reason: reason[:200],
        },
        synchronize_session=False,
    )
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "费用状态已变化，无法退费"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/inpatientCharge/getSummary")
def get_charge_summary(current_user: User = Depends(require_roles(*INPATIENT_FINANCE_ROLES)),
    db: Session = Depends(get_db)):
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


@router.post("/inpatientCharge/depositRecharge")
def deposit_recharge(req: dict, current_user: User = Depends(require_roles(*INPATIENT_FINANCE_ROLES)),
    db: Session = Depends(get_db)):
    """预缴金充值/补缴。

    amount 必须为正数；充值成功返回最新余额（已缴-已计费）。
    原缺陷：预缴金仅入院时写入一次，无充值/余额接口。
    """
    admission = db.query(Admission).filter(Admission.admission_id == req.get("admission_id")).first()
    if not admission:
        return {"code": 500, "msg": "住院记录不存在"}
    if admission.status != 1:
        return {"code": 500, "msg": "患者已出院，不能充值预缴金"}
    try:
        amount = float(req.get("amount", 0))
    except (TypeError, ValueError):
        return {"code": 400, "msg": "充值金额格式错误"}
    if amount <= 0:
        return {"code": 400, "msg": "充值金额必须大于0"}

    charged = (
        db.query(func.sum(InpatientCharge.total_amount))
        .filter(InpatientCharge.admission_id == admission.admission_id, InpatientCharge.status != 2)
        .scalar()
        or 0
    )
    from decimal import Decimal

    admission.deposit_amount = Decimal(str(admission.deposit_amount or 0)) + Decimal(str(amount))
    db.add(admission)
    db.commit()
    balance = float(admission.deposit_amount) - float(charged)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "admission_id": admission.admission_id,
            "deposit_amount": float(admission.deposit_amount),
            "charged_amount": round(float(charged), 2),
            "balance": round(balance, 2),
        },
    }


@router.get("/inpatientCharge/depositBalance")
def deposit_balance(admission_id: str, current_user: User = Depends(require_roles(*INPATIENT_FINANCE_ROLES)),
    db: Session = Depends(get_db)):
    """预缴金余额查询（已缴、已计费、余额、是否低于预警线）。"""
    admission = db.query(Admission).filter(Admission.admission_id == admission_id).first()
    if not admission:
        return {"code": 500, "msg": "住院记录不存在"}
    charged = (
        db.query(func.sum(InpatientCharge.total_amount))
        .filter(InpatientCharge.admission_id == admission.admission_id, InpatientCharge.status != 2)
        .scalar()
        or 0
    )
    deposit = float(admission.deposit_amount or 0)
    balance = deposit - float(charged)
    from app.config_service import get_config_float

    warn_ratio = get_config_float(db, "deposit_warning_ratio", 0.3)
    # 预警：余额为负，或剩余比例（余额/已缴）低于预警线且已缴>0
    low = balance < 0 or (deposit > 0 and balance / deposit < warn_ratio)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "admission_id": admission.admission_id,
            "patient_name": admission.patient.name if admission.patient else "",
            "deposit_amount": deposit,
            "charged_amount": round(float(charged), 2),
            "balance": round(balance, 2),
            "low_balance_warning": bool(low),
        },
    }
