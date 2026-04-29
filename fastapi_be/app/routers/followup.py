import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import FollowUp, Appointment, DoctorSchedule, Queue, Doctor
from app.schemas import (
    FollowUpCreatePlanRequest, FollowUpRecordRequest,
    FollowUpAppointmentCreateRequest, AppointmentCreateRequest
)
from app.dependencies import get_current_user

router = APIRouter()


def parse_date_str(val):
    if isinstance(val, str):
        try:
            return datetime.datetime.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            return datetime.datetime.strptime(val, "%Y-%m-%d %H:%M:%S").date()
    return val


@router.post("/followUpAppointment/create")
def create_follow_up_appointment(req: FollowUpAppointmentCreateRequest, db: Session = Depends(get_db)):
    appointment = Appointment(
        patient_id=req.patient_id,
        doctor_id=req.doctor_id,
        specialist=0,
        department_id=db.query(Doctor).filter(Doctor.doctor_id == req.doctor_id).first().department_id if db.query(Doctor).filter(Doctor.doctor_id == req.doctor_id).first() else None,
        prefer_time=req.time,
        appointment_time=datetime.datetime.now(),
        time=parse_date_str(req.date),
        status=0,
    )
    db.add(appointment)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/followUp/createPlan")
def create_follow_up_plan(req: FollowUpCreatePlanRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    follow_up = FollowUp(
        patient_id=req.patient_id,
        doctor_id=doctor_obj.doctor_id if doctor_obj else None,
        plan_date=parse_date_str(req.plan_date),
        content=req.content,
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(follow_up)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/followUp/getList")
def get_follow_up_list(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if doctor_obj:
        follow_ups = db.query(FollowUp).filter(FollowUp.doctor_id == doctor_obj.doctor_id).order_by(FollowUp.plan_date.desc()).all()
    else:
        follow_ups = db.query(FollowUp).order_by(FollowUp.plan_date.desc()).all()
    data = []
    for item in follow_ups:
        data.append({
            "id": item.follow_up_id,
            "patient_name": item.patient.name if item.patient else "",
            "plan_date": str(item.plan_date),
            "content": item.content,
            "status": item.status,
        })
    return {"code": 200, "msg": "success", "data": data}


@router.post("/followUp/record")
def record_follow_up(req: FollowUpRecordRequest, db: Session = Depends(get_db)):
    follow_up = db.query(FollowUp).filter(FollowUp.follow_up_id == req.follow_up_id).first()
    if not follow_up:
        return {"code": 500, "msg": "随访计划不存在"}
    follow_up.result = req.result
    follow_up.patient_feedback = req.patient_feedback
    follow_up.status = 1
    db.add(follow_up)
    db.commit()
    return {"code": 200, "msg": "success"}
