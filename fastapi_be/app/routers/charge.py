import datetime
import traceback
import random
from fastapi import APIRouter, Depends
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Charge, Invoice, Prescription, PrePha, Pharmaceutical, Patient, User
from app.schemas import ChargeRefundRequest, InvoiceCreateRequest, InvoicePrintRequest, ChargeCommitRequest, PaymentCreateRequest, PaymentQueryRequest, PaymentMockNotifyRequest
from app.dependencies import get_current_user
from app.pagination import paginate

router = APIRouter()


@router.get("/chargeManagement/getList")
def get_charge_list(current_user: User = Depends(get_current_user), keyword: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None, db: Session = Depends(get_db)):
    data = []
    total = 0
    if current_user.user_role == "admin" or current_user.user_role not in ("admin", "patient"):
        query = db.query(Charge)
        charge_list, total = paginate(query, page, page_size)
        for item in charge_list:
            data.append({
                "id": str(item.charge_id),
                "charge_time": str(item.charge_time),
                "time": str(item.time),
                "pre_id": str(item.prescription.prescription_id) if item.prescription else "",
                "amount": round(item.amount, 2) if item.amount else 0,
                "status": item.status,
            })
    elif current_user.user_role == "patient":
        patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
        if patient_obj:
            pres = db.query(Prescription).filter(Prescription.patient_id == patient_obj.patient_id).all()
            for pre in pres:
                item = db.query(Charge).filter(Charge.prescription_id == pre.prescription_id).first()
                if item:
                    data.append({
                        "id": str(item.charge_id),
                        "charge_time": str(item.charge_time),
                        "time": str(item.time),
                        "pre_id": str(item.prescription.prescription_id) if item.prescription else "",
                        "amount": round(item.amount, 2) if item.amount else 0,
                        "status": item.status,
                    })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/chargeManagement/charge")
def charge_commit(req: ChargeCommitRequest, db: Session = Depends(get_db)):
    charge_obj = db.query(Charge).filter(Charge.charge_id == req.id).first()
    if charge_obj:
        charge_obj.status = 1
        charge_obj.time = datetime.datetime.now()
        db.add(charge_obj)
        db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/chargeManagement/refund")
def charge_refund(req: ChargeRefundRequest, db: Session = Depends(get_db)):
    charge_obj = db.query(Charge).filter(Charge.charge_id == req.charge_id).first()
    if not charge_obj:
        return {"code": 500, "msg": "收费记录不存在"}
    if charge_obj.status != 1:
        return {"code": 500, "msg": "未缴费或已退费，无法退费"}
    charge_obj.status = 2
    db.add(charge_obj)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/invoice/getList")
def get_invoice_list(keyword: Optional[str] = None, db: Session = Depends(get_db)):
    invoices = db.query(Invoice).all()
    data = []
    for item in invoices:
        data.append({
            "id": str(item.invoice_id),
            "invoice_no": item.invoice_no,
            "charge_id": str(item.charge_id),
            "amount": round(item.amount, 2) if item.amount else 0,
            "invoice_time": str(item.invoice_time),
        })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


import traceback
import random

@router.post("/invoice/create")
def create_invoice(req: InvoiceCreateRequest, db: Session = Depends(get_db)):
    charge = db.query(Charge).filter(Charge.charge_id == req.charge_id).first()
    if not charge:
        return {"code": 500, "msg": "收费记录不存在"}
    try:
        invoice_no = "INV" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(1000, 9999))
        invoice = Invoice(
            charge_id=req.charge_id,
            invoice_no=invoice_no,
            amount=charge.amount,
            tax=round(charge.amount * 0.06, 2) if charge.amount else 0,
            invoice_time=datetime.datetime.now(),
            status=0,
        )
        db.add(invoice)
        db.commit()
        return {"code": 200, "msg": "success", "data": {"invoice_no": invoice_no}}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "发票生成失败"}


@router.post("/invoice/print")
def print_invoice(req: InvoicePrintRequest, db: Session = Depends(get_db)):
    invoice = db.query(Invoice).filter(Invoice.invoice_id == req.invoice_id).first()
    if not invoice:
        return {"code": 500, "msg": "发票不存在"}
    return {"code": 200, "msg": "success", "data": {"pdf_url": f"/api/invoice/pdf/{invoice.invoice_id}"}}


@router.post("/windowRegistration/create")
def window_registration(req: dict, db: Session = Depends(get_db)):
    """窗口挂号：收费员代病人现场挂号"""
    from app.models import Patient, Registration, DoctorSchedule
    identity = req.get("identity")
    patient = db.query(Patient).filter(Patient.identity == identity).first()
    if not patient:
        return {"code": 500, "msg": "病人信息不存在，请先注册"}
    schedule_id = req.get("schedule_id")
    doctor_id = req.get("doctor_id")
    department_id = req.get("department_id")
    specialist = req.get("specialist", 0)
    reg_obj = db.query(DoctorSchedule).filter(DoctorSchedule.schedule_id == schedule_id).first()
    if reg_obj and reg_obj.number <= 0:
        return {"code": 500, "msg": "该时段号源已满"}
    try:
        if reg_obj:
            reg_obj.number -= 1
            db.add(reg_obj)
        registration = Registration(
            registration_id=1,
            patient_id=patient.patient_id,
            doctor_id=doctor_id,
            specialist=specialist,
            department_id=department_id,
            time=datetime.datetime.now(),
            status=0,
        )
        db.add(registration)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "挂号失败"}


