"""科室绩效核算：工作量×系数 - 成本分摊（用户手工录入明细）。"""
import datetime
import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, User, require_roles
from app.models import Department, DepartmentPerformance

router = APIRouter()

PERF_ROLES = ADMIN_ROLES  # 绩效核算仅管理员/院领导
STATUS_TEXT = {0: "草稿", 1: "已提交", 2: "已审核发放"}


def _parse_items(raw) -> list[dict]:
    """明细兼容 list[dict] 或 JSON 字符串。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return raw if isinstance(raw, list) else []


def _sum_items(items: list[dict], amount_key: str = "金额", subtotal_key: str = "小计", qty_key: str = "数量", price_key: str = "单价") -> float:
    """工作量明细按 单价×数量 或直接 小计 求和；成本按 金额 求和。"""
    total = 0.0
    for it in items:
        if subtotal_key in it and it[subtotal_key] not in (None, ""):
            total += float(it[subtotal_key])
        elif qty_key in it and price_key in it:
            try:
                total += float(it[qty_key] or 0) * float(it[price_key] or 0)
            except (TypeError, ValueError):
                continue
        elif amount_key in it and it[amount_key] not in (None, ""):
            try:
                total += float(it[amount_key])
            except (TypeError, ValueError):
                continue
    return round(total, 2)


def _ser(p: DepartmentPerformance) -> dict:
    return {
        "performance_id": p.performance_id,
        "period": p.period,
        "department_id": p.department_id,
        "department_name": p.department.name if p.department else "",
        "workload_items": _parse_items(p.workload_items),
        "total_workload": float(p.total_workload or 0),
        "cost_items": _parse_items(p.cost_items),
        "total_cost": float(p.total_cost or 0),
        "coefficient": float(p.coefficient or 1),
        "performance_amount": float(p.performance_amount or 0),
        "status": p.status,
        "status_text": STATUS_TEXT.get(p.status, str(p.status)),
        "creator_name": p.creator.username if p.creator else "",
        "auditor_name": p.auditor.username if p.auditor else "",
        "remark": p.remark or "",
        "create_time": p.create_time.strftime("%Y-%m-%d %H:%M:%S") if p.create_time else "",
        "update_time": p.update_time.strftime("%Y-%m-%d %H:%M:%S") if p.update_time else "",
    }


@router.get("/performance/getList")
def list_performances(period: str | None = None, department_id: int | None = None, status: int | None = None, current_user: User = Depends(require_roles(*PERF_ROLES)), db: Session = Depends(get_db)):
    query = db.query(DepartmentPerformance)
    if period:
        query = query.filter(DepartmentPerformance.period == period)
    if department_id is not None:
        query = query.filter(DepartmentPerformance.department_id == department_id)
    if status is not None:
        query = query.filter(DepartmentPerformance.status == status)
    rows = query.order_by(DepartmentPerformance.period.desc(), DepartmentPerformance.performance_id.desc()).limit(1000).all()
    return {"code": 200, "msg": "success", "data": [_ser(p) for p in rows]}


@router.post("/performance/create")
def create_performance(req: dict, current_user: User = Depends(require_roles(*PERF_ROLES)), db: Session = Depends(get_db)):
    dept = db.query(Department).filter(Department.department_id == req.get("department_id")).first()
    if not dept:
        return {"code": 500, "msg": "科室不存在"}
    period = (req.get("period") or "").strip()
    if not period:
        return {"code": 400, "msg": "统计期不能为空（如 2026-08）"}
    dup = db.query(DepartmentPerformance).filter(
        DepartmentPerformance.period == period,
        DepartmentPerformance.department_id == dept.department_id,
    ).first()
    if dup:
        return {"code": 500, "msg": "该科室此统计期已有核算记录"}
    workload = _parse_items(req.get("workload_items"))
    costs = _parse_items(req.get("cost_items"))
    total_workload = _sum_items(workload)
    total_cost = _sum_items(costs)
    try:
        coefficient = float(req.get("coefficient", 1) or 1)
    except (TypeError, ValueError):
        return {"code": 400, "msg": "绩效系数必须为数字"}
    if not 0 <= coefficient <= 10:
        return {"code": 400, "msg": "绩效系数应在 0-10 之间"}
    amount = round((total_workload - total_cost) * coefficient, 2)
    item = DepartmentPerformance(
        period=period,
        department_id=dept.department_id,
        workload_items=json.dumps(workload, ensure_ascii=False),
        total_workload=total_workload,
        cost_items=json.dumps(costs, ensure_ascii=False),
        total_cost=total_cost,
        coefficient=coefficient,
        performance_amount=amount,
        status=0,
        creator_id=current_user.user_id,
        remark=(req.get("remark") or "").strip() or None,
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"performance_id": item.performance_id, "performance_amount": amount}}


@router.post("/performance/update")
def update_performance(req: dict, current_user: User = Depends(require_roles(*PERF_ROLES)), db: Session = Depends(get_db)):
    item = db.query(DepartmentPerformance).filter(DepartmentPerformance.performance_id == req.get("performance_id")).first()
    if not item:
        return {"code": 500, "msg": "核算记录不存在"}
    if item.status != 0:
        return {"code": 500, "msg": "仅草稿状态可修改（已提交/已发放需先退回）"}
    if "workload_items" in req:
        workload = _parse_items(req["workload_items"])
        item.workload_items = json.dumps(workload, ensure_ascii=False)
        item.total_workload = _sum_items(workload)
    if "cost_items" in req:
        costs = _parse_items(req["cost_items"])
        item.cost_items = json.dumps(costs, ensure_ascii=False)
        item.total_cost = _sum_items(costs)
    if req.get("coefficient") is not None:
        try:
            coef = float(req["coefficient"])
        except (TypeError, ValueError):
            return {"code": 400, "msg": "绩效系数必须为数字"}
        if not 0 <= coef <= 10:
            return {"code": 400, "msg": "绩效系数应在 0-10 之间"}
        item.coefficient = coef
    if req.get("remark") is not None:
        item.remark = (req["remark"] or "").strip() or None
    # 重算绩效
    item.performance_amount = round((float(item.total_workload or 0) - float(item.total_cost or 0)) * float(item.coefficient or 1), 2)
    item.update_time = datetime.datetime.now()
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"performance_amount": float(item.performance_amount)}}


@router.post("/performance/submit")
def submit_performance(req: dict, current_user: User = Depends(require_roles(*PERF_ROLES)), db: Session = Depends(get_db)):
    """草稿→已提交（锁定明细，等待审核发放）。"""
    item = db.query(DepartmentPerformance).filter(DepartmentPerformance.performance_id == req.get("performance_id")).first()
    if not item:
        return {"code": 500, "msg": "核算记录不存在"}
    if item.status != 0:
        return {"code": 500, "msg": "仅草稿状态可提交"}
    item.status = 1
    item.update_time = datetime.datetime.now()
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/performance/audit")
def audit_performance(req: dict, current_user: User = Depends(require_roles("super_admin", "admin")), db: Session = Depends(get_db)):
    """已提交→已审核发放（approve=False 退回草稿修改）。"""
    item = db.query(DepartmentPerformance).filter(DepartmentPerformance.performance_id == req.get("performance_id")).first()
    if not item:
        return {"code": 500, "msg": "核算记录不存在"}
    if item.status != 1:
        return {"code": 500, "msg": "仅已提交状态可审核"}
    approve = bool(req.get("approve", True))
    item.status = 2 if approve else 0
    if approve:
        item.auditor_id = current_user.user_id
    item.update_time = datetime.datetime.now()
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"status": item.status, "status_text": STATUS_TEXT[item.status]}}
