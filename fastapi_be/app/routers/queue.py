import datetime
from fastapi import APIRouter, Depends
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Queue, Patient, Doctor, Registration, Appointment
from app.schemas import QueueCallNextRequest, QueuePassRequest, QueueSkipRequest

router = APIRouter()


@router.get("/queue/getList")
def get_queue_list(keyword: Optional[str] = None, db: Session = Depends(get_db)):
    queues = db.query(Queue).order_by(Queue.queue_number).all()
    data = []
    for item in queues:
        data.append({
            "queue_id": item.queue_id,
            "queue_number": item.queue_number,
            "patient_name": item.patient.name if item.patient else "",
            "doctor_name": item.doctor.name if item.doctor else "",
            "status": item.status,
            "type": item.type,
        })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/queue/callNext")
def call_next(req: QueueCallNextRequest, db: Session = Depends(get_db)):
    queue_item = db.query(Queue).filter(
        Queue.doctor_id == req.doctor_id,
        Queue.status == 0
    ).order_by(Queue.queue_number).first()
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
