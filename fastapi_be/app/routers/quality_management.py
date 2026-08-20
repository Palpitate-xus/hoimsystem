"""质量管理：不良事件 RCA 根因分析 + HQMS 指标上报。"""
import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, User, require_roles
from app.models import AdverseEvent, AdverseEventRca, HqmsIndicator

router = APIRouter()


def _parse_date(val):
    if not val:
        return None
    if isinstance(val, datetime.date):
        return val
    try:
        return datetime.datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


QM_ROLES = ADMIN_ROLES | CLINICAL_ROLES


# ---------------- RCA ----------------

def _rca_ser(r: AdverseEventRca) -> dict:
    return {
        "rca_id": r.rca_id,
        "event_id": r.event_id,
        "event_summary": r.event_summary,
        "timeline": r.timeline or "",
        "root_cause": r.root_cause,
        "corrective_actions": r.corrective_actions,
        "pdca_cycle": r.pdca_cycle or "P",
        "responsible_dept": r.responsible_dept or "",
        "due_date": r.due_date.isoformat() if r.due_date else "",
        "completed_date": r.completed_date.isoformat() if r.completed_date else "",
        "effect_evaluation": r.effect_evaluation or "",
        "create_time": r.create_time.strftime("%Y-%m-%d %H:%M:%S") if r.create_time else "",
        "update_time": r.update_time.strftime("%Y-%m-%d %H:%M:%S") if r.update_time else "",
    }


@router.get("/rca/getList")
def list_rca(event_id: int | None = None, pdca_cycle: str | None = None, current_user: User = Depends(require_roles(*QM_ROLES)), db: Session = Depends(get_db)):
    query = db.query(AdverseEventRca)
    if event_id is not None:
        query = query.filter(AdverseEventRca.event_id == event_id)
    if pdca_cycle:
        query = query.filter(AdverseEventRca.pdca_cycle == pdca_cycle)
    rows = query.order_by(AdverseEventRca.rca_id.desc()).limit(1000).all()
    return {"code": 200, "msg": "success", "data": [_rca_ser(r) for r in rows]}


@router.post("/rca/create")
def create_rca(req: dict, current_user: User = Depends(require_roles(*QM_ROLES)), db: Session = Depends(get_db)):
    event = db.query(AdverseEvent).filter(AdverseEvent.event_id == req.get("event_id")).first()
    if not event:
        return {"code": 500, "msg": "关联不良事件不存在"}
    existing = db.query(AdverseEventRca).filter(AdverseEventRca.event_id == event.event_id).first()
    if existing:
        return {"code": 500, "msg": "该事件已有 RCA 分析记录"}
    if not (req.get("root_cause") or "").strip() or not (req.get("corrective_actions") or "").strip():
        return {"code": 400, "msg": "根因分析与改进措施不能为空"}
    item = AdverseEventRca(
        event_id=event.event_id,
        event_summary=(req.get("event_summary") or (event.description or ""))[:500],
        timeline=req.get("timeline") or None,
        root_cause=(req["root_cause"]).strip(),
        corrective_actions=(req["corrective_actions"]).strip(),
        pdca_cycle=(req.get("pdca_cycle") or "P").strip(),
        responsible_dept=(req.get("responsible_dept") or "").strip() or None,
        due_date=_parse_date(req.get("due_date")),
        analyst_id=current_user.user_id,
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"rca_id": item.rca_id}}


@router.post("/rca/advance")
def advance_rca(req: dict, current_user: User = Depends(require_roles(*QM_ROLES)), db: Session = Depends(get_db)):
    """PDCA 推进：P→D→C→A。A 阶段必须填效果评价与完成日期。"""
    item = db.query(AdverseEventRca).filter(AdverseEventRca.rca_id == req.get("rca_id")).first()
    if not item:
        return {"code": 500, "msg": "RCA 记录不存在"}
    target = (req.get("pdca_cycle") or "").strip().upper()
    flow = {"P": "D", "D": "C", "C": "A"}
    allowed = flow.get(item.pdca_cycle)
    if target not in ("D", "C", "A") or target != allowed:
        return {"code": 400, "msg": f"PDCA 只能按 P→D→C→A 顺序推进，当前 {item.pdca_cycle} 只能进入 {allowed}"}
    if target == "A":
        if not (req.get("effect_evaluation") or "").strip():
            return {"code": 400, "msg": "进入 A 阶段必须填写效果评价"}
        item.effect_evaluation = (req["effect_evaluation"]).strip()
        item.completed_date = _parse_date(req.get("completed_date")) or datetime.date.today()
    item.pdca_cycle = target
    item.update_time = datetime.datetime.now()
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


# ---------------- HQMS ----------------

