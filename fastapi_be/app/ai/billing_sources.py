"""Bounded, read-only billing evidence. A missing link never establishes a billable service."""

from decimal import Decimal, InvalidOperation, localcontext

from fastapi import HTTPException
from sqlalchemy import case, exists, func

from app.ai.outpatient_billing import attach_outpatient_billing, outpatient_reconciliation
from app.models import Admission, InpatientCharge, InpatientOrder, OrderExecution


def attach_billing_sources(db, user, spec, patient, encounter, bundle, add, selected, bounded, authorize) -> None:
    if spec.number != 69:
        return
    if attach_outpatient_billing(db, user, spec, patient, encounter, bundle, add, selected, bounded, authorize):
        return
    chosen = selected.get("inpatient_charge_id")
    home = selected.get("home_id")
    admission = encounter if isinstance(encounter, Admission) else None
    if chosen is not None:
        if encounter is not None and (admission is None or chosen.admission_id != admission.admission_id):
            raise HTTPException(422, "住院费用与所选就诊不一致")
        if home is not None and chosen.admission_id != home.admission_id:
            raise HTTPException(422, "住院费用与所选病案首页不一致")
        admission = db.get(Admission, chosen.admission_id)
    elif admission is None and home is not None and encounter is None:
        admission = db.get(Admission, home.admission_id)
    if admission is None:
        bundle.data["missing_data"].append("未选择可核实的住院费用范围，未加载住院账目")
        return
    if home is not None and home.admission_id != admission.admission_id:
        raise HTTPException(422, "病案首页与所选收费住院不一致")
    if admission.patient_id != patient.patient_id:
        raise HTTPException(422, "费用记录与住院患者关联不一致")
    authorize(db, user, patient.patient_id, spec.category, admission.admission_id)
    bundle.department_ids = {admission.department_id} if admission.department_id else set()
    bundle.data["billing_scope"] = {"kind": "inpatient", "admission_id": admission.admission_id, "note": "仅核对所选住院中的有限费用和原始关联记录"}
    if home is not None:
        bundle.data["billing_case_home"] = add(
            "billing-home:" + home.home_id, "病案首页已保存费用字段", {name: getattr(home, name) for name in ("home_id", "admission_id", "total_fee", "status")}, home.update_time
        )
    charges = bounded(
        db.query(InpatientCharge).filter_by(patient_id=patient.patient_id, admission_id=admission.admission_id).order_by(InpatientCharge.create_time.desc(), InpatientCharge.charge_id),
        50,
        "住院收费记录",
        "inpatient_charge_id",
        "charge_id",
    )
    fields = (
        "charge_id",
        "admission_id",
        "item_name",
        "item_type",
        "quantity",
        "unit_price",
        "total_amount",
        "charge_date",
        "related_order_id",
        "status",
        "settled_time",
        "refunded_time",
        "refund_reason",
    )
    bundle.data["inpatient_charges"] = [add("inpatient-charge:" + row.charge_id, "住院原始收费记录", {name: getattr(row, name) for name in fields}, row.create_time) for row in charges]
    order_ids = {row.related_order_id for row in charges if row.related_order_id}
    linked = (
        db.query(InpatientOrder)
        .filter(InpatientOrder.order_id.in_(order_ids), InpatientOrder.patient_id == patient.patient_id, InpatientOrder.admission_id == admission.admission_id)
        .order_by(InpatientOrder.order_id)
        .all()
    )
    unlinked = (
        db.query(InpatientOrder)
        .filter(
            InpatientOrder.patient_id == patient.patient_id,
            InpatientOrder.admission_id == admission.admission_id,
            InpatientOrder.status.in_([1, 2, 3]),
            exists().where(OrderExecution.order_id == InpatientOrder.order_id, OrderExecution.status == 1, OrderExecution.execution_time.is_not(None)),
            ~exists().where(InpatientCharge.related_order_id == InpatientOrder.order_id),
        )
        .order_by(InpatientOrder.create_time.desc(), InpatientOrder.order_id)
        .limit(21)
        .all()
    )
    if len(unlinked) > 20:
        bundle.data["truncated_sources"].append({"source": "已记录执行且未保存收费关联的医嘱", "limit": 20, "note": "仅列待核对候选；不构成应收费或应补费判断"})
    unlinked_ids = {row.order_id for row in unlinked[:20]}
    all_orders = {row.order_id: row for row in [*linked, *unlinked[:20]]}
    execution_summary = {}
    for order_id, status, count, timed_count, first_time, last_time in (
        db.query(
            OrderExecution.order_id,
            OrderExecution.status,
            func.count(OrderExecution.execution_id),
            func.sum(case((OrderExecution.execution_time.is_not(None), 1), else_=0)),
            func.min(OrderExecution.execution_time),
            func.max(OrderExecution.execution_time),
        )
        .filter(OrderExecution.order_id.in_(all_orders))
        .group_by(OrderExecution.order_id, OrderExecution.status)
        .order_by(OrderExecution.order_id, OrderExecution.status)
        .all()
    ):
        execution_summary.setdefault(order_id, []).append(
            {"status": status, "count": count, "records_with_actual_time": timed_count, "first_recorded_time": first_time, "last_recorded_time": last_time}
        )
    bundle.data["billing_related_orders"] = [
        add(
            "billing-order:" + row.order_id,
            "收费关联医嘱与执行记录汇总",
            {
                "order_id": row.order_id,
                "category": row.category,
                "status": row.status,
                "execution_summary": execution_summary.get(row.order_id, []),
                "execution_scope_note": "医嘱级执行汇总不证明每个收费项目已经执行或具有收费资格",
                "has_no_charge_link": row.order_id in unlinked_ids,
            },
            row.create_time,
        )
        for row in sorted(all_orders.values(), key=lambda item: item.order_id)
    ]


