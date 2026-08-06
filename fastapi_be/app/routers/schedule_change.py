import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, ROLE_DIRECTOR, User, require_roles
from app.models import Doctor, DoctorSchedule, ScheduleChangeRequest
from app.schemas import ScheduleChangeActionRequest, ScheduleChangeCreateRequest

router = APIRouter()
APPROVER_ROLES = ADMIN_ROLES | {ROLE_DIRECTOR}
VALID_TYPES = {"stop", "add"}


def _serialize(item: ScheduleChangeRequest):
    return {
        "id": item.request_id,
        "request_id": item.request_id,
        "doctor_id": item.doctor_id,
        "doctor_name": item.doctor.name if item.doctor else "",
        "request_type": item.request_type,
        "request_type_text": "停诊" if item.request_type == "stop" else "加号",
        "target_date": item.target_date,
        "schedule_id": item.schedule_id,
        "extra_slots": item.extra_slots,
        "reason": item.reason,
        "status": item.status,
        "status_text": {0: "待审批", 1: "已批准", 2: "已驳回"}.get(item.status, "未知"),
        "applicant_name": item.applicant.username if item.applicant else "",
        "approver_name": item.approver.username if item.approver else "",
        "create_time": item.create_time,
        "approve_time": item.approve_time,
    }


@router.post("/scheduleChange/create")
def create_schedule_change(req: ScheduleChangeCreateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    if req.request_type not in VALID_TYPES:
        return {"code": 500, "msg": "申请类型必须为停诊或加号"}
    try:
        target_date = datetime.datetime.strptime(req.target_date, "%Y-%m-%d").date()
    except ValueError:
        return {"code": 500, "msg": "日期格式必须为 YYYY-MM-DD"}
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor:
        return {"code": 500, "msg": "医生信息不存在"}
    if req.request_type == "add" and req.extra_slots <= 0:
        return {"code": 500, "msg": "加号数量必须大于0"}
    if req.request_type == "stop" and req.extra_slots != 0:
        return {"code": 500, "msg": "停诊申请不能填写加号数量"}
    if req.schedule_id and not db.query(DoctorSchedule).filter(DoctorSchedule.schedule_id == req.schedule_id, DoctorSchedule.doctor_id == doctor.doctor_id).first():
        return {"code": 500, "msg": "排班不属于当前医生"}
    item = ScheduleChangeRequest(doctor_id=doctor.doctor_id, schedule_id=req.schedule_id, request_type=req.request_type, target_date=target_date, extra_slots=req.extra_slots, reason=req.reason.strip(), status=0, applicant_id=current_user.user_id, create_time=datetime.datetime.now())
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.get("/scheduleChange/list")
def list_schedule_changes(current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    query = db.query(ScheduleChangeRequest).order_by(ScheduleChangeRequest.create_time.desc())
    if current_user.user_role not in APPROVER_ROLES:
        doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
        query = query.filter(ScheduleChangeRequest.doctor_id == (doctor.doctor_id if doctor else -1))
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in query.all()]}


def _act(request_id: str, current_user: User, db: Session, status: int):
    item = db.query(ScheduleChangeRequest).filter(ScheduleChangeRequest.request_id == request_id, ScheduleChangeRequest.status == 0).first()
    if not item:
        return None, {"code": 500, "msg": "申请不存在或已处理"}
    if item.applicant_id == current_user.user_id:
        return None, {"code": 500, "msg": "申请人不能审批自己的申请"}
    item.status = status
    item.approver_id = current_user.user_id
    item.approve_time = datetime.datetime.now()
    return item, None


@router.post("/scheduleChange/approve")
def approve_schedule_change(req: ScheduleChangeActionRequest, current_user: User = Depends(require_roles(*APPROVER_ROLES)), db: Session = Depends(get_db)):
    item, error = _act(req.request_id, current_user, db, 1)
    if error:
        return error
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/scheduleChange/reject")
def reject_schedule_change(req: ScheduleChangeActionRequest, current_user: User = Depends(require_roles(*APPROVER_ROLES)), db: Session = Depends(get_db)):
    item, error = _act(req.request_id, current_user, db, 2)
    if error:
        return error
    db.commit()
    return {"code": 200, "msg": "success"}
