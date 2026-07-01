import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, User, User, require_roles, NURSING_ROLES
from app.models import Patient, VitalSign
from app.schemas import VitalSignCreateRequest

router = APIRouter()


@router.post("/vitalSign/create")
def create_vital_sign(req: VitalSignCreateRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.patient_id).first()
    if not patient:
        return {"code": 500, "msg": "病人不存在"}
    vital = VitalSign(
        patient_id=req.patient_id,
        nurse_id=current_user.user_id,
        temperature=req.temperature,
        blood_pressure_systolic=req.blood_pressure_systolic,
        blood_pressure_diastolic=req.blood_pressure_diastolic,
        pulse=req.pulse,
        weight=req.weight,
        check_time=datetime.datetime.now(),
    )
    db.add(vital)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/vitalSign/getList")
def get_vital_sign_list(keyword: str | None = None, current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    vitals = db.query(VitalSign).order_by(VitalSign.check_time.desc()).all()
    data = []
    for item in vitals:
        data.append(
            {
                "id": item.vital_id,
                "patient_name": item.patient.name if item.patient else "",
                "temperature": item.temperature,
                "blood_pressure": f"{item.blood_pressure_systolic}/{item.blood_pressure_diastolic}",
                "pulse": item.pulse,
                "weight": item.weight,
                "check_time": (item.check_time.strftime("%Y-%m-%d %H:%M:%S") if item.check_time else None),
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}
