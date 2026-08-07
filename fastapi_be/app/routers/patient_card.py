import datetime
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import REGISTRAR_ROLES, ROLE_PATIENT, User, require_roles
from app.models import Patient, PatientCard

router = APIRouter()
CARD_READ_ROLES = {*REGISTRAR_ROLES, ROLE_PATIENT}


def _patient_for_user(current_user: User, db: Session):
    return db.query(Patient).filter(Patient.identity == current_user.username).first()


def _card_data(item: PatientCard):
    return {
        "card_id": item.card_id,
        "card_no": item.card_no,
        "patient_id": item.patient_id,
        "patient_name": item.patient.name if item.patient else "",
        "identity": item.patient.identity if item.patient else "",
        "status": item.status,
        "status_text": {0: "有效", 1: "已挂失", 2: "已注销"}.get(item.status, ""),
        "issue_time": item.issue_time.strftime("%Y-%m-%d %H:%M:%S") if item.issue_time else "",
        "lost_time": item.lost_time.strftime("%Y-%m-%d %H:%M:%S") if item.lost_time else "",
        "cancel_time": item.cancel_time.strftime("%Y-%m-%d %H:%M:%S") if item.cancel_time else "",
    }


@router.get("/patientCard/list")
def list_patient_cards(keyword: str | None = None, current_user: User = Depends(require_roles(*CARD_READ_ROLES)), db: Session = Depends(get_db)):
    query = db.query(PatientCard)
    if current_user.user_role == ROLE_PATIENT:
        patient = _patient_for_user(current_user, db)
        query = query.filter(PatientCard.patient_id == patient.patient_id if patient else -1)
    elif keyword:
        like = f"%{keyword.strip()}%"
        query = query.join(Patient).filter((PatientCard.card_no.like(like)) | Patient.name.like(like) | Patient.identity.like(like))
    items = query.order_by(PatientCard.issue_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [_card_data(item) for item in items]}


@router.post("/patientCard/issue")
def issue_patient_card(req: dict, current_user: User = Depends(require_roles(*REGISTRAR_ROLES)), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.get("patient_id")).first()
    if not patient and req.get("identity"):
        patient = db.query(Patient).filter(Patient.identity == str(req["identity"]).strip()).first()
    if not patient:
        return {"code": 404, "msg": "患者不存在"}
    active = db.query(PatientCard).filter(PatientCard.patient_id == patient.patient_id, PatientCard.status == 0).first()
    if active:
        return {"code": 400, "msg": "该患者已有有效就诊卡", "data": _card_data(active)}
    card = PatientCard(
        card_no=f"C{datetime.datetime.now():%Y%m%d}{uuid.uuid4().hex[:6].upper()}",
        patient_id=patient.patient_id,
        issuer_id=current_user.user_id,
        issue_time=datetime.datetime.now(),
    )
    db.add(card)
    db.commit()
    return {"code": 200, "msg": "就诊卡办理成功", "data": _card_data(card)}


@router.post("/patientCard/lost")
def report_patient_card_lost(req: dict, current_user: User = Depends(require_roles(*CARD_READ_ROLES)), db: Session = Depends(get_db)):
    card = db.query(PatientCard).filter(PatientCard.card_id == req.get("card_id")).first()
    if not card:
        return {"code": 404, "msg": "就诊卡不存在"}
    if current_user.user_role == ROLE_PATIENT:
        patient = _patient_for_user(current_user, db)
        if not patient or card.patient_id != patient.patient_id:
            return {"code": 403, "msg": "无权操作该就诊卡"}
    if card.status != 0:
        return {"code": 400, "msg": "只有有效就诊卡可以挂失"}
    card.status = 1
    card.lost_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "就诊卡已挂失", "data": _card_data(card)}


@router.post("/patientCard/cancel")
def cancel_patient_card(req: dict, current_user: User = Depends(require_roles(*REGISTRAR_ROLES)), db: Session = Depends(get_db)):
    card = db.query(PatientCard).filter(PatientCard.card_id == req.get("card_id")).first()
    if not card:
        return {"code": 404, "msg": "就诊卡不存在"}
    if card.status == 2:
        return {"code": 400, "msg": "就诊卡已注销"}
    card.status = 2
    card.cancel_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "就诊卡已注销", "data": _card_data(card)}
