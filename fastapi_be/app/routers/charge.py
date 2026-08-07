import datetime
import math
import random
import traceback
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import ADMIN_ROLES, ROLE_CASHIER, ROLE_PATIENT, ROLE_REGISTRAR, get_current_user, require_roles
from app.models import Charge, Doctor, Invoice, Patient, Prescription, User
from app.pagination import paginate
from app.registration import allocate_registration_id
from app.schemas import (
    ChargeCommitRequest,
    ChargeRefundRequest,
    InvoiceCreateRequest,
    InvoicePrintRequest,
    PaymentCreateRequest,
    PaymentMockNotifyRequest,
)

router = APIRouter()


CASHIER_ROLES = {ROLE_CASHIER, *ADMIN_ROLES}


def _is_cashier_role(user: User) -> bool:
    return user.user_role in CASHIER_ROLES


def _owns_charge(user: User, charge: Charge | None) -> bool:
    if not charge or user.user_role != ROLE_PATIENT:
        return False
    return bool(charge.prescription and charge.prescription.patient and charge.prescription.patient.identity == user.username)


@router.get("/chargeManagement/getList")
def get_charge_list(current_user: User = Depends(get_current_user), keyword: str | None = None, page: int | None = None, page_size: int | None = None, db: Session = Depends(get_db)):
    def _enrich(item):
        patient_name = ""
        doctor_name = ""
        if item.prescription:
            pat = db.query(Patient).filter(Patient.patient_id == item.prescription.patient_id).first()
            if pat:
                patient_name = pat.name
            doc = db.query(Doctor).filter(Doctor.doctor_id == item.prescription.doctor_id).first()
            if doc:
                doctor_name = doc.name
        return {
            "id": str(item.charge_id),
            "charge_time": (item.charge_time.strftime("%Y-%m-%d %H:%M:%S") if item.charge_time else None),
            "time": (item.time.strftime("%Y-%m-%d %H:%M:%S") if item.time and item.time.year > 1970 else ""),
            "pre_id": str(item.prescription.prescription_id) if item.prescription else "",
            "patient_name": patient_name,
            "doctor_name": doctor_name,
            "amount": round(item.amount, 2) if item.amount else 0,
            "status": item.status,
            "status_text": {0: "未缴费", 1: "已缴费", 2: "已退费"}.get(item.status, ""),
        }

    data = []
    total = 0
    if _is_cashier_role(current_user):
        query = db.query(Charge)
        charge_list, total = paginate(query, page, page_size)
        for item in charge_list:
            data.append(_enrich(item))
    elif current_user.user_role == ROLE_PATIENT:
        patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
        if patient_obj:
            pres = db.query(Prescription).filter(Prescription.patient_id == patient_obj.patient_id).all()
            for pre in pres:
                item = db.query(Charge).filter(Charge.prescription_id == pre.prescription_id).first()
                if item:
                    data.append(_enrich(item))
    else:
        return {"code": 403, "msg": "无权访问", "data": []}
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/chargeManagement/charge")
def charge_commit(req: ChargeCommitRequest, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, *ADMIN_ROLES))):
    charge_obj = db.query(Charge).filter(Charge.charge_id == req.id).first()
    if not charge_obj:
        return {"code": 500, "msg": "收费记录不存在"}
    if charge_obj.status == 1:
        return {"code": 500, "msg": "该收费记录已缴费，不能重复收费"}
    if charge_obj.status != 0:
        return {"code": 500, "msg": "该收费记录状态不允许收费"}
    paid_time = datetime.datetime.now()
    updated = db.query(Charge).filter(
        Charge.charge_id == charge_obj.charge_id,
        Charge.status == 0,
    ).update({Charge.status: 1, Charge.time: paid_time}, synchronize_session=False)
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "该收费记录已缴费，不能重复收费"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/chargeManagement/refund")
def charge_refund(req: ChargeRefundRequest, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, *ADMIN_ROLES))):
    charge_obj = db.query(Charge).filter(Charge.charge_id == req.charge_id).first()
    if not charge_obj:
        return {"code": 500, "msg": "收费记录不存在"}
    if charge_obj.status != 1:
        return {"code": 500, "msg": "未缴费或已退费，无法退费"}

    # 当前接口是整笔退款，退款金额取自收费记录本身。拒绝异常金额，避免
    # 脏数据导致财务报表出现负数、NaN/Infinity 或无法追溯的退款金额。
    try:
        charge_amount = float(charge_obj.amount)
    except (TypeError, ValueError, OverflowError):
        charge_amount = 0.0
    if not math.isfinite(charge_amount) or charge_amount <= 0:
        return {"code": 500, "msg": "收费金额非法，无法退费"}

    # 状态条件放进 UPDATE，避免两个并发退款请求都先读到 status=1，
    # 从而将同一笔收费记录重复退费。
    result = db.execute(
        update(Charge)
        .where(Charge.charge_id == req.charge_id, Charge.status == 1)
        .values(status=2)
    )
    if result.rowcount != 1:
        db.rollback()
        return {"code": 500, "msg": "未缴费或已退费，无法退费"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/invoice/getList")
def get_invoice_list(keyword: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, *ADMIN_ROLES))):
    invoices = db.query(Invoice).all()
    data = []
    for item in invoices:
        charge = db.query(Charge).filter(Charge.charge_id == item.charge_id).first()
        patient_name = ""
        if charge and charge.prescription:
            pat = db.query(Patient).filter(Patient.patient_id == charge.prescription.patient_id).first()
            patient_name = pat.name if pat else ""
        data.append(
            {
                "id": str(item.invoice_id),
                "invoice_no": item.invoice_no,
                "charge_id": str(item.charge_id),
                "patient_name": patient_name,
                "amount": round(item.amount, 2) if item.amount else 0,
                "invoice_time": (item.invoice_time.strftime("%Y-%m-%d %H:%M:%S") if item.invoice_time else None),
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/windowRegistration/schedules")
def get_window_registration_schedules(
    keyword: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(ROLE_CASHIER, ROLE_REGISTRAR, *ADMIN_ROLES)),
):
    """获取窗口挂号可选的逐条排班号源。"""
    from app.models import DoctorSchedule

    schedules = db.query(DoctorSchedule).all()
    data = []
    for item in schedules:
        doctor = item.doctor
        department = doctor.department if doctor else None
        row = {
            "schedule_id": item.schedule_id,
            "doctor_id": item.doctor_id,
            "doctor_name": doctor.name if doctor else "",
            "department_id": department.department_id if department else None,
            "department_name": department.name if department else "",
            "specialist": item.specialist,
            "week": item.week,
            "time": item.time,
            "number": item.number or 0,
        }
        data.append(row)
    if keyword:
        kw = keyword.lower()
        data = [row for row in data if any(kw in str(value).lower() for value in row.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/windowRegistration/patient")
def get_window_registration_patient(
    identity: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(ROLE_CASHIER, ROLE_REGISTRAR, *ADMIN_ROLES)),
):
    """窗口挂号前核验患者身份并返回最小必要信息。"""
    patient = db.query(Patient).filter(Patient.identity == identity).first()
    if not patient:
        return {"code": 500, "msg": "病人信息不存在，请先注册"}
    return {
        "code": 200,
        "msg": "success",
        "data": {"patient_id": patient.patient_id, "identity": patient.identity, "name": patient.name, "phone": patient.phone},
    }


@router.get("/windowRegistration/appointments")
def get_window_appointments(identity: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, ROLE_REGISTRAR, *ADMIN_ROLES))):
    from app.models import Appointment, Patient

    query = db.query(Appointment).order_by(Appointment.appointment_time.desc())
    if identity:
        patient = db.query(Patient).filter(Patient.identity == identity.strip()).first()
        if not patient:
            return {"code": 200, "msg": "success", "data": []}
        query = query.filter(Appointment.patient_id == patient.patient_id)
    data = []
    status_map = {0: "待确认", 1: "已报到/就诊", 2: "已取消"}
    for item in query.all():
        data.append({"uuid": item.registration_uuid, "patient_name": item.patient.name if item.patient else "", "identity": item.patient.identity if item.patient else "", "doctor_name": item.doctor.name if item.doctor else "", "department_name": item.department.name if item.department else "", "time": str(item.time) if item.time else "", "prefer_time": item.prefer_time or "", "status": item.status, "status_text": status_map.get(item.status, "未知"), "confirmed": item.confirmed, "confirmed_text": "已确认" if item.confirmed else "未确认"})
    return {"code": 200, "msg": "success", "data": data}


