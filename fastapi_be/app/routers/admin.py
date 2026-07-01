import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, get_current_user, require_roles
from app.models import Department, Doctor, Notice, Patient, User
from app.pagination import paginate
from app.schemas import (
    DepartmentCreateRequest,
    DepartmentDeleteRequest,
    DepartmentUpdateRequest,
    DoctorDeleteRequest,
    DoctorUpdateRequest,
    NoticeCreateRequest,
    NoticeDeleteRequest,
    NoticeUpdateRequest,
    PatientUpdateRequest,
)

router = APIRouter()


@router.get("/doctorManagement/getList")
def get_doctor_list(keyword: str | None = None, page: int | None = None, page_size: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Doctor)
    doctors, total = paginate(query, page, page_size)
    data = []
    for item in doctors:
        data.append(
            {
                "id": item.doctor_id,
                "name": item.name,
                "sex": item.sex,
                "education": item.education,
                "phone": item.phone,
                "permission": item.permission,
                "title": item.title,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/doctorManagement/update")
def update_doctor(req: DoctorUpdateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.doctor_id == req.doctor_id).first()
    if not doctor:
        return {"code": 500, "msg": "医生不存在"}
    doctor.name = req.name
    doctor.title = req.title
    doctor.sex = 0 if req.sex == "女" else 1
    doctor.phone = req.phone
    doctor.department_id = req.department
    doctor.permission = req.permission
    doctor.education = req.education
    db.add(doctor)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/doctorManagement/delete")
def delete_doctor(req: DoctorDeleteRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.doctor_id == req.doctor_id).first()
    if not doctor:
        return {"code": 500, "msg": "医生不存在"}
    if doctor.user_id:
        user = db.query(User).filter(User.user_id == doctor.user_id).first()
        if user:
            db.delete(user)
    db.delete(doctor)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/patientManagement/getList")
def get_patient_list(keyword: str | None = None, page: int | None = None, page_size: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Patient)
    patient_data, total = paginate(query, page, page_size)
    data = []
    for item in patient_data:
        sex = "女" if item.sex == 0 else "男"
        data.append(
            {
                "id": item.patient_id,
                "name": item.name,
                "sex": sex,
                "birthday": (item.birthday.strftime("%Y-%m-%d") if item.birthday else None),
                "phone": item.phone,
                "permission": item.permission,
                "address": item.address,
                "identity": item.identity,
                "allergy_history": item.allergy_history or "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/patientManagement/update")
def update_patient(req: PatientUpdateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.patient_id).first()
    if not patient:
        return {"code": 500, "msg": "病人不存在"}
    patient.name = req.name
    patient.sex = req.sex
    patient.phone = req.phone
    patient.address = req.address
    if req.allergy_history is not None:
        patient.allergy_history = req.allergy_history
    db.add(patient)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/departmentManagement/getList")
def get_department_list(keyword: str | None = None, page: int | None = None, page_size: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Department)
    departments, total = paginate(query, page, page_size)
    data = []
    for item in departments:
        director = db.query(Doctor).filter(Doctor.doctor_id == item.director).first()
        director_name = director.name if director else ""
        data.append(
            {
                "id": item.department_id,
                "name": item.name,
                "phone": item.phone,
                "location": item.location,
                "director": director_name,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/departmentManagement/create")
def department_register(req: DepartmentCreateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    try:
        dept = Department(
            name=req.name,
            phone=req.phone,
            location=req.location,
            director=req.director,
        )
        db.add(dept)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        return {"code": 500, "msg": "科室注册失败"}


@router.post("/departmentManagement/update")
def update_department(req: DepartmentUpdateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    dept = db.query(Department).filter(Department.department_id == req.department_id).first()
    if not dept:
        return {"code": 500, "msg": "科室不存在"}
    dept.name = req.name
    dept.phone = req.phone
    dept.location = req.location
    dept.director = req.director
    db.add(dept)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/departmentManagement/delete")
def delete_department(req: DepartmentDeleteRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    dept = db.query(Department).filter(Department.department_id == req.department_id).first()
    if not dept:
        return {"code": 500, "msg": "科室不存在"}
    db.delete(dept)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/notice/getList")
def get_notice_list(current_user: User = Depends(get_current_user), keyword: str | None = None, page: int | None = None, page_size: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Notice)
    notices, total = paginate(query, page, page_size)
    data = []
    for item in notices:
        towho = item.towho or []
        # "all" 表示对所有角色可见；admin 始终可见所有公告
        is_for_all = "all" in towho
        if current_user.user_role == "director" and not is_for_all and "科室主任" not in towho:
            continue
        if current_user.user_role == "doctor" and not is_for_all and "医生" not in towho:
            continue
        if current_user.user_role == "patient" and not is_for_all and "病人" not in towho:
            continue
        data.append(
            {
                "uuid": str(item.notice_id),
                "title": item.title,
                "content": item.content,
                "isemergency": item.isemergency,
                "towho": item.towho,
                "sendtime": (item.sendtime.strftime("%Y-%m-%d %H:%M:%S") if item.sendtime else None),
                "expiredtime": (item.expiredtime.strftime("%Y-%m-%d %H:%M:%S") if item.expiredtime else None),
                "readnum": item.readnum,
                "writer": item.writer.username if item.writer else "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/notice/create")
def notice_register(req: NoticeCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    expired = None
    if req.expiredtime:
        try:
            expired = datetime.datetime.strptime(req.expiredtime, "%Y-%m-%d")
        except ValueError:
            expired = datetime.datetime.strptime(req.expiredtime, "%Y-%m-%d %H:%M:%S")
    notice = Notice(
        title=req.title,
        content=req.content,
        isemergency=req.isemergency,
        towho=str(req.towho),
        sendtime=datetime.datetime.now(),
        expiredtime=expired,
        readnum=0,
        writer_id=current_user.user_id,
    )
    db.add(notice)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/notice/update")
def update_notice(req: NoticeUpdateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    notice = db.query(Notice).filter(Notice.notice_id == req.notice_id).first()
    if not notice:
        return {"code": 500, "msg": "通知不存在"}
    notice.title = req.title
    notice.content = req.content
    notice.isemergency = req.isemergency
    notice.towho = str(req.towho)
    if req.expiredtime:
        try:
            notice.expiredtime = datetime.datetime.strptime(req.expiredtime, "%Y-%m-%d")
        except ValueError:
            notice.expiredtime = datetime.datetime.strptime(req.expiredtime, "%Y-%m-%d %H:%M:%S")
    db.add(notice)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/notice/delete")
def delete_notice(req: NoticeDeleteRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    notice = db.query(Notice).filter(Notice.notice_id == req.notice_id).first()
    if not notice:
        return {"code": 500, "msg": "通知不存在"}
    db.delete(notice)
    db.commit()
    return {"code": 200, "msg": "success"}
