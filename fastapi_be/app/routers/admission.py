import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    Admission,
    Bed,
    Department,
    Doctor,
    InpatientCharge,
    Patient,
    User,
    Ward,
)
from app.schemas import AdmissionCreateRequest, AdmissionUpdateRequest

router = APIRouter()


def _generate_admission_no(db: Session) -> str:
    today = datetime.datetime.now().strftime("%Y%m%d")
    count = db.query(Admission).filter(Admission.admission_no.like(f"ZY{today}%")).count()
    return f"ZY{today}{count + 1:03d}"


@router.get("/admission/getList")
def get_admission_list(
    status: int | None = None,
    ward_id: int | None = None,
    keyword: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    db: Session = Depends(get_db),
):
    from app.pagination import paginate

    query = db.query(Admission)
    if status is not None:
        query = query.filter(Admission.status == status)
    if ward_id is not None:
        query = query.filter(Admission.ward_id == ward_id)
    query = query.order_by(Admission.create_time.desc())
    records, total = paginate(query, page, page_size)

    status_map = ["待入院", "在院", "已出院", "已退院"]
    type_map = ["门诊入院", "急诊入院", "转诊入院", "预约入院"]
    data = []
    for item in records:
        data.append(
            {
                "admission_id": item.admission_id,
                "admission_no": item.admission_no,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "patient_identity": item.patient.identity if item.patient else "",
                "patient_sex": "男" if item.patient and item.patient.sex == 1 else "女",
                "doctor_id": item.doctor_id,
                "doctor_name": item.doctor.name if item.doctor else "",
                "department_id": item.department_id,
                "department_name": item.department.name if item.department else "",
                "ward_id": item.ward_id,
                "ward_name": item.ward.name if item.ward else "",
                "bed_id": item.bed_id,
                "bed_no": item.bed.bed_no if item.bed else "",
                "room_no": item.bed.room_no if item.bed else "",
                "admission_type": item.admission_type,
                "admission_type_text": type_map[item.admission_type] if item.admission_type is not None and item.admission_type < len(type_map) else "",
                "admission_time": str(item.admission_time) if item.admission_time else "",
                "admission_diagnosis": item.admission_diagnosis or "",
                "chief_complaint": item.chief_complaint or "",
                "deposit_amount": item.deposit_amount,
                "discharge_time": str(item.discharge_time) if item.discharge_time else "",
                "status": item.status,
                "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/admission/create")
def create_admission(req: AdmissionCreateRequest, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.patient_id).first()
    if not patient:
        return {"code": 500, "msg": "病人不存在"}
    bed = db.query(Bed).filter(Bed.bed_id == req.bed_id).first()
    if not bed:
        return {"code": 500, "msg": "床位不存在"}
    if bed.status == 1:
        return {"code": 500, "msg": "该床位已被占用"}
    if bed.status == 2:
        return {"code": 500, "msg": "该床位已禁用"}

    # 检查是否已有在院记录
    existing = (
        db.query(Admission)
        .filter(Admission.patient_id == req.patient_id, Admission.status == 1)
        .first()
    )
    if existing:
        return {"code": 500, "msg": "该病人已有在院记录"}

    admission_no = _generate_admission_no(db)
    admission = Admission(
        admission_no=admission_no,
        patient_id=req.patient_id,
        doctor_id=req.doctor_id,
        department_id=req.department_id,
        ward_id=req.ward_id,
        bed_id=req.bed_id,
        admission_type=req.admission_type,
        admission_time=datetime.datetime.now(),
        admission_diagnosis=req.admission_diagnosis,
        chief_complaint=req.chief_complaint,
        present_illness=req.present_illness,
        past_history=req.past_history,
        deposit_amount=req.deposit_amount,
        status=1,
        create_time=datetime.datetime.now(),
    )
    db.add(admission)

    # 占用床位
    bed.status = 1
    db.add(bed)

    # 创建床位费记录
    if bed.price_per_day > 0:
        charge = InpatientCharge(
            admission_id=admission.admission_id,
            patient_id=req.patient_id,
            item_name=f"床位费({bed.bed_type})",
            item_type="bed",
            quantity=1,
            unit_price=bed.price_per_day,
            total_amount=bed.price_per_day,
            charge_date=datetime.datetime.now().date(),
            status=0,
            create_time=datetime.datetime.now(),
        )
        db.add(charge)

    db.commit()
    return {"code": 200, "msg": "success", "data": {"admission_id": admission.admission_id, "admission_no": admission_no}}


@router.get("/admission/detail")
def get_admission_detail(admission_id: str, db: Session = Depends(get_db)):
    item = db.query(Admission).filter(Admission.admission_id == admission_id).first()
    if not item:
        return {"code": 500, "msg": "入院记录不存在"}
    status_map = ["待入院", "在院", "已出院", "已退院"]
    type_map = ["门诊入院", "急诊入院", "转诊入院", "预约入院"]
    data = {
        "admission_id": item.admission_id,
        "admission_no": item.admission_no,
        "patient_id": item.patient_id,
        "patient_name": item.patient.name if item.patient else "",
        "patient_identity": item.patient.identity if item.patient else "",
        "patient_sex": "男" if item.patient and item.patient.sex == 1 else "女",
        "patient_birthday": str(item.patient.birthday) if item.patient and item.patient.birthday else "",
        "patient_phone": item.patient.phone if item.patient else "",
        "patient_address": item.patient.address if item.patient else "",
        "doctor_id": item.doctor_id,
        "doctor_name": item.doctor.name if item.doctor else "",
        "department_id": item.department_id,
        "department_name": item.department.name if item.department else "",
        "ward_id": item.ward_id,
        "ward_name": item.ward.name if item.ward else "",
        "bed_id": item.bed_id,
        "bed_no": item.bed.bed_no if item.bed else "",
        "room_no": item.bed.room_no if item.bed else "",
        "bed_type": item.bed.bed_type if item.bed else "",
        "admission_type": item.admission_type,
        "admission_type_text": type_map[item.admission_type] if item.admission_type is not None and item.admission_type < len(type_map) else "",
        "admission_time": str(item.admission_time) if item.admission_time else "",
        "admission_diagnosis": item.admission_diagnosis or "",
        "chief_complaint": item.chief_complaint or "",
        "present_illness": item.present_illness or "",
        "past_history": item.past_history or "",
        "deposit_amount": item.deposit_amount,
        "discharge_time": str(item.discharge_time) if item.discharge_time else "",
        "discharge_diagnosis": item.discharge_diagnosis or "",
        "status": item.status,
        "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
    }
    return {"code": 200, "msg": "success", "data": data}


@router.post("/admission/update")
def update_admission(req: AdmissionUpdateRequest, db: Session = Depends(get_db)):
    admission = db.query(Admission).filter(Admission.admission_id == req.admission_id).first()
    if not admission:
        return {"code": 500, "msg": "入院记录不存在"}
    if req.bed_id is not None and req.bed_id != admission.bed_id:
        # 换床
        old_bed = db.query(Bed).filter(Bed.bed_id == admission.bed_id).first()
        new_bed = db.query(Bed).filter(Bed.bed_id == req.bed_id).first()
        if not new_bed:
            return {"code": 500, "msg": "新床位不存在"}
        if new_bed.status == 1:
            return {"code": 500, "msg": "新床位已被占用"}
        if old_bed:
            old_bed.status = 0
            db.add(old_bed)
        new_bed.status = 1
        db.add(new_bed)
        admission.bed_id = req.bed_id
    if req.admission_diagnosis is not None:
        admission.admission_diagnosis = req.admission_diagnosis
    if req.status is not None:
        admission.status = req.status
        if req.status == 2:  # 已出院
            admission.discharge_time = datetime.datetime.now()
            bed = db.query(Bed).filter(Bed.bed_id == admission.bed_id).first()
            if bed:
                bed.status = 0
                db.add(bed)
        elif req.status == 3:  # 已退院
            bed = db.query(Bed).filter(Bed.bed_id == admission.bed_id).first()
            if bed:
                bed.status = 0
                db.add(bed)
    db.add(admission)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/admission/getAvailableBeds")
def get_available_beds(ward_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Bed).filter(Bed.status == 0)
    if ward_id:
        query = query.filter(Bed.ward_id == ward_id)
    beds = query.all()
    data = []
    for item in beds:
        ward = db.query(Ward).filter(Ward.ward_id == item.ward_id).first()
        data.append(
            {
                "bed_id": item.bed_id,
                "bed_no": item.bed_no,
                "room_no": item.room_no or "",
                "bed_type": item.bed_type,
                "price_per_day": item.price_per_day,
                "ward_id": item.ward_id,
                "ward_name": ward.name if ward else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.get("/admission/getInpatientList")
def get_inpatient_list(ward_id: int | None = None, doctor_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Admission).filter(Admission.status == 1)
    if ward_id:
        query = query.filter(Admission.ward_id == ward_id)
    if doctor_id:
        query = query.filter(Admission.doctor_id == doctor_id)
    records = query.order_by(Admission.admission_time.desc()).all()
    data = []
    for item in records:
        data.append(
            {
                "admission_id": item.admission_id,
                "admission_no": item.admission_no,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "patient_identity": item.patient.identity if item.patient else "",
                "patient_sex": "男" if item.patient and item.patient.sex == 1 else "女",
                "doctor_id": item.doctor_id,
                "doctor_name": item.doctor.name if item.doctor else "",
                "department_name": item.department.name if item.department else "",
                "ward_name": item.ward.name if item.ward else "",
                "bed_no": item.bed.bed_no if item.bed else "",
                "room_no": item.bed.room_no if item.bed else "",
                "admission_time": str(item.admission_time) if item.admission_time else "",
                "admission_diagnosis": item.admission_diagnosis or "",
                "days": (datetime.datetime.now() - item.admission_time).days + 1 if item.admission_time else 0,
            }
        )
    return {"code": 200, "msg": "success", "data": data}
