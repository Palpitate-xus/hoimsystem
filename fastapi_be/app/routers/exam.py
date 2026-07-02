import datetime
import traceback

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, User, get_current_user, require_roles
from app.models import (
    Doctor,
    ExamAppointment,
    ExamItem,
    ExamPackage,
    ExamRecord,
    ExamResult,
    Patient,
    User,
)

router = APIRouter()


# ===== 体检套餐管理 =====


@router.get("/examPackage/getList")
def get_exam_package_list(
    category: str | None = None,
    keyword: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ExamPackage).filter(ExamPackage.status == 0)
    if category:
        query = query.filter(ExamPackage.category == category)
    packages = query.order_by(ExamPackage.create_time.desc()).all()
    data = []
    for item in packages:
        data.append(
            {
                "package_id": item.package_id,
                "name": item.name,
                "category": item.category,
                "price": item.price,
                "items": item.items,
                "description": item.description,
                "status": item.status,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else None,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/examPackage/create")
def create_exam_package(
    req: dict,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        package = ExamPackage(
            name=req.get("name"),
            category=req.get("category"),
            price=req.get("price", 0),
            items=req.get("items", ""),
            description=req.get("description"),
            status=0,
            create_time=datetime.datetime.now(),
        )
        db.add(package)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "创建体检套餐失败"}


@router.post("/examPackage/update")
def update_exam_package(
    req: dict,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    package = db.query(ExamPackage).filter(ExamPackage.package_id == req.get("package_id")).first()
    if not package:
        return {"code": 500, "msg": "体检套餐不存在"}
    try:
        if "name" in req:
            package.name = req["name"]
        if "category" in req:
            package.category = req["category"]
        if "price" in req:
            package.price = req["price"]
        if "items" in req:
            package.items = req["items"]
        if "description" in req:
            package.description = req["description"]
        db.add(package)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "更新体检套餐失败"}


@router.post("/examPackage/delete")
def delete_exam_package(
    req: dict,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    package = db.query(ExamPackage).filter(ExamPackage.package_id == req.get("package_id")).first()
    if not package:
        return {"code": 500, "msg": "体检套餐不存在"}
    try:
        package.status = 1
        db.add(package)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "删除体检套餐失败"}


# ===== 体检项目管理 =====


@router.get("/examItem/getList")
def get_exam_item_list(
    category: str | None = None,
    keyword: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ExamItem).filter(ExamItem.status == 0)
    if category:
        query = query.filter(ExamItem.category == category)
    items = query.order_by(ExamItem.create_time.desc()).all()
    data = []
    for item in items:
        data.append(
            {
                "item_id": item.item_id,
                "name": item.name,
                "category": item.category,
                "unit": item.unit,
                "reference_range": item.reference_range,
                "price": item.price,
                "status": item.status,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else None,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/examItem/create")
def create_exam_item(
    req: dict,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        item = ExamItem(
            name=req.get("name"),
            category=req.get("category"),
            unit=req.get("unit"),
            reference_range=req.get("reference_range"),
            price=req.get("price", 0),
            status=0,
            create_time=datetime.datetime.now(),
        )
        db.add(item)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "创建体检项目失败"}


@router.post("/examItem/update")
def update_exam_item(
    req: dict,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    item = db.query(ExamItem).filter(ExamItem.item_id == req.get("item_id")).first()
    if not item:
        return {"code": 500, "msg": "体检项目不存在"}
    try:
        if "name" in req:
            item.name = req["name"]
        if "category" in req:
            item.category = req["category"]
        if "unit" in req:
            item.unit = req["unit"]
        if "reference_range" in req:
            item.reference_range = req["reference_range"]
        if "price" in req:
            item.price = req["price"]
        db.add(item)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "更新体检项目失败"}


@router.post("/examItem/delete")
def delete_exam_item(
    req: dict,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    item = db.query(ExamItem).filter(ExamItem.item_id == req.get("item_id")).first()
    if not item:
        return {"code": 500, "msg": "体检项目不存在"}
    try:
        item.status = 1
        db.add(item)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "删除体检项目失败"}


# ===== 体检预约管理 =====


@router.get("/examAppointment/getList")
def get_exam_appointment_list(
    status: int | None = None,
    keyword: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ExamAppointment)
    if status is not None:
        query = query.filter(ExamAppointment.status == status)
    appointments = query.order_by(ExamAppointment.create_time.desc()).all()
    data = []
    status_map = {0: "待体检", 1: "已报到", 2: "进行中", 3: "已完成", 4: "已取消"}
    for item in appointments:
        data.append(
            {
                "appointment_id": item.appointment_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "package_id": item.package_id,
                "package_name": item.package.name if item.package else "",
                "exam_date": str(item.exam_date) if item.exam_date else "",
                "status": item.status,
                "status_text": status_map.get(item.status, ""),
                "note": item.note,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else None,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/examAppointment/create")
def create_exam_appointment(
    req: dict,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        exam_date = req.get("exam_date")
        if isinstance(exam_date, str):
            exam_date = datetime.datetime.strptime(exam_date, "%Y-%m-%d").date()
        patient_id = req.get("patient_id")
        if current_user.user_role == "patient":
            patient_obj = db.query(Patient).filter(Patient.identity == current_user.username).first()
            if patient_obj:
                patient_id = patient_obj.patient_id
        appointment = ExamAppointment(
            patient_id=patient_id,
            package_id=req.get("package_id"),
            exam_date=exam_date,
            status=0,
            note=req.get("note"),
            create_time=datetime.datetime.now(),
        )
        db.add(appointment)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "创建体检预约失败"}


@router.post("/examAppointment/updateStatus")
def update_exam_appointment_status(
    req: dict,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    appointment = db.query(ExamAppointment).filter(ExamAppointment.appointment_id == req.get("appointment_id")).first()
    if not appointment:
        return {"code": 500, "msg": "体检预约不存在"}
    try:
        appointment.status = req.get("status")
        db.add(appointment)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "更新预约状态失败"}


# ===== 体检记录管理 =====


@router.get("/examRecord/getList")
def get_exam_record_list(
    keyword: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = db.query(ExamRecord).order_by(ExamRecord.create_time.desc()).all()
    data = []
    status_map = {0: "待录入", 1: "录入中", 2: "待总检", 3: "已完成"}
    for item in records:
        data.append(
            {
                "record_id": item.record_id,
                "appointment_id": item.appointment_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "package_id": item.package_id,
                "package_name": item.package.name if item.package else "",
                "doctor_id": item.doctor_id,
                "doctor_name": item.doctor.name if item.doctor else "",
                "overall_result": item.overall_result,
                "overall_advice": item.overall_advice,
                "exam_time": (item.exam_time.strftime("%Y-%m-%d %H:%M:%S") if item.exam_time else None) if item.exam_time else "",
                "report_time": (item.report_time.strftime("%Y-%m-%d %H:%M:%S") if item.report_time else None) if item.report_time else "",
                "status": item.status,
                "status_text": status_map.get(item.status, ""),
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else None,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/examRecord/create")
def create_exam_record(
    req: dict,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    appointment = db.query(ExamAppointment).filter(
        ExamAppointment.appointment_id == req.get("appointment_id")
    ).first()
    if not appointment:
        return {"code": 500, "msg": "体检预约不存在"}
    try:
        record = ExamRecord(
            appointment_id=appointment.appointment_id,
            patient_id=appointment.patient_id,
            package_id=appointment.package_id,
            status=0,
            create_time=datetime.datetime.now(),
        )
        db.add(record)
        db.commit()
        return {"code": 200, "msg": "success", "data": {"record_id": record.record_id}}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "创建体检记录失败"}


@router.post("/examRecord/update")
def update_exam_record(
    req: dict,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    record = db.query(ExamRecord).filter(ExamRecord.record_id == req.get("record_id")).first()
    if not record:
        return {"code": 500, "msg": "体检记录不存在"}
    try:
        if "overall_result" in req:
            record.overall_result = req["overall_result"]
        if "overall_advice" in req:
            record.overall_advice = req["overall_advice"]
        if "status" in req:
            record.status = req["status"]
        if "doctor_id" in req:
            record.doctor_id = req["doctor_id"]
        db.add(record)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "更新体检记录失败"}


@router.post("/examRecord/complete")
def complete_exam_record(
    req: dict,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    record = db.query(ExamRecord).filter(ExamRecord.record_id == req.get("record_id")).first()
    if not record:
        return {"code": 500, "msg": "体检记录不存在"}
    try:
        record.status = 3
        record.report_time = datetime.datetime.now()
        db.add(record)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "完成体检记录失败"}


# ===== 体检结果管理 =====


@router.get("/examResult/getList")
def get_exam_result_list(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    results = (
        db.query(ExamResult)
        .filter(ExamResult.record_id == record_id)
        .order_by(ExamResult.create_time.desc())
        .all()
    )
    data = []
    for item in results:
        data.append(
            {
                "result_id": item.result_id,
                "record_id": item.record_id,
                "item_id": item.item_id,
                "item_name": item.item_name,
                "result_value": item.result_value,
                "unit": item.unit,
                "reference_range": item.reference_range,
                "abnormal_flag": item.abnormal_flag,
                "note": item.note,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else None,
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/examResult/create")
def create_exam_result(
    req: dict,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        existing = (
            db.query(ExamResult)
            .filter(
                ExamResult.record_id == req.get("record_id"),
                ExamResult.item_id == req.get("item_id"),
            )
            .first()
        )
        item_obj = db.query(ExamItem).filter(ExamItem.item_id == req.get("item_id")).first()
        if existing:
            existing.result_value = req.get("result_value")
            existing.abnormal_flag = req.get("abnormal_flag", 0)
            existing.note = req.get("note")
            if item_obj:
                existing.item_name = item_obj.name
                existing.unit = item_obj.unit
                existing.reference_range = item_obj.reference_range
            db.add(existing)
        else:
            result = ExamResult(
                record_id=req.get("record_id"),
                item_id=req.get("item_id"),
                item_name=item_obj.name if item_obj else "",
                result_value=req.get("result_value"),
                unit=item_obj.unit if item_obj else None,
                reference_range=item_obj.reference_range if item_obj else None,
                abnormal_flag=req.get("abnormal_flag", 0),
                note=req.get("note"),
                create_time=datetime.datetime.now(),
            )
            db.add(result)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "保存体检结果失败"}


# ===== 体检报告 =====


@router.get("/examReport/getDetail")
def get_exam_report_detail(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(ExamRecord).filter(ExamRecord.record_id == record_id).first()
    if not record:
        return {"code": 500, "msg": "体检记录不存在"}

    results = (
        db.query(ExamResult)
        .filter(ExamResult.record_id == record_id)
        .order_by(ExamResult.create_time.desc())
        .all()
    )

    result_list = []
    for item in results:
        result_list.append(
            {
                "result_id": item.result_id,
                "item_id": item.item_id,
                "item_name": item.item_name,
                "result_value": item.result_value,
                "unit": item.unit,
                "reference_range": item.reference_range,
                "abnormal_flag": item.abnormal_flag,
                "note": item.note,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else None,
            }
        )

    status_map = {0: "待录入", 1: "录入中", 2: "待总检", 3: "已完成"}
    data = {
        "record_id": record.record_id,
        "appointment_id": record.appointment_id,
        "patient_id": record.patient_id,
        "patient_name": record.patient.name if record.patient else "",
        "package_id": record.package_id,
        "package_name": record.package.name if record.package else "",
        "doctor_id": record.doctor_id,
        "doctor_name": record.doctor.name if record.doctor else "",
        "overall_result": record.overall_result,
        "overall_advice": record.overall_advice,
        "exam_time": (record.exam_time.strftime("%Y-%m-%d %H:%M:%S") if record.exam_time else None) if record.exam_time else "",
        "report_time": (record.report_time.strftime("%Y-%m-%d %H:%M:%S") if record.report_time else None) if record.report_time else "",
        "status": record.status,
        "status_text": status_map.get(record.status, ""),
        "results": result_list,
    }
    return {"code": 200, "msg": "success", "data": data}