def _decimal(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def billing_reconciliation(context: dict) -> dict:
    """Compare saved facts exactly without inventing service eligibility or a rounding policy."""
    orders = {row["order_id"]: row for row in context.get("billing_related_orders", [])}
    checks = []
    for charge in context.get("inpatient_charges", []):
        quantity, price, amount = (_decimal(charge.get(key)) for key in ("quantity", "unit_price", "total_amount"))
        with localcontext() as arithmetic:
            arithmetic.prec = 64  # Exact product of a persisted Float quantity and NUMERIC(12,2) price.
            raw_product = quantity * price if quantity is not None and price is not None else None
        amount_comparison = "unknown" if raw_product is None or amount is None else "equal_raw_product" if raw_product == amount else "raw_product_differs"
        findings = []
        order = orders.get(charge.get("related_order_id"))
        if charge.get("status") == 2:
            findings.append("已记录退费，须按退费事实核对，不列为补费候选")
        elif charge.get("status") not in {0, 1}:
            findings.append("收费状态未知，须核实原始账务")
        if not charge.get("related_order_id"):
            findings.append("未保存关联医嘱，不能自动核对执行情况")
        elif order is None:
            findings.append("所记关联医嘱未能在所选住院中核实")
        elif not any(item["status"] == 1 and item["records_with_actual_time"] for item in order.get("execution_summary", [])):
            findings.append("关联医嘱缺少同时具备已执行状态和实际时间的记录，不能据此断言未执行")
        if amount_comparison == "raw_product_differs":
            findings.append("原始数量乘单价与保存金额不同，需核实计价、精度和舍入口径")
        elif amount_comparison == "unknown":
            findings.append("数量、单价或金额缺失，未按零值代入")
        checks.append(
            {
                "charge_id": charge["charge_id"],
                "item_name": charge.get("item_name"),
                "charge_status": charge.get("status"),
                "quantity": str(quantity) if quantity is not None else None,
                "unit_price": str(price) if price is not None else None,
                "stored_amount": str(amount) if amount is not None else None,
                "raw_product": str(raw_product) if raw_product is not None else None,
                "amount_comparison": amount_comparison,
                "findings": findings,
                "source_ids": [charge["source_id"], *([order["source_id"]] if order else [])],
            }
        )
    return {
        "scope": context.get("billing_scope"),
        "checks": checks,
        "outpatient_checks": outpatient_reconciliation(context),
        "executed_without_charge_link": [{"order_id": row["order_id"], "category": row.get("category"), "source_ids": [row["source_id"]]} for row in orders.values() if row.get("has_no_charge_link")],
        "scope_note": (
            "门诊收费与支付票据原始金额、状态核对；现金或历史流水缺失须人工核实，不按当前药价反算历史账单"
            if context.get("billing_scope", {}).get("kind") == "outpatient"
            else "有限原始账目与执行关联核对；无收费关联可能是免费项目、打包计费或关联未保存，不能直接认定漏收费；数量乘单价未套用未提供的舍入或计价政策"
        ),
        "truncated_sources": context.get("truncated_sources", []),
        "missing_data": context.get("missing_data", []),
        "changes_written": [],
    }
