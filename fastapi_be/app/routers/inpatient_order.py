import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, NURSING_ROLES, require_roles
from app.models import (
    Admission,
    Doctor,
    InpatientCharge,
    InpatientOrder,
    InpatientOrderItem,
    OrderExecution,
    Pharmaceutical,
    User,
)
from app.pagination import paginate
from app.pharmacy_safety import get_patient_safe_pharmaceutical
from app.schemas import InpatientOrderCreateRequest, InpatientOrderStopRequest, OrderExecutionRequest

router = APIRouter()

_INPATIENT_ROLES = CLINICAL_ROLES | NURSING_ROLES


def _can_manage_order(order: InpatientOrder, current_user: User, db: Session) -> bool:
    if current_user.user_role in ADMIN_ROLES or current_user.user_role == "director":
        return True
    doctor_ids = [item.doctor_id for item in db.query(Doctor).filter(Doctor.user_id == current_user.user_id).all()]
    return order.doctor_id in doctor_ids


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

        # 以医嘱为单位按"天数 × 最高频次"生成执行记录（一次执行同时覆盖全部明细）。
        # 原实现对每个明细各生成一整套，导致 N 个明细的医嘱执行计划放大 N 倍。
        max_freq = 1
        for item in order.items:
            max_freq = max(max_freq, freq_map.get(item.frequency, 1))

        for d in range(days):
            base_time = datetime.datetime.now() + datetime.timedelta(days=d)
            for i in range(max_freq):
                planned = base_time.replace(hour=8 + i * (16 // max(max_freq, 1)), minute=0, second=0)
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
    page: int | None = None,
    page_size: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*_INPATIENT_ROLES)),
):
    query = db.query(InpatientOrder).options(
        joinedload(InpatientOrder.patient),
        joinedload(InpatientOrder.doctor),
        selectinload(InpatientOrder.items),
    ).order_by(InpatientOrder.create_time.desc())
    if admission_id:
        query = query.filter(InpatientOrder.admission_id == admission_id)
    if patient_id:
        query = query.filter(InpatientOrder.patient_id == patient_id)
    if status is not None:
        query = query.filter(InpatientOrder.status == status)
    if order_type is not None:
        query = query.filter(InpatientOrder.order_type == order_type)
    if current_user.user_role not in ADMIN_ROLES and current_user.user_role not in NURSING_ROLES:
        doctor_ids = [item.doctor_id for item in db.query(Doctor).filter(Doctor.user_id == current_user.user_id).all()]
        query = query.filter(InpatientOrder.doctor_id.in_(doctor_ids or [-1]))
    orders, total = paginate(query, page, page_size)

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
                "start_time": (item.start_time.strftime("%Y-%m-%d %H:%M:%S") if item.start_time else None) if item.start_time else "",
                "stop_time": (item.stop_time.strftime("%Y-%m-%d %H:%M:%S") if item.stop_time else None) if item.stop_time else "",
                "status": item.status,
                "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
                "priority": item.priority,
                "priority_text": priority_map[item.priority] if item.priority is not None and item.priority < len(priority_map) else "",
                "note": item.note or "",
                "items": items_data,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else "",
            }
        )
    result = {"code": 200, "msg": "success", "data": data}
    if page is not None or page_size is not None:
        result["total"] = total
    return result