@router.post("/windowRegistration/appointmentConfirm")
def confirm_window_appointment(req: dict, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, ROLE_REGISTRAR, *ADMIN_ROLES))):
    from app.models import Appointment

    item = db.query(Appointment).filter(Appointment.registration_uuid == req.get("uuid")).first()
    if not item:
        return {"code": 500, "msg": "预约记录不存在"}
    if item.status == 2:
        return {"code": 500, "msg": "预约已取消，不能确认"}
    item.confirmed = 1
    item.confirmed_time = datetime.datetime.now()
    item.confirmed_by = current_user.user_id
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/windowRegistration/appointmentCancel")
def cancel_window_appointment(req: dict, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, ROLE_REGISTRAR, *ADMIN_ROLES))):
    from app.models import Appointment, DoctorSchedule

    item = db.query(Appointment).filter(Appointment.registration_uuid == req.get("uuid")).first()
    if not item:
        return {"code": 500, "msg": "预约记录不存在"}
    if item.status == 2:
        return {"code": 500, "msg": "预约已取消，无需重复操作"}
    if item.status == 1:
        return {"code": 500, "msg": "预约已报到/就诊，不能取消"}
    item.status = 2
    schedule = db.query(DoctorSchedule).filter(DoctorSchedule.doctor_id == item.doctor_id, DoctorSchedule.specialist == item.specialist).first()
    if schedule:
        schedule.number = (schedule.number or 0) + 1
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/invoice/create")
def create_invoice(req: InvoiceCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, *ADMIN_ROLES))):
    charge = db.query(Charge).filter(Charge.charge_id == req.charge_id).first()
    if not charge:
        return {"code": 500, "msg": "收费记录不存在"}
    if charge.status != 1:
        return {"code": 500, "msg": "收费记录未缴费，无法开具发票"}
    if db.query(Invoice).filter(Invoice.charge_id == charge.charge_id).first():
        return {"code": 500, "msg": "该收费记录已开具发票，不能重复开票"}
    try:
        invoice_no = "INV" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(1000, 9999))
        invoice = Invoice(
            charge_id=req.charge_id,
            invoice_no=invoice_no,
            amount=charge.amount,
            tax=round(charge.amount * Decimal("0.06"), 2) if charge.amount else 0,
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
def print_invoice(req: InvoicePrintRequest, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, *ADMIN_ROLES))):
    invoice = db.query(Invoice).filter(Invoice.invoice_id == req.invoice_id).first()
    if not invoice:
        return {"code": 500, "msg": "发票不存在"}
    return {"code": 200, "msg": "success", "data": {"pdf_url": f"/api/invoice/pdf/{invoice.invoice_id}"}}


