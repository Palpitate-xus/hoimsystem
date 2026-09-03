import datetime
import json

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, NURSING_ROLES, PHARMACY_ROLES, User, require_roles
from app.event_bus import patient_user_ids, publish_event
from app.models import (
    InpatientOrder,
    MedicationAdministration,
    OrderExecution,
    PatientCard,
    Pharmaceutical,
)
from app.pagination import paginate

router = APIRouter()


class MedicationVerifyRequest(BaseModel):
    execution_id: int = Field(gt=0)
    patient_barcode: str = Field(min_length=1, max_length=64)
    medication_barcodes: list[str] = Field(min_length=1, max_length=30)


class MedicationAdministerRequest(BaseModel):
    administration_id: str = Field(min_length=1, max_length=36)
    note: str = Field(default="", max_length=300)


class MedicationBarcodeRequest(BaseModel):
    pharmaceutical_id: int = Field(gt=0)
    barcode: str = Field(min_length=1, max_length=64)


def _execution_query(db: Session, execution_id: int):
    return (
        db.query(OrderExecution)
        .options(
            joinedload(OrderExecution.order).joinedload(InpatientOrder.patient),
            joinedload(OrderExecution.order).selectinload(InpatientOrder.items),
        )
        .filter(OrderExecution.execution_id == execution_id)
        .first()
    )


@router.post("/emar/verify")
def verify_medication(
    req: MedicationVerifyRequest,
    current_user: User = Depends(require_roles(*NURSING_ROLES)),
    db: Session = Depends(get_db),
):
    execution = _execution_query(db, req.execution_id)
    if not execution or not execution.order:
        return {"code": 404, "msg": "医嘱执行记录不存在"}
    if execution.status != 0 or execution.order.status not in (1, 2):
        return {"code": 409, "msg": "该医嘱当前不可执行"}
    active_card = (
        db.query(PatientCard)
        .filter(PatientCard.card_no == req.patient_barcode.strip(), PatientCard.status == 0)
        .first()
    )
    if not active_card or active_card.patient_id != execution.order.patient_id:
        return {"code": 400, "msg": "患者腕带/就诊卡与医嘱患者不匹配"}

    drug_items = [item for item in execution.order.items if item.item_type == "drug"]
    if not drug_items:
        return {"code": 400, "msg": "该执行记录不是药品医嘱"}
    pharmaceutical_ids = {item.item_id_ref for item in drug_items if item.item_id_ref}
    if len(pharmaceutical_ids) != len(drug_items):
        return {"code": 409, "msg": "医嘱药品未绑定药品目录，无法扫码执行"}
    pharmaceuticals = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id.in_(pharmaceutical_ids)).all()
    if len(pharmaceuticals) != len(pharmaceutical_ids) or any(not item.barcode for item in pharmaceuticals):
        return {"code": 409, "msg": "医嘱中存在未配置条码的药品"}
    expected_barcodes = {item.barcode for item in pharmaceuticals}
    scanned_barcodes = {barcode.strip() for barcode in req.medication_barcodes if barcode.strip()}
    if scanned_barcodes != expected_barcodes:
        return {"code": 400, "msg": "扫描药品与医嘱不匹配，请核对药名、剂量和给药途径"}

    existing = db.query(MedicationAdministration).filter_by(execution_id=execution.execution_id).first()
    if existing:
        if existing.status == 2:
            return {"code": 409, "msg": "该次给药已完成"}
        existing.nurse_id = current_user.user_id
        existing.patient_barcode = active_card.card_no
        existing.medication_barcodes_json = json.dumps(sorted(scanned_barcodes), ensure_ascii=False)
        existing.status = 1
        existing.verified_at = datetime.datetime.now()
        administration = existing
    else:
        administration = MedicationAdministration(
            execution_id=execution.execution_id,
            order_id=execution.order_id,
            patient_id=execution.order.patient_id,
            nurse_id=current_user.user_id,
            patient_barcode=active_card.card_no,
            medication_barcodes_json=json.dumps(sorted(scanned_barcodes), ensure_ascii=False),
            status=1,
            verified_at=datetime.datetime.now(),
        )
        db.add(administration)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"code": 409, "msg": "该执行记录已由其他护士完成扫码核对"}
    return {
        "code": 200,
        "msg": "患者与药品核对通过",
        "data": {
            "administration_id": administration.administration_id,
            "patient_name": execution.order.patient.name if execution.order.patient else "",
            "medications": [item.name for item in pharmaceuticals],
        },
    }


