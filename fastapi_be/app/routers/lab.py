import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, LAB_ROLES, require_roles
from app.models import LabOrder, LabResult, Message, SampleTracking, User
from app.schemas import LabCriticalActionRequest, LabResultAuditRequest, LabResultCreateRequest

router = APIRouter()


def _record_tracking(db: Session, lab_order_id: str, stage: str, current_user: User, note: str = ""):
    db.add(SampleTracking(lab_order_id=lab_order_id, stage=stage, operator_id=current_user.user_id, event_time=datetime.datetime.now(), note=note))


def check_critical_value(check_type: str, result_text: str) -> bool:
    """简单危急值判断逻辑"""
    result_lower = result_text.lower()
    # 血压危急值
    if "血压" in check_type or "blood pressure" in result_lower:
        try:
            import re

            nums = re.findall(r"\d+", result_text)
            if len(nums) >= 2:
                sbp, dbp = int(nums[0]), int(nums[1])
                return sbp >= 180 or sbp <= 90 or dbp >= 110 or dbp <= 60
        except Exception:
            pass
    # 血糖危急值
    if "血糖" in check_type or "glucose" in result_lower:
        try:
            import re

            nums = re.findall(r"\d+\.?\d*", result_text)
            if nums:
                val = float(nums[0])
                return val >= 16.7 or val <= 2.8
        except Exception:
            pass
    # 心率危急值
    if "心率" in check_type or "heart rate" in result_lower:
        try:
            import re

            nums = re.findall(r"\d+", result_text)
            if nums:
                val = int(nums[0])
                return val >= 120 or val <= 50
        except Exception:
            pass
    return False


