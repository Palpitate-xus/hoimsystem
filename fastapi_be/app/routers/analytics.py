import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics import aggregate_daily_metrics, serialize_metric
from app.database import get_db
from app.dependencies import ADMIN_ROLES, ROLE_DIRECTOR, User, require_roles
from app.models import DailyOperationalMetric

router = APIRouter()
ANALYTICS_ROLES = {*ADMIN_ROLES, ROLE_DIRECTOR}


@router.get("/analytics/operations")
def operational_trend(
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    current_user: User = Depends(require_roles(*ANALYTICS_ROLES)),
    db: Session = Depends(get_db),
):
    end = date_to or datetime.date.today()
    start = date_from or end - datetime.timedelta(days=29)
    if start > end or (end - start).days > 366:
        return {"code": 400, "msg": "统计区间必须为正序且不超过367天"}
    rows = db.query(DailyOperationalMetric).filter(
        DailyOperationalMetric.metric_date >= start,
        DailyOperationalMetric.metric_date <= end,
    ).order_by(DailyOperationalMetric.metric_date).all()
    return {"code": 200, "msg": "success", "data": [serialize_metric(row) for row in rows]}


@router.post("/analytics/refresh")
def refresh_operational_metric(
    metric_date: datetime.date | None = None,
    current_user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    target = metric_date or datetime.date.today()
    if target > datetime.date.today() or target < datetime.date.today() - datetime.timedelta(days=3660):
        return {"code": 400, "msg": "汇总日期不在允许范围内"}
    return {"code": 200, "msg": "汇总完成", "data": aggregate_daily_metrics(db, target)}
