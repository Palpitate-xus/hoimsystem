import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, User, require_roles
from app.models import MedicalRecordArchive, MedicalRecordHome
from app.schemas import MedicalRecordArchiveActionRequest, MedicalRecordArchiveCreateRequest

router = APIRouter()
ARCHIVE_ADMIN_ROLES = ADMIN_ROLES | {"director"}


def _serialize(item: MedicalRecordArchive):
    home = item.home
    return {
        "archive_id": item.archive_id,
        "home_id": item.home_id,
        "archive_no": item.archive_no,
        "admission_no": home.admission.admission_no if home and home.admission else "",
        "patient_name": home.patient.name if home and home.patient else "",
        "doctor_name": home.doctor.name if home and home.doctor else "",
        "location": item.location or "",
        "status": item.status,
        "status_text": {0: "待归档", 1: "已归档", 2: "借阅中", 3: "已封存"}.get(item.status, "未知"),
        "borrow_reason": item.borrow_reason or "",
        "borrower_name": item.borrower.username if item.borrower else "",
        "borrow_status": item.borrow_status or 0,
        "borrow_status_text": {0: "无申请", 1: "待审批", 2: "已批准借出", 3: "已驳回"}.get(item.borrow_status or 0, "未知"),
        "approver_name": item.approver.username if item.approver else "",
        "approve_time": item.approve_time,
        "reject_reason": item.reject_reason or "",
        "seal_reason": item.seal_reason or "",
        "archive_time": item.archive_time,
        "borrow_time": item.borrow_time,
        "return_time": item.return_time,
        "create_time": item.create_time,
        "update_time": item.update_time,
    }


def _next_archive_no(db: Session) -> str:
    today = datetime.datetime.now().strftime("%Y%m%d")
    return f"BA{today}{db.query(MedicalRecordArchive).filter(MedicalRecordArchive.archive_no.like(f'BA{today}%')).count() + 1:04d}"


@router.get("/medicalRecordArchive/list")
def list_archives(current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in db.query(MedicalRecordArchive).order_by(MedicalRecordArchive.update_time.desc()).all()]}