@router.post("/emar/administer")
def administer_medication(
    req: MedicationAdministerRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_roles(*NURSING_ROLES)),
    db: Session = Depends(get_db),
):
    administration = db.get(MedicationAdministration, req.administration_id)
    if not administration:
        return {"code": 404, "msg": "给药核对记录不存在"}
    if administration.status != 1:
        return {"code": 409, "msg": "该给药记录不在待执行状态"}
    if administration.nurse_id != current_user.user_id:
        return {"code": 403, "msg": "必须由完成扫码核对的护士执行给药"}
    now = datetime.datetime.now()
    updated = (
        db.query(OrderExecution)
        .filter(OrderExecution.execution_id == administration.execution_id, OrderExecution.status == 0)
        .update(
            {
                OrderExecution.status: 1,
                OrderExecution.nurse_id: current_user.user_id,
                OrderExecution.execution_time: now,
                OrderExecution.note: req.note.strip(),
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        return {"code": 409, "msg": "该医嘱执行记录已被处理"}
    administration.status = 2
    administration.administration_time = now
    administration.note = req.note.strip()
    order = db.get(InpatientOrder, administration.order_id)
    if order and order.status == 1:
        order.status = 2
    db.commit()
    audience_user_ids = patient_user_ids(db, administration.patient)
    if order and order.doctor and order.doctor.user_id:
        audience_user_ids.append(order.doctor.user_id)
    background_tasks.add_task(
        publish_event,
        "medication.administered",
        {
            "administration_id": administration.administration_id,
            "order_id": administration.order_id,
            "patient_id": administration.patient_id,
            "administration_time": now,
        },
        audience_roles=["nurse", "director", "admin", "super_admin"],
        audience_user_ids=audience_user_ids,
    )
    return {"code": 200, "msg": "给药完成", "data": {"administration_time": now}}


@router.get("/emar/list")
def list_medication_administrations(
    patient_id: int | None = None,
    status: int | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(require_roles(*NURSING_ROLES, *CLINICAL_ROLES, *ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    query = db.query(MedicationAdministration).options(
        joinedload(MedicationAdministration.patient),
        joinedload(MedicationAdministration.nurse),
        joinedload(MedicationAdministration.order).selectinload(InpatientOrder.items),
    )
    if patient_id:
        query = query.filter(MedicationAdministration.patient_id == patient_id)
    if status is not None:
        query = query.filter(MedicationAdministration.status == status)
    rows, total = paginate(query.order_by(MedicationAdministration.verified_at.desc()), page, page_size)
    return {
        "code": 200,
        "msg": "success",
        "data": [
            {
                "administration_id": item.administration_id,
                "execution_id": item.execution_id,
                "order_id": item.order_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "medications": [line.item_name for line in item.order.items if line.item_type == "drug"],
                "nurse_name": item.nurse.username if item.nurse else "",
                "status": item.status,
                "status_text": {1: "核对通过", 2: "已给药", 3: "已取消"}.get(item.status, ""),
                "verified_at": item.verified_at,
                "administration_time": item.administration_time,
                "note": item.note or "",
            }
            for item in rows
        ],
        "total": total,
    }


@router.post("/emar/medication/barcode")
def set_medication_barcode(
    req: MedicationBarcodeRequest,
    current_user: User = Depends(require_roles(*PHARMACY_ROLES, *ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    pharmaceutical = db.get(Pharmaceutical, req.pharmaceutical_id)
    if not pharmaceutical:
        return {"code": 404, "msg": "药品不存在"}
    barcode = req.barcode.strip()
    duplicate = db.query(Pharmaceutical).filter(
        Pharmaceutical.barcode == barcode,
        Pharmaceutical.pharmaceutical_id != pharmaceutical.pharmaceutical_id,
    ).first()
    if duplicate:
        return {"code": 409, "msg": "该药品条码已绑定其他药品"}
    pharmaceutical.barcode = barcode
    db.commit()
    return {"code": 200, "msg": "药品条码已绑定"}
