import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, NURSING_ROLES, User, require_roles
from app.models import Doctor, Patient, SkinTestOrder
from app.pharmacy_safety import get_usable_pharmaceutical
from app.schemas import SkinTestAssessRequest, SkinTestCreateRequest, SkinTestIdRequest

router = APIRouter()
VALID_RESULTS = {"negative", "positive", "invalid"}
RESULT_STATUS = {"negative": 2, "positive": 3, "invalid": 4}


def _serialize(item: SkinTestOrder):
    return {
        "id": item.skin_test_id,
        "skin_test_id": item.skin_test_id,
        "patient_id": item.patient_id,
        "patient_name": item.patient.name if item.patient else "",
        "doctor_name": item.doctor.name if item.doctor else "",
        "nurse_name": item.nurse.username if item.nurse else "",
        "pharmaceutical_id": item.pharmaceutical_id,
        "pharmaceutical_name": item.pharmaceutical.name if item.pharmaceutical else "",
        "dose": item.dose,
        "site": item.site,
        "observe_minutes": item.observe_minutes,
        "status": item.status,
        "result_note": item.result_note or "",
        "create_time": item.create_time,
        "administer_time": item.administer_time,
        "observe_time": item.observe_time,
    }


@router.post("/skinTest/create")
def create_skin_test(req: SkinTestCreateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor:
        return {"code": 500, "msg": "医生信息不存在"}
    if not db.query(Patient).filter(Patient.patient_id == req.patient_id).first():
        return {"code": 500, "msg": "患者不存在"}
    pharmaceutical, medication_error = get_usable_pharmaceutical(db, req.pharmaceutical_id)
    if medication_error:
        return {"code": 500, "msg": medication_error}
    item = SkinTestOrder(
        patient_id=req.patient_id,
        doctor_id=doctor.doctor_id,
        pharmaceutical_id=req.pharmaceutical_id,
        dose=req.dose.strip(),
        site=req.site.strip(),
        observe_minutes=req.observe_minutes,
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.get("/skinTest/list")
def list_skin_tests(current_user: User = Depends(require_roles(*(CLINICAL_ROLES | NURSING_ROLES))), db: Session = Depends(get_db)):
    items = db.query(SkinTestOrder).order_by(SkinTestOrder.create_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in items]}


@router.post("/skinTest/administer")
def administer_skin_test(req: SkinTestIdRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    updated = (
        db.query(SkinTestOrder)
        .filter(SkinTestOrder.skin_test_id == req.skin_test_id, SkinTestOrder.status == 0)
        .update({SkinTestOrder.status: 1, SkinTestOrder.nurse_id: current_user.user_id, SkinTestOrder.administer_time: datetime.datetime.now()}, synchronize_session=False)
    )
    if updated != 1:
        return {"code": 500, "msg": "皮试医嘱状态不允许执行"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/skinTest/assess")
def assess_skin_test(req: SkinTestAssessRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    if req.result not in VALID_RESULTS:
        return {"code": 500, "msg": "皮试结果必须为阴性、阳性或无效"}
    updated = (
        db.query(SkinTestOrder)
        .filter(SkinTestOrder.skin_test_id == req.skin_test_id, SkinTestOrder.status == 1, SkinTestOrder.nurse_id == current_user.user_id)
        .update({SkinTestOrder.status: RESULT_STATUS[req.result], SkinTestOrder.result_note: req.note.strip(), SkinTestOrder.observe_time: datetime.datetime.now()}, synchronize_session=False)
    )
    if updated != 1:
        return {"code": 500, "msg": "只有执行该皮试的护士可以判定结果"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/skinTest/cancel")
def cancel_skin_test(req: SkinTestIdRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    updated = (
        db.query(SkinTestOrder)
        .filter(SkinTestOrder.skin_test_id == req.skin_test_id, SkinTestOrder.status == 0)
        .update({SkinTestOrder.status: 5, SkinTestOrder.observe_time: datetime.datetime.now()}, synchronize_session=False)
    )
    if updated != 1:
        return {"code": 500, "msg": "只有未执行的皮试医嘱可以取消"}
    db.commit()
    return {"code": 200, "msg": "success"}
