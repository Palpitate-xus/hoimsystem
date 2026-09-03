import datetime
import json

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, User, require_roles
from app.models import IntegrationOutbox
from app.pagination import paginate

router = APIRouter()


def _serialize(item: IntegrationOutbox) -> dict:
    return {
        "event_id": item.event_id,
        "destination": item.destination,
        "event_type": item.event_type,
        "aggregate_type": item.aggregate_type,
        "aggregate_id": item.aggregate_id,
        "payload": json.loads(item.payload_json),
        "status": item.status,
        "attempts": item.attempts,
        "next_attempt_at": item.next_attempt_at,
        "last_attempt_at": item.last_attempt_at,
        "delivered_at": item.delivered_at,
        "last_http_status": item.last_http_status,
        "last_error": item.last_error,
        "created_at": item.created_at,
    }


@router.get("/integration/outbox")
def list_outbox(
    status: str | None = None,
    destination: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    query = db.query(IntegrationOutbox)
    if status:
        query = query.filter(IntegrationOutbox.status == status)
    if destination:
        query = query.filter(IntegrationOutbox.destination == destination)
    rows, total = paginate(query.order_by(IntegrationOutbox.created_at.desc()), page, page_size)
    return {"code": 200, "msg": "success", "data": [_serialize(row) for row in rows], "total": total}


@router.post("/integration/outbox/{event_id}/retry")
def retry_outbox_event(
    event_id: str,
    current_user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    event = db.get(IntegrationOutbox, event_id)
    if not event:
        return {"code": 404, "msg": "对接事件不存在"}
    if event.status == "delivered":
        return {"code": 409, "msg": "已成功投递的事件不能重放"}
    event.status = "pending"
    event.attempts = 0
    event.next_attempt_at = datetime.datetime.now()
    event.last_error = None
    event.last_http_status = None
    db.commit()
    return {"code": 200, "msg": "已进入重试队列"}


@router.get("/integration/reconciliation")
def integration_reconciliation(
    current_user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    counts = dict(
        db.query(IntegrationOutbox.status, func.count(IntegrationOutbox.event_id))
        .group_by(IntegrationOutbox.status)
        .all()
    )
    oldest_pending = (
        db.query(func.min(IntegrationOutbox.created_at))
        .filter(IntegrationOutbox.status.in_(("pending", "retry")))
        .scalar()
    )
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "counts": {key: counts.get(key, 0) for key in ("pending", "retry", "delivered", "dead")},
            "oldest_pending_at": oldest_pending,
        },
    }
