import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import PatrolRecord, Queue
from app.schemas import QueueCallNextRequest, QueuePassRequest, QueueSkipRequest

router = APIRouter()


@router.post("/queue/emergency")
def mark_emergency(req: QueueSkipRequest, db: Session = Depends(get_db)):
    """护士将队列记录标记为急诊优先"""
    queue_item = db.query(Queue).filter(Queue.queue_id == req.queue_id).first()
    if not queue_item:
        return {"code": 500, "msg": "队列记录不存在"}
    queue_item.type = 2  # 2 = 急诊优先
    db.add(queue_item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/queue/reorder")
def reorder_queue(req: dict, db: Session = Depends(get_db)):
    """护士调整队列顺序（将指定记录移到最前面）"""
    queue_id = req.get("queue_id")
    queue_item = db.query(Queue).filter(Queue.queue_id == queue_id).first()
    if not queue_item:
        return {"code": 500, "msg": "队列记录不存在"}
    # 将该记录设为最小序号（优先）
    min_queue = db.query(Queue).filter(Queue.doctor_id == queue_item.doctor_id, Queue.status == 0).order_by(Queue.queue_number).first()
    if min_queue and min_queue.queue_id != queue_id:
        queue_item.queue_number = min_queue.queue_number - 1
        db.add(queue_item)
        db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/queue/getList")
def get_queue_list(keyword: str | None = None, db: Session = Depends(get_db)):
    queues = db.query(Queue).order_by(Queue.queue_number).all()
    data = []
    for item in queues:
        data.append(
            {
                "queue_id": item.queue_id,
                "queue_number": item.queue_number,
                "patient_name": item.patient.name if item.patient else "",
                "doctor_name": item.doctor.name if item.doctor else "",
                "status": item.status,
                "type": item.type,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/queue/callNext")
def call_next(req: QueueCallNextRequest, db: Session = Depends(get_db)):
    queue_item = db.query(Queue).filter(Queue.doctor_id == req.doctor_id, Queue.status == 0).order_by(Queue.queue_number).first()
    if not queue_item:
        return {"code": 500, "msg": "暂无候诊患者"}
    queue_item.status = 1
    queue_item.call_time = datetime.datetime.now()
    db.add(queue_item)
    db.commit()
    data = {
        "queue_id": queue_item.queue_id,
        "queue_number": queue_item.queue_number,
        "patient_name": queue_item.patient.name if queue_item.patient else "",
        "registration_uuid": queue_item.registration_uuid,
    }
    return {"code": 200, "msg": "success", "data": data}


@router.post("/queue/pass")
def pass_queue(req: QueuePassRequest, db: Session = Depends(get_db)):
    queue_item = db.query(Queue).filter(Queue.queue_id == req.queue_id).first()
    if not queue_item:
        return {"code": 500, "msg": "队列记录不存在"}
    queue_item.status = 2
    db.add(queue_item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/queue/skip")
def skip_queue(req: QueueSkipRequest, db: Session = Depends(get_db)):
    queue_item = db.query(Queue).filter(Queue.queue_id == req.queue_id).first()
    if not queue_item:
        return {"code": 500, "msg": "队列记录不存在"}
    queue_item.status = 2
    db.add(queue_item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/patrol/create")
def create_patrol_record(req: dict, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    record = PatrolRecord(
        nurse_id=current_user.user_id,
        patient_id=req.get("patient_id"),
        content=req.get("content", ""),
        status=req.get("status", 0),
        create_time=datetime.datetime.now(),
    )
    db.add(record)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/patrol/getList")
def get_patrol_list(keyword: str | None = None, db: Session = Depends(get_db)):
    records = db.query(PatrolRecord).order_by(PatrolRecord.create_time.desc()).all()
    data = []
    for item in records:
        data.append(
            {
                "patrol_id": item.patrol_id,
                "nurse_name": item.nurse.username if item.nurse else "",
                "patient_name": item.patient.name if item.patient else "",
                "content": item.content,
                "status": item.status,
                "create_time": str(item.create_time),
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}
