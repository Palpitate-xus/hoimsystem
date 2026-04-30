import datetime
from fastapi import APIRouter, Depends
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Appointment, Patient, Queue
from app.schemas import CheckInRequest

router = APIRouter()


@router.post("/checkIn/checkIn")
def check_in(req: CheckInRequest, db: Session = Depends(get_db)):
    appointment = db.query(Appointment).filter(Appointment.registration_uuid == req.appointment_uuid).first()
    if not appointment:
        return {"code": 500, "msg": "预约记录不存在"}
    patient = db.query(Patient).filter(Patient.identity == req.identity).first()
    if not patient:
        return {"code": 500, "msg": "病人信息不存在"}
    if appointment.patient_id != patient.patient_id:
        return {"code": 500, "msg": "身份证号与预约信息不匹配"}

    max_queue = db.query(Queue).order_by(Queue.queue_number.desc()).first()
    queue_number = (max_queue.queue_number + 1) if max_queue else 1

    queue = Queue(
        queue_number=queue_number,
        registration_uuid=appointment.registration_uuid,
        patient_id=patient.patient_id,
        doctor_id=appointment.doctor_id,
        type=1,
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(queue)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"queue_number": queue_number}}
