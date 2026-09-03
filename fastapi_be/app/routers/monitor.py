import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, User, require_roles
from app.models import OperationLog
from app.observability import request_stats

router = APIRouter()


@router.get("/monitor/summary")
def monitor_summary(current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    since = datetime.datetime.now() - datetime.timedelta(hours=24)
    recent = db.query(OperationLog).filter(OperationLog.create_time >= since)
    summary = request_stats.snapshot()
    errors = recent.filter((OperationLog.result == "失败") | (OperationLog.status_code >= 400)).order_by(OperationLog.create_time.desc()).limit(10).all()
    summary.update({
        "window": "24h",
        "scope": "current_worker",
        "metrics_endpoint": "/metrics",
        "recent_errors": [
            {
                "path": item.path,
                "status_code": item.status_code,
                "username": item.username,
                "create_time": item.create_time,
            }
            for item in errors
        ],
    })
    return {"code": 200, "msg": "success", "data": summary}