@router.post("/medicalRecordArchive/create")
def create_archive(req: MedicalRecordArchiveCreateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    location = req.location.strip()
    if not location:
        return {"code": 500, "msg": "归档位置不能为空"}
    home = db.query(MedicalRecordHome).filter(MedicalRecordHome.home_id == req.home_id).first()
    if not home:
        return {"code": 500, "msg": "病案首页不存在"}
    if home.status != 1:
        return {"code": 500, "msg": "只有已提交的病案首页可以归档"}
    if db.query(MedicalRecordArchive).filter(MedicalRecordArchive.home_id == req.home_id).first():
        return {"code": 500, "msg": "该病案首页已建立归档记录"}
    now = datetime.datetime.now()
    item = MedicalRecordArchive(home_id=req.home_id, archive_no=_next_archive_no(db), location=location, status=0, create_time=now, update_time=now)
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.post("/medicalRecordArchive/archive")
def archive_record(req: MedicalRecordArchiveActionRequest, current_user: User = Depends(require_roles(*ARCHIVE_ADMIN_ROLES)), db: Session = Depends(get_db)):
    item = db.query(MedicalRecordArchive).filter(MedicalRecordArchive.archive_id == req.archive_id).first()
    if not item:
        return {"code": 500, "msg": "归档记录不存在"}
    if item.status != 0:
        return {"code": 500, "msg": "当前状态不可归档"}
    now = datetime.datetime.now()
    item.status = 1
    item.archived_by = current_user.user_id
    item.archive_time = now
    item.update_time = now
    item.home.status = 2
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.post("/medicalRecordArchive/borrow")
def borrow_record(req: MedicalRecordArchiveActionRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    """提交借阅申请（进入待审批，审批通过后方可借出）。"""
    item = db.query(MedicalRecordArchive).filter(MedicalRecordArchive.archive_id == req.archive_id).first()
    if not item:
        return {"code": 500, "msg": "归档记录不存在"}
    if item.status != 1:
        return {"code": 500, "msg": "只有已归档病案可以申请借阅"}
    if item.borrow_status == 1:
        return {"code": 500, "msg": "已有待审批的借阅申请"}
    if item.borrow_status == 2 and item.status == 2:
        return {"code": 500, "msg": "病案已在借阅中，不能重复申请"}
    reason = req.reason.strip()
    if not reason:
        return {"code": 500, "msg": "借阅事由不能为空"}
    now = datetime.datetime.now()
    item.borrow_status = 1
    item.borrower_id = current_user.user_id
    item.borrow_reason = reason
    item.reject_reason = None
    item.update_time = now
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.get("/medicalRecordArchive/borrowRequests")
def list_borrow_requests(borrow_status: int | None = None, current_user: User = Depends(require_roles(*ARCHIVE_ADMIN_ROLES)), db: Session = Depends(get_db)):
    """病案管理员审批工作台：待审批/全部借阅申请。"""
    query = db.query(MedicalRecordArchive).filter(MedicalRecordArchive.borrow_status > 0)
    if borrow_status is not None:
        query = query.filter(MedicalRecordArchive.borrow_status == borrow_status)
    rows = query.order_by(MedicalRecordArchive.update_time.desc()).limit(500).all()
    return {"code": 200, "msg": "success", "data": [_serialize(i) for i in rows]}


@router.post("/medicalRecordArchive/borrowApprove")
def approve_borrow(req: MedicalRecordArchiveActionRequest, current_user: User = Depends(require_roles(*ARCHIVE_ADMIN_ROLES)), db: Session = Depends(get_db)):
    """审批借阅申请：approve=True 借出（status→2 借阅中），False 驳回（必填驳回原因）。"""
    item = db.query(MedicalRecordArchive).filter(MedicalRecordArchive.archive_id == req.archive_id).first()
    if not item:
        return {"code": 500, "msg": "归档记录不存在"}
    if item.borrow_status != 1:
        return {"code": 500, "msg": "当前没有待审批的借阅申请"}
    approve = bool(req.approve) if req.approve is not None else True
    now = datetime.datetime.now()
    item.approver_id = current_user.user_id
    item.approve_time = now
    item.update_time = now
    if approve:
        item.borrow_status = 2
        item.status = 2  # 借阅中
        item.borrow_time = now
    else:
        reject_reason = (req.reason or "").strip()
        if not reject_reason:
            return {"code": 500, "msg": "驳回必须填写原因"}
        item.borrow_status = 3
        item.reject_reason = reject_reason
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.post("/medicalRecordArchive/return")
def return_record(req: MedicalRecordArchiveActionRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    item = db.query(MedicalRecordArchive).filter(MedicalRecordArchive.archive_id == req.archive_id).first()
    if not item:
        return {"code": 500, "msg": "归档记录不存在"}
    if item.status != 2:
        return {"code": 500, "msg": "当前病案不在借阅中"}
    # 归还人校验：借阅人本人或病案管理员（防他人伪造归还时间线）
    from app.dependencies import ADMIN_ROLES

    if current_user.user_role not in ADMIN_ROLES and item.borrower_id != current_user.user_id:
        return {"code": 403, "msg": "仅借阅人本人或管理员可归还病案"}
    item.status = 1
    item.borrow_status = 0  # 归还后重置借阅审批流，可再次发起新申请
    item.return_time = datetime.datetime.now()
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.post("/medicalRecordArchive/seal")
def seal_record(req: MedicalRecordArchiveActionRequest, current_user: User = Depends(require_roles(*ARCHIVE_ADMIN_ROLES)), db: Session = Depends(get_db)):
    item = db.query(MedicalRecordArchive).filter(MedicalRecordArchive.archive_id == req.archive_id).first()
    if not item:
        return {"code": 500, "msg": "归档记录不存在"}
    if item.status not in (1, 2):
        return {"code": 500, "msg": "当前状态不可封存"}
    reason = req.reason.strip()
    if not reason:
        return {"code": 500, "msg": "封存原因不能为空"}
    item.status = 3
    item.seal_reason = reason
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}
