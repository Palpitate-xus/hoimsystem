import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, ROLE_DIRECTOR, User, require_roles
from app.models import Doctor, Referral

router = APIRouter()


@router.post("/referral/create")
def create_referral(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    r = Referral(
        patient_id=req.get("patient_id"),
        from_department_id=req.get("from_department_id"),
        to_department_id=req.get("to_department_id"),
        referral_type=req.get("referral_type", "up"),
        reason=req.get("reason", ""),
        status=0,
        create_time=datetime.datetime.now(),
        applicant_id=current_user.user_id,
    )
    db.add(r)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/referral/getList")
def get_referral_list(current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    items = db.query(Referral).order_by(Referral.create_time.desc()).all()
    data = []
    for it in items:
        data.append(
            {
                "referral_id": it.referral_id,
                "patient_name": it.patient.name if it.patient else "",
                "from_department": it.from_department.name if it.from_department else "",
                "to_department": it.to_department.name if it.to_department else "",
                "referral_type": "上转" if it.referral_type == "up" else "下转",
                "reason": it.reason,
                "status": it.status,
                "status_text": {0: "待接收", 1: "已接收", 2: "已退回"}.get(it.status, ""),
                "applicant_name": it.applicant.username if it.applicant else "",
                "review_note": it.review_note or "",
                "create_time": (it.create_time.strftime("%Y-%m-%d %H:%M:%S") if it.create_time else None) if it.create_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/referral/updateStatus")
def update_referral_status(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    r = db.query(Referral).filter(Referral.referral_id == req.get("referral_id")).first()
    if not r:
        return {"code": 500, "msg": "记录不存在"}
    r.status = req.get("status")
    db.commit()
    return {"code": 200, "msg": "success"}


def _approval_scope(current_user: User, db: Session):
    if current_user.user_role in ADMIN_ROLES:
        return None
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if current_user.user_role == ROLE_DIRECTOR and doctor and doctor.department_id:
        return {doctor.department_id}
    return set()


@router.get("/referral/approvalList")
def get_referral_approval_list(current_user: User = Depends(require_roles(*ADMIN_ROLES, ROLE_DIRECTOR)), db: Session = Depends(get_db)):
    scope = _approval_scope(current_user, db)
    query = db.query(Referral).filter(Referral.status == 0)
    if scope is not None:
        query = query.filter(Referral.from_department_id.in_(scope))
    items = query.order_by(Referral.create_time.desc()).all()
    return {
        "code": 200,
        "msg": "success",
        "data": [
            {
                "referral_id": item.referral_id,
                "patient_name": item.patient.name if item.patient else "",
                "from_department": item.from_department.name if item.from_department else "",
                "to_department": item.to_department.name if item.to_department else "",
                "reason": item.reason or "",
                "applicant_name": item.applicant.username if item.applicant else "",
                "create_time": item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else "",
            }
            for item in items
        ],
    }


@router.post("/referral/approval")
def approve_referral(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES, ROLE_DIRECTOR)), db: Session = Depends(get_db)):
    referral = db.query(Referral).filter(Referral.referral_id == req.get("referral_id"), Referral.status == 0).first()
    if not referral:
        return {"code": 404, "msg": "待审批转诊不存在"}
    scope = _approval_scope(current_user, db)
    if scope is not None and referral.from_department_id not in scope:
        return {"code": 403, "msg": "无权审批其他科室转诊"}
    status = req.get("status")
    if status not in (1, 2):
        return {"code": 400, "msg": "审批状态必须为1(通过)或2(退回)"}
    referral.status = status
    referral.reviewer_id = current_user.user_id
    referral.review_time = datetime.datetime.now()
    referral.review_note = req.get("note", "")
    db.commit()
    return {"code": 200, "msg": "审批完成"}
