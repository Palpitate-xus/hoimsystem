import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, NURSING_ROLES, ROLE_PATIENT, User, get_current_user, require_roles
from app.models import Doctor, Patient, PatrolRecord, Queue
from app.schemas import QueueCallNextRequest, QueuePassRequest, QueueSkipRequest

router = APIRouter()


@router.post("/queue/emergency")
def mark_emergency(req: QueueSkipRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    """护士将队列记录标记为急诊优先"""
    queue_item = db.query(Queue).filter(Queue.queue_id == req.queue_id).first()
    if not queue_item:
        return {"code": 500, "msg": "队列记录不存在"}
    if queue_item.status != 0:
        return {"code": 500, "msg": "当前队列状态不允许标记急诊"}
    queue_item.type = 2  # 2 = 急诊优先
    db.add(queue_item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/queue/reorder")
def reorder_queue(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    """护士调整队列顺序（将指定记录移到最前面）"""
    queue_id = req.get("queue_id")
    queue_item = db.query(Queue).filter(Queue.queue_id == queue_id).first()
    if not queue_item:
        return {"code": 500, "msg": "队列记录不存在"}
    if queue_item.status != 0:
        return {"code": 500, "msg": "只有候诊队列可以调整顺序"}
    # 将该记录设为最小序号（优先）
    min_queue = db.query(Queue).filter(Queue.doctor_id == queue_item.doctor_id, Queue.status == 0).order_by(Queue.queue_number).first()
    if min_queue and min_queue.queue_id != queue_id:
        queue_item.queue_number = min_queue.queue_number - 1
        db.add(queue_item)
        db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/queue/getList")
def get_queue_list(keyword: str | None = None, current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    query = db.query(Queue)
    if current_user.user_role == ROLE_PATIENT:
        patient_ids = [item.patient_id for item in db.query(Patient).filter(Patient.identity == current_user.username).all()]
        query = query.filter(Queue.patient_id.in_(patient_ids or [-1]))
    elif current_user.user_role == "doctor":
        doctor_ids = [item.doctor_id for item in db.query(Doctor).filter(Doctor.user_id == current_user.user_id).all()]
        query = query.filter(Queue.doctor_id.in_(doctor_ids or [-1]))
    elif current_user.user_role not in ADMIN_ROLES and current_user.user_role not in {"director", "nurse"}:
        query = query.filter(Queue.queue_id == -1)
    queues = query.order_by(Queue.queue_number).all()
    data = []
    for item in queues:
        data.append(
            {
                "queue_id": item.queue_id,
                "queue_number": item.queue_number,
                "patient_name": item.patient.name if item.patient else "",
                "doctor_name": item.doctor.name if item.doctor else "",
                "status": item.status,
                "type": item.type,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/queue/progress")
def get_queue_progress(current_user: User = Depends(require_roles(ROLE_PATIENT)), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient:
        return {"code": 200, "msg": "success", "data": []}
    current_items = db.query(Queue).filter(Queue.patient_id == patient.patient_id, Queue.status.in_((0, 1))).order_by(Queue.create_time.desc()).all()
    data = []
    for item in current_items:
        ahead = db.query(Queue).filter(Queue.doctor_id == item.doctor_id, Queue.status == 0, Queue.queue_number < item.queue_number).count()
        data.append({"queue_id": item.queue_id, "queue_number": item.queue_number, "doctor_name": item.doctor.name if item.doctor else "", "status": item.status, "status_text": {0: "候诊中", 1: "已叫号"}.get(item.status, ""), "ahead_count": ahead, "estimated_wait_minutes": ahead * 10})
    return {"code": 200, "msg": "success", "data": data}


@router.post("/queue/callNext")
def call_next(req: QueueCallNextRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    if current_user.user_role == "doctor":
        doctor_ids = [item.doctor_id for item in db.query(Doctor).filter(Doctor.user_id == current_user.user_id).all()]
        if req.doctor_id not in doctor_ids:
            return {"code": 403, "msg": "不能操作其他医生的候诊队列"}
    queue_item = db.query(Queue).filter(Queue.doctor_id == req.doctor_id, Queue.status == 0).order_by(Queue.queue_number).first()
    if not queue_item:
        return {"code": 500, "msg": "暂无候诊患者"}
    queue_item.status = 1
    queue_item.call_time = datetime.datetime.now()
    db.add(queue_item)
    db.commit()
    data = {
        "queue_id": queue_item.queue_id,
        "queue_number": queue_item.queue_number,
        "patient_name": queue_item.patient.name if queue_item.patient else "",
        "registration_uuid": queue_item.registration_uuid,
    }
    return {"code": 200, "msg": "success", "data": data}


@router.post("/queue/pass")
def pass_queue(req: QueuePassRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    queue_item = db.query(Queue).filter(Queue.queue_id == req.queue_id).first()
    if not queue_item:
        return {"code": 500, "msg": "队列记录不存在"}
    if queue_item.status != 1:
        return {"code": 500, "msg": "只有已叫号队列可以过号"}
    queue_item.status = 2
    db.add(queue_item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/queue/skip")
def skip_queue(req: QueueSkipRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    queue_item = db.query(Queue).filter(Queue.queue_id == req.queue_id).first()
    if not queue_item:
        return {"code": 500, "msg": "队列记录不存在"}
    if queue_item.status not in (0, 1):
        return {"code": 500, "msg": "当前队列状态不允许跳过"}
    queue_item.status = 2
    db.add(queue_item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/patrol/create")
def create_patrol_record(req: dict, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    record = PatrolRecord(
        nurse_id=current_user.user_id,
        patient_id=req.get("patient_id"),
        content=req.get("content", ""),
        status=req.get("status", 0),
        create_time=datetime.datetime.now(),
    )
    db.add(record)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/patrol/getList")
def get_patrol_list(keyword: str | None = None, current_user: User = Depends(require_roles(*NURSING_ROLES, *CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    records = db.query(PatrolRecord).order_by(PatrolRecord.create_time.desc()).all()
    data = []
    for item in records:
        data.append(
            {
                "patrol_id": item.patrol_id,
                "nurse_name": item.nurse.username if item.nurse else "",
                "patient_name": item.patient.name if item.patient else "",
                "content": item.content,
                "status": item.status,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None),
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}
