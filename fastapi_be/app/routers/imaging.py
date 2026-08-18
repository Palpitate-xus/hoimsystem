import datetime
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, LAB_ROLES, ROLE_DIRECTOR, ROLE_PATIENT, User, get_current_user, require_roles
from app.models import Doctor, ImagingFilm, ImagingOrder, ImagingReport, ImagingTemplate, Patient

router = APIRouter()
IMAGING_ROLES = {*CLINICAL_ROLES, *LAB_ROLES}
REVIEW_ROLES = {*ADMIN_ROLES, ROLE_DIRECTOR}


def _patient_scope(query, current_user: User, db: Session):
    if current_user.user_role == ROLE_PATIENT:
        patient = db.query(Patient).filter(Patient.identity == current_user.username).first()
        return query.filter(ImagingOrder.patient_id == patient.patient_id) if patient else query.filter(ImagingOrder.patient_id == -1)
    return query


def _order_data(item: ImagingOrder):
    return {
        "imaging_order_id": item.imaging_order_id,
        "patient_id": item.patient_id,
        "patient_name": item.patient.name if item.patient else "",
        "doctor_id": item.doctor_id,
        "doctor_name": item.doctor.name if item.doctor else "",
        "modality": item.modality,
        "body_part": item.body_part,
        "clinical_diagnosis": item.clinical_diagnosis or "",
        "priority": item.priority,
        "status": item.status,
        "status_text": {0: "待检查", 1: "检查中", 2: "待报告", 3: "待审核", 4: "已审核", 5: "已取消"}.get(item.status, ""),
        "accession_no": item.accession_no or "",
        "viewer_url": item.viewer_url or "",
        "integration_status": item.integration_status or "pending",
        "create_time": item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else "",
        "schedule_time": item.schedule_time.strftime("%Y-%m-%d %H:%M:%S") if item.schedule_time else "",
        "report": {
            "report_id": item.report.report_id,
            "findings": item.report.findings,
            "impression": item.report.impression,
            "status": item.report.status,
            "status_text": {0: "草稿", 1: "待审核", 2: "已审核", 3: "已退回"}.get(item.report.status, ""),
            "review_note": item.report.review_note or "",
        } if item.report else None,
    }


def _film_data(item: ImagingFilm):
    return {
        "film_id": item.film_id,
        "imaging_order_id": item.imaging_order_id,
        "accession_no": item.order.accession_no if item.order else "",
        "patient_id": item.order.patient_id if item.order else None,
        "patient_name": item.order.patient.name if item.order and item.order.patient else "",
        "delivery_type": item.delivery_type,
        "delivery_type_text": "云胶片" if item.delivery_type == "cloud" else "实体胶片",
        "copies": item.copies,
        "status": item.status,
        "status_text": {0: "待处理", 1: "已完成", 2: "已取消"}.get(item.status, ""),
        "cloud_url": item.cloud_url or "",
        "create_time": item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else "",
        "complete_time": item.complete_time.strftime("%Y-%m-%d %H:%M:%S") if item.complete_time else "",
    }


@router.get("/imaging/order/list")
def get_imaging_order_list(status: int | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = _patient_scope(db.query(ImagingOrder), current_user, db)
    if status is not None:
        query = query.filter(ImagingOrder.status == status)
    return {"code": 200, "msg": "success", "data": [_order_data(item) for item in query.order_by(ImagingOrder.create_time.desc()).all()]}


@router.post("/imaging/order/create")
def create_imaging_order(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.get("patient_id")).first()
    if not patient:
        return {"code": 404, "msg": "患者不存在"}
    doctor = db.query(Doctor).filter(Doctor.doctor_id == req.get("doctor_id")).first()
    if not doctor:
        doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor:
        return {"code": 400, "msg": "未找到申请医生"}
    order = ImagingOrder(
        patient_id=patient.patient_id,
        doctor_id=doctor.doctor_id,
        modality=req.get("modality", "DR"),
        body_part=req.get("body_part", "").strip(),
        clinical_diagnosis=req.get("clinical_diagnosis", ""),
        priority=int(req.get("priority", 0)),
        accession_no=f"IMG-{datetime.datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6].upper()}",
        status=0,
        create_time=datetime.datetime.now(),
    )
    if not order.body_part:
        return {"code": 400, "msg": "检查部位不能为空"}
    db.add(order)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"imaging_order_id": order.imaging_order_id, "accession_no": order.accession_no}}


