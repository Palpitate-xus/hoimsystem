import traceback
import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    User, Patient, Doctor, Department, DoctorSchedule,
    Pharmaceutical, Prescription, PrePha, Charge,
    MedicalRecord, LabOrder
)
from app.schemas import (
    DoctorCreateRequest, DoctorScheduleCreateRequest,
    PharmaceuticalCreateRequest, PharmaceuticalStockQueryRequest,
    PrescriptionCreateRequest, PrescriptionCancelRequest,
    PharmaceuticalUpdateRequest, PharmaceuticalDeleteRequest,
    MedicalRecordCreateRequest, MedicalRecordUpdateRequest, MedicalRecordDetailRequest,
    LabOrderCreateRequest
)
from app.dependencies import get_current_user

router = APIRouter()


@router.post("/doctorManagement/register")
def add_doctor(req: DoctorCreateRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == req.username).first():
        return {"code": 500, "msg": "已存在相同用户"}
    password = req.password
    name = req.name
    title = req.title
    sex = 0 if req.sex == "女" else 1
    phone = req.phone
    department_obj = db.query(Department).filter(Department.department_id == req.department).first()
    permission = req.permission
    education = req.education
    try:
        if permission == "director":
            user = User(username=req.username, password=password, user_role="director")
        else:
            user = User(username=req.username, password=password, user_role="doctor")
        db.add(user)
        db.flush()
        doctor_obj = Doctor(
            name=name,
            sex=sex,
            title=title,
            education=education,
            phone=phone,
            permission=permission,
            department_id=req.department,
            user_id=user.user_id,
        )
        db.add(doctor_obj)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "医生注册失败"}


@router.post("/doctorScheduleManagement/register")
def doctor_schedule_register(req: DoctorScheduleCreateRequest, db: Session = Depends(get_db)):
    doctor_obj = db.query(Doctor).filter(Doctor.doctor_id == req.doctor).first()
    for i in req.schedule:
        week = i[0:3]
        time = i[3:5]
        existing = db.query(DoctorSchedule).filter(
            DoctorSchedule.week == week,
            DoctorSchedule.time == time,
            DoctorSchedule.doctor_id == req.doctor
        ).first()
        if existing:
            existing.number = req.number
            existing.specialist = req.specialist
            db.add(existing)
        else:
            new_schedule = DoctorSchedule(
                week=week,
                time=time,
                number=req.number,
                specialist=req.specialist,
                doctor_id=req.doctor,
            )
            db.add(new_schedule)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/doctorScheduleManagement/getList")
def doctor_schedule_getlist(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = []
    if current_user.user_role in ("admin", "patient"):
        doctor_list = db.query(Doctor).all()
        for i in doctor_list:
            schedule_list = db.query(DoctorSchedule).filter(DoctorSchedule.doctor_id == i.doctor_id).all()
            schedule = []
            number = 0
            specialist = 0
            for j in schedule_list:
                schedule.append(j.week[2] + j.time[0])
                number = j.number
                specialist = j.specialist
            data.append({
                "id": i.doctor_id,
                "name": i.name,
                "schedule": schedule,
                "number": number,
                "specialist": specialist,
            })
    elif current_user.user_role in ("doctor", "director"):
        doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
        if doctor_obj:
            schedule_list = db.query(DoctorSchedule).filter(DoctorSchedule.doctor_id == doctor_obj.doctor_id).all()
            schedule = []
            for i in schedule_list:
                schedule.append(i.week[2] + i.time[0])
            data.append({
                "id": doctor_obj.doctor_id,
                "name": doctor_obj.name,
                "schedule": schedule,
            })
    return {"code": 200, "msg": "success", "data": data}


@router.post("/pharmaceuticalManagement/create")
def pharmaceutical_register(req: PharmaceuticalCreateRequest, db: Session = Depends(get_db)):
    pha = Pharmaceutical(
        name=req.name,
        stock=req.stock,
        price=float(req.price),
        expireddate=req.expireddate,
        purchasing_time=datetime.datetime.now(),
        supplier=req.supplier,
        remark=req.remark,
    )
    db.add(pha)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/pharmaceuticalManagement/getList")
def get_pharmaceutical_list(db: Session = Depends(get_db)):
    pharmaceutical_list = db.query(Pharmaceutical).all()
    data = []
    for item in pharmaceutical_list:
        data.append({
            "id": item.pharmaceutical_id,
            "name": item.name,
            "stock": item.stock,
            "price": item.price,
            "expireddate": str(item.expireddate),
            "purchasing_time": str(item.purchasing_time),
            "supplier": item.supplier,
            "remark": item.remark,
        })
    return {"code": 200, "msg": "success", "data": data}


@router.post("/pharmaceuticalManagement/update")
def update_pharmaceutical(req: PharmaceuticalUpdateRequest, db: Session = Depends(get_db)):
    pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pharmaceutical_id).first()
    if not pha:
        return {"code": 500, "msg": "药品不存在"}
    pha.name = req.name
    pha.stock = req.stock
    pha.price = float(req.price)
    pha.expireddate = req.expireddate
    pha.supplier = req.supplier
    pha.remark = req.remark
    db.add(pha)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/pharmaceuticalManagement/delete")
