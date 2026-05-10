import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdverseEvent

router = APIRouter()


@router.post("/adverseEvent/create")
def create_event(req: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    ev = AdverseEvent(
        event_type=req.get("event_type", ""),
        patient_id=req.get("patient_id"),
        description=req.get("description", ""),
        severity=req.get("severity", 1),
        reporter_id=current_user.user_id,
        report_time=datetime.datetime.now(),
        status=0,
    )
    db.add(ev)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/adverseEvent/getList")
def get_event_list(db: Session = Depends(get_db)):
    items = db.query(AdverseEvent).order_by(AdverseEvent.report_time.desc()).all()
    data = []
    for it in items:
        data.append(
            {
                "event_id": it.event_id,
                "event_type": it.event_type,
                "patient_name": it.patient.name if it.patient else "",
                "description": it.description,
                "severity": it.severity,
                "severity_text": {1: "轻度", 2: "中度", 3: "重度"}.get(it.severity, ""),
                "status": it.status,
                "status_text": {0: "待处理", 1: "处理中", 2: "已闭环"}.get(it.status, ""),
                "report_time": str(it.report_time) if it.report_time else "",
                "handle_result": it.handle_result,
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/adverseEvent/updateStatus")
def update_event_status(req: dict, db: Session = Depends(get_db)):
    ev = db.query(AdverseEvent).filter(AdverseEvent.event_id == req.get("event_id")).first()
    if not ev:
        return {"code": 500, "msg": "记录不存在"}
    ev.status = req.get("status")
    if req.get("handle_result"):
        ev.handle_result = req.get("handle_result")
    db.commit()
    return {"code": 200, "msg": "success"}