@router.get("/invoice/pdf/{invoice_id}")
def download_invoice_pdf(invoice_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """下载电子票据 PDF（当前为本地生成的可归档票据）。"""
    invoice = db.query(Invoice).filter(Invoice.invoice_id == invoice_id).first()
    if not invoice:
        return {"code": 500, "msg": "发票不存在"}
    if not _is_cashier_role(current_user) and not _owns_charge(current_user, invoice.charge):
        raise HTTPException(status_code=403, detail="无权访问该发票")

    charge = invoice.charge
    patient_name = charge.prescription.patient.name if charge and charge.prescription and charge.prescription.patient else ""
    lines = [
        "HOIM MEDICAL INVOICE",
        f"Invoice No: {invoice.invoice_no or ''}",
        f"Patient: {patient_name}",
        f"Amount: {float(invoice.amount or 0):.2f}",
        f"Time: {invoice.invoice_time.strftime('%Y-%m-%d %H:%M:%S') if invoice.invoice_time else ''}",
    ]
    def pdf_escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    text_lines = "BT /F1 12 Tf 50 760 Td " + " ".join(
        f"({pdf_escape(line)}) Tj 0 -24 Td" for line in lines
    ) + " ET"
    stream = text_lines.encode("ascii", errors="replace")
    objects = [
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n",
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n",
        b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n",
        b"5 0 obj<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream\nendobj\n",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref_offset}\n%%EOF".encode())
    return Response(
        content=bytes(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="invoice-{invoice.invoice_no or invoice.invoice_id}.pdf"'},
    )


@router.post("/windowRegistration/create")
def window_registration(req: dict, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, ROLE_REGISTRAR, *ADMIN_ROLES))):
    """窗口挂号：收费员代病人现场挂号"""
    from app.models import DoctorSchedule, Patient, Registration

    identity = req.get("identity")
    patient = db.query(Patient).filter(Patient.identity == identity).first()
    if not patient:
        return {"code": 500, "msg": "病人信息不存在，请先注册"}
    schedule_id = req.get("schedule_id")
    doctor_id = req.get("doctor_id")
    department_id = req.get("department_id")
    specialist = req.get("specialist")
    reg_obj = db.query(DoctorSchedule).filter(DoctorSchedule.schedule_id == schedule_id).first()
    if not reg_obj:
        return {"code": 500, "msg": "排班不存在"}
    if doctor_id is not None and reg_obj.doctor_id != doctor_id:
        return {"code": 500, "msg": "预约医生与排班不匹配"}
    if specialist is not None and reg_obj.specialist != specialist:
        return {"code": 500, "msg": "预约号类与排班不匹配"}
    if department_id is not None and reg_obj.doctor and reg_obj.doctor.department_id != department_id:
        return {"code": 500, "msg": "预约科室与排班不匹配"}
    if db.query(Registration).filter(
        Registration.patient_id == patient.patient_id,
        Registration.doctor_id == reg_obj.doctor_id,
        Registration.specialist == reg_obj.specialist,
        Registration.status == 0,
    ).first():
        return {"code": 500, "msg": "该患者已存在同一医生的有效挂号"}
    if reg_obj.number is None or reg_obj.number <= 0:
        return {"code": 500, "msg": "该时段号源已满"}
    try:
        registration_time = datetime.datetime.now()
        updated = db.query(DoctorSchedule).filter(
            DoctorSchedule.schedule_id == reg_obj.schedule_id,
            DoctorSchedule.number > 0,
        ).update({DoctorSchedule.number: DoctorSchedule.number - 1}, synchronize_session=False)
        if updated != 1:
            db.rollback()
            return {"code": 500, "msg": "该时段号源已满"}
        registration = Registration(
            patient_id=patient.patient_id,
            doctor_id=reg_obj.doctor_id,
            specialist=reg_obj.specialist,
            department_id=reg_obj.doctor.department_id if reg_obj.doctor else department_id,
            registration_id=allocate_registration_id(db, registration_time),
            time=registration_time,
            status=0,
        )
        db.add(registration)
        db.commit()
        return {
            "code": 200,
            "msg": "success",
            "data": {
                "registration_uuid": registration.registration_uuid,
                "registration_id": registration.registration_id,
            },
        }
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "挂号失败"}


