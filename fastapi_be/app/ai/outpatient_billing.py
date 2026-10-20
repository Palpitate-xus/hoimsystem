"""Verified outpatient charge links and payment/invoice summaries without payment credentials."""

from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import case, func
from sqlalchemy.orm import selectinload

from app.models import Charge, Invoice, Payment, Registration


def resolve_outpatient_charge(db, patient_id: int, reference: str) -> Charge:
    if not isinstance(reference, str) or not reference or len(reference) > 50:
        raise HTTPException(422, "所选收费标识格式不正确")
    charge = db.get(Charge, reference)
    if charge is None:
        raise HTTPException(404, "所选收费资料不存在或不属于该患者")
    prescription = charge.prescription if charge.prescription_id else None
    registration = db.get(Registration, charge.registration_uuid) if charge.registration_uuid else None
    if (charge.prescription_id and prescription is None) or (charge.registration_uuid and registration is None):
        raise HTTPException(422, "收费关联资料不完整，须先核实原始记录")
    owners = [row.patient_id for row in (prescription, registration) if row is not None]
    if not owners or any(owner != patient_id for owner in owners):
        raise HTTPException(404, "所选收费资料不存在或不属于该患者")
    return charge


def attach_outpatient_billing(db, user, spec, patient, encounter, bundle, add, selected, bounded, authorize) -> bool:
    chosen = selected.get("outpatient_charge_id")
    if chosen is None and not isinstance(encounter, Registration):
        return False
    if selected.get("inpatient_charge_id") is not None or selected.get("home_id") is not None:
        raise HTTPException(422, "门诊收费不能与住院费用或病案首页混合核对")
    registration = db.get(Registration, chosen.registration_uuid) if chosen is not None and chosen.registration_uuid else encounter
    if chosen is not None and encounter is not None and (not isinstance(encounter, Registration) or chosen.registration_uuid != encounter.registration_uuid):
        raise HTTPException(422, "门诊收费没有与所选就诊一致的原始关联")
    if registration is not None:
        if registration.patient_id != patient.patient_id:
            raise HTTPException(422, "门诊收费与就诊患者关联不一致")
        authorize(db, user, patient.patient_id, spec.category, registration.registration_uuid)
    bundle.department_ids = {registration.department_id} if registration is not None and registration.department_id else set()
    bundle.data["billing_scope"] = {
        "kind": "outpatient",
        "registration_uuid": registration.registration_uuid if registration is not None else None,
        "charge_id": chosen.charge_id if chosen is not None else None,
        "note": "仅所选收费或所选门诊的原始收费关联；处方本身未保存就诊关联时，不按日期猜测归属",
    }
    query = db.query(Charge).options(selectinload(Charge.prescription))
    query = query.filter(Charge.charge_id == chosen.charge_id) if chosen is not None else query.filter(Charge.registration_uuid == registration.registration_uuid)
    rows = bounded(query.order_by(Charge.charge_time.desc(), Charge.charge_id), 50, "门诊收费记录", "outpatient_charge_id", "charge_id")
    charges = []
    for row in rows:
        try:
            charges.append(resolve_outpatient_charge(db, patient.patient_id, row.charge_id))
        except HTTPException:
            # Never expose an inconsistent other-patient prescription through an otherwise owned visit.
            bundle.data["missing_data"].append("所选门诊存在无法核实一致患者归属的收费关联，已排除；本次清单不完整")
    bundle.data["missing_data"] = list(dict.fromkeys(bundle.data["missing_data"]))
    charge_ids = [row.charge_id for row in charges]
    bundle.data["outpatient_charges"] = [
        add(
            "outpatient-charge:" + row.charge_id,
            "门诊原始收费记录",
            {name: getattr(row, name) for name in ("charge_id", "charge_type", "prescription_id", "registration_uuid", "amount", "status", "charge_time", "time")},
            row.charge_time,
        )
        for row in charges
    ]
    prescriptions = {row.prescription_id: row.prescription for row in charges if row.prescription is not None}
    bundle.data["billing_prescription_states"] = [
        add(
            "billing-prescription:" + row.prescription_id,
            "收费关联处方状态",
            {name: getattr(row, name) for name in ("prescription_id", "status", "create_time")},
            row.create_time,
        )
        for row in sorted(prescriptions.values(), key=lambda row: row.prescription_id)
    ]
    for key, model, primary_key, known_states, time_field, title in (
        ("billing_payment_summaries", Payment, "payment_id", [0, 1, 2, 3], "paid_time", "门诊支付流水分状态汇总"),
        ("billing_invoice_summaries", Invoice, "invoice_id", [0, 1, 2], "invoice_time", "门诊票据分状态汇总"),
    ):
        state = case((model.status.in_(known_states), model.status), else_=-1)
        grouped = {}
        for charge_id, status, count, priced_count, total, first_time, last_time in (
            db.query(
                model.charge_id,
                state,
                func.count(getattr(model, primary_key)),
                func.count(model.amount),
                func.sum(model.amount),
                func.min(getattr(model, time_field)),
                func.max(getattr(model, time_field)),
            )
            .filter(model.charge_id.in_(charge_ids))
            .group_by(model.charge_id, state)
            .order_by(model.charge_id, state)
            .all()
        ):
            grouped.setdefault(charge_id, []).append(
                {"status": status, "count": count, "priced_record_count": priced_count, "amount_sum": total, "first_recorded_time": first_time, "last_recorded_time": last_time}
            )
        bundle.data[key] = [
            add(
                key + ":" + charge_id,
                title,
                {"charge_id": charge_id, "status_totals": grouped.get(charge_id, []), "scope_note": "所选收费的全部已保存流水按状态汇总；未知状态归入-1，不发送二维码、交易单号或外部支付标识"},
            )
            for charge_id in charge_ids
        ]
    return True


