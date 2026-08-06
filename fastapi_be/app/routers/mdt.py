import datetime
import re

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, ROLE_DIRECTOR, User, get_current_user, require_roles
from app.models import Department, Doctor, MdtCase

router = APIRouter()


def _resolve_dept_names(department_ids_str, db):
    """解析 department_ids 字符串，返回科室名字列表"""
    if not department_ids_str:
        return []
    import re
    ids = [int(s) for s in re.findall(r'\d+', str(department_ids_str))]
    if not ids:
        return []
    depts = db.query(Department).filter(Department.department_id.in_(ids)).all()
    name_map = {d.department_id: d.name for d in depts}
    return [name_map.get(i, f"科室{i}") for i in ids]


@router.post("/mdt/create")
def create_mdt(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    m = MdtCase(
        patient_id=req.get("patient_id"),
        diagnosis=req.get("diagnosis", ""),
        department_ids=req.get("department_ids", ""),
        status=0,
        create_time=datetime.datetime.now(),
        applicant_id=current_user.user_id,
    )
    db.add(m)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/mdt/getList")
def get_mdt_list(current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    items = db.query(MdtCase).order_by(MdtCase.create_time.desc()).all()
    data = []
    for it in items:
        data.append(
            {
                "mdt_id": it.mdt_id,
                "patient_name": it.patient.name if it.patient else "",
                "diagnosis": it.diagnosis,
                "department_ids": it.department_ids,
                "department_names": _resolve_dept_names(it.department_ids, db),
                "status": it.status,
                "status_text": {0: "待审批", 1: "会诊中", 2: "已完成", 3: "已退回"}.get(it.status, ""),
                "result": it.result,
                "applicant_name": it.applicant.username if it.applicant else "",
                "review_note": it.review_note or "",
                "create_time": (it.create_time.strftime("%Y-%m-%d %H:%M:%S") if it.create_time else None) if it.create_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/mdt/update")
def update_mdt(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    m = db.query(MdtCase).filter(MdtCase.mdt_id == req.get("mdt_id")).first()
    if not m:
        return {"code": 500, "msg": "记录不存在"}
    if "status" in req:
        m.status = req["status"]
    if "result" in req:
        m.result = req["result"]
    db.commit()
    return {"code": 200, "msg": "success"}


def _approval_scope(current_user: User, db: Session):
    if current_user.user_role in ADMIN_ROLES:
        return None
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if current_user.user_role == ROLE_DIRECTOR and doctor and doctor.department_id:
        return doctor.department_id
    return 0


@router.get("/mdt/approvalList")
def get_mdt_approval_list(current_user: User = Depends(require_roles(*ADMIN_ROLES, ROLE_DIRECTOR)), db: Session = Depends(get_db)):
    scope = _approval_scope(current_user, db)
    items = db.query(MdtCase).filter(MdtCase.status == 0).order_by(MdtCase.create_time.desc()).all()
    if scope is not None:
        scoped = []
        for item in items:
            if str(scope) in [part.strip() for part in (item.department_ids or "").strip("[]").replace('"', "").split(",")]:
                scoped.append(item)
        items = scoped
    return {
        "code": 200,
        "msg": "success",
        "data": [
            {
                "mdt_id": item.mdt_id,
                "patient_name": item.patient.name if item.patient else "",
                "diagnosis": item.diagnosis or "",
                "department_names": _resolve_dept_names(item.department_ids, db),
                "applicant_name": item.applicant.username if item.applicant else "",
                "create_time": item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else "",
            }
            for item in items
        ],
    }


@router.post("/mdt/approval")
def approve_mdt(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES, ROLE_DIRECTOR)), db: Session = Depends(get_db)):
    case = db.query(MdtCase).filter(MdtCase.mdt_id == req.get("mdt_id"), MdtCase.status == 0).first()
    if not case:
        return {"code": 404, "msg": "待审批会诊不存在"}
    scope = _approval_scope(current_user, db)
    department_ids = {int(part) for part in re.findall(r"\d+", case.department_ids or "")}
    if scope is not None and scope not in department_ids:
        return {"code": 403, "msg": "无权审批未涉及本科室的会诊"}
    status = req.get("status")
    if status not in (1, 2):
        return {"code": 400, "msg": "审批状态必须为1(通过)或2(退回)"}
    case.status = 1 if status == 1 else 3
    case.reviewer_id = current_user.user_id
    case.review_time = datetime.datetime.now()
    case.review_note = req.get("note", "")
    db.commit()
    return {"code": 200, "msg": "审批完成"}
