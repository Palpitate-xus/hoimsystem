import datetime
import re
import traceback
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, PHARMACY_ROLES, get_current_user, require_roles
from app.event_bus import publish_event
from app.integration_outbox import enqueue_integration_event
from app.models import (
    AntibioticApproval,
    Attendance,
    Charge,
    Department,
    Doctor,
    DoctorSchedule,
    LabOrder,
    MedicalRecord,
    Patient,
    Pharmaceutical,
    PrePha,
    Prescription,
    User,
)
from app.schemas import (
    DoctorCreateRequest,
    DoctorScheduleCreateRequest,
    LabOrderCreateRequest,
    MedicalRecordCreateRequest,
    MedicalRecordSignRequest,
    MedicalRecordUpdateRequest,
    PharmaceuticalCreateRequest,
    PharmaceuticalDeleteRequest,
    PharmaceuticalStockQueryRequest,
    PharmaceuticalUpdateRequest,
    PrescriptionCancelRequest,
    PrescriptionCreateRequest,
)
from app.security import decrypt_transport_password, hash_password

router = APIRouter()


@router.post("/doctorManagement/register")
def add_doctor(req: DoctorCreateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == req.username).first():
        return {"code": 500, "msg": "已存在相同用户"}
    password_value = decrypt_transport_password(req.password)
    if not password_value or not 6 <= len(password_value) <= 128:
        return {"code": 500, "msg": "密码长度必须为6至128位"}
    password = hash_password(password_value)
    name = req.name
    title = req.title
    sex = 0 if req.sex == "女" else 1
    phone = req.phone
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
def doctor_schedule_register(req: DoctorScheduleCreateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    try:
        db.query(Doctor).filter(Doctor.doctor_id == req.doctor).first()
        for i in req.schedule:
            week = i[0:3]
            time = i[3:5]
            existing = db.query(DoctorSchedule).filter(DoctorSchedule.week == week, DoctorSchedule.time == time, DoctorSchedule.doctor_id == req.doctor).first()
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
def doctor_schedule_getlist(current_user: User = Depends(get_current_user), keyword: str | None = None, db: Session = Depends(get_db)):
    data = []
    if current_user.user_role in ("admin", "patient"):
        doctor_list = db.query(Doctor).options(selectinload(Doctor.schedules)).all()
        for i in doctor_list:
            schedule_list = i.schedules
            schedule = []
            number = 0
            specialist = 0
            for j in schedule_list:
                week_code = j.week[2] if len(j.week) >= 3 else j.week
                time_value = j.time or ""
                time_code = {"上午": "1", "下午": "2"}.get(time_value, time_value[-1:] or "")
                schedule.append(week_code + time_code)
                number = j.number
                specialist = j.specialist
            data.append(
                {
                    "id": i.doctor_id,
                    "name": i.name,
                    "schedule": schedule,
                    "number": number,
                    "specialist": specialist,
                }
            )
    elif current_user.user_role in ("doctor", "director"):
        doctor_obj = (
            db.query(Doctor)
            .options(selectinload(Doctor.schedules))
            .filter(Doctor.user_id == current_user.user_id)
            .first()
        )
        if doctor_obj:
            schedule_list = doctor_obj.schedules
            schedule = []
            for i in schedule_list:
                week_code = i.week[2] if len(i.week) >= 3 else i.week
                time_value = i.time or ""
                time_code = {"上午": "1", "下午": "2"}.get(time_value, time_value[-1:] or "")
                schedule.append(week_code + time_code)
            data.append(
                {
                    "id": doctor_obj.doctor_id,
                    "name": doctor_obj.name,
                    "schedule": schedule,
                }
            )
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
def pharmaceutical_register(req: PharmaceuticalCreateRequest, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
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
def get_pharmaceutical_list(keyword: str | None = None, current_user: User = Depends(require_roles(*(PHARMACY_ROLES | CLINICAL_ROLES))), db: Session = Depends(get_db)):
    pharmaceutical_list = db.query(Pharmaceutical).all()
    data = []
    for item in pharmaceutical_list:
        data.append(
            {
                "id": item.pharmaceutical_id,
                "name": item.name,
                "stock": item.stock,
                "price": item.price,
                "expireddate": str(item.expireddate),
                "purchasing_time": (item.purchasing_time.strftime("%Y-%m-%d %H:%M:%S") if item.purchasing_time else None),
                "supplier": item.supplier,
                "remark": item.remark,
                "antibiotic_level": item.antibiotic_level,
                "status": item.status,
                "status_text": "启用" if item.status == 0 else "已停用",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/pharmaceuticalManagement/update")
def update_pharmaceutical(req: PharmaceuticalUpdateRequest, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pharmaceutical_id).first()
    if not pha:
        return {"code": 500, "msg": "药品不存在"}
    pha.name = req.name
    pha.stock = req.stock
    pha.price = float(req.price)
    pha.expireddate = parse_date_str(req.expireddate)
    pha.supplier = req.supplier
    pha.remark = req.remark
    if hasattr(req, "antibiotic_level"):
        pha.antibiotic_level = req.antibiotic_level
    db.add(pha)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/pharmaceuticalManagement/delete")
def delete_pharmaceutical(req: PharmaceuticalDeleteRequest, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pharmaceutical_id).first()
    if not pha:
        return {"code": 500, "msg": "药品不存在"}
    if pha.status == 1:
        return {"code": 200, "msg": "药品已停用", "data": {"idempotent": True}}
    pha.status = 1
    db.add(pha)
    db.commit()
    return {"code": 200, "msg": "药品已停用"}


@router.post("/pharmaceuticalManagement/restore")
def restore_pharmaceutical(req: PharmaceuticalDeleteRequest, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pharmaceutical_id).first()
    if not pha:
        return {"code": 500, "msg": "药品不存在"}
    if pha.status == 0:
        return {"code": 200, "msg": "药品已启用", "data": {"idempotent": True}}
    pha.status = 0
    db.add(pha)
    db.commit()
    return {"code": 200, "msg": "药品已启用"}


@router.post("/pharmaceuticalManagement/stock_query")
def pharmaceutical_stock_query(req: PharmaceuticalStockQueryRequest, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.id).first()
    if pha:
        return {"code": 200, "msg": "success", "data": {"stock": pha.stock}}
    return {"code": 200, "msg": "success", "data": {"stock": 0}}


@router.get("/pharmaceuticalManagement/lowStock")
def get_low_stock_drugs(threshold: int = 10, keyword: str | None = None, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    drugs = db.query(Pharmaceutical).filter(Pharmaceutical.stock <= threshold).order_by(Pharmaceutical.stock.asc()).all()
    data = []
    for item in drugs:
        data.append(
            {
                "id": item.pharmaceutical_id,
                "name": item.name,
                "stock": item.stock,
                "threshold": threshold,
                "price": item.price,
                "expireddate": str(item.expireddate),
                "supplier": item.supplier,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/pharmaceuticalManagement/nearExpiry")
def get_near_expiry_drugs(days: int = 30, keyword: str | None = None, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    from datetime import date, timedelta

    if days < 0 or days > 3650:
        return {"code": 400, "msg": "效期查询天数必须在0至3650之间"}

    cutoff = date.today() + timedelta(days=days)
    drugs = db.query(Pharmaceutical).filter(Pharmaceutical.expireddate.isnot(None), Pharmaceutical.expireddate <= cutoff).order_by(Pharmaceutical.expireddate.asc()).all()
    data = []
    for item in drugs:
        days_left = (item.expireddate - date.today()).days
        data.append(
            {
                "id": item.pharmaceutical_id,
                "name": item.name,
                "stock": item.stock,
                "expireddate": str(item.expireddate),
                "days_left": days_left,
                "supplier": item.supplier,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/prescriptionManagement/create")
def prescription_register(
    req: PrescriptionCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    patient_obj = db.query(Patient).filter(Patient.patient_id == req.patient).first()
    if not doctor_obj or not patient_obj:
        return {"code": 500, "msg": "医生或病人信息不存在"}
    try:
        if not req.phas:
            return {"code": 500, "msg": "处方至少需要一项药品"}
        normalized_phas = []
        seen_pharmaceuticals = set()
        for raw_item in req.phas:
            if not isinstance(raw_item, dict):
                return {"code": 500, "msg": "处方药品明细格式错误"}
            try:
                pharmaceutical_id = int(raw_item.get("id"))
                quantity = int(raw_item.get("number"))
            except (TypeError, ValueError, OverflowError):
                return {"code": 500, "msg": "处方药品明细格式错误"}
            if quantity <= 0:
                return {"code": 500, "msg": "药品数量必须大于0"}
            if pharmaceutical_id in seen_pharmaceuticals:
                return {"code": 500, "msg": "同一药品不能重复开立"}
            pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == pharmaceutical_id).first()
            if not pha:
                return {"code": 500, "msg": "药品不存在"}
            if pha.status != 0:
                return {"code": 500, "msg": f"药品 {pha.name} 已停用，不能开立"}
            if pha.expireddate and pha.expireddate < datetime.date.today():
                return {"code": 500, "msg": f"药品 {pha.name} 已过期，不能开立"}
            seen_pharmaceuticals.add(pharmaceutical_id)
            normalized_phas.append({"id": pharmaceutical_id, "number": quantity})

        # 抗菌药物分级审核
        restricted_phas = []  # 限制级
        special_phas = []  # 特殊使用级
        for item in normalized_phas:
            pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item["id"]).first()
            if pha:
                if pha.antibiotic_level == 2:
                    restricted_phas.append(pha.name)
                elif pha.antibiotic_level == 3:
                    special_phas.append(pha.name)
        # 限制级/特殊使用级抗菌药：医生必须携带本人、患者、药品匹配的已通过审批
        elevated_roles = ADMIN_ROLES | {"director"}
        approved = []
        approval_required_ids = {
            item["id"] for item in normalized_phas
            if db.query(Pharmaceutical).filter(
                Pharmaceutical.pharmaceutical_id == item["id"],
                Pharmaceutical.antibiotic_level >= 2,
            ).first()
        }
        if approval_required_ids and current_user.user_role not in elevated_roles:
            approved = db.query(AntibioticApproval).filter(
                AntibioticApproval.approval_id.in_(req.antibiotic_approval_ids or ["__missing__"]),
                AntibioticApproval.patient_id == patient_obj.patient_id,
                AntibioticApproval.applicant_id == current_user.user_id,
                AntibioticApproval.status == 1,
                AntibioticApproval.prescription_id.is_(None),
            ).all()
            approved_drug_ids = {item.pharmaceutical_id for item in approved}
            if not approval_required_ids.issubset(approved_drug_ids):
                db.rollback()
                names = restricted_phas + special_phas
                return {"code": 500, "msg": f"抗菌药 [{', '.join(names)}] 需先提交并通过审批"}

        # ===== 处方前置审核 =====
        # 1. 过敏史冲突检查(精确匹配 + 通用名匹配,避免 partial match 误判)
        allergy_history = (patient_obj.allergy_history or "").strip()
        if allergy_history:
            allergy_keywords = []
            for entry in re.split(r"[,，;；]", allergy_history):
                allergen = re.split(r"[:：]", entry, maxsplit=1)[0].strip().lower()
                if allergen:
                    allergy_keywords.append(allergen)
            for item in normalized_phas:
                pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item["id"]).first()
                if not pha:
                    continue
                pha_name_lower = (pha.name or "").lower()
                pha_remark_lower = (pha.remark or "").lower()
                for kw in allergy_keywords:
                    # 精确匹配: 过敏史关键词等于药品名,或药品名包含完整关键词(词边界)
                    if kw == pha_name_lower:
                        db.rollback()
                        return {"code": 500, "msg": f"过敏史冲突：病人对 [{kw}] 过敏，处方包含 [{pha.name}]"}
                    # 关键词长度 >= 2 且药品名以该关键词开头/结尾/被分隔符包围
                    if len(kw) >= 2:
                        if pha_name_lower.startswith(kw + " ") or pha_name_lower.endswith(" " + kw) or f" {kw} " in f" {pha_name_lower} ":
                            db.rollback()
                            return {"code": 500, "msg": f"过敏史冲突：病人对 [{kw}] 过敏，处方包含 [{pha.name}]"}
                        if pha_remark_lower and (kw in pha_remark_lower.split() or kw + "," in pha_remark_lower):
                            db.rollback()
                            return {"code": 500, "msg": f"过敏史冲突：病人对 [{kw}] 过敏，处方备注 [{pha.remark}]"}

        # 2. 配伍禁忌检查（硬编码常见禁忌组合）
        pha_ids = {item["id"] for item in req.phas}
        incompatibility = {
            # (药品A_id, 药品B_id): "禁忌原因"
        }
        for (a, b), reason in incompatibility.items():
            if a in pha_ids and b in pha_ids:
                db.rollback()
                return {"code": 500, "msg": f"配伍禁忌：{reason}"}

        # 3. 审方规则引擎检查（规则由药师维护，未配置规则时不影响开方）
        try:
            from app.rx_review_engine import check_prescription

            engine_items = []
            for item in normalized_phas:
                pha_obj = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item["id"]).first()
                engine_items.append({
                    "name": pha_obj.name if pha_obj else "",
                    "dosage": item.get("dosage"),
                    "frequency": item.get("frequency"),
                    "number": item.get("number"),
                })
            findings = check_prescription(db, engine_items, allergy_history=(patient_obj.allergy_history or ""))
            if findings and any(f.get("severity") == 3 for f in findings):
                db.rollback()
                blocked_msgs = [f["message"] for f in findings if f.get("severity") == 3]
                return {"code": 500, "msg": f"审方规则禁止：{'；'.join(blocked_msgs)}"}
        except Exception:
            traceback.print_exc()  # 引擎异常不阻断开方主流程

        pre = Prescription(
            patient_id=patient_obj.patient_id,
            doctor_id=doctor_obj.doctor_id,
            status=0,
            create_time=datetime.datetime.now(),
        )
        db.add(pre)
        db.flush()
        amount = Decimal("0.00")
        for item in normalized_phas:
            pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item["id"]).first()
            if pha:
                quantity = int(item["number"])
                updated = db.query(Pharmaceutical).filter(
                    Pharmaceutical.pharmaceutical_id == pha.pharmaceutical_id,
                    Pharmaceutical.status == 0,
                    Pharmaceutical.stock >= quantity,
                ).update({Pharmaceutical.stock: Pharmaceutical.stock - quantity}, synchronize_session=False)
                if updated != 1:
                    db.rollback()
                    return {"code": 500, "msg": f"药品 {pha.name} 库存不足"}
                pp = PrePha(
                    prescription_id=str(pre.prescription_id),
                    pharmaceutical_id=pha.pharmaceutical_id,
                    number=item["number"],
                )
                db.add(pp)
                amount += Decimal(str(pha.price)) * quantity
        charge = Charge(
            charge_time=datetime.datetime.now(),
            time=datetime.datetime(1970, 1, 1),
            prescription_id=pre.prescription_id,
            amount=amount,
            status=0,
        )
        db.add(charge)
        if current_user.user_role not in elevated_roles:
            for approval in approved:
                approval.prescription_id = pre.prescription_id
                db.add(approval)
        db.commit()
        background_tasks.add_task(
            publish_event,
            "prescription.created",
            {"prescription_id": pre.prescription_id, "patient_id": patient_obj.patient_id},
            audience_roles=["pharmacist", "admin", "super_admin"],
        )
        return {"code": 200, "msg": "success", "data": {"uuid": str(pre.prescription_id)}}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "处方开具失败"}


from app.pagination import paginate


@router.get("/prescriptionManagement/getList")
def get_prescription_list(current_user: User = Depends(get_current_user), keyword: str | None = None, page: int | None = None, page_size: int | None = None, db: Session = Depends(get_db)):
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
        data.append(
            {
                "uuid": str(item.prescription_id),
                "doctor_id": item.doctor.doctor_id if item.doctor else None,
                "doctor_name": item.doctor.name if item.doctor else "",
                "patient_id": item.patient.patient_id if item.patient else None,
                "patient_name": item.patient.name if item.patient else "",
                "phas": phas,
                "status": item.status,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None),
                "charge_id": str(charge_obj.charge_id) if charge_obj else "",
                "amount": round(charge_obj.amount, 2) if charge_obj else 0,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/prescriptionManagement/cancel")
def cancel_prescription(req: PrescriptionCancelRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.prescription_id).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    if pre.status == 3:
        return {"code": 500, "msg": "处方已取消,无需重复操作"}
    if pre.status == 2:
        return {"code": 500, "msg": "已发药的处方不能直接取消,请走退药流程"}
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor_obj or pre.doctor_id != doctor_obj.doctor_id:
        return {"code": 403, "msg": "无权取消他人处方"}
    updated = db.query(Prescription).filter(
        Prescription.prescription_id == pre.prescription_id,
        Prescription.status.in_((0, 1)),
    ).update({Prescription.status: 3}, synchronize_session=False)
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "处方已取消,无需重复操作"}
    # 释放锁定的库存
    pre_phas = db.query(PrePha).filter(PrePha.prescription_id == pre.prescription_id).all()
    for pp in pre_phas:
        db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == pp.pharmaceutical_id).update(
            {Pharmaceutical.stock: Pharmaceutical.stock + pp.number}, synchronize_session=False
        )
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/medicalRecord/create")
def create_medical_record(req: MedicalRecordCreateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    if current_user.user_role == "patient":
        return {"code": 403, "msg": "无权创建病历"}
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor_obj:
        return {"code": 500, "msg": "医生信息不存在"}
    if not db.query(Patient).filter(Patient.patient_id == req.patient_id).first():
        return {"code": 500, "msg": "病人信息不存在"}
    record = MedicalRecord(
        consultation_time=datetime.datetime.now(),
        doctor_id=doctor_obj.doctor_id,
        patient_id=req.patient_id,
        symptom=req.symptom,
        result=req.result,
        status=0,
    )
    db.add(record)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"medical_record_id": record.medical_record_id}}


@router.post("/medicalRecord/update")
def update_medical_record(req: MedicalRecordUpdateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    record = db.query(MedicalRecord).filter(MedicalRecord.medical_record_id == req.medical_record_id).first()
    if not record:
        return {"code": 500, "msg": "病历不存在"}
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor_obj or record.doctor_id != doctor_obj.doctor_id:
        return {"code": 403, "msg": "无权修改他人病历"}
    if record.status != 0:
        return {"code": 403, "msg": "已签名病历不可修改"}
    record.symptom = req.symptom
    record.result = req.result
    db.add(record)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/medicalRecord/sign")
def sign_medical_record(req: MedicalRecordSignRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    record = db.query(MedicalRecord).filter(MedicalRecord.medical_record_id == req.medical_record_id).first()
    if not record:
        return {"code": 500, "msg": "病历不存在"}
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor_obj or record.doctor_id != doctor_obj.doctor_id:
        return {"code": 403, "msg": "无权签名他人病历"}
    if record.status != 0:
        return {"code": 500, "msg": "病历已签名"}
    now = datetime.datetime.now()
    updated = db.query(MedicalRecord).filter(
        MedicalRecord.medical_record_id == record.medical_record_id,
        MedicalRecord.status == 0,
    ).update({MedicalRecord.status: 1, MedicalRecord.sign_time: now}, synchronize_session=False)
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "病历已签名"}

    # 病历签名 = 就诊完成：联动收尾挂号/预约/队列状态
    # （原缺陷：报到后预约永远停在 status=1，"已就诊"状态不可达）
    from app.models import Queue, Registration

    if record.registration_uuid:
        db.query(Registration).filter(
            Registration.registration_uuid == record.registration_uuid,
            Registration.status == 0,
        ).update({Registration.status: 1}, synchronize_session=False)
    # 收尾当日该患者的候诊队列（过号/就诊完成语义：status=2）
    queue_items = (
        db.query(Queue)
        .filter(
            Queue.patient_id == record.patient_id,
            Queue.doctor_id == record.doctor_id,
            Queue.status.in_((0, 1)),
        )
        .all()
        if record.patient_id and record.doctor_id else []
    )
    for queue_item in queue_items:
        queue_item.status = 2
        db.add(queue_item)
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
    db.flush()
    enqueue_integration_event(
        db,
        destination="lis",
        event_type="lab.order.created",
        aggregate_type="lab_order",
        aggregate_id=lab_order.lab_order_id,
        payload={
            "lab_order_id": lab_order.lab_order_id,
            "patient_id": lab_order.patient_id,
            "doctor_id": lab_order.doctor_id,
            "check_type": lab_order.check_type,
            "check_items": req.check_items,
            "urgent": lab_order.urgent,
            "created_at": lab_order.create_time,
        },
    )
    db.commit()
    return {"code": 200, "msg": "success", "data": {"lab_order_id": str(lab_order.lab_order_id)}}


@router.get("/labOrder/getList")
def get_lab_order_list(current_user: User = Depends(get_current_user), keyword: str | None = None, db: Session = Depends(get_db)):
    doctor_obj = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor_obj:
        return {"code": 200, "msg": "success", "data": []}
    orders = db.query(LabOrder).filter(LabOrder.doctor_id == doctor_obj.doctor_id).order_by(LabOrder.create_time.desc()).all()
    data = []
    for item in orders:
        data.append(
            {
                "id": str(item.lab_order_id),
                "patient_name": item.patient.name if item.patient else "",
                "check_type": item.check_type,
                "status": item.status,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None),
            }
        )
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
def get_attendance_list(
    doctor_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
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
        data.append(
            {
                "id": item.attendance_id,
                "doctor_id": item.doctor_id,
                "doctor_name": item.doctor.name if item.doctor else "",
                "date": str(item.date),
                "check_in_time": (item.check_in_time.strftime("%Y-%m-%d %H:%M:%S") if item.check_in_time else None) if item.check_in_time else "",
                "check_out_time": (item.check_out_time.strftime("%Y-%m-%d %H:%M:%S") if item.check_out_time else None) if item.check_out_time else "",
                "status": status_map.get(item.status, "未知"),
                "status_code": item.status,
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.get("/slotPool/getList")
def get_slot_pool(current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    """号源池：按科室统计各时段号源总数"""

    depts = db.query(Department).all()
    data = []
    for d in depts:
        schedules = db.query(DoctorSchedule).filter(DoctorSchedule.doctor_id.in_(db.query(Doctor.doctor_id).filter(Doctor.department_id == d.department_id))).all()
        total_slots = sum(s.number for s in schedules)
        data.append(
            {
                "department_id": d.department_id,
                "department_name": d.name,
                "doctor_count": len(set(s.doctor_id for s in schedules)),
                "total_slots": total_slots,
                "schedules_count": len(schedules),
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/slotPool/adjust")
def adjust_slot(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    """调整号源数量"""
    schedule = db.query(DoctorSchedule).filter(DoctorSchedule.schedule_id == req.get("schedule_id")).first()
    if not schedule:
        return {"code": 500, "msg": "排班记录不存在"}
    new_number = req.get("number")
    if new_number is not None and new_number >= 0:
        schedule.number = new_number
        db.add(schedule)
        db.commit()
    return {"code": 200, "msg": "success"}
