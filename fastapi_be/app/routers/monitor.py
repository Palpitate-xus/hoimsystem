import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, User, require_roles
from app.models import OperationLog

router = APIRouter()


@router.get("/monitor/summary")
def monitor_summary(current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    since = datetime.datetime.now() - datetime.timedelta(hours=24)
    recent = db.query(OperationLog).filter(OperationLog.create_time >= since)
    total = recent.count()
    failed = recent.filter((OperationLog.result == "失败") | (OperationLog.status_code >= 400)).count()
    average = recent.with_entities(func.avg(OperationLog.response_time_ms)).scalar()
    online_since = datetime.datetime.now() - datetime.timedelta(minutes=15)
    online_users = db.query(func.count(distinct(OperationLog.username))).filter(OperationLog.create_time >= online_since, OperationLog.username != "anonymous").scalar() or 0
    top_endpoints = db.query(OperationLog.path, func.count(OperationLog.log_id).label("count")).filter(OperationLog.create_time >= since).group_by(OperationLog.path).order_by(func.count(OperationLog.log_id).desc()).limit(10).all()
    errors = recent.filter((OperationLog.result == "失败") | (OperationLog.status_code >= 400)).order_by(OperationLog.create_time.desc()).limit(10).all()
    return {"code": 200, "msg": "success", "data": {"window": "24h", "total_requests": total, "failed_requests": failed, "error_rate": round(failed / total * 100, 2) if total else 0, "online_users": online_users, "average_response_time_ms": round(float(average), 2) if average is not None else 0, "top_endpoints": [{"path": path, "count": count} for path, count in top_endpoints], "recent_errors": [{"path": item.path, "status_code": item.status_code, "username": item.username, "create_time": item.create_time} for item in errors]}}
