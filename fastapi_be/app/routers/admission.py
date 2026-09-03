import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import NURSING_ROLES, User, require_roles
from app.models import (
    Admission,
    Bed,
    InpatientCharge,
    Patient,
)
from app.schemas import AdmissionCreateRequest, AdmissionUpdateRequest

router = APIRouter()


def _generate_admission_no(db: Session) -> str:
    today = datetime.datetime.now().strftime("%Y%m%d")
    count = db.query(Admission).filter(Admission.admission_no.like(f"ZY{today}%")).count()
    candidate = f"ZY{today}{count + 1:03d}"
    # 并发防护：候选号已被占用时（count+1 撞号）改用序号+微秒后缀保证唯一
    exists = db.query(Admission).filter(Admission.admission_no == candidate).first()
    if exists:
        us = datetime.datetime.now().strftime("%f")
        candidate = f"ZY{today}{count + 1:03d}{us}"
    return candidate



@router.get("/admission/getList")
def get_admission_list(
    status: int | None = None,
    ward_id: int | None = None,
    keyword: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    current_user: User = Depends(require_roles(*NURSING_ROLES)),
    db: Session = Depends(get_db),
):
    from app.pagination import paginate

    query = db.query(Admission).options(
        joinedload(Admission.patient),
        joinedload(Admission.doctor),
        joinedload(Admission.department),
        joinedload(Admission.ward),
        joinedload(Admission.bed),
    )
    if status is not None:
        query = query.filter(Admission.status == status)
    if ward_id is not None:
        query = query.filter(Admission.ward_id == ward_id)
    if keyword:
        from app.models import Patient as _Patient

        kw = f"%{keyword}%"
        query = query.outerjoin(_Patient, Admission.patient_id == _Patient.patient_id).filter(
            db.query(_Patient).filter(
                _Patient.patient_id == Admission.patient_id,
                (_Patient.name.like(kw)) | (_Patient.identity.like(kw)) | (_Patient.phone.like(kw)),
            ).exists()
            | Admission.admission_no.like(kw)
            | Admission.admission_diagnosis.like(kw)
        )
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
                "admission_time": (item.admission_time.strftime("%Y-%m-%d %H:%M:%S") if item.admission_time else None) if item.admission_time else "",
                "admission_diagnosis": item.admission_diagnosis or "",
                "chief_complaint": item.chief_complaint or "",
                "deposit_amount": item.deposit_amount,
                "discharge_time": (item.discharge_time.strftime("%Y-%m-%d %H:%M:%S") if item.discharge_time else None) if item.discharge_time else "",
                "status": item.status,
                "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
            }
        )
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/admission/create")
def create_admission(req: AdmissionCreateRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
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
    # 必须 flush 生成主键（admission_id 为 Python 端 uuid default），
    # 否则下方床位费的 admission_id 为 NULL，成为孤儿费用记录、住院账单漏计
    db.flush()

    # 占用床位
    bed.status = 1
    db.add(bed)

    # 创建床位费记录（首日；后续每日由出院结算按住院天数补差）
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

    # 并发重号防护：冲突时住院号追加当日序时后缀重试（rollback 会丢床位/床位费写入，
    # 因此采用"重算唯一号 + 全量重建"策略——重建由调用方 create 重入完成，此处仅拒绝并提示）
    from sqlalchemy.exc import IntegrityError

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"code": 500, "msg": "住院号生成冲突（并发入院），请重试登记"}
    return {"code": 200, "msg": "success", "data": {"admission_id": admission.admission_id, "admission_no": admission_no}}


@router.get("/admission/detail")
def get_admission_detail(admission_id: str, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    item = (
        db.query(Admission)
        .options(
            joinedload(Admission.patient),
            joinedload(Admission.doctor),
            joinedload(Admission.department),
            joinedload(Admission.ward),
            joinedload(Admission.bed),
        )
        .filter(Admission.admission_id == admission_id)
        .first()
    )
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
        "admission_time": (item.admission_time.strftime("%Y-%m-%d %H:%M:%S") if item.admission_time else None) if item.admission_time else "",
        "admission_diagnosis": item.admission_diagnosis or "",
        "chief_complaint": item.chief_complaint or "",
        "present_illness": item.present_illness or "",
        "past_history": item.past_history or "",
        "deposit_amount": item.deposit_amount,
        "discharge_time": (item.discharge_time.strftime("%Y-%m-%d %H:%M:%S") if item.discharge_time else None) if item.discharge_time else "",
        "discharge_diagnosis": item.discharge_diagnosis or "",
        "status": item.status,
        "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
    }
    return {"code": 200, "msg": "success", "data": data}


@router.post("/admission/update")
def update_admission(req: AdmissionUpdateRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
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
        # 出院/退院不允许走本接口：会绕过 doDischarge 的费用结算、医嘱停止
        # 与出院小结生成。请使用 /discharge/doDischarge。
        if req.status in (2, 3):
            return {"code": 500, "msg": "出院/退院请使用出院结算接口办理，不能直接修改状态"}
        admission.status = req.status
    db.add(admission)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/admission/getAvailableBeds")
def get_available_beds(ward_id: int | None = None, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    query = db.query(Bed).options(joinedload(Bed.ward)).filter(Bed.status == 0)
    if ward_id:
        query = query.filter(Bed.ward_id == ward_id)
    beds = query.all()
    data = []
    for item in beds:
        data.append(
            {
                "bed_id": item.bed_id,
                "bed_no": item.bed_no,
                "room_no": item.room_no or "",
                "bed_type": item.bed_type,
                "price_per_day": item.price_per_day,
                "ward_id": item.ward_id,
                "ward_name": item.ward.name if item.ward else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.get("/admission/getInpatientList")
def get_inpatient_list(ward_id: int | None = None, doctor_id: int | None = None, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    query = db.query(Admission).options(
        joinedload(Admission.patient),
        joinedload(Admission.doctor),
        joinedload(Admission.department),
        joinedload(Admission.ward),
        joinedload(Admission.bed),
    ).filter(Admission.status == 1)
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
                "admission_time": (item.admission_time.strftime("%Y-%m-%d %H:%M:%S") if item.admission_time else None) if item.admission_time else "",
                "admission_diagnosis": item.admission_diagnosis or "",
                "days": (datetime.datetime.now() - item.admission_time).days + 1 if item.admission_time else 0,
            }
        )
    return {"code": 200, "msg": "success", "data": data}
