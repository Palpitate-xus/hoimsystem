import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, User, require_roles
from app.models import MedicalRecordHome, MedicalRecordHomeQuality
from app.schemas import MedicalRecordHomeQualityCheckRequest

router = APIRouter()


def _serialize(item: MedicalRecordHomeQuality):
    return {
        "quality_id": item.quality_id,
        "home_id": item.home_id,
        "admission_no": item.home.admission.admission_no if item.home and item.home.admission else "",
        "patient_name": item.home.patient.name if item.home and item.home.patient else "",
        "check_item": item.check_item,
        "check_result": item.check_result,
        "check_result_text": {0: "通过", 1: "警告", 2: "错误"}.get(item.check_result, "未知"),
        "issue": item.issue or "",
        "score": item.score,
        "checker_name": item.checker.username if item.checker else "",
        "check_time": item.check_time,
    }


@router.get("/medicalRecordHomeQuality/list")
def list_quality(home_id: str | None = None, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    query = db.query(MedicalRecordHomeQuality).order_by(MedicalRecordHomeQuality.check_time.desc())
    if home_id:
        query = query.filter(MedicalRecordHomeQuality.home_id == home_id)
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in query.all()]}


@router.post("/medicalRecordHomeQuality/check")
def check_quality(req: MedicalRecordHomeQualityCheckRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    home = db.query(MedicalRecordHome).filter(MedicalRecordHome.home_id == req.home_id).first()
    if not home:
        return {"code": 500, "msg": "病案首页不存在"}
    item = MedicalRecordHomeQuality(home_id=req.home_id, check_item=req.check_item.strip(), check_result=req.check_result, issue=req.issue.strip(), score=req.score, checker_id=current_user.user_id, check_time=datetime.datetime.now())
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.get("/medicalRecordHomeQuality/summary")
def quality_summary(current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    total = db.query(func.count(MedicalRecordHomeQuality.quality_id)).scalar() or 0
    errors = db.query(func.count(MedicalRecordHomeQuality.quality_id)).filter(MedicalRecordHomeQuality.check_result == 2).scalar() or 0
    warnings = db.query(func.count(MedicalRecordHomeQuality.quality_id)).filter(MedicalRecordHomeQuality.check_result == 1).scalar() or 0
    average = db.query(func.avg(MedicalRecordHomeQuality.score)).scalar()
    return {"code": 200, "msg": "success", "data": {"total": total, "error_count": errors, "warning_count": warnings, "average_score": round(float(average), 1) if average is not None else 0}}
