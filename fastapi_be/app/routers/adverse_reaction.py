import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdverseReaction

router = APIRouter()


@router.post("/adverseReaction/create")
def create_adr(req: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    ar = AdverseReaction(
        patient_id=req.get("patient_id"),
        pharmaceutical_id=req.get("pharmaceutical_id"),
        symptom=req.get("symptom", ""),
        severity=req.get("severity", 1),
        report_time=datetime.datetime.now(),
        reporter_id=current_user.user_id,
        status=0,
        note=req.get("note", ""),
    )
    db.add(ar)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/adverseReaction/getList")
def get_adr_list(db: Session = Depends(get_db)):
    items = db.query(AdverseReaction).order_by(AdverseReaction.report_time.desc()).all()
    data = []
    for it in items:
        data.append(
            {
                "reaction_id": it.reaction_id,
                "patient_name": it.patient.name if it.patient else "",
                "pharmaceutical_name": it.pharmaceutical.name if it.pharmaceutical else "",
                "symptom": it.symptom,
                "severity": it.severity,
                "severity_text": {1: "轻度", 2: "中度", 3: "重度"}.get(it.severity, ""),
                "status": it.status,
                "status_text": {0: "待审核", 1: "已确认", 2: "已处理"}.get(it.status, ""),
                "report_time": str(it.report_time) if it.report_time else "",
                "note": it.note,
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/adverseReaction/updateStatus")
def update_adr_status(req: dict, db: Session = Depends(get_db)):
    ar = db.query(AdverseReaction).filter(AdverseReaction.reaction_id == req.get("reaction_id")).first()
    if not ar:
        return {"code": 500, "msg": "记录不存在"}
    ar.status = req.get("status")
    db.commit()
    return {"code": 200, "msg": "success"}