@router.post("/lab/sampleReceive")
def sample_receive(req: dict, current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    """样本接收"""
    lab_order = db.query(LabOrder).filter(LabOrder.lab_order_id == req.get("lab_order_id")).first()
    if not lab_order:
        return {"code": 500, "msg": "检查申请单不存在"}
    if lab_order.status != 0 or lab_order.sample_status != 0:
        return {"code": 500, "msg": "当前检查申请单不允许接收样本"}
    lab_order.sample_status = 1
    _record_tracking(db, lab_order.lab_order_id, "样本已接收", current_user)
    db.add(lab_order)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/lab/sampleReject")
def sample_reject(req: dict, current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    """样本拒收"""
    lab_order = db.query(LabOrder).filter(LabOrder.lab_order_id == req.get("lab_order_id")).first()
    if not lab_order:
        return {"code": 500, "msg": "检查申请单不存在"}
    if lab_order.status != 0 or lab_order.sample_status not in (0, 1):
        return {"code": 500, "msg": "当前检查申请单不允许拒收样本"}
    lab_order.sample_status = 2
    _record_tracking(db, lab_order.lab_order_id, "样本已拒收", current_user, req.get("reason", ""))
    db.add(lab_order)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/lab/sampleTracking")
def sample_tracking(lab_order_id: str, current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    """样本流转跟踪"""
    lab_order = db.query(LabOrder).filter(LabOrder.lab_order_id == lab_order_id).first()
    if not lab_order:
        return {"code": 500, "msg": "检查申请单不存在"}
    events = db.query(SampleTracking).filter(SampleTracking.lab_order_id == lab_order_id).order_by(SampleTracking.event_time.asc()).all()
    tracking = [{"time": (lab_order.create_time.strftime("%Y-%m-%d %H:%M:%S") if lab_order.create_time else None), "stage": "申请创建", "operator": lab_order.doctor.name if lab_order.doctor else ""}]
    tracking.extend(
        {
            "time": item.event_time.strftime("%Y-%m-%d %H:%M:%S"),
            "stage": item.stage,
            "operator": item.operator.username if item.operator else "",
            "note": item.note or "",
        }
        for item in events
    )
    return {"code": 200, "msg": "success", "data": tracking}


@router.post("/labResult/create")
def create_lab_result(req: LabResultCreateRequest, current_user=Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    lab_order = db.query(LabOrder).filter(LabOrder.lab_order_id == req.lab_order_id).first()
    if not lab_order:
        return {"code": 500, "msg": "检查申请单不存在"}
    if lab_order.sample_status != 1:
        return {"code": 500, "msg": "样本尚未接收，不能录入结果"}
    if lab_order.status != 0 or lab_order.lab_results:
        return {"code": 500, "msg": "当前检查申请单已录入结果"}
    is_critical = check_critical_value(lab_order.check_type or "", req.result or "")
    result = LabResult(
        lab_order_id=req.lab_order_id,
        sample_id=req.sample_id,
        result=req.result,
        abnormal_flag=1 if is_critical else req.abnormal_flag,
        technician_id=current_user.user_id,
        report_time=datetime.datetime.now(),
        audit_status=0,
        critical_status=1 if is_critical else 0,
    )
    db.add(result)
    _record_tracking(db, lab_order.lab_order_id, "结果已录入", current_user)
    lab_order.status = 1
    db.add(lab_order)
    db.commit()
    msg = "success"
    if is_critical:
        msg = "结果已录入，检测到危急值！"
    return {"code": 200, "msg": msg, "data": {"critical": is_critical}}


@router.post("/labResult/audit")
def audit_lab_result(req: LabResultAuditRequest, current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    result = db.query(LabResult).filter(LabResult.lab_result_id == req.lab_result_id).first()
    if not result:
        return {"code": 500, "msg": "检查结果不存在"}
    if result.audit_status != 0 or not result.lab_order or result.lab_order.status != 1:
        return {"code": 500, "msg": "当前检查结果不允许审核"}
    result.audit_status = 1
    if result.lab_order:
        result.lab_order.status = 2
        db.add(result.lab_order)
    db.add(result)
    _record_tracking(db, result.lab_order.lab_order_id, "结果已审核", current_user)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/labResult/getPending")
def get_pending_lab_orders(keyword: str | None = None, current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    orders = db.query(LabOrder).filter(LabOrder.status == 0).order_by(LabOrder.create_time.desc()).all()
    data = []
    for item in orders:
        data.append(
            {
                "id": str(item.lab_order_id),
                "patient_name": item.patient.name if item.patient else "",
                "check_type": item.check_type,
                "status": item.status,
                "sample_status": item.sample_status,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None),
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/labResult/getList")
def get_lab_result_list(keyword: str | None = None, current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    results = db.query(LabResult).order_by(LabResult.report_time.desc()).all()
    data = []
    for item in results:
        data.append(
            {
                "id": str(item.lab_result_id),
                "check_name": item.lab_order.check_type if item.lab_order else "",
                "check_time": (item.report_time.strftime("%Y-%m-%d %H:%M:%S") if item.report_time else None),
                "result": item.result,
                "abnormal_flag": item.abnormal_flag,
                "technician_name": item.technician.username if item.technician else "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/labResult/getCritical")
def get_critical_lab_results(current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    results = db.query(LabResult).filter(LabResult.abnormal_flag == 1).order_by(LabResult.report_time.desc()).all()
    data = []
    for item in results:
        data.append({
            "id": str(item.lab_result_id),
            "patient_name": item.lab_order.patient.name if item.lab_order and item.lab_order.patient else "",
            "check_name": item.lab_order.check_type if item.lab_order else "",
            "check_time": (item.report_time.strftime("%Y-%m-%d %H:%M:%S") if item.report_time else None),
            "result": item.result,
            "audit_status": item.audit_status,
            "audit_status_text": "已审核" if item.audit_status else "待审核",
            "critical_status": item.critical_status,
            "critical_status_text": {
                1: "待通知", 2: "已通知", 3: "已确认", 4: "已处理"
            }.get(item.critical_status, "非危急"),
            "critical_notified_time": item.critical_notified_time,
            "critical_acknowledged_time": item.critical_acknowledged_time,
            "critical_handled_time": item.critical_handled_time,
            "critical_handling_note": item.critical_handling_note,
            "technician_name": item.technician.username if item.technician else "",
        })
    return {"code": 200, "msg": "success", "data": data}


def _critical_result(db: Session, lab_result_id: str):
    return db.query(LabResult).filter(LabResult.lab_result_id == lab_result_id).first()


def _assigned_clinician_or_admin(result: LabResult, current_user: User) -> bool:
    return current_user.user_role in {"admin", "super_admin"} or (
        result.lab_order and result.lab_order.doctor and result.lab_order.doctor.user_id == current_user.user_id
    )


@router.post("/labResult/critical/notify")
def notify_critical_lab_result(req: LabCriticalActionRequest, current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    result = _critical_result(db, req.lab_result_id)
    if not result:
        return {"code": 500, "msg": "检查结果不存在"}
    if result.critical_status == 0:
        return {"code": 500, "msg": "该结果不是危急值"}
    if result.critical_status >= 2:
        return {"code": 200, "msg": "危急值已通知", "data": {"idempotent": True}}
    doctor = result.lab_order.doctor if result.lab_order else None
    if not doctor or not doctor.user_id:
        return {"code": 500, "msg": "该检验结果没有关联临床医生"}
    now = datetime.datetime.now()
    updated = db.query(LabResult).filter(
        LabResult.lab_result_id == req.lab_result_id,
        LabResult.critical_status == 1,
    ).update({
        LabResult.critical_status: 2,
        LabResult.critical_notified_by: current_user.user_id,
        LabResult.critical_notified_time: now,
    }, synchronize_session=False)
    if not updated:
        return {"code": 200, "msg": "危急值已通知", "data": {"idempotent": True}}
    db.add(Message(
        recipient_id=doctor.user_id,
        title="检验危急值提醒",
        content=f"患者{result.lab_order.patient.name if result.lab_order.patient else ''}的{result.lab_order.check_type}结果为：{result.result}，请及时确认并处理。",
        msg_type="app",
        is_read=0,
        create_time=now,
    ))
    _record_tracking(db, result.lab_order_id, "危急值已通知", current_user, "已发送院内消息")
    db.commit()
    return {"code": 200, "msg": "危急值已通知", "data": {"idempotent": False}}


@router.post("/labResult/critical/acknowledge")
def acknowledge_critical_lab_result(req: LabCriticalActionRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    result = _critical_result(db, req.lab_result_id)
    if not result:
        return {"code": 500, "msg": "检查结果不存在"}
    if not _assigned_clinician_or_admin(result, current_user):
        return {"code": 403, "msg": "只有开单医生可以确认该危急值"}
    if result.critical_status < 2:
        return {"code": 500, "msg": "危急值尚未通知，不能确认"}
    if result.critical_status >= 3:
        return {"code": 200, "msg": "危急值已确认", "data": {"idempotent": True}}
    now = datetime.datetime.now()
    updated = db.query(LabResult).filter(
        LabResult.lab_result_id == req.lab_result_id,
        LabResult.critical_status == 2,
    ).update({
        LabResult.critical_status: 3,
        LabResult.critical_acknowledged_by: current_user.user_id,
        LabResult.critical_acknowledged_time: now,
    }, synchronize_session=False)
    if not updated:
        return {"code": 200, "msg": "危急值已确认", "data": {"idempotent": True}}
    _record_tracking(db, result.lab_order_id, "危急值已确认", current_user, req.note)
    db.commit()
    return {"code": 200, "msg": "危急值已确认", "data": {"idempotent": False}}


@router.post("/labResult/critical/handle")
def handle_critical_lab_result(req: LabCriticalActionRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    result = _critical_result(db, req.lab_result_id)
    if not result:
        return {"code": 500, "msg": "检查结果不存在"}
    if not _assigned_clinician_or_admin(result, current_user):
        return {"code": 403, "msg": "只有开单医生可以处理该危急值"}
    if result.critical_status < 3:
        return {"code": 500, "msg": "请先确认危急值"}
    if result.critical_status >= 4:
        return {"code": 200, "msg": "危急值已处理", "data": {"idempotent": True}}
    if not req.note.strip():
        return {"code": 400, "msg": "请填写危急值处理记录"}
    now = datetime.datetime.now()
    updated = db.query(LabResult).filter(
        LabResult.lab_result_id == req.lab_result_id,
        LabResult.critical_status == 3,
    ).update({
        LabResult.critical_status: 4,
        LabResult.critical_handled_by: current_user.user_id,
        LabResult.critical_handled_time: now,
        LabResult.critical_handling_note: req.note.strip(),
    }, synchronize_session=False)
    if not updated:
        return {"code": 200, "msg": "危急值已处理", "data": {"idempotent": True}}
    _record_tracking(db, result.lab_order_id, "危急值已处理", current_user, req.note.strip())
    db.commit()
    return {"code": 200, "msg": "危急值已处理", "data": {"idempotent": False}}


@router.post("/labResult/detail")
def get_lab_result_detail(req: LabResultAuditRequest, current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    result = db.query(LabResult).filter(LabResult.lab_result_id == req.lab_result_id).first()
    if not result:
        return {"code": 500, "msg": "检查结果不存在"}
    data = {
        "id": str(result.lab_result_id),
        "check_name": result.lab_order.check_type if result.lab_order else "",
        "check_time": (result.report_time.strftime("%Y-%m-%d %H:%M:%S") if result.report_time else None),
        "result": result.result,
        "abnormal_flag": result.abnormal_flag,
        "technician_name": result.technician.username if result.technician else "",
    }
    return {"code": 200, "msg": "success", "data": data}
