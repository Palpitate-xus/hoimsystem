import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    Admission,
    AnesthesiaRecord,
    Doctor,
    InpatientCharge,
    Patient,
    SurgeryApplication,
    SurgerySchedule,
    User,
)

router = APIRouter()


@router.get("/surgeryApplication/getList")
def get_surgery_application_list(
    status: int | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(SurgeryApplication).order_by(SurgeryApplication.create_time.desc())
    if status is not None:
        query = query.filter(SurgeryApplication.status == status)
    applications = query.all()

    status_map = ["待审批", "已批准", "已排台", "已完成", "已取消"]
    level_map = ["", "一级", "二级", "三级", "四级"]
    data = []
    for item in applications:
        data.append(
            {
                "application_id": item.application_id,
                "admission_id": item.admission_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "patient_identity": item.patient.identity if item.patient else "",
                "doctor_id": item.doctor_id,
                "doctor_name": item.doctor.name if item.doctor else "",
                "surgery_name": item.surgery_name,
                "surgery_code": item.surgery_code or "",
                "surgery_level": item.surgery_level,
                "surgery_level_text": level_map[item.surgery_level] if item.surgery_level and item.surgery_level < len(level_map) else "",
                "anesthesia_type": item.anesthesia_type,
                "scheduled_date": str(item.scheduled_date) if item.scheduled_date else "",
                "preop_diagnosis": item.preop_diagnosis or "",
                "status": item.status,
                "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
                "approver_name": item.approver.name if item.approver else "",
                "approve_time": (item.approve_time.strftime("%Y-%m-%d %H:%M:%S") if item.approve_time else None) if item.approve_time else "",
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/surgeryApplication/create")
def create_surgery_application(req: dict, db: Session = Depends(get_db)):
    admission = db.query(Admission).filter(Admission.admission_id == req.get("admission_id")).first()
    if not admission:
        return {"code": 500, "msg": "入院记录不存在"}

    application = SurgeryApplication(
        admission_id=req.get("admission_id"),
        patient_id=req.get("patient_id"),
        doctor_id=req.get("doctor_id"),
        surgery_name=req.get("surgery_name", ""),
        surgery_code=req.get("surgery_code"),
        surgery_level=req.get("surgery_level", 1),
        anesthesia_type=req.get("anesthesia_type", "局部麻醉"),
        scheduled_date=req.get("scheduled_date"),
        preop_diagnosis=req.get("preop_diagnosis"),
        surgery_indication=req.get("surgery_indication"),
        contraindication=req.get("contraindication"),
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(application)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"application_id": application.application_id}}


@router.post("/surgeryApplication/approve")
def approve_surgery_application(req: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    application = db.query(SurgeryApplication).filter(SurgeryApplication.application_id == req.get("application_id")).first()
    if not application:
        return {"code": 500, "msg": "申请不存在"}
    if application.status != 0:
        return {"code": 500, "msg": "申请状态不正确"}
    application.status = 1
    application.approver_id = current_user.user_id
    application.approve_time = datetime.datetime.now()
    db.add(application)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/surgeryApplication/cancel")
def cancel_surgery_application(req: dict, db: Session = Depends(get_db)):
    application = db.query(SurgeryApplication).filter(SurgeryApplication.application_id == req.get("application_id")).first()
    if not application:
        return {"code": 500, "msg": "申请不存在"}
    application.status = 4
    db.add(application)
    # 取消已排台的手术
    schedule = db.query(SurgerySchedule).filter(SurgerySchedule.application_id == req.get("application_id")).first()
    if schedule:
        schedule.status = 3
        db.add(schedule)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/surgerySchedule/getList")
def get_surgery_schedule_list(
    surgery_date: str | None = None,
    status: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(SurgerySchedule).order_by(SurgerySchedule.surgery_date.desc())
    if surgery_date:
        try:
            from datetime import date as dt_date
            d = dt_date.fromisoformat(surgery_date)
            query = query.filter(SurgerySchedule.surgery_date == d)
        except ValueError:
            pass
    if status is not None:
        query = query.filter(SurgerySchedule.status == status)
    schedules = query.all()

    status_map = ["待手术", "手术中", "已完成", "已取消"]
    data = []
    for item in schedules:
        data.append(
            {
                "schedule_id": item.schedule_id,
                "application_id": item.application_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "surgery_name": item.application.surgery_name if item.application else "",
                "operating_room": item.operating_room,
                "surgery_date": str(item.surgery_date) if item.surgery_date else "",
                "start_time": (item.start_time.strftime("%Y-%m-%d %H:%M:%S") if item.start_time else None) if item.start_time else "",
                "end_time": str(item.end_time) if item.end_time else "",
                "surgeon_name": item.surgeon.name if item.surgeon else "",
                "anesthesiologist_name": item.anesthesiologist.name if item.anesthesiologist else "",
                "status": item.status,
                "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/surgerySchedule/create")
def create_surgery_schedule(req: dict, db: Session = Depends(get_db)):
    application = db.query(SurgeryApplication).filter(SurgeryApplication.application_id == req.get("application_id")).first()
    if not application:
        return {"code": 500, "msg": "手术申请不存在"}
    if application.status != 1:
        return {"code": 500, "msg": "申请未批准，无法排台"}

    schedule = SurgerySchedule(
        application_id=req.get("application_id"),
        patient_id=application.patient_id,
        operating_room=req.get("operating_room", ""),
        surgery_date=req.get("surgery_date"),
        surgeon_id=req.get("surgeon_id"),
        assistant_ids=req.get("assistant_ids"),
        anesthesiologist_id=req.get("anesthesiologist_id"),
        scrub_nurse_id=req.get("scrub_nurse_id"),
        circulating_nurse_id=req.get("circulating_nurse_id"),
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(schedule)

    application.status = 2
    db.add(application)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"schedule_id": schedule.schedule_id}}


@router.post("/surgerySchedule/start")
def start_surgery(req: dict, db: Session = Depends(get_db)):
    schedule = db.query(SurgerySchedule).filter(SurgerySchedule.schedule_id == req.get("schedule_id")).first()
    if not schedule:
        return {"code": 500, "msg": "排台记录不存在"}
    schedule.status = 1
    schedule.start_time = datetime.datetime.now()
    db.add(schedule)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/surgerySchedule/complete")
def complete_surgery(req: dict, db: Session = Depends(get_db)):
    schedule = db.query(SurgerySchedule).filter(SurgerySchedule.schedule_id == req.get("schedule_id")).first()
    if not schedule:
        return {"code": 500, "msg": "排台记录不存在"}
    schedule.status = 2
    schedule.end_time = datetime.datetime.now()
    db.add(schedule)

    application = db.query(SurgeryApplication).filter(SurgeryApplication.application_id == schedule.application_id).first()
    if application:
        application.status = 3
        db.add(application)

    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/anesthesiaRecord/getList")
def get_anesthesia_record_list(schedule_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(AnesthesiaRecord).order_by(AnesthesiaRecord.create_time.desc())
    if schedule_id:
        query = query.filter(AnesthesiaRecord.schedule_id == schedule_id)
    records = query.all()
    data = []
    for item in records:
        data.append(
            {
                "record_id": item.record_id,
                "schedule_id": item.schedule_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "anesthesiologist_name": item.anesthesiologist.name if item.anesthesiologist else "",
                "enter_time": (item.enter_time.strftime("%Y-%m-%d %H:%M:%S") if item.enter_time else None) if item.enter_time else "",
                "anesthesia_method": item.anesthesia_method or "",
                "blood_loss": item.blood_loss,
                "urine_output": item.urine_output,
                "fluid_input": item.fluid_input,
                "leave_time": (item.leave_time.strftime("%Y-%m-%d %H:%M:%S") if item.leave_time else None) if item.leave_time else "",
                "complications": item.complications or "",
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/anesthesiaRecord/create")
def create_anesthesia_record(req: dict, db: Session = Depends(get_db)):
    schedule = db.query(SurgerySchedule).filter(SurgerySchedule.schedule_id == req.get("schedule_id")).first()
    if not schedule:
        return {"code": 500, "msg": "手术排台不存在"}

    record = AnesthesiaRecord(
        schedule_id=req.get("schedule_id"),
        patient_id=schedule.patient_id,
        anesthesiologist_id=req.get("anesthesiologist_id"),
        enter_time=req.get("enter_time"),
        consciousness=req.get("consciousness"),
        preop_bp=req.get("preop_bp"),
        preop_hr=req.get("preop_hr"),
        preop_spo2=req.get("preop_spo2"),
        anesthesia_method=req.get("anesthesia_method"),
        induction_drugs=req.get("induction_drugs"),
        maintenance_drugs=req.get("maintenance_drugs"),
        intraop_bp=req.get("intraop_bp"),
        intraop_hr=req.get("intraop_hr"),
        blood_loss=req.get("blood_loss", 0),
        urine_output=req.get("urine_output", 0),
        fluid_input=req.get("fluid_input", 0),
        extubation_time=req.get("extubation_time"),
        leave_time=req.get("leave_time"),
        postop_consciousness=req.get("postop_consciousness"),
        complications=req.get("complications"),
        create_time=datetime.datetime.now(),
    )
    db.add(record)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"record_id": record.record_id}}
