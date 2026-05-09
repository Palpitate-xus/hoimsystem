import datetime
import traceback
import random
from fastapi import APIRouter, Depends
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Charge, Invoice, Prescription, PrePha, Pharmaceutical, Patient, User
from app.schemas import ChargeRefundRequest, InvoiceCreateRequest, InvoicePrintRequest, ChargeCommitRequest
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