@router.post("/windowRegistration/cancel")
def window_cancel_registration(req: dict, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, ROLE_REGISTRAR, *ADMIN_ROLES))):
    """窗口退号"""
    from app.models import DoctorSchedule, Registration

    reg = db.query(Registration).filter(Registration.registration_uuid == req.get("uuid")).first()
    if not reg:
        return {"code": 500, "msg": "挂号记录不存在"}
    if reg.status == 3:
        return {"code": 500, "msg": "该挂号已退号"}
    if reg.status != 0:
        return {"code": 500, "msg": "该挂号已就诊，不能退号"}
    updated = db.query(Registration).filter(
        Registration.registration_uuid == reg.registration_uuid,
        Registration.status == 0,
    ).update({Registration.status: 3}, synchronize_session=False)
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "该挂号已就诊，不能退号"}
    schedule = (
        db.query(DoctorSchedule)
        .filter(DoctorSchedule.doctor_id == reg.doctor_id, DoctorSchedule.specialist == reg.specialist)
        .first()
    )
    if schedule:
        schedule.number += 1
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/dailySettlement/report")
def daily_settlement(req: dict, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, *ADMIN_ROLES))):
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
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "date": date,
            "total_income": round(total_income, 2),
            "total_refund": round(total_refund, 2),
            "total_pending": round(total_pending, 2),
            "count_paid": count_paid,
            "count_refund": count_refund,
            "count_pending": count_pending,
            "record_count": len(charges),
        },
    }


# ===== 支付接口（微信/支付宝 Mock）=====