@router.post("/inpatientOrder/create")
def create_inpatient_order(req: InpatientOrderCreateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    admission = db.query(Admission).filter(Admission.admission_id == req.admission_id).first()
    if not admission:
        return {"code": 500, "msg": "入院记录不存在"}
    if admission.status != 1:
        return {"code": 500, "msg": "病人不在院状态，无法开立医嘱"}
    if admission.patient_id != req.patient_id:
        return {"code": 500, "msg": "医嘱患者与入院记录不匹配"}
    doctor_ids = [item.doctor_id for item in db.query(Doctor).filter(Doctor.user_id == current_user.user_id).all()]
    if current_user.user_role not in ADMIN_ROLES and req.doctor_id not in doctor_ids:
        return {"code": 403, "msg": "不能以其他医生身份开立医嘱"}
    if not req.items:
        return {"code": 500, "msg": "医嘱明细不能为空"}

    validated_items = []
    for it in req.items:
        if not isinstance(it, dict) or not str(it.get("item_name", "")).strip():
            return {"code": 500, "msg": "医嘱明细名称不能为空"}
        try:
            quantity = int(it.get("quantity", 1))
            days = int(it.get("days", 1))
            unit_price = float(it.get("unit_price", 0))
        except (TypeError, ValueError, OverflowError):
            return {"code": 500, "msg": "医嘱数量、天数或价格格式错误"}
        if quantity <= 0 or days <= 0 or unit_price < 0:
            return {"code": 500, "msg": "医嘱数量、天数和价格必须合法"}
        if it.get("item_type") == "drug" and it.get("item_id_ref"):
            pha, safety_error = get_patient_safe_pharmaceutical(db, it.get("item_id_ref"), req.patient_id)
            if not pha:
                return {"code": 500, "msg": safety_error}
            if pha.stock < quantity * days:
                return {"code": 500, "msg": f"药品 {pha.name} 库存不足"}
        validated_items.append((it, quantity, days, unit_price))

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
    for it, quantity, days, unit_price in validated_items:
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
    # 预缴金余额预警（不阻断开嘱，返回提示供前端弹窗）
    from app.config_service import get_config_float

    admission = db.query(Admission).filter(Admission.admission_id == req.admission_id).first()
    warning = None
    if admission and admission.deposit_amount:
        charged = (
            db.query(func.sum(InpatientCharge.total_amount))
            .filter(InpatientCharge.admission_id == admission.admission_id, InpatientCharge.status != 2)
            .scalar()
            or 0
        )
        balance = float(admission.deposit_amount) - float(charged)
        warn_ratio = get_config_float(db, "deposit_warning_ratio", 0.3)
        if balance < 0 or (admission.deposit_amount > 0 and balance / float(admission.deposit_amount) < warn_ratio):
            warning = f"预缴金余额不足（当前余额 {balance:.2f} 元），请通知患者补缴"
    return {"code": 200, "msg": "success", "data": {"order_id": order.order_id, "total_amount": total_amount, "deposit_warning": warning}}


@router.post("/inpatientOrder/audit")
def audit_inpatient_order(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    order = db.query(InpatientOrder).filter(InpatientOrder.order_id == req.get("order_id")).first()
    if not order:
        return {"code": 500, "msg": "医嘱不存在"}
    if not _can_manage_order(order, current_user, db):
        return {"code": 403, "msg": "无权审核其他医生的医嘱"}
    if order.status != 0:
        return {"code": 500, "msg": "医嘱状态不正确，无法审核"}
    updated = db.query(InpatientOrder).filter(
        InpatientOrder.order_id == order.order_id,
        InpatientOrder.status == 0,
    ).update({InpatientOrder.status: 1}, synchronize_session=False)
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "医嘱状态不正确，无法审核"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/inpatientOrder/stop")
def stop_inpatient_order(req: InpatientOrderStopRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    order = db.query(InpatientOrder).filter(InpatientOrder.order_id == req.order_id).first()
    if not order:
        return {"code": 500, "msg": "医嘱不存在"}
    if not _can_manage_order(order, current_user, db):
        return {"code": 403, "msg": "无权停止其他医生的医嘱"}
    if order.status not in (1, 2):
        return {"code": 500, "msg": "医嘱状态不正确，无法停止"}
    now = datetime.datetime.now()
    updated = db.query(InpatientOrder).filter(
        InpatientOrder.order_id == req.order_id,
        InpatientOrder.status.in_((1, 2)),
    ).update({InpatientOrder.status: 3, InpatientOrder.stop_time: now}, synchronize_session=False)
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "医嘱状态不正确，无法停止"}

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
def cancel_inpatient_order(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    order = db.query(InpatientOrder).filter(InpatientOrder.order_id == req.get("order_id")).first()
    if not order:
        return {"code": 500, "msg": "医嘱不存在"}
    if not _can_manage_order(order, current_user, db):
        return {"code": 403, "msg": "无权撤销其他医生的医嘱"}
    if order.status not in (0, 1):
        return {"code": 500, "msg": "医嘱已执行，无法撤销"}
    updated = db.query(InpatientOrder).filter(
        InpatientOrder.order_id == order.order_id,
        InpatientOrder.status.in_((0, 1)),
    ).update({InpatientOrder.status: 4}, synchronize_session=False)
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "医嘱已执行，无法撤销"}

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
def get_execution_list(
    order_id: str | None = None,
    nurse_id: int | None = None,
    status: int | None = None,
    page: int | None = None,
    page_size: int | None = None,
    current_user: User = Depends(require_roles(*NURSING_ROLES, *CLINICAL_ROLES)),
    db: Session = Depends(get_db),
):
    query = db.query(OrderExecution).options(
        joinedload(OrderExecution.nurse),
        joinedload(OrderExecution.order).joinedload(InpatientOrder.patient),
        joinedload(OrderExecution.order).selectinload(InpatientOrder.items),
    ).order_by(OrderExecution.planned_time)
    if order_id:
        query = query.filter(OrderExecution.order_id == order_id)
    if nurse_id:
        query = query.filter(OrderExecution.nurse_id == nurse_id)
    if status is not None:
        query = query.filter(OrderExecution.status == status)
    executions, total = paginate(query, page, page_size)

    status_map = ["待执行", "已执行", "已跳过", "已停止"]
    data = []
    for item in executions:
        order = item.order
        data.append(
            {
                "execution_id": item.execution_id,
                "order_id": item.order_id,
                "patient_name": order.patient.name if order and order.patient else "",
                "item_names": ", ".join([it.item_name for it in order.items]) if order else "",
                "order_type_text": "长期" if order and order.order_type == 0 else "临时" if order else "",
                "planned_time": (item.planned_time.strftime("%Y-%m-%d %H:%M:%S") if item.planned_time else None) if item.planned_time else "",
                "execution_time": (item.execution_time.strftime("%Y-%m-%d %H:%M:%S") if item.execution_time else None) if item.execution_time else "",
                "status": item.status,
                "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
                "nurse_name": item.nurse.name if item.nurse else "",
                "note": item.note or "",
            }
        )
    result = {"code": 200, "msg": "success", "data": data}
    if page is not None or page_size is not None:
        result["total"] = total
    return result


@router.post("/inpatientOrder/execute")
def execute_order(req: OrderExecutionRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    if req.status not in (1, 2):
        return {"code": 500, "msg": "执行结果只能是已执行或已跳过"}
    order = db.query(InpatientOrder).filter(InpatientOrder.order_id == req.order_id).first()
    if not order or order.status not in (1, 2):
        return {"code": 500, "msg": "医嘱当前状态不允许执行"}
    execution = (
        db.query(OrderExecution)
        .filter(OrderExecution.order_id == req.order_id, OrderExecution.status == 0)
        .order_by(OrderExecution.planned_time.asc())
        .first()
    )
    if not execution:
        return {"code": 500, "msg": "无可执行记录"}
    updated = db.query(OrderExecution).filter(
        OrderExecution.execution_id == execution.execution_id,
        OrderExecution.status == 0,
    ).update({
        OrderExecution.status: req.status,
        OrderExecution.nurse_id: current_user.user_id,
        OrderExecution.execution_time: datetime.datetime.now(),
        OrderExecution.note: req.note,
    }, synchronize_session=False)
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "执行记录已被其他护士处理"}

    # 更新医嘱状态为执行中
    if order.status == 1:
        order.status = 2
        db.add(order)

    db.commit()
    return {"code": 200, "msg": "success"}
