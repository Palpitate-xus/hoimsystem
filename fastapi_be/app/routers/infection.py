import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, NURSING_ROLES, ROLE_DIRECTOR, User, get_current_user, require_roles
from app.models import Department, DisinfectionMonitor, InfectionCase, OccupationalExposure, Patient

router = APIRouter()
REPORT_ROLES = {*ADMIN_ROLES, ROLE_DIRECTOR}
OPERATE_ROLES = {*CLINICAL_ROLES, *NURSING_ROLES}


def _case_data(item: InfectionCase):
    return {"case_id": item.case_id, "patient_name": item.patient.name if item.patient else "", "department_name": item.department.name if item.department else "", "infection_type": item.infection_type, "pathogen": item.pathogen or "", "onset_date": str(item.onset_date), "severity": item.severity, "status": item.status, "status_text": {0: "已报告", 1: "调查中", 2: "已闭环"}.get(item.status, ""), "description": item.description or "", "create_time": item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else ""}


@router.get("/infection/case/list")
def list_infection_cases(current_user: User = Depends(require_roles(*OPERATE_ROLES)), db: Session = Depends(get_db)):
    return {"code": 200, "msg": "success", "data": [_case_data(item) for item in db.query(InfectionCase).order_by(InfectionCase.create_time.desc()).all()]}


@router.post("/infection/case/create")
def create_infection_case(req: dict, current_user: User = Depends(require_roles(*OPERATE_ROLES)), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.get("patient_id")).first()
    if not patient or not req.get("infection_type"):
        return {"code": 400, "msg": "患者和感染类型不能为空"}
    try:
        onset_date = datetime.datetime.strptime(req.get("onset_date"), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {"code": 400, "msg": "发病日期格式必须为YYYY-MM-DD"}
    now = datetime.datetime.now()
    item = InfectionCase(patient_id=patient.patient_id, department_id=req.get("department_id"), infection_type=req["infection_type"], pathogen=req.get("pathogen"), onset_date=onset_date, severity=int(req.get("severity", 1)), description=req.get("description", ""), reporter_id=current_user.user_id, create_time=now, update_time=now)
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"case_id": item.case_id}}


@router.post("/infection/case/status")
def update_infection_case_status(req: dict, current_user: User = Depends(require_roles(*REPORT_ROLES)), db: Session = Depends(get_db)):
    item = db.query(InfectionCase).filter(InfectionCase.case_id == req.get("case_id")).first()
    if not item or req.get("status") not in (0, 1, 2):
        return {"code": 400, "msg": "记录或状态不合法"}
    # 状态机：已报告(0)→调查中(1)→已闭环(2)，只能前进不能回退/跳转
    allowed = {0: {1}, 1: {2}, 2: set()}
    if req["status"] not in allowed.get(item.status, set()):
        return {"code": 400, "msg": f"状态迁移不合法：{item.status} → {req['status']}"}
    item.status = req["status"]
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/infection/outbreakAlert")
def infection_outbreak_alert(days: int = 30, current_user: User = Depends(require_roles(*REPORT_ROLES)), db: Session = Depends(get_db)):
    start = datetime.date.today() - datetime.timedelta(days=max(1, min(days, 365)))
    rows = db.query(InfectionCase.infection_type, InfectionCase.pathogen, func.count(InfectionCase.case_id)).filter(InfectionCase.onset_date >= start).group_by(InfectionCase.infection_type, InfectionCase.pathogen).all()
    alerts = [{"infection_type": infection_type, "pathogen": pathogen or "未检出", "case_count": count, "alert": count >= 3} for infection_type, pathogen, count in rows]
    return {"code": 200, "msg": "success", "data": alerts}


