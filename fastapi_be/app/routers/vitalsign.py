import datetime
import math

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import NURSING_ROLES, User, require_roles
from app.models import Patient, VitalSign
from app.schemas import VitalSignCreateRequest

router = APIRouter()


VITAL_SIGN_LIMITS = {
    "temperature": (30.0, 45.0, "体温"),
    "blood_pressure_systolic": (0, 300, "收缩压"),
    "blood_pressure_diastolic": (0, 200, "舒张压"),
    "pulse": (0, 300, "脉搏"),
    "weight": (0.0, 500.0, "体重"),
}


def _validate_vital_sign(req: VitalSignCreateRequest) -> str | None:
    """Validate measurement values before persisting a vital-sign record."""
    for field, (minimum, maximum, label) in VITAL_SIGN_LIMITS.items():
        value = getattr(req, field)
        if not math.isfinite(value) or not minimum < value < maximum:
            return f"{label}应在{minimum:g}到{maximum:g}之间"

    if req.blood_pressure_systolic <= req.blood_pressure_diastolic:
        return "收缩压必须高于舒张压"

    return None


@router.post("/vitalSign/create")
def create_vital_sign(req: VitalSignCreateRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    validation_error = _validate_vital_sign(req)
    if validation_error:
        return {"code": 400, "msg": validation_error}

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
def get_vital_sign_list(keyword: str | None = None, current_user: User = Depends(require_roles(*NURSING_ROLES)),
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