def _amount(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def outpatient_reconciliation(context: dict) -> list[dict]:
    payments = {row["charge_id"]: row for row in context.get("billing_payment_summaries", [])}
    invoices = {row["charge_id"]: row for row in context.get("billing_invoice_summaries", [])}
    checks = []
    for charge in context.get("outpatient_charges", []):
        amount = _amount(charge.get("amount"))
        payment = payments.get(charge["charge_id"], {})
        invoice = invoices.get(charge["charge_id"], {})
        paid = next((row for row in payment.get("status_totals", []) if row["status"] == 1), None)
        refunded = next((row for row in payment.get("status_totals", []) if row["status"] == 3), None)
        active_invoices = [row for row in invoice.get("status_totals", []) if row["status"] in {0, 1}]
        findings = []
        if amount is None:
            findings.append("保存应收金额缺失，未按零值代入")
        if charge["status"] == 1:
            if paid is None:
                findings.append("已缴费但未找到当前成功支付流水，须核实现金或历史账务，不能判为未支付")
            elif paid["priced_record_count"] != paid["count"] or _amount(paid["amount_sum"]) is None:
                findings.append("成功支付流水存在缺失金额，不能完成金额对账")
            elif amount is not None and _amount(paid["amount_sum"]) != amount:
                findings.append("成功支付流水原始合计与保存应收金额不同，需核实分次支付、退款及历史账务")
        elif charge["status"] == 0 and paid is not None:
            findings.append("收费仍为未缴费但存在成功支付流水，需核实支付回调和状态同步")
        elif charge["status"] == 2:
            if paid is not None:
                findings.append("收费已退费但仍存在成功支付流水，需核实退款回执和状态同步")
            if refunded is None:
                findings.append("收费已退费但未找到已退款流水，须核实历史退款记录，不能直接断言未退款")
            if active_invoices:
                findings.append("收费已退费但仍有未作废票据，需人工核实票据状态")
        elif charge["status"] not in {0, 1}:
            findings.append("收费状态未知，须核实原始账务")
        if any(row["status"] == -1 for row in [*payment.get("status_totals", []), *invoice.get("status_totals", [])]):
            findings.append("存在未知状态的支付或票据流水，不能视为成功、退款或作废")
        if sum(row["count"] for row in active_invoices) > 1:
            findings.append("同一收费保存多条未作废票据，须核实开票范围，不能自动作废")
        for row in active_invoices:
            if row["priced_record_count"] != row["count"] or _amount(row["amount_sum"]) is None:
                findings.append("未作废票据存在缺失金额，不能完成票据金额对账")
            elif amount is not None and row["count"] == 1 and _amount(row["amount_sum"]) != amount:
                findings.append("未作废票据保存金额与应收金额不同，需核实票据原记录")
        checks.append(
            {
                "charge_id": charge["charge_id"],
                "charge_type": charge.get("charge_type"),
                "charge_status": charge["status"],
                "expected_amount": str(amount) if amount is not None else None,
                "payment_status_totals": payment.get("status_totals", []),
                "invoice_status_totals": invoice.get("status_totals", []),
                "findings": list(dict.fromkeys(findings)),
                "source_ids": [row["source_id"] for row in (charge, payment, invoice) if row.get("source_id")],
            }
        )
    return checks