@router.post("/imaging/order/status")
def update_imaging_order_status(req: dict, current_user: User = Depends(require_roles(*IMAGING_ROLES)), db: Session = Depends(get_db)):
    order = db.query(ImagingOrder).filter(ImagingOrder.imaging_order_id == req.get("imaging_order_id")).first()
    if not order:
        return {"code": 404, "msg": "影像申请不存在"}
    status = req.get("status")
    if status not in (1, 2, 5):
        return {"code": 400, "msg": "状态不合法"}
    # 状态机校验：已进入报告/审核流程（3/4）的单禁止用本接口改状态；5 取消后不可再改
    allowed = {
        0: {1, 5},      # 待检查 → 检查中 / 取消
        1: {2, 5},      # 检查中 → 退回 / 取消
        2: {1},         # 退回 → 检查中
    }
    if status not in allowed.get(order.status, set()):
        return {"code": 400, "msg": f"状态迁移不合法：当前 {order.status} → 目标 {status}（报告流程状态请走报告接口）"}
    order.status = status
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/imaging/order/viewer")
def update_imaging_viewer(req: dict, current_user: User = Depends(require_roles(*IMAGING_ROLES)), db: Session = Depends(get_db)):
    order = db.query(ImagingOrder).filter(ImagingOrder.imaging_order_id == req.get("imaging_order_id")).first()
    if not order:
        return {"code": 404, "msg": "影像申请不存在"}
    url = (req.get("viewer_url") or "").strip()[:500] or None
    # 仅允许 https（院外 PACS 云胶片查看器），阻断 javascript:/data: 等危险协议
    if url and not url.lower().startswith("https://"):
        return {"code": 400, "msg": "viewer 地址仅支持 https://"}
    order.viewer_url = url
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/imaging/report/list")
def get_imaging_report_list(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(ImagingOrder).join(ImagingReport)
    query = _patient_scope(query, current_user, db)
    return {"code": 200, "msg": "success", "data": [_order_data(item) for item in query.order_by(ImagingReport.report_time.desc()).all()]}


@router.post("/imaging/report/save")
def save_imaging_report(req: dict, current_user: User = Depends(require_roles(*IMAGING_ROLES)), db: Session = Depends(get_db)):
    order = db.query(ImagingOrder).filter(ImagingOrder.imaging_order_id == req.get("imaging_order_id")).first()
    if not order:
        return {"code": 404, "msg": "影像申请不存在"}
    report = order.report
    if report and report.status == 2:
        return {"code": 400, "msg": "报告已审核发布，不能直接修改（需退回后重新提交审核）"}
    if not report:
        report = ImagingReport(imaging_order_id=order.imaging_order_id, author_id=current_user.user_id, findings="", impression="", status=0)
        db.add(report)
    report.findings = req.get("findings", report.findings)
    report.impression = req.get("impression", report.impression)
    report.template_id = req.get("template_id", report.template_id)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"report_id": report.report_id}}


@router.post("/imaging/report/submit")
def submit_imaging_report(req: dict, current_user: User = Depends(require_roles(*IMAGING_ROLES)), db: Session = Depends(get_db)):
    report = db.query(ImagingReport).filter(ImagingReport.report_id == req.get("report_id")).first()
    if not report:
        return {"code": 404, "msg": "影像报告不存在"}
    if report.status not in (0, 3):
        return {"code": 400, "msg": "仅草稿或退回状态的报告可提交审核"}
    report.status = 1
    report.report_time = datetime.datetime.now()
    report.order.status = 3
    db.commit()
    return {"code": 200, "msg": "已提交审核"}


@router.post("/imaging/report/review")
def review_imaging_report(req: dict, current_user: User = Depends(require_roles(*REVIEW_ROLES)), db: Session = Depends(get_db)):
    report = db.query(ImagingReport).filter(ImagingReport.report_id == req.get("report_id")).first()
    if not report:
        return {"code": 404, "msg": "影像报告不存在"}
    status = req.get("status")
    if status not in (2, 3):
        return {"code": 400, "msg": "审核状态必须为2(通过)或3(退回)"}
    if report.status not in (1,):
        return {"code": 400, "msg": "仅待审核状态的报告可审核"}
    if report.author_id and report.author_id == current_user.user_id:
        return {"code": 400, "msg": "报告书写者不能审核自己的报告"}
    report.status = status
    report.reviewer_id = current_user.user_id
    report.review_time = datetime.datetime.now()
    report.review_note = req.get("note", "")
    report.order.status = 4 if status == 2 else 2
    db.commit()
    return {"code": 200, "msg": "审核完成"}


