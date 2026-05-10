import traceback
import datetime
from fastapi import APIRouter, Depends
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    User, Patient, Doctor, Department, DoctorSchedule,
    Pharmaceutical, Prescription, PrePha, Charge,
    MedicalRecord, LabOrder, Attendance
)
from app.schemas import (
    DoctorCreateRequest, DoctorScheduleCreateRequest,
    PharmaceuticalCreateRequest, PharmaceuticalStockQueryRequest,
    PrescriptionCreateRequest, PrescriptionCancelRequest,
    PharmaceuticalUpdateRequest, PharmaceuticalDeleteRequest,
    MedicalRecordCreateRequest, MedicalRecordUpdateRequest,
    LabOrderCreateRequest
)
from app.dependencies import get_current_user
from app.security import hash_password

router = APIRouter()


@router.post("/doctorManagement/register")
def add_doctor(req: DoctorCreateRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == req.username).first():
        return {"code": 500, "msg": "已存在相同用户"}
    password = hash_password(req.password)
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
    try:
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
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "排班保存失败"}


@router.get("/doctorScheduleManagement/getList")
def doctor_schedule_getlist(current_user: User = Depends(get_current_user), keyword: Optional[str] = None, db: Session = Depends(get_db)):
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
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


def parse_date_str(val):
    if isinstance(val, str):
        try:
            return datetime.datetime.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            return datetime.datetime.strptime(val, "%Y-%m-%d %H:%M:%S").date()
    return val


@router.post("/pharmaceuticalManagement/create")
def pharmaceutical_register(req: PharmaceuticalCreateRequest, db: Session = Depends(get_db)):
    pha = Pharmaceutical(
        name=req.name,
        stock=req.stock,
        price=float(req.price),
        expireddate=parse_date_str(req.expireddate),
        purchasing_time=datetime.datetime.now(),
        supplier=req.supplier,
        remark=req.remark,
    )
    db.add(pha)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/pharmaceuticalManagement/getList")
def get_pharmaceutical_list(keyword: Optional[str] = None, db: Session = Depends(get_db)):
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
            "antibiotic_level": item.antibiotic_level,
        })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/pharmaceuticalManagement/update")
def update_pharmaceutical(req: PharmaceuticalUpdateRequest, db: Session = Depends(get_db)):
    pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pharmaceutical_id).first()
    if not pha:
        return {"code": 500, "msg": "药品不存在"}
    pha.name = req.name
    pha.stock = req.stock
    pha.price = float(req.price)
    pha.expireddate = parse_date_str(req.expireddate)
    pha.supplier = req.supplier
    pha.remark = req.remark
    if hasattr(req, 'antibiotic_level'):
        pha.antibiotic_level = req.antibiotic_level
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


@router.get("/pharmaceuticalManagement/lowStock")
def get_low_stock_drugs(threshold: int = 10, keyword: Optional[str] = None, db: Session = Depends(get_db)):
    drugs = db.query(Pharmaceutical).filter(Pharmaceutical.stock <= threshold).order_by(Pharmaceutical.stock.asc()).all()
    data = []
    for item in drugs:
        data.append({
            "id": item.pharmaceutical_id,
            "name": item.name,
            "stock": item.stock,
            "threshold": threshold,
            "price": item.price,
            "expireddate": str(item.expireddate),
            "supplier": item.supplier,
        })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/pharmaceuticalManagement/nearExpiry")
def get_near_expiry_drugs(days: int = 30, keyword: Optional[str] = None, db: Session = Depends(get_db)):
    from datetime import date, timedelta
    cutoff = date.today() + timedelta(days=days)
    drugs = db.query(Pharmaceutical).filter(Pharmaceutical.expireddate <= cutoff).order_by(Pharmaceutical.expireddate.asc()).all()
    data = []
    for item in drugs:
        days_left = (item.expireddate - date.today()).days
        data.append({
            "id": item.pharmaceutical_id,
            "name": item.name,
            "stock": item.stock,
            "expireddate": str(item.expireddate),
            "days_left": days_left,
            "supplier": item.supplier,
        })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/prescriptionManagement/create")
def prescription_register(req: PrescriptionCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    patient_obj = db.query(Patient).filter(Patient.patient_id == req.patient).first()
    if not doctor_obj or not patient_obj:
        return {"code": 500, "msg": "医生或病人信息不存在"}
    try:
        # 抗菌药物分级审核
        restricted_phas = []  # 限制级
        special_phas = []  # 特殊使用级
        for item in req.phas:
            pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item["id"]).first()
            if pha:
                if pha.antibiotic_level == 2:
                    restricted_phas.append(pha.name)
                elif pha.antibiotic_level == 3:
                    special_phas.append(pha.name)
        # 限制级抗菌药：需要科室主任权限
        if restricted_phas and current_user.user_role not in ("director", "admin"):
            db.rollback()
            return {"code": 500, "msg": f"限制级抗菌药 [{', '.join(restricted_phas)}] 需科室主任审批后方可开具"}
        # 特殊使用级抗菌药：需要更高权限
        if special_phas and current_user.user_role != "admin":
            db.rollback()
            return {"code": 500, "msg": f"特殊使用级抗菌药 [{', '.join(special_phas)}] 需抗菌药物管理组审批后方可开具"}

        # ===== 处方前置审核 =====
        # 1. 过敏史冲突检查
        allergy_history = patient_obj.allergy_history or ""
        if allergy_history:
            allergy_keywords = [a.strip() for a in allergy_history.split(",") if a.strip()]
            for item in req.phas:
                pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item["id"]).first()
                if pha:
                    for kw in allergy_keywords:
                        if kw in pha.name or (pha.remark and kw in pha.remark):
                            db.rollback()
                            return {"code": 500, "msg": f"过敏史冲突：病人对 [{kw}] 过敏，处方包含 [{pha.name}]"}

        # 2. 配伍禁忌检查（硬编码常见禁忌组合）
        pha_ids = {item["id"] for item in req.phas}
        INCOMPATIBILITY = {
            # (药品A_id, 药品B_id): "禁忌原因"
        }
        for (a, b), reason in INCOMPATIBILITY.items():
            if a in pha_ids and b in pha_ids:
                db.rollback()
                return {"code": 500, "msg": f"配伍禁忌：{reason}"}

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
                if pha.stock < int(item["number"]):
                    db.rollback()
                    return {"code": 500, "msg": f"药品 {pha.name} 库存不足"}
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
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "处方开具失败"}


