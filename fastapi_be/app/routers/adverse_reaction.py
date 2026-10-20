import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.adr_status import AdrStatusWrite, describe_adr_status
from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, NURSING_ROLES, User, require_roles
from app.models import AdverseReaction

router = APIRouter()


@router.post("/adverseReaction/create")
def create_adr(req: dict, current_user: User = Depends(require_roles(*{*CLINICAL_ROLES, *NURSING_ROLES, *ADMIN_ROLES})), db: Session = Depends(get_db)):
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
def get_adr_list(current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    items = db.query(AdverseReaction).order_by(AdverseReaction.report_time.desc()).all()
    data = []
    for it in items:
        data.append(
            {
                "reaction_id": it.reaction_id,
                "patient_id": it.patient_id,
                "pharmaceutical_id": it.pharmaceutical_id,
                "patient_name": it.patient.name if it.patient else "",
                "pharmaceutical_name": it.pharmaceutical.name if it.pharmaceutical else "",
                "symptom": it.symptom,
                "severity": it.severity,
                "severity_text": {1: "轻度", 2: "中度", 3: "重度"}.get(it.severity, ""),
                "status": it.status,
                **describe_adr_status(it),
                "report_time": (it.report_time.strftime("%Y-%m-%d %H:%M:%S") if it.report_time else None) if it.report_time else "",
                "note": it.note,
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/adverseReaction/updateStatus")
def update_adr_status(req: AdrStatusWrite, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    ar = db.query(AdverseReaction).filter(AdverseReaction.reaction_id == req.reaction_id).with_for_update().populate_existing().first()
    if not ar:
        return {"code": 500, "msg": "记录不存在"}
    if req.status == 1 and ar.status == 0:
        resolution = req.resolution or "confirmed"
        if resolution != "confirmed":
            return {"code": 400, "msg": "确认ADR须使用明确的确认结果"}
    elif req.status == 2 and ar.status == 1:
        resolution = req.resolution or "processed"
        if resolution != "processed":
            return {"code": 400, "msg": "已确认ADR的处理操作须登记已处理"}
    elif req.status == 2 and ar.status == 0:
        if req.resolution != "excluded" or len(req.note) < 3:
            return {"code": 400, "msg": "排除ADR须明确选择排除并填写依据"}
        resolution = "excluded"
    elif req.status == 2 and ar.status == 2 and ar.status_resolution is None:
        if req.resolution not in {"processed", "excluded"} or len(req.note) < 3:
            return {"code": 400, "msg": "历史状态2须人工核实为已处理或已排除，并填写说明"}
        resolution = req.resolution
    else:
        return {"code": 400, "msg": f"状态迁移不合法：{ar.status} → {req.status}"}
    ar.status = req.status
    ar.status_resolution = resolution
    ar.resolution_note = req.note or None
    ar.status_reviewed_by = current_user.user_id
    ar.status_reviewed_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    db.commit()
    return {"code": 200, "msg": "success"}