@router.get("/imaging/template/list")
def get_imaging_template_list(modality: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(ImagingTemplate).filter(ImagingTemplate.status == 1)
    if modality:
        query = query.filter(ImagingTemplate.modality == modality)
    return {
        "code": 200,
        "msg": "success",
        "data": [
            {"template_id": item.template_id, "name": item.name, "modality": item.modality, "content": item.content}
            for item in query.order_by(ImagingTemplate.template_id.desc()).all()
        ],
    }


@router.post("/imaging/template/save")
def save_imaging_template(req: dict, current_user: User = Depends(require_roles(*IMAGING_ROLES)), db: Session = Depends(get_db)):
    item = db.query(ImagingTemplate).filter(ImagingTemplate.template_id == req.get("template_id")).first() if req.get("template_id") else None
    now = datetime.datetime.now()
    if not item:
        item = ImagingTemplate(
            name=req.get("name", ""), modality=req.get("modality", "DR"), content=req.get("content", ""),
            creator_id=current_user.user_id, status=1, create_time=now, update_time=now,
        )
        db.add(item)
    else:
        item.name = req.get("name", item.name)
        item.modality = req.get("modality", item.modality)
        item.content = req.get("content", item.content)
        item.update_time = now
    db.commit()
    return {"code": 200, "msg": "success", "data": {"template_id": item.template_id}}


@router.get("/imaging/viewer/{imaging_order_id}")
def get_imaging_viewer(imaging_order_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.query(ImagingOrder).filter(ImagingOrder.imaging_order_id == imaging_order_id).first()
    if not order:
        return {"code": 404, "msg": "影像申请不存在"}
    if current_user.user_role == ROLE_PATIENT:
        patient = db.query(Patient).filter(Patient.identity == current_user.username).first()
        if not patient or order.patient_id != patient.patient_id:
            return {"code": 403, "msg": "无权查看该影像"}
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "viewer_url": order.viewer_url,
            "integration_status": "configured" if order.viewer_url else "not_configured",
            "sync_status": order.integration_status or "pending",
        },
    }


@router.get("/imaging/film/list")
def get_imaging_film_list(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(ImagingFilm).join(ImagingOrder)
    if current_user.user_role == ROLE_PATIENT:
        patient = db.query(Patient).filter(Patient.identity == current_user.username).first()
        query = query.filter(ImagingOrder.patient_id == (patient.patient_id if patient else -1))
    items = query.order_by(ImagingFilm.create_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [_film_data(item) for item in items]}


@router.post("/imaging/film/create")
def create_imaging_film(req: dict, current_user: User = Depends(require_roles(*{*IMAGING_ROLES, ROLE_PATIENT})), db: Session = Depends(get_db)):
    order = db.query(ImagingOrder).filter(ImagingOrder.imaging_order_id == req.get("imaging_order_id")).first()
    if not order:
        return {"code": 404, "msg": "影像申请不存在"}
    if current_user.user_role == ROLE_PATIENT:
        patient = db.query(Patient).filter(Patient.identity == current_user.username).first()
        if not patient or order.patient_id != patient.patient_id:
            return {"code": 403, "msg": "无权申请该影像胶片"}
    delivery_type = req.get("delivery_type", "print")
    if delivery_type not in ("print", "cloud"):
        return {"code": 400, "msg": "胶片交付类型不合法"}
    try:
        copies = max(1, min(int(req.get("copies", 1)), 10))
    except (TypeError, ValueError):
        return {"code": 400, "msg": "胶片份数不合法"}
    item = ImagingFilm(
        imaging_order_id=order.imaging_order_id,
        delivery_type=delivery_type,
        copies=copies,
        requester_id=current_user.user_id,
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "胶片申请已提交", "data": _film_data(item)}


@router.post("/imaging/film/status")
def update_imaging_film_status(req: dict, current_user: User = Depends(require_roles(*IMAGING_ROLES)), db: Session = Depends(get_db)):
    item = db.query(ImagingFilm).filter(ImagingFilm.film_id == req.get("film_id")).first()
    if not item:
        return {"code": 404, "msg": "胶片申请不存在"}
    status = req.get("status")
    if status not in (1, 2):
        return {"code": 400, "msg": "胶片状态不合法"}
    item.status = status
    item.complete_time = datetime.datetime.now() if status == 1 else None
    if item.delivery_type == "cloud" and req.get("cloud_url"):
        url = str(req["cloud_url"]).strip()[:500]
        if not url.startswith("https://"):
            return {"code": 400, "msg": "云胶片链接必须为 https:// 地址"}
        item.cloud_url = url
    db.commit()
    return {"code": 200, "msg": "胶片状态已更新", "data": _film_data(item)}
