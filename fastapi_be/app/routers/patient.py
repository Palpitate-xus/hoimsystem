import datetime
from fastapi import APIRouter, Depends
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    User, Patient, Doctor, Department, DoctorSchedule,
    Registration, Appointment, MedicalRecord, Charge, Prescription, Review
)
from app.schemas import (
    UuidRequest, AppointmentCreateRequest,
    RegistrationCreateRequest,
    MedicalRecordDetailRequest, ReviewCreateRequest
)
from app.dependencies import get_current_user

router = APIRouter()


@router.get("/appointmentManagement/getList")
def get_appointment_list(current_user: User = Depends(get_current_user), keyword: Optional[str] = None, db: Session = Depends(get_db)):
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj:
        return {"code": 200, "msg": "success", "data": []}
    appointment_list = db.query(Appointment).filter(Appointment.patient_id == patient_obj.patient_id).all()
    data = []
    status_map = ["未就诊", "已就诊", "已取消"]
    for item in appointment_list:
        data.append({
            "uuid": str(item.registration_uuid),
            "doctor": item.doctor.name if item.doctor else "",
            "specialist": item.specialist,
            "department": item.department.name if item.department else "",
            "time": str(item.time),
            "prefer_time": item.prefer_time,
            "appointment_time": str(item.appointment_time)[0:10] if item.appointment_time else "",
            "status": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
        })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/appointmentManagement/appointmentList")
def appointmentList(keyword: Optional[str] = None, db: Session = Depends(get_db)):
    schedules = db.query(DoctorSchedule).all()
    today_weeky = datetime.datetime.now().weekday()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期天"]
    date_map = {}
    begin = datetime.datetime.now()
    for i in range(7):
        date_map[weekdays[(begin + datetime.timedelta(days=i)).weekday()]] = str(begin + datetime.timedelta(days=i))[0:10]
    data = []
    for item in schedules:
        if date_map[item.week] == str(begin)[0:10]:
            continue
        data.append({
            "id": item.schedule_id,
            "time": item.time,
            "specialist": item.specialist,
            "date": date_map[item.week],
            "doctor": item.doctor.name if item.doctor else "",
            "doctor_id": item.doctor.doctor_id if item.doctor else None,
            "department_id": item.doctor.department.department_id if item.doctor and item.doctor.department else None,
            "stock": item.number,
        })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/appointmentManagement/create")
