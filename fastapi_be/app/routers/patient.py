import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, User, User, require_roles, CLINICAL_ROLES
from app.models import (
    Appointment,
    Doctor,
    DoctorSchedule,
    MedicalRecord,
    Patient,
    Registration,
    Review,
    User,
)
from app.schemas import (
    AppointmentCreateRequest,
    MedicalRecordDetailRequest,
    RegistrationCreateRequest,
    ReviewCreateRequest,
    UuidRequest,
)

router = APIRouter()


WEEKDAY_ALIASES = {
    "星期一": "周一",
    "星期二": "周二",
    "星期三": "周三",
    "星期四": "周四",
    "星期五": "周五",
    "星期六": "周六",
    "星期日": "周日",
    "星期天": "周日",
}


def normalize_weekday(value: str | None) -> str | None:
    if not value:
        return value
    return WEEKDAY_ALIASES.get(value, value)


@router.get("/appointmentManagement/getList")
def get_appointment_list(current_user: User = Depends(get_current_user), keyword: str | None = None, db: Session = Depends(get_db)):
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj:
        return {"code": 200, "msg": "success", "data": []}
    appointment_list = db.query(Appointment).filter(Appointment.patient_id == patient_obj.patient_id).all()
    data = []
    status_map = ["未就诊", "已就诊", "已取消"]
    for item in appointment_list:
        data.append(
            {
                "uuid": str(item.registration_uuid),
                "doctor": item.doctor.name if item.doctor else "",
                "specialist": item.specialist,
                "department": item.department.name if item.department else "",
                "time": str(item.time),
                "prefer_time": item.prefer_time,
                "appointment_time": (item.appointment_time.strftime("%Y-%m-%d %H:%M:%S") if item.appointment_time else None)[0:10] if item.appointment_time else "",
                "status": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/appointmentManagement/appointmentList")
def appointment_list(keyword: str | None = None, current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    schedules = db.query(DoctorSchedule).all()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    date_map = {}
    begin = datetime.datetime.now()
    for i in range(7):
        date_map[weekdays[(begin + datetime.timedelta(days=i)).weekday()]] = str(begin + datetime.timedelta(days=i))[0:10]
    data = []
    for item in schedules:
        normalized_week = normalize_weekday(item.week)
        if normalized_week not in date_map:
            continue
        if date_map[normalized_week] == str(begin)[0:10]:
            continue
        data.append(
            {
                "id": item.schedule_id,
                "time": item.time,
                "specialist": item.specialist,
                "date": date_map[normalized_week],
                "doctor": item.doctor.name if item.doctor else "",
                "doctor_id": item.doctor.doctor_id if item.doctor else None,
                "department_id": item.doctor.department.department_id if item.doctor and item.doctor.department else None,
                "stock": item.number,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/appointmentManagement/create")
def patient_appointment(req: AppointmentCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj:
        return {"code": 500, "msg": "病人信息不存在"}
    # 检查是否处于暂停预约状态
    from app.models import BreachRecord

    since = datetime.datetime.now() - datetime.timedelta(days=30)
    breach_count = (
        db.query(BreachRecord)
        .join(Appointment, BreachRecord.registration_id == Appointment.registration_uuid)
        .filter(Appointment.patient_id == patient_obj.patient_id, BreachRecord.breach_time >= since)
        .count()
    )
    if breach_count >= 3:
        return {"code": 500, "msg": "您30天内违约3次，预约资格已暂停30天"}
    reg_obj = db.query(DoctorSchedule).filter(DoctorSchedule.schedule_id == req.id).first()
    if reg_obj and reg_obj.number <= 0:
        return {"code": 500, "msg": "该时段号源已满"}
    try:
        if reg_obj:
            reg_obj.number -= 1
            db.add(reg_obj)
        try:
            appt_date = datetime.datetime.strptime(req.date, "%Y-%m-%d").date()
        except ValueError:
            appt_date = req.date
        appointment = Appointment(
            patient_id=patient_obj.patient_id,
            doctor_id=req.doctor_id,
            specialist=req.specialist,
            department_id=req.department_id,
            prefer_time=req.time,
            appointment_time=datetime.datetime.now(),
            time=appt_date,
            status=0,
        )
        db.add(appointment)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        import traceback

        traceback.print_exc()
        return {"code": 500, "msg": "预约失败"}


@router.post("/appointmentManagement/cancel")
def patient_appointment_cancel(req: UuidRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = db.query(Appointment).filter(Appointment.registration_uuid == req.uuid).first()
    if not app:
        return {"code": 500, "msg": "预约记录不存在"}
    if app.status == 2:
        return {"code": 500, "msg": "预约已取消,无需重复操作"}
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj or app.patient_id != patient_obj.patient_id:
        return {"code": 403, "msg": "无权取消他人预约"}
    app.status = 2
    db.add(app)
    schedule = db.query(DoctorSchedule).filter(DoctorSchedule.doctor_id == app.doctor_id).filter(
        DoctorSchedule.specialist == app.specialist
    ).first()
    if schedule:
        schedule.number += 1
        db.add(schedule)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/registrationManagement/getList")
def get_registration_list(current_user: User = Depends(get_current_user), keyword: str | None = None, db: Session = Depends(get_db)):
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj:
        return {"code": 200, "msg": "success", "data": []}
    registration_list = db.query(Registration).filter(Registration.patient_id == patient_obj.patient_id).all()
    data = []
    status_map = ["未就诊", "已就诊", "", "已取消"]
    for item in registration_list:
        data.append(
            {
                "uuid": str(item.registration_uuid),
                "order": item.registration_id,
                "doctor": item.doctor.name if item.doctor else "",
                "specialist": item.specialist,
                "department": item.department.name if item.department else "",
                "time": str(item.time)[0:10] if item.time else "",
                "status": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/registrationManagement/registrationList")
def registration_list(current_user: User = Depends(get_current_user), keyword: str | None = None, db: Session = Depends(get_db)):
    today_weeky = datetime.datetime.now().weekday()
    weekdays = ["周一", "周二", "周三", "周四", "周五"]
    if today_weeky > 4:
        return {"code": 200, "msg": "success", "data": "今天为休息日"}
    data = []
    target_week = weekdays[today_weeky]
    schedules = [item for item in db.query(DoctorSchedule).all() if normalize_weekday(item.week) == target_week]
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    for item in schedules:
        if (
            patient_obj
            and db.query(Registration)
            .filter(Registration.patient_id == patient_obj.patient_id, Registration.doctor_id == item.doctor_id, Registration.specialist == item.specialist, Registration.status == 0)
            .first()
        ):
            status = 1
        else:
            status = 0
        data.append(
            {
                "id": item.schedule_id,
                "time": item.time,
                "specialist": item.specialist,
                "doctor": item.doctor.name if item.doctor else "",
                "doctor_id": item.doctor.doctor_id if item.doctor else None,
                "department_id": item.doctor.department.department_id if item.doctor and item.doctor.department else None,
                "stock": item.number,
                "status": status,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/registrationManagement/create")
def patient_registration(req: RegistrationCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj:
        return {"code": 500, "msg": "病人信息不存在"}
    reg_obj = db.query(DoctorSchedule).filter(DoctorSchedule.schedule_id == req.id).first()
    if reg_obj and reg_obj.number <= 0:
        return {"code": 500, "msg": "该时段号源已满"}
    exists = (
        db.query(Registration)
        .filter(
            Registration.patient_id == patient_obj.patient_id,
            Registration.doctor_id == req.doctor_id,
            Registration.specialist == req.specialist,
            Registration.department_id == req.department_id,
            Registration.status == 0,
        )
        .first()
    )
    if exists:
        return {"code": 500, "msg": "您的挂号次数被限制"}
    try:
        if reg_obj:
            reg_obj.number -= 1
            db.add(reg_obj)
        registration = Registration(
            patient_id=patient_obj.patient_id,
            doctor_id=req.doctor_id,
            specialist=req.specialist,
            department_id=req.department_id,
            time=datetime.datetime.now(),
            status=0,
        )
        db.add(registration)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        import traceback

        traceback.print_exc()
        return {"code": 500, "msg": "挂号失败"}


@router.post("/registrationManagement/cancel")
def patient_registration_cancel(req: UuidRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reg = db.query(Registration).filter(Registration.registration_uuid == req.uuid).first()
    if not reg:
        return {"code": 500, "msg": "挂号记录不存在"}
    if reg.status == 3:
        return {"code": 500, "msg": "挂号已取消,无需重复操作"}
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj or reg.patient_id != patient_obj.patient_id:
        return {"code": 403, "msg": "无权取消他人挂号"}
    reg.status = 3
    db.add(reg)
    schedule = db.query(DoctorSchedule).filter(DoctorSchedule.schedule_id == req.schedule_id).first()
    if not schedule:
        schedule = (
            db.query(DoctorSchedule)
            .filter(DoctorSchedule.doctor_id == reg.doctor_id, DoctorSchedule.specialist == reg.specialist)
            .first()
        )
    if schedule:
        schedule.number += 1
        db.add(schedule)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/medicalRecord/getList")
def get_medical_record_list(current_user: User = Depends(get_current_user), keyword: str | None = None, page: int | None = None, page_size: int | None = None, db: Session = Depends(get_db)):
    from app.pagination import paginate

    data = []
    total = 0
    if current_user.user_role == "patient":
        patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
        if not patient_obj:
            return {"code": 200, "msg": "success", "data": []}
        query = db.query(MedicalRecord).filter(MedicalRecord.patient_id == patient_obj.patient_id).order_by(MedicalRecord.consultation_time.desc())
        records, total = paginate(query, page, page_size)
        for item in records:
            data.append(
                {
                    "uuid": str(item.medical_record_id),
                    "consultation_time": (item.consultation_time.strftime("%Y-%m-%d %H:%M:%S") if item.consultation_time else None),
                    "doctor_name": item.doctor.name if item.doctor else "",
                    "symptom": item.symptom,
                    "result": item.result,
                }
            )
    elif current_user.user_role in ("doctor", "director"):
        doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
        if not doctor_obj:
            return {"code": 200, "msg": "success", "data": []}
        query = db.query(MedicalRecord).filter(MedicalRecord.doctor_id == doctor_obj.doctor_id).order_by(MedicalRecord.consultation_time.desc())
        records, total = paginate(query, page, page_size)
        for item in records:
            data.append(
                {
                    "uuid": str(item.medical_record_id),
                    "consultation_time": (item.consultation_time.strftime("%Y-%m-%d %H:%M:%S") if item.consultation_time else None),
                    "patient_id": item.patient_id,
                    "patient_name": item.patient.name if item.patient else "",
                    "symptom": item.symptom,
                    "result": item.result,
                }
            )
    else:
        return {"code": 200, "msg": "success", "data": []}
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/medicalRecord/detail")
def get_medical_record_detail(req: MedicalRecordDetailRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(MedicalRecord).filter(MedicalRecord.medical_record_id == req.medical_record_id).first()
    if not record:
        return {"code": 500, "msg": "病历不存在"}
    data = {
        "uuid": str(record.medical_record_id),
        "consultation_time": (record.consultation_time.strftime("%Y-%m-%d %H:%M:%S") if record.consultation_time else None),
        "doctor_id": record.doctor_id,
        "doctor_name": record.doctor.name if record.doctor else "",
        "patient_id": record.patient_id,
        "patient_name": record.patient.name if record.patient else "",
        "symptom": record.symptom,
        "result": record.result,
    }
    return {"code": 200, "msg": "success", "data": data}


@router.get("/healthRecord/getProfile")
def get_health_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj:
        return {"code": 500, "msg": "病人信息不存在"}
    sex = "女" if patient_obj.sex == 0 else "男"
    data = {
        "patient_id": patient_obj.patient_id,
        "name": patient_obj.name,
        "sex": sex,
        "identity": patient_obj.identity,
        "birthday": (patient_obj.birthday.strftime("%Y-%m-%d") if patient_obj.birthday else None),
        "phone": patient_obj.phone,
        "address": patient_obj.address,
        "allergy_history": patient_obj.allergy_history or "",
    }
    return {"code": 200, "msg": "success", "data": data}


@router.get("/healthRecord/getVisits")
def get_visit_records(current_user: User = Depends(get_current_user), keyword: str | None = None, db: Session = Depends(get_db)):
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj:
        return {"code": 200, "msg": "success", "data": []}
    records = db.query(MedicalRecord).filter(MedicalRecord.patient_id == patient_obj.patient_id).order_by(MedicalRecord.consultation_time.desc()).all()
    data = []
    for item in records:
        data.append(
            {
                "medical_record_id": item.medical_record_id,
                "visit_time": (item.consultation_time.strftime("%Y-%m-%d %H:%M:%S") if item.consultation_time else None),
                "doctor_name": item.doctor.name if item.doctor else "",
                "department": item.doctor.department.name if item.doctor and item.doctor.department else "",
                "diagnosis": item.result,
                "prescription_id": "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/review/create")
def create_review(req: ReviewCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj:
        return {"code": 500, "msg": "病人信息不存在"}
    review = Review(
        patient_id=patient_obj.patient_id,
        doctor_id=req.doctor_id,
        visit_id=req.visit_id,
        score=req.score,
        comment=req.comment or "",
        review_time=datetime.datetime.now(),
    )
    db.add(review)
    db.commit()
    return {"code": 200, "msg": "success"}