from app.pagination import paginate

@router.get("/prescriptionManagement/getList")
def get_prescription_list(current_user: User = Depends(get_current_user), keyword: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None, db: Session = Depends(get_db)):
    data = []
    total = 0
    query = db.query(Prescription)
    if current_user.user_role == "admin":
        pass
    elif current_user.user_role in ("doctor", "director"):
        doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
        if doctor_obj:
            query = query.filter(Prescription.doctor_id == doctor_obj.doctor_id)
        else:
            query = query.filter(Prescription.prescription_id == -1)
    elif current_user.user_role == "patient":
        patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
        if patient_obj:
            query = query.filter(Prescription.patient_id == patient_obj.patient_id)
        else:
            query = query.filter(Prescription.prescription_id == -1)
    else:
        query = query.filter(Prescription.prescription_id == -1)

    prescriptions, total = paginate(query, page, page_size)
    for item in prescriptions:
        phas = []
        for j in item.pre_phas:
            phas.append({"name": j.pharmaceutical.name if j.pharmaceutical else "", "number": j.number})
        charge_obj = db.query(Charge).filter(Charge.prescription_id == item.prescription_id).first()
        data.append({
            "uuid": str(item.prescription_id),
            "doctor_id": item.doctor.doctor_id if item.doctor else None,
            "doctor_name": item.doctor.name if item.doctor else "",
            "patient_id": item.patient.patient_id if item.patient else None,
            "patient_name": item.patient.name if item.patient else "",
            "phas": phas,
            "status": item.status,
            "create_time": str(item.create_time),
            "charge_id": str(charge_obj.charge_id) if charge_obj else "",
            "amount": round(charge_obj.amount, 2) if charge_obj else 0,
        })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


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
def get_lab_order_list(current_user: User = Depends(get_current_user), keyword: Optional[str] = None, db: Session = Depends(get_db)):
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
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/attendance/checkIn")
def attendance_check_in(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor_obj:
        return {"code": 500, "msg": "医生信息不存在"}
    today = datetime.datetime.now().date()
    existing = db.query(Attendance).filter(Attendance.doctor_id == doctor_obj.doctor_id, Attendance.date == today).first()
    if existing and existing.check_in_time:
        return {"code": 500, "msg": "今日已签到"}
    now = datetime.datetime.now()
    is_late = now.hour >= 9 and (now.hour > 9 or now.minute > 0)
    if existing:
        existing.check_in_time = now
        existing.status = 1 if is_late else 0
        db.add(existing)
    else:
        att = Attendance(
            doctor_id=doctor_obj.doctor_id,
            date=today,
            check_in_time=now,
            status=1 if is_late else 0,
        )
        db.add(att)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"status": "迟到" if is_late else "正常", "check_in_time": str(now)}}


@router.post("/attendance/checkOut")
def attendance_check_out(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor_obj:
        return {"code": 500, "msg": "医生信息不存在"}
    today = datetime.datetime.now().date()
    att = db.query(Attendance).filter(Attendance.doctor_id == doctor_obj.doctor_id, Attendance.date == today).first()
    if not att:
        return {"code": 500, "msg": "今日未签到，无法签退"}
    if att.check_out_time:
        return {"code": 500, "msg": "今日已签退"}
    now = datetime.datetime.now()
    is_early = now.hour < 17
    att.check_out_time = now
    if att.status == 0 and is_early:
        att.status = 2
    db.add(att)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"status": "早退" if is_early else "正常", "check_out_time": str(now)}}


@router.get("/attendance/getList")
def get_attendance_list(doctor_id: Optional[int] = None, start_date: Optional[str] = None, end_date: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Attendance).order_by(Attendance.date.desc())
    if doctor_id:
        query = query.filter(Attendance.doctor_id == doctor_id)
    if start_date:
        query = query.filter(Attendance.date >= start_date)
    if end_date:
        query = query.filter(Attendance.date <= end_date)
    records = query.all()
    data = []
    status_map = {0: "正常", 1: "迟到", 2: "早退", 3: "缺勤"}
    for item in records:
        data.append({
            "id": item.attendance_id,
            "doctor_id": item.doctor_id,
            "doctor_name": item.doctor.name if item.doctor else "",
            "date": str(item.date),
            "check_in_time": str(item.check_in_time) if item.check_in_time else "",
            "check_out_time": str(item.check_out_time) if item.check_out_time else "",
            "status": status_map.get(item.status, "未知"),
            "status_code": item.status,
        })
    return {"code": 200, "msg": "success", "data": data}