def delete_pharmaceutical(req: PharmaceuticalDeleteRequest, db: Session = Depends(get_db)):
    pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pharmaceutical_id).first()
    if not pha:
        return {"code": 500, "msg": "药品不存在"}
    db.delete(pha)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/pharmaceuticalManagement/stock_query")
def pharmaceutical_stock_query(req: PharmaceuticalStockQueryRequest, db: Session = Depends(get_db)):
    pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.id).first()
    if pha:
        return {"code": 200, "msg": "success", "data": {"stock": pha.stock}}
    return {"code": 200, "msg": "success", "data": {"stock": 0}}


@router.post("/prescriptionManagement/create")
def prescription_register(req: PrescriptionCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    patient_obj = db.query(Patient).filter(Patient.patient_id == req.patient).first()
    if not doctor_obj or not patient_obj:
        return {"code": 500, "msg": "医生或病人信息不存在"}
    pre = Prescription(
        patient_id=patient_obj.patient_id,
        doctor_id=doctor_obj.doctor_id,
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(pre)
    db.flush()
    amount = 0
    for item in req.phas:
        pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item["id"]).first()
        if pha:
            pha.stock -= int(item["number"])
            db.add(pha)
            pp = PrePha(
                prescription_id=str(pre.prescription_id),
                pharmaceutical_id=pha.pharmaceutical_id,
                number=item["number"],
            )
            db.add(pp)
            amount += float(pha.price) * int(item["number"])
    charge = Charge(
        charge_time=datetime.datetime.now(),
        time=datetime.datetime(1970, 1, 1),
        prescription_id=pre.prescription_id,
        amount=amount,
        status=0,
    )
    db.add(charge)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/prescriptionManagement/getList")
def get_prescription_list(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = []
    if current_user.user_role == "admin":
        prescriptions = db.query(Prescription).all()
    elif current_user.user_role in ("doctor", "director"):
        doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
        if doctor_obj:
            prescriptions = db.query(Prescription).filter(Prescription.doctor_id == doctor_obj.doctor_id).all()
        else:
            prescriptions = []
    elif current_user.user_role == "patient":
        patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
        if patient_obj:
            prescriptions = db.query(Prescription).filter(Prescription.patient_id == patient_obj.patient_id).all()
        else:
            prescriptions = []
    else:
        prescriptions = []

    for item in prescriptions:
        phas = []
        for j in item.pre_phas:
            phas.append({"name": j.pharmaceutical.name if j.pharmaceutical else "", "number": j.number})
        data.append({
            "uuid": str(item.prescription_id),
            "doctor_id": item.doctor.doctor_id if item.doctor else None,
            "doctor_name": item.doctor.name if item.doctor else "",
            "patient_id": item.patient.patient_id if item.patient else None,
            "patient_name": item.patient.name if item.patient else "",
            "phas": phas,
            "status": item.status,
            "create_time": str(item.create_time),
        })
    return {"code": 200, "msg": "success", "data": data}


@router.post("/prescriptionManagement/cancel")
def cancel_prescription(req: PrescriptionCancelRequest, db: Session = Depends(get_db)):
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.prescription_id).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    pre.status = 3
    db.add(pre)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/medicalRecord/create")
def create_medical_record(req: MedicalRecordCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor_obj:
        return {"code": 500, "msg": "医生信息不存在"}
    record = MedicalRecord(
        consultation_time=datetime.datetime.now(),
        doctor_id=doctor_obj.doctor_id,
        patient_id=req.patient_id,
        symptom=req.symptom,
        result=req.result,
    )
    db.add(record)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/medicalRecord/getList")
def get_medical_record_list_doctor(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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


@router.post("/medicalRecord/detail")
def get_medical_record_detail_doctor(req: MedicalRecordDetailRequest, db: Session = Depends(get_db)):
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


@router.post("/medicalRecord/update")
def update_medical_record(req: MedicalRecordUpdateRequest, db: Session = Depends(get_db)):
    record = db.query(MedicalRecord).filter(MedicalRecord.medical_record_id == req.medical_record_id).first()
    if not record:
        return {"code": 500, "msg": "病历不存在"}
    record.symptom = req.symptom
    record.result = req.result
    db.add(record)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/labOrder/create")
def create_lab_order(req: LabOrderCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor_obj:
        return {"code": 500, "msg": "医生信息不存在"}
    lab_order = LabOrder(
        patient_id=req.patient_id,
        doctor_id=doctor_obj.doctor_id,
        check_type=req.check_type,
        check_items=str(req.check_items),
        urgent=req.urgent,
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(lab_order)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"lab_order_id": str(lab_order.lab_order_id)}}


@router.get("/labOrder/getList")
def get_lab_order_list(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor_obj:
        return {"code": 200, "msg": "success", "data": []}
    orders = db.query(LabOrder).filter(LabOrder.doctor_id == doctor_obj.doctor_id).order_by(LabOrder.create_time.desc()).all()
    data = []
    for item in orders:
        data.append({
            "id": str(item.lab_order_id),
            "patient_name": item.patient.name if item.patient else "",
            "check_type": item.check_type,
            "status": item.status,
            "create_time": str(item.create_time),
        })
    return {"code": 200, "msg": "success", "data": data}