def _hqms_ser(h: HqmsIndicator) -> dict:
    return {
        "indicator_id": h.indicator_id,
        "period": h.period,
        "indicator_code": h.indicator_code,
        "indicator_name": h.indicator_name,
        "indicator_value": float(h.indicator_value) if h.indicator_value is not None else None,
        "numerator": float(h.numerator) if h.numerator is not None else None,
        "denominator": float(h.denominator) if h.denominator is not None else None,
        "unit": h.unit or "",
        "department": h.department or "全院",
        "report_status": h.report_status,
        "report_status_text": "待上报" if h.report_status == 0 else "已上报",
        "remark": h.remark or "",
    }


@router.get("/hqms/getList")
def list_hqms(period: str | None = None, report_status: int | None = None, current_user: User = Depends(require_roles(*QM_ROLES)), db: Session = Depends(get_db)):
    query = db.query(HqmsIndicator)
    if period:
        query = query.filter(HqmsIndicator.period == period)
    if report_status is not None:
        query = query.filter(HqmsIndicator.report_status == report_status)
    rows = query.order_by(HqmsIndicator.indicator_id.desc()).limit(3000).all()
    return {"code": 200, "msg": "success", "data": [_hqms_ser(h) for h in rows]}


@router.post("/hqms/create")
def create_hqms(req: dict, current_user: User = Depends(require_roles(*QM_ROLES)), db: Session = Depends(get_db)):
    period = (req.get("period") or "").strip()
    code = (req.get("indicator_code") or "").strip()
    name = (req.get("indicator_name") or "").strip()
    if not period or not code or not name:
        return {"code": 400, "msg": "统计期、指标编码、指标名称不能为空"}
    department = (req.get("department") or "").strip() or None
    dup = db.query(HqmsIndicator).filter(
        HqmsIndicator.period == period,
        HqmsIndicator.indicator_code == code,
        HqmsIndicator.department == department,
    ).first()
    if dup:
        return {"code": 500, "msg": "该统计期此指标已存在（同科室）"}
    value = None
    num, den = req.get("numerator"), req.get("denominator")
    if num is not None and den not in (None, 0):
        try:
            value = float(num) / float(den) * 100 if (req.get("unit") or "").strip() == "%" else float(num) / float(den)
        except (TypeError, ValueError, ZeroDivisionError):
            value = None
    if req.get("indicator_value") is not None:
        try:
            value = float(req["indicator_value"])
        except (TypeError, ValueError):
            pass
    item = HqmsIndicator(
        period=period,
        indicator_code=code,
        indicator_name=name,
        indicator_value=value,
        numerator=num,
        denominator=den,
        unit=(req.get("unit") or "").strip() or None,
        department=(req.get("department") or "").strip() or None,
        report_status=0,
        reporter_id=current_user.user_id,
        remark=(req.get("remark") or "").strip() or None,
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"indicator_id": item.indicator_id}}


@router.post("/hqms/batchImport")
def import_hqms(req: dict, current_user: User = Depends(require_roles(*QM_ROLES)), db: Session = Depends(get_db)):
    """Excel 批量导入：rows=[{统计期,指标编码,指标名称,分子,分母,单位,科室,备注}]。"""
    rows = req.get("rows") or []
    if not rows:
        return {"code": 400, "msg": "导入行不能为空"}
    imported, errors = 0, []
    for i, row in enumerate(rows, start=2):
        period = (row.get("统计期") or "").strip()
        code = (row.get("指标编码") or "").strip()
        name = (row.get("指标名称") or "").strip()
        if not period or not code or not name:
            errors.append(f"第{i}行：统计期/编码/名称缺失")
            continue
        dept = (row.get("科室") or "").strip() or None
        dup = db.query(HqmsIndicator).filter(
            HqmsIndicator.period == period,
            HqmsIndicator.indicator_code == code,
            HqmsIndicator.department == dept,
        ).first()
        if dup:
            continue

        def _num(key):
            try:
                return float(row.get(key)) if row.get(key) not in (None, "") else None
            except (TypeError, ValueError):
                return None

        num, den = _num("分子"), _num("分母")
        value = None
        if num is not None and den:
            value = num / den * 100 if (row.get("单位") or "").strip() == "%" else num / den
        db.add(HqmsIndicator(
            period=period, indicator_code=code, indicator_name=name,
            indicator_value=value, numerator=num, denominator=den,
            unit=(row.get("单位") or "").strip() or None, department=dept,
            report_status=0, reporter_id=current_user.user_id,
            remark=(row.get("备注") or "").strip() or None,
            create_time=datetime.datetime.now(),
        ))
        imported += 1
    db.commit()
    return {"code": 200, "msg": "success", "data": {"imported": imported, "errors": errors[:20]}}


@router.post("/hqms/submit")
def submit_hqms(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    """标记已上报（批量可传 ids）。"""
    ids = req.get("ids") or ([req["indicator_id"]] if req.get("indicator_id") else [])
    if not ids:
        return {"code": 400, "msg": "未指定指标"}
    updated = db.query(HqmsIndicator).filter(HqmsIndicator.indicator_id.in_(ids), HqmsIndicator.report_status == 0).update({HqmsIndicator.report_status: 1}, synchronize_session=False)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"updated": updated}}