@router.post("/payment/create")
def create_payment(req: PaymentCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """创建支付订单"""
    from app.models import Payment

    charge = db.query(Charge).filter(Charge.charge_id == req.charge_id).first()
    if not charge:
        return {"code": 500, "msg": "收费记录不存在"}
    if not (_is_cashier_role(current_user) or _owns_charge(current_user, charge)):
        return {"code": 403, "msg": "无权访问该收费记录"}
    if charge.status == 1:
        return {"code": 500, "msg": "该订单已缴费"}
    if charge.status != 0:
        return {"code": 500, "msg": "该收费记录状态不允许支付"}
    if req.channel not in {"wechat", "alipay", "cash"}:
        return {"code": 500, "msg": "不支持的支付渠道"}
    try:
        requested_amount = Decimal(str(req.amount))
        charge_amount = Decimal(str(charge.amount or 0))
    except (InvalidOperation, TypeError, ValueError):
        requested_amount = None
        charge_amount = None
    if requested_amount is None or not requested_amount.is_finite() or requested_amount <= 0:
        return {"code": 500, "msg": "支付金额必须大于0"}
    if requested_amount != requested_amount.quantize(Decimal("0.01")):
        return {"code": 500, "msg": "支付金额最多保留两位小数"}
    if charge_amount is None or requested_amount.quantize(Decimal("0.01")) != charge_amount.quantize(Decimal("0.01")):
        return {"code": 500, "msg": "支付金额与收费金额不一致"}
    pending = db.query(Payment).filter(Payment.charge_id == charge.charge_id, Payment.status == 0).first()
    if pending:
        return {"code": 500, "msg": "该收费记录已有待支付订单"}
    payment_no = "PAY" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(1000, 9999))
    normalized_amount = requested_amount.quantize(Decimal("0.01"))
    qr_data = f"mock://payment?no={payment_no}&amount={normalized_amount}&channel={req.channel}"
    payment = Payment(
        payment_no=payment_no,
        charge_id=req.charge_id,
        channel=req.channel,
        amount=normalized_amount,
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
        },
    }


@router.get("/payment/query/{payment_no}")
def query_payment(payment_no: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """查询支付状态"""
    from app.models import Payment

    payment = db.query(Payment).filter(Payment.payment_no == payment_no).first()
    if not payment:
        return {"code": 500, "msg": "支付单不存在"}
    if not (_is_cashier_role(current_user) or _owns_charge(current_user, payment.charge)):
        return {"code": 403, "msg": "无权访问该支付单"}
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "payment_no": payment.payment_no,
            "charge_id": payment.charge_id,
            "channel": payment.channel,
            "amount": payment.amount,
            "status": payment.status,
            "paid_time": (payment.paid_time.strftime("%Y-%m-%d %H:%M:%S") if payment.paid_time else None) if payment.paid_time else None,
            "create_time": (payment.create_time.strftime("%Y-%m-%d %H:%M:%S") if payment.create_time else None),
        },
    }


@router.post("/payment/mockNotify")
def mock_payment_notify(req: PaymentMockNotifyRequest, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, *ADMIN_ROLES))):
    """Mock 支付回调（模拟微信/支付宝异步通知）"""
    if settings.is_production:
        return {"code": 403, "msg": "生产环境禁止使用模拟支付回调"}
    from app.models import Payment

    payment = db.query(Payment).filter(Payment.payment_no == req.payment_no).first()
    if not payment:
        return {"code": 500, "msg": "支付单不存在"}
    if payment.status != 0:
        return {"code": 500, "msg": "支付单状态异常"}
    charge = db.query(Charge).filter(Charge.charge_id == payment.charge_id).first()
    if not charge or charge.status != 0:
        return {"code": 500, "msg": "收费记录状态异常"}
    try:
        paid_time = datetime.datetime.now()
        payment_updated = db.query(Payment).filter(
            Payment.payment_no == payment.payment_no,
            Payment.status == 0,
        ).update({Payment.status: 1, Payment.paid_time: paid_time}, synchronize_session=False)
        charge_updated = db.query(Charge).filter(
            Charge.charge_id == charge.charge_id,
            Charge.status == 0,
        ).update({Charge.status: 1, Charge.time: paid_time}, synchronize_session=False)
        if payment_updated != 1 or charge_updated != 1:
            db.rollback()
            return {"code": 500, "msg": "支付单状态异常"}
        db.commit()
        return {"code": 200, "msg": "支付成功"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "支付处理失败"}


@router.get("/payment/getList")
def get_payment_list(keyword: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(require_roles(ROLE_CASHIER, *ADMIN_ROLES))):
    """支付流水列表"""
    from app.models import Payment

    payments = db.query(Payment).order_by(Payment.create_time.desc()).all()
    data = []
    for item in payments:
        data.append(
            {
                "payment_id": item.payment_id,
                "payment_no": item.payment_no,
                "charge_id": item.charge_id,
                "channel": item.channel,
                "amount": round(item.amount, 2) if item.amount else 0,
                "status": item.status,
                "paid_time": (item.paid_time.strftime("%Y-%m-%d %H:%M:%S") if item.paid_time else None) if item.paid_time else "",
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None),
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}
