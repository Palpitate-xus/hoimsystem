import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import LAB_ROLES, get_current_user, require_roles
from app.models import LabOrder, LabResult, User
from app.schemas import LabResultAuditRequest, LabResultCreateRequest

router = APIRouter()


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
    lab_order.sample_status = 1
    db.add(lab_order)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/lab/sampleReject")
def sample_reject(req: dict, current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    """样本拒收"""
    lab_order = db.query(LabOrder).filter(LabOrder.lab_order_id == req.get("lab_order_id")).first()
    if not lab_order:
        return {"code": 500, "msg": "检查申请单不存在"}
    lab_order.sample_status = 2
    db.add(lab_order)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/lab/sampleTracking")
def sample_tracking(lab_order_id: str, current_user: User = Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    """样本流转跟踪"""
    lab_order = db.query(LabOrder).filter(LabOrder.lab_order_id == lab_order_id).first()
    if not lab_order:
        return {"code": 500, "msg": "检查申请单不存在"}
    status_map = {0: "待接收", 1: "已接收", 2: "已拒收"}
    tracking = [
        {"time": (lab_order.create_time.strftime("%Y-%m-%d %H:%M:%S") if lab_order.create_time else None), "stage": "申请创建", "operator": lab_order.doctor.name if lab_order.doctor else ""},
    ]
    if lab_order.sample_status >= 1:
        tracking.append({"time": "", "stage": status_map.get(lab_order.sample_status, ""), "operator": "检验科"})
    if lab_order.status >= 1:
        tracking.append({"time": "", "stage": "结果已录入", "operator": "检验科技师"})
    if lab_order.status >= 2:
        tracking.append({"time": "", "stage": "结果已审核", "operator": "审核医生"})
    return {"code": 200, "msg": "success", "data": tracking}


@router.post("/labResult/create")
def create_lab_result(req: LabResultCreateRequest, current_user=Depends(require_roles(*LAB_ROLES)), db: Session = Depends(get_db)):
    lab_order = db.query(LabOrder).filter(LabOrder.lab_order_id == req.lab_order_id).first()
    if not lab_order:
        return {"code": 500, "msg": "检查申请单不存在"}
    is_critical = check_critical_value(lab_order.check_type or "", req.result or "")
    result = LabResult(
        lab_order_id=req.lab_order_id,
        sample_id=req.sample_id,
        result=req.result,
        abnormal_flag=1 if is_critical else req.abnormal_flag,
        technician_id=current_user.user_id,
        report_time=datetime.datetime.now(),
        audit_status=0,
    )
    db.add(result)
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
    result.audit_status = 1
    if result.lab_order:
        result.lab_order.status = 2
        db.add(result.lab_order)
    db.add(result)
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
