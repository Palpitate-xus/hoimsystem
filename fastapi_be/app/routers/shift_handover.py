import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, NURSING_ROLES, User, require_roles
from app.models import ShiftHandover
from app.schemas import ShiftHandoverCreateRequest, ShiftHandoverIdRequest

router = APIRouter()


def _serialize(item: ShiftHandover):
    return {
        "id": item.handover_id,
        "handover_id": item.handover_id,
        "shift_type": item.shift_type,
        "content": item.content,
        "status": item.status,
        "status_text": "待接班" if item.status == 0 else "已确认",
        "handover_user_name": item.handover_user.username if item.handover_user else "",
        "receiver_user_name": item.receiver_user.username if item.receiver_user else "",
        "create_time": item.create_time,
        "receive_time": item.receive_time,
    }


@router.post("/shiftHandover/create")
def create_handover(req: ShiftHandoverCreateRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    item = ShiftHandover(shift_type=req.shift_type.strip(), content=req.content.strip(), status=0, handover_user_id=current_user.user_id, create_time=datetime.datetime.now())
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.get("/shiftHandover/list")
def list_handovers(current_user: User = Depends(require_roles(*(NURSING_ROLES | ADMIN_ROLES))), db: Session = Depends(get_db)):
    items = db.query(ShiftHandover).order_by(ShiftHandover.create_time.desc()).limit(100).all()
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in items]}


@router.post("/shiftHandover/receive")
def receive_handover(req: ShiftHandoverIdRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    updated = db.query(ShiftHandover).filter(ShiftHandover.handover_id == req.handover_id, ShiftHandover.status == 0, ShiftHandover.handover_user_id != current_user.user_id).update({ShiftHandover.status: 1, ShiftHandover.receiver_user_id: current_user.user_id, ShiftHandover.receive_time: datetime.datetime.now()}, synchronize_session=False)
    if updated != 1:
        return {"code": 500, "msg": "只能确认其他护士提交的待接班记录"}
    db.commit()
    return {"code": 200, "msg": "success"}