@router.get("/infection/report")
def infection_report(start_date: str | None = None, end_date: str | None = None, current_user: User = Depends(require_roles(*REPORT_ROLES)), db: Session = Depends(get_db)):
    query = db.query(InfectionCase)
    if start_date:
        query = query.filter(InfectionCase.onset_date >= start_date)
    if end_date:
        query = query.filter(InfectionCase.onset_date <= end_date)
    items = query.all()
    return {"code": 200, "msg": "success", "data": {"total_cases": len(items), "closed_cases": sum(item.status == 2 for item in items), "high_severity_cases": sum(item.severity >= 3 for item in items), "by_type": [{"infection_type": name, "count": count} for name, count in db.query(InfectionCase.infection_type, func.count(InfectionCase.case_id)).filter(InfectionCase.case_id.in_([item.case_id for item in items]) if items else False).group_by(InfectionCase.infection_type).all()]}}


@router.get("/infection/disinfection/list")
def list_disinfection(current_user: User = Depends(require_roles(*OPERATE_ROLES)), db: Session = Depends(get_db)):
    items = db.query(DisinfectionMonitor).order_by(DisinfectionMonitor.monitor_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [{"monitor_id": item.monitor_id, "area": item.area, "item": item.item, "result": item.result, "standard": item.standard or "", "pass_flag": item.pass_flag, "remark": item.remark or "", "monitor_time": item.monitor_time.strftime("%Y-%m-%d %H:%M:%S")} for item in items]}


@router.post("/infection/disinfection/create")
def create_disinfection(req: dict, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    item = DisinfectionMonitor(area=req.get("area", "").strip(), item=req.get("item", "").strip(), result=req.get("result", "").strip(), standard=req.get("standard"), pass_flag=int(req.get("pass_flag", 1)), remark=req.get("remark"), operator_id=current_user.user_id, monitor_time=datetime.datetime.now())
    if not item.area or not item.item or not item.result:
        return {"code": 400, "msg": "区域、监测项目和结果不能为空"}
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/infection/exposure/list")
def list_exposure(current_user: User = Depends(require_roles(*OPERATE_ROLES)), db: Session = Depends(get_db)):
    items = db.query(OccupationalExposure).order_by(OccupationalExposure.exposure_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [{"exposure_id": item.exposure_id, "exposure_type": item.exposure_type, "body_site": item.body_site, "description": item.description, "action_taken": item.action_taken or "", "status": item.status, "status_text": {0: "待处理", 1: "处理中", 2: "已结案"}.get(item.status, ""), "exposure_time": item.exposure_time.strftime("%Y-%m-%d %H:%M:%S")} for item in items]}


@router.post("/infection/exposure/create")
def create_exposure(req: dict, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    item = OccupationalExposure(exposure_type=req.get("exposure_type", "").strip(), source_patient_id=req.get("source_patient_id"), body_site=req.get("body_site", "").strip(), description=req.get("description", "").strip(), action_taken=req.get("action_taken"), reporter_id=current_user.user_id, exposure_time=datetime.datetime.now(), create_time=datetime.datetime.now())
    if not item.exposure_type or not item.body_site or not item.description:
        return {"code": 400, "msg": "暴露类型、暴露部位和经过不能为空"}
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/infection/exposure/handle")
def handle_exposure(req: dict, current_user: User = Depends(require_roles(*OPERATE_ROLES)), db: Session = Depends(get_db)):
    """职业暴露处置：登记处置措施并推进状态（0→1→2）。"""
    item = db.query(OccupationalExposure).filter(OccupationalExposure.exposure_id == req.get("exposure_id")).first()
    if not item:
        return {"code": 500, "msg": "暴露记录不存在"}
    action = str(req.get("action_taken", "")).strip()
    if not action:
        return {"code": 400, "msg": "处置措施不能为空"}
    target = req.get("status")
    if target not in (1, 2):
        return {"code": 400, "msg": "目标状态必须为1(处理中)或2(已结案)"}
    allowed = {0: {1, 2}, 1: {2}, 2: set()}
    if target not in allowed.get(item.status, set()):
        return {"code": 400, "msg": f"状态迁移不合法：{item.status} → {target}"}
    item.action_taken = ((item.action_taken or "") + ("；" if item.action_taken else "") + action)[:500]
    item.status = target
    db.commit()
    return {"code": 200, "msg": "success"}