def patient_appointment(req: AppointmentCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj:
        return {"code": 500, "msg": "病人信息不存在"}
    department_obj = db.query(Department).filter(Department.department_id == req.department_id).first()
    doctor_obj = db.query(Doctor).filter(Doctor.doctor_id == req.doctor_id).first()
    reg_obj = db.query(DoctorSchedule).filter(DoctorSchedule.schedule_id == req.id).first()
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


@router.post("/appointmentManagement/cancel")
def patient_appointment_cancel(req: UuidRequest, db: Session = Depends(get_db)):
    app = db.query(Appointment).filter(Appointment.registration_uuid == req.uuid).first()
    if app:
        app.status = 2
        db.add(app)
        db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/registrationManagement/getList")
def get_registration_list(current_user: User = Depends(get_current_user), keyword: Optional[str] = None, db: Session = Depends(get_db)):
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj:
        return {"code": 200, "msg": "success", "data": []}
    registration_list = db.query(Registration).filter(Registration.patient_id == patient_obj.patient_id).all()
    data = []
    status_map = ["未就诊", "已就诊", "", "已取消"]
    for item in registration_list:
        data.append({
            "uuid": str(item.registration_uuid),
            "order": item.registration_id,
            "doctor": item.doctor.name if item.doctor else "",
            "specialist": item.specialist,
            "department": item.department.name if item.department else "",
            "time": str(item.time)[0:10] if item.time else "",
            "status": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
        })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/registrationManagement/registrationList")
def registrationList(current_user: User = Depends(get_current_user), keyword: Optional[str] = None, db: Session = Depends(get_db)):
    today_weeky = datetime.datetime.now().weekday()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五"]
    if today_weeky > 4:
        return {"code": 200, "msg": "success", "data": "今天为休息日"}
    data = []
    schedules = db.query(DoctorSchedule).filter(DoctorSchedule.week == weekdays[today_weeky]).all()
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    for item in schedules:
        if patient_obj and db.query(Registration).filter(
            Registration.patient_id == patient_obj.patient_id,
            Registration.doctor_id == item.doctor_id,
            Registration.specialist == item.specialist,
            Registration.status == 0
        ).first():
            status = 1
        else:
            status = 0
        data.append({
            "id": item.schedule_id,
            "time": item.time,
            "specialist": item.specialist,
            "doctor": item.doctor.name if item.doctor else "",
            "doctor_id": item.doctor.doctor_id if item.doctor else None,
            "department_id": item.doctor.department.department_id if item.doctor and item.doctor.department else None,
            "stock": item.number,
            "status": status,
        })
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
    if reg_obj:
        reg_obj.number -= 1
        db.add(reg_obj)
    doctor_obj = db.query(Doctor).filter(Doctor.doctor_id == req.doctor_id).first()
    department_obj = db.query(Department).filter(Department.department_id == req.department_id).first()
    exists = db.query(Registration).filter(
        Registration.patient_id == patient_obj.patient_id,
        Registration.doctor_id == req.doctor_id,
        Registration.specialist == req.specialist,
        Registration.department_id == req.department_id,
        Registration.status == 0
    ).first()
    if exists:
        return {"code": 500, "msg": "您的挂号次数被限制"}
    registration = Registration(
        registration_id=1,
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


@router.post("/registrationManagement/cancel")
def patient_registration_cancel(req: UuidRequest, db: Session = Depends(get_db)):
    reg = db.query(Registration).filter(Registration.registration_uuid == req.uuid).first()
    if reg:
        reg.status = 3
        db.add(reg)
        db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/medicalRecord/getList")
def get_medical_record_list(current_user: User = Depends(get_current_user), keyword: Optional[str] = None, db: Session = Depends(get_db)):
    if current_user.user_role == "patient":
        patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
        if not patient_obj:
            return {"code": 200, "msg": "success", "data": []}
        records = db.query(MedicalRecord).filter(MedicalRecord.patient_id == patient_obj.patient_id).order_by(MedicalRecord.consultation_time.desc()).all()
        data = []
        for item in records:
            data.append({
                "uuid": str(item.medical_record_id),
                "consultation_time": str(item.consultation_time),
                "doctor_name": item.doctor.name if item.doctor else "",
                "symptom": item.symptom,
                "result": item.result,
            })
        return {"code": 200, "msg": "success", "data": data}
    elif current_user.user_role in ("doctor", "director"):
        doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
        if not doctor_obj:
            return {"code": 200, "msg": "success", "data": []}
        records = db.query(MedicalRecord).filter(MedicalRecord.doctor_id == doctor_obj.doctor_id).order_by(MedicalRecord.consultation_time.desc()).all()
        data = []
        for item in records:
            data.append({
                "uuid": str(item.medical_record_id),
                "consultation_time": str(item.consultation_time),
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "symptom": item.symptom,
                "result": item.result,
            })
        return {"code": 200, "msg": "success", "data": data}
    return {"code": 200, "msg": "success", "data": []}


@router.post("/medicalRecord/detail")
def get_medical_record_detail(req: MedicalRecordDetailRequest, db: Session = Depends(get_db)):
    record = db.query(MedicalRecord).filter(MedicalRecord.medical_record_id == req.medical_record_id).first()
    if not record:
        return {"code": 500, "msg": "病历不存在"}
    data = {
        "uuid": str(record.medical_record_id),
        "consultation_time": str(record.consultation_time),
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
        "birthday": str(patient_obj.birthday),
        "phone": patient_obj.phone,
        "address": patient_obj.address,
        "allergy_history": patient_obj.allergy_history or "",
    }
    return {"code": 200, "msg": "success", "data": data}


@router.get("/healthRecord/getVisits")
def get_visit_records(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient_obj:
        return {"code": 200, "msg": "success", "data": []}
    records = db.query(MedicalRecord).filter(MedicalRecord.patient_id == patient_obj.patient_id).order_by(MedicalRecord.consultation_time.desc()).all()
    data = []
    for item in records:
        data.append({
            "medical_record_id": item.medical_record_id,
            "visit_time": str(item.consultation_time),
            "doctor_name": item.doctor.name if item.doctor else "",
            "department": item.doctor.department.name if item.doctor and item.doctor.department else "",
            "diagnosis": item.result,
            "prescription_id": "",
        })
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
