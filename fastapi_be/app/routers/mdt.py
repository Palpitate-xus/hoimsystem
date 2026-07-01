import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import User, get_current_user, require_roles, CLINICAL_ROLES
from app.models import Department, MdtCase

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
                "status_text": {0: "待会诊", 1: "会诊中", 2: "已完成"}.get(it.status, ""),
                "result": it.result,
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