@router.post("/windowRegistration/cancel")
def window_cancel_registration(req: dict, db: Session = Depends(get_db)):
    """窗口退号"""
    from app.models import Registration
    reg = db.query(Registration).filter(Registration.registration_uuid == req.get("uuid")).first()
    if not reg:
        return {"code": 500, "msg": "挂号记录不存在"}
    reg.status = 3
    db.add(reg)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/dailySettlement/report")
def daily_settlement(req: dict, db: Session = Depends(get_db)):
    """日结对账"""
    from sqlalchemy import func
    from app.models import Charge
    date = req.get("date")
    if not date:
        date = str(datetime.datetime.now().date())
    query = db.query(Charge).filter(func.date(Charge.charge_time) == date)
    charges = query.all()
    total_income = sum(c.amount for c in charges if c.status == 1)
    total_refund = sum(c.amount for c in charges if c.status == 2)
    total_pending = sum(c.amount for c in charges if c.status == 0)
    count_paid = len([c for c in charges if c.status == 1])
    count_refund = len([c for c in charges if c.status == 2])
    count_pending = len([c for c in charges if c.status == 0])
    return {"code": 200, "msg": "success", "data": {
        "date": date,
        "total_income": round(total_income, 2),
        "total_refund": round(total_refund, 2),
        "total_pending": round(total_pending, 2),
        "count_paid": count_paid,
        "count_refund": count_refund,
        "count_pending": count_pending,
        "record_count": len(charges),
    }}


# ===== 支付接口（微信/支付宝 Mock）=====

@router.post("/payment/create")
def create_payment(req: PaymentCreateRequest, db: Session = Depends(get_db)):
    """创建支付订单"""
    from app.models import Payment
    charge = db.query(Charge).filter(Charge.charge_id == req.charge_id).first()
    if not charge:
        return {"code": 500, "msg": "收费记录不存在"}
    if charge.status == 1:
        return {"code": 500, "msg": "该订单已缴费"}
    payment_no = "PAY" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(1000, 9999))
    qr_data = f"mock://payment?no={payment_no}&amount={req.amount}&channel={req.channel}"
    payment = Payment(
        payment_no=payment_no,
        charge_id=req.charge_id,
        channel=req.channel,
        amount=req.amount,
        status=0,
        qr_code_data=qr_data,
        create_time=datetime.datetime.now(),
    )
    db.add(payment)
    db.commit()
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "payment_no": payment_no,
            "qr_code_data": qr_data,
            "channel": req.channel,
            "amount": req.amount,
        }
    }


@router.get("/payment/query/{payment_no}")
def query_payment(payment_no: str, db: Session = Depends(get_db)):
    """查询支付状态"""
    from app.models import Payment
    payment = db.query(Payment).filter(Payment.payment_no == payment_no).first()
    if not payment:
        return {"code": 500, "msg": "支付单不存在"}
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "payment_no": payment.payment_no,
            "charge_id": payment.charge_id,
            "channel": payment.channel,
            "amount": payment.amount,
            "status": payment.status,
            "paid_time": str(payment.paid_time) if payment.paid_time else None,
            "create_time": str(payment.create_time),
        }
    }


@router.post("/payment/mockNotify")
def mock_payment_notify(req: PaymentMockNotifyRequest, db: Session = Depends(get_db)):
    """Mock 支付回调（模拟微信/支付宝异步通知）"""
    from app.models import Payment
    payment = db.query(Payment).filter(Payment.payment_no == req.payment_no).first()
    if not payment:
        return {"code": 500, "msg": "支付单不存在"}
    if payment.status != 0:
        return {"code": 500, "msg": "支付单状态异常"}
    try:
        payment.status = 1
        payment.paid_time = datetime.datetime.now()
        db.add(payment)
        # 更新收费记录状态为已缴费
        charge = db.query(Charge).filter(Charge.charge_id == payment.charge_id).first()
        if charge:
            charge.status = 1
            charge.time = datetime.datetime.now()
            db.add(charge)
        db.commit()
        return {"code": 200, "msg": "支付成功"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "支付处理失败"}


@router.get("/payment/getList")
def get_payment_list(keyword: Optional[str] = None, db: Session = Depends(get_db)):
    """支付流水列表"""
    from app.models import Payment
    payments = db.query(Payment).order_by(Payment.create_time.desc()).all()
    data = []
    for item in payments:
        data.append({
            "payment_id": item.payment_id,
            "payment_no": item.payment_no,
            "charge_id": item.charge_id,
            "channel": item.channel,
            "amount": round(item.amount, 2) if item.amount else 0,
            "status": item.status,
            "paid_time": str(item.paid_time) if item.paid_time else "",
            "create_time": str(item.create_time),
        })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}
