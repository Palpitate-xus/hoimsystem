import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    Admission,
    Doctor,
    InpatientCharge,
    InpatientOrder,
    InpatientOrderItem,
    OrderExecution,
    Patient,
    Pharmaceutical,
    User,
)
from app.schemas import InpatientOrderCreateRequest, InpatientOrderStopRequest, OrderExecutionRequest

router = APIRouter()


def _create_order_executions(db: Session, order: InpatientOrder):
    """根据医嘱类型和频次生成执行计划"""
    if order.order_type == 1:  # 临时医嘱，只生成一次
        execution = OrderExecution(
            order_id=order.order_id,
            planned_time=datetime.datetime.now(),
            status=0,
        )
        db.add(execution)
    else:  # 长期医嘱，按频次生成
        freq_map = {
            "qd": 1,   # 每日一次
            "bid": 2,  # 每日两次
            "tid": 3,  # 每日三次
            "qid": 4,  # 每日四次
        }
        # 获取医嘱天数（默认7天）
        days = 7
        for item in order.items:
            if item.days and item.days > 0:
                days = item.days
                break

        # 简化处理：每天按频次生成执行记录
        for d in range(days):
            base_time = datetime.datetime.now() + datetime.timedelta(days=d)
            for item in order.items:
                freq_count = freq_map.get(item.frequency, 1)
                for i in range(freq_count):
                    planned = base_time.replace(hour=8 + i * (16 // max(freq_count, 1)), minute=0, second=0)
                    execution = OrderExecution(
                        order_id=order.order_id,
                        planned_time=planned,
                        status=0,
                    )
                    db.add(execution)


@router.get("/inpatientOrder/getList")
def get_inpatient_order_list(
    admission_id: str | None = None,
    patient_id: int | None = None,
    status: int | None = None,
    order_type: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(InpatientOrder).order_by(InpatientOrder.create_time.desc())
    if admission_id:
        query = query.filter(InpatientOrder.admission_id == admission_id)
    if patient_id:
        query = query.filter(InpatientOrder.patient_id == patient_id)
    if status is not None:
        query = query.filter(InpatientOrder.status == status)
    if order_type is not None:
        query = query.filter(InpatientOrder.order_type == order_type)
    orders = query.all()

    type_text = ["长期医嘱", "临时医嘱"]
    category_map = {"drug": "药品", "treatment": "治疗", "exam": "检查", "diet": "饮食", "nursing": "护理", "other": "其他"}
    status_map = ["新开", "已审核", "执行中", "已停止", "已撤销"]
    priority_map = ["常规", "紧急", "抢救"]
    data = []
    for item in orders:
        items_data = []
        for it in item.items:
            items_data.append(
                {
                    "item_id": it.item_id,
                    "item_name": it.item_name,
                    "item_type": it.item_type,
                    "dose": it.dose or "",
                    "unit": it.unit or "",
                    "frequency": it.frequency or "",
                    "route": it.route or "",
                    "days": it.days,
                    "quantity": it.quantity,
                    "unit_price": it.unit_price,
                    "total_price": it.total_price,
                    "note": it.note or "",
                }
            )
        data.append(
            {
                "order_id": item.order_id,
                "admission_id": item.admission_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "doctor_id": item.doctor_id,
                "doctor_name": item.doctor.name if item.doctor else "",
                "order_type": item.order_type,
                "order_type_text": type_text[item.order_type] if item.order_type is not None and item.order_type < len(type_text) else "",
                "category": item.category,
                "category_text": category_map.get(item.category, item.category),
                "start_time": str(item.start_time) if item.start_time else "",
                "stop_time": str(item.stop_time) if item.stop_time else "",
                "status": item.status,
                "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
                "priority": item.priority,
                "priority_text": priority_map[item.priority] if item.priority is not None and item.priority < len(priority_map) else "",
                "note": item.note or "",
                "items": items_data,
                "create_time": str(item.create_time) if item.create_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/inpatientOrder/create")
def create_inpatient_order(req: InpatientOrderCreateRequest, db: Session = Depends(get_db)):
    admission = db.query(Admission).filter(Admission.admission_id == req.admission_id).first()
    if not admission:
        return {"code": 500, "msg": "入院记录不存在"}
    if admission.status != 1:
        return {"code": 500, "msg": "病人不在院状态，无法开立医嘱"}

    order = InpatientOrder(
        admission_id=req.admission_id,
        patient_id=req.patient_id,
        doctor_id=req.doctor_id,
        order_type=req.order_type,
        category=req.category,
        start_time=datetime.datetime.now(),
        status=0,
        priority=req.priority,
        note=req.note,
        create_time=datetime.datetime.now(),
    )
    db.add(order)
    db.flush()  # 获取 order_id

    total_amount = 0
    for it in req.items:
        unit_price = it.get("unit_price", 0)
        quantity = it.get("quantity", 1)
        days = it.get("days", 1)
        item_total = unit_price * quantity * days
        total_amount += item_total

        order_item = InpatientOrderItem(
            order_id=order.order_id,
            item_name=it.get("item_name", ""),
            item_type=it.get("item_type", "drug"),
            item_id_ref=it.get("item_id_ref"),
            dose=it.get("dose"),
            unit=it.get("unit"),
            frequency=it.get("frequency"),
            route=it.get("route"),
            days=days,
            quantity=quantity,
            unit_price=unit_price,
            total_price=item_total,
            note=it.get("note"),
        )
        db.add(order_item)

        # 生成费用记录
        if item_total > 0:
            charge = InpatientCharge(
                admission_id=req.admission_id,
                patient_id=req.patient_id,
                item_name=it.get("item_name", ""),
                item_type=it.get("item_type", "drug"),
                quantity=quantity * days,
                unit_price=unit_price,
                total_amount=item_total,
                charge_date=datetime.datetime.now().date(),
                related_order_id=order.order_id,
                status=0,
                create_time=datetime.datetime.now(),
            )
            db.add(charge)

        # 扣减药品库存
        if it.get("item_type") == "drug" and it.get("item_id_ref"):
            pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == it.get("item_id_ref")).first()
            if pha:
                pha.stock -= quantity * days
                db.add(pha)

    # 生成执行计划
    db.flush()
    _create_order_executions(db, order)

    db.commit()
    return {"code": 200, "msg": "success", "data": {"order_id": order.order_id, "total_amount": total_amount}}


@router.post("/inpatientOrder/audit")
def audit_inpatient_order(req: dict, db: Session = Depends(get_db)):
    order = db.query(InpatientOrder).filter(InpatientOrder.order_id == req.get("order_id")).first()
    if not order:
        return {"code": 500, "msg": "医嘱不存在"}
    if order.status != 0:
        return {"code": 500, "msg": "医嘱状态不正确，无法审核"}
    order.status = 1
    db.add(order)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/inpatientOrder/stop")
def stop_inpatient_order(req: InpatientOrderStopRequest, db: Session = Depends(get_db)):
    order = db.query(InpatientOrder).filter(InpatientOrder.order_id == req.order_id).first()
    if not order:
        return {"code": 500, "msg": "医嘱不存在"}
    if order.status not in (1, 2):
        return {"code": 500, "msg": "医嘱状态不正确，无法停止"}
    order.status = 3
    order.stop_time = datetime.datetime.now()
    db.add(order)

    # 取消未执行的执行计划
    executions = (
        db.query(OrderExecution)
        .filter(OrderExecution.order_id == req.order_id, OrderExecution.status == 0)
        .all()
    )
    for e in executions:
        e.status = 3
        db.add(e)

    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/inpatientOrder/cancel")
def cancel_inpatient_order(req: dict, db: Session = Depends(get_db)):
    order = db.query(InpatientOrder).filter(InpatientOrder.order_id == req.get("order_id")).first()
    if not order:
        return {"code": 500, "msg": "医嘱不存在"}
    if order.status not in (0, 1):
        return {"code": 500, "msg": "医嘱已执行，无法撤销"}
    order.status = 4
    db.add(order)

    # 取消未执行的执行计划
    executions = (
        db.query(OrderExecution)
        .filter(OrderExecution.order_id == order.order_id, OrderExecution.status == 0)
        .all()
    )
    for e in executions:
        e.status = 3
        db.add(e)

    # 退费：将关联的费用记录标记为已退费
    charges = db.query(InpatientCharge).filter(
        InpatientCharge.related_order_id == order.order_id,
        InpatientCharge.status == 0,
    ).all()
    for c in charges:
        c.status = 2
        db.add(c)

    # 恢复库存
    for item in order.items:
        if item.item_type == "drug" and item.item_id_ref:
            pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item.item_id_ref).first()
            if pha:
                pha.stock += item.quantity * item.days
                db.add(pha)

    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/inpatientOrder/getExecutionList")
def get_execution_list(order_id: str | None = None, nurse_id: int | None = None, status: int | None = None, db: Session = Depends(get_db)):
    query = db.query(OrderExecution).order_by(OrderExecution.planned_time)
    if order_id:
        query = query.filter(OrderExecution.order_id == order_id)
    if nurse_id:
        query = query.filter(OrderExecution.nurse_id == nurse_id)
    if status is not None:
        query = query.filter(OrderExecution.status == status)
    executions = query.all()

    status_map = ["待执行", "已执行", "已跳过", "已停止"]
    data = []
    for item in executions:
        order = db.query(InpatientOrder).filter(InpatientOrder.order_id == item.order_id).first()
        data.append(
            {
                "execution_id": item.execution_id,
                "order_id": item.order_id,
                "patient_name": order.patient.name if order and order.patient else "",
                "item_names": ", ".join([it.item_name for it in order.items]) if order else "",
                "order_type_text": "长期" if order and order.order_type == 0 else "临时" if order else "",
                "planned_time": str(item.planned_time) if item.planned_time else "",
                "execution_time": str(item.execution_time) if item.execution_time else "",
                "status": item.status,
                "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
                "nurse_name": item.nurse.name if item.nurse else "",
                "note": item.note or "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/inpatientOrder/execute")
def execute_order(req: OrderExecutionRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    execution = db.query(OrderExecution).filter(OrderExecution.order_id == req.order_id, OrderExecution.status == 0).first()
    if not execution:
        return {"code": 500, "msg": "无可执行记录"}
    execution.status = req.status
    execution.nurse_id = current_user.user_id
    execution.execution_time = datetime.datetime.now()
    execution.note = req.note
    db.add(execution)

    # 更新医嘱状态为执行中
    order = db.query(InpatientOrder).filter(InpatientOrder.order_id == req.order_id).first()
    if order and order.status == 1:
        order.status = 2
        db.add(order)

    db.commit()
    return {"code": 200, "msg": "success"}
