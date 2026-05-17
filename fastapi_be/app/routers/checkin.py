import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Appointment, BreachRecord, Patient, Queue
from app.schemas import CheckInRequest

router = APIRouter()


def is_breach(appointment):
    """检查是否违约：预约日期已过且未报到"""
    now = datetime.datetime.now()
    appt_date = appointment.time
    if isinstance(appt_date, datetime.date) and not isinstance(appt_date, datetime.datetime):
        appt_date = datetime.datetime.combine(appt_date, datetime.time(23, 59))
    return now > appt_date


def record_breach(db, appointment, breach_type="未取号"):
    """记录违约"""
    breach = BreachRecord(
        registration_id=appointment.registration_uuid,
        breach_time=datetime.datetime.now(),
        breach_type=breach_type,
    )
    db.add(breach)


def get_breach_count(db, patient_id, days=30):
    """查询病人最近 N 天内违约次数"""
    since = datetime.datetime.now() - datetime.timedelta(days=days)
    return (
        db.query(BreachRecord).join(Appointment, BreachRecord.registration_id == Appointment.registration_uuid).filter(Appointment.patient_id == patient_id, BreachRecord.breach_time >= since).count()
    )


from app.models import Doctor


@router.get("/checkIn/getAppointments")
def get_appointments_for_checkin(identity: str, db: Session = Depends(get_db)):
    """根据身份证号查询可报到的预约列表"""
    patient = db.query(Patient).filter(Patient.identity == identity).first()
    if not patient:
        return {"code": 500, "msg": "病人信息不存在"}
    today = datetime.date.today()
    appointments = (
        db.query(Appointment)
        .filter(Appointment.patient_id == patient.patient_id, Appointment.status == 0, Appointment.time == today)
        .order_by(Appointment.appointment_time.asc())
        .all()
    )
    data = []
    for appt in appointments:
        doc = db.query(Doctor).filter(Doctor.doctor_id == appt.doctor_id).first()
        dept_name = ""
        if doc and doc.department_id:
            from app.models import Department
            dept = db.query(Department).filter(Department.department_id == doc.department_id).first()
            dept_name = dept.name if dept else ""
        data.append({
            "uuid": appt.registration_uuid,
            "doctor_name": doc.name if doc else "",
            "department_name": dept_name,
            "time": str(appt.time) if appt.time else "",
            "appointment_time": str(appt.appointment_time) if appt.appointment_time else "",
            "specialist": "专家号" if appt.specialist == 1 else "普通号",
        })
    return {"code": 200, "msg": "success", "data": data}


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

    # 检查是否违约（预约日期已过）
    if is_breach(appointment):
        record_breach(db, appointment, "超时未报到")

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


@router.get("/breach/getList")
def get_breach_list(patient_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(BreachRecord, Appointment, Patient).join(Appointment, BreachRecord.registration_id == Appointment.registration_uuid).join(Patient, Appointment.patient_id == Patient.patient_id)
    if patient_id:
        query = query.filter(Appointment.patient_id == patient_id)
    results = query.order_by(BreachRecord.breach_time.desc()).all()
    data = []
    for breach, appt, pat in results:
        data.append(
            {
                "breach_id": breach.breach_id,
                "registration_id": breach.registration_id,
                "breach_time": (breach.breach_time.strftime("%Y-%m-%d %H:%M:%S") if breach.breach_time else None),
                "breach_type": breach.breach_type,
                "patient_name": pat.name if pat else "",
                "patient_id": pat.patient_id if pat else None,
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.get("/breach/checkSuspend")
def check_suspend(patient_id: int, db: Session = Depends(get_db)):
    """检查病人是否处于暂停预约状态：30天内违约3次则暂停30天"""
    count = get_breach_count(db, patient_id, days=30)
    suspended = count >= 3
    return {"code": 200, "msg": "success", "data": {"breach_count": count, "suspended": suspended, "suspend_reason": "30天内违约3次，暂停预约资格30天" if suspended else ""}}
