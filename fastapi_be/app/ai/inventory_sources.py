"""Selected inventory snapshots and raw movement histories, without patient or transaction references."""

import datetime

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_

from app.models import Consumable, ConsumableTrace, Pharmaceutical, PharmaceuticalBatch, PharmaceuticalStockLedger, PurchaseOrder, PurchaseOrderItem


def inventory_selection(values: dict) -> tuple[list[int], list[int]]:
    selections = []
    for key in ("drug_ids", "consumable_ids"):
        raw = values.get(key, [])
        if not isinstance(raw, list) or any(type(value) is not int or value < 1 for value in raw):
            raise HTTPException(422, "库存品种须为真实目录正整数标识列表")
        selections.append(sorted(set(raw)))
    if sum(map(len, selections)) > 20:
        raise HTTPException(422, "单次库存分析最多选择20个品种，请分批核对")
    return selections[0], selections[1]


def attach_inventory_sources(db, departments, start, end, bundle, add, values):
    if departments is not None:
        bundle.data["missing_data"].append("当前库存未保存可核实的科室归属，不向科室范围提供全院库存")
        return
    drug_ids, consumable_ids = inventory_selection(values)
    if not drug_ids and not consumable_ids:
        bundle.data["missing_data"].append("尚未选择具体药品或耗材，未加载跨品种库存；请选择真实目录品种")
        return
    drugs = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id.in_(drug_ids)).order_by(Pharmaceutical.pharmaceutical_id).all()
    consumables = db.query(Consumable).filter(Consumable.consumable_id.in_(consumable_ids)).order_by(Consumable.consumable_id).all()
    if len(drugs) != len(drug_ids) or len(consumables) != len(consumable_ids):
        raise HTTPException(422, "所选库存品种已不存在或不完整，请刷新目录")
    today = datetime.date.today()
    beginning = datetime.datetime.combine(start, datetime.time.min)
    ending = datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min)
    fields = {
        "drugs": [],
        "consumables": [],
        "batch_rows": [],
        "scope_note": "只含明确所选品种；药品目录未记录库存计数单位，不补写成盒、片或剂量单位，不跨品种汇总数量。批次、目录及历史台账可能不一致，保留缺口供核实",
    }
    totals = {
        drug_id: (count, total)
        for drug_id, count, total in db.query(PharmaceuticalBatch.pharmaceutical_id, func.count(PharmaceuticalBatch.batch_id), func.sum(PharmaceuticalBatch.stock))
        .filter(PharmaceuticalBatch.pharmaceutical_id.in_(drug_ids))
        .group_by(PharmaceuticalBatch.pharmaceutical_id)
        .all()
    }
    for drug in drugs:
        batch_count, batch_total = totals.get(drug.pharmaceutical_id, (0, None))
        fields["drugs"].append(
            {
                "drug_id": drug.pharmaceutical_id,
                "name": drug.name,
                "catalog_status": drug.status,
                "catalog_stock": drug.stock,
                "stock_count_unit": None,
                "catalog_expiry_date": drug.expireddate,
                "recorded_batch_count": batch_count,
                "all_batch_stock_sum": batch_total,
                "catalog_matches_batch_sum": drug.stock == batch_total if drug.stock is not None and batch_total is not None else None,
            }
        )
    fields["consumables"] = [{"consumable_id": row.consumable_id, "name": row.name, "stock": row.stock, "unit": row.unit, "status": row.status} for row in consumables]
    batches = (
        db.query(PharmaceuticalBatch)
        .filter(PharmaceuticalBatch.pharmaceutical_id.in_(drug_ids))
        .order_by(PharmaceuticalBatch.expiry_date.is_(None), PharmaceuticalBatch.expiry_date, PharmaceuticalBatch.batch_id)
        .limit(201)
        .all()
    )
    fields["batch_rows"] = [
        {
            "batch_id": row.batch_id,
            "drug_id": row.pharmaceutical_id,
            "batch_no": row.batch_no,
            "stock": row.stock,
            "status": row.status,
            "expiry_date": row.expiry_date,
            "expiry_before_business_date": row.expiry_date < today if row.expiry_date is not None else None,
            "location": row.location,
            "updated_at": row.update_time,
        }
        for row in batches[:200]
    ]
    fields["batch_rows_truncated"] = len(batches) > 200
    fields["batch_note"] = "批次状态0在用、1冻结；效期标记仅表示日期早于本次业务日，不替代既有药房规则。药品无批次记录时批次合计保持未知，不作零值或完整覆盖判断"
    ledger = PharmaceuticalStockLedger
    day = func.date(ledger.create_time)
    state = case((ledger.transaction_type.in_(["inbound", "outbound", "return", "adjustment"]), ledger.transaction_type), else_="unknown")
    delta = ledger.after_stock - ledger.before_stock
    consistent = or_(
        and_(ledger.transaction_type == "outbound", ledger.quantity >= 0, delta == -ledger.quantity),
        and_(ledger.transaction_type.in_(["inbound", "return"]), ledger.quantity >= 0, delta == ledger.quantity),
        and_(ledger.transaction_type == "adjustment", delta == ledger.quantity),
    )
    rows = (
        db.query(day, ledger.pharmaceutical_id, state, func.count(), func.sum(ledger.quantity), func.sum(delta), func.sum(case((consistent, 1), else_=0)))
        .join(PharmaceuticalBatch, ledger.batch_id == PharmaceuticalBatch.batch_id)
        .filter(ledger.pharmaceutical_id.in_(drug_ids), PharmaceuticalBatch.pharmaceutical_id == ledger.pharmaceutical_id, ledger.create_time >= beginning, ledger.create_time < ending)
        .group_by(day, ledger.pharmaceutical_id, state)
        .order_by(day.desc(), ledger.pharmaceutical_id, state)
        .limit(1001)
        .all()
    )
    fields["drug_ledger_daily"] = {
        "columns": ["date", "drug_id", "transaction_type", "record_count", "raw_quantity_sum", "recorded_stock_delta_sum", "consistent_quantity_delta_count"],
        "rows": [[str(date), drug_id, kind, count, quantity, change, matching] for date, drug_id, kind, count, quantity, change, matching in reversed(rows[:1000])],
        "truncated": len(rows) > 1000,
        "definition_note": "出库原数量通常为正数，库存差额为负；调整数量保留正负。不同类型不混成净消耗，退回不直接等于需求减少；数量与前后库存不符的记录须核实",
    }
    fields["loaded_quantity_delta_mismatch_count"] = sum(count - matching for _, _, _, count, _, _, matching in rows[:1000])
    if fields["loaded_quantity_delta_mismatch_count"]:
        bundle.data["missing_data"].append("所选药品台账原数量与前后库存变化存在不一致，不能将其视为已核实消耗序列")
    invalid_links = (
        db.query(func.count(ledger.ledger_id))
        .outerjoin(PharmaceuticalBatch, ledger.batch_id == PharmaceuticalBatch.batch_id)
        .filter(
            ledger.pharmaceutical_id.in_(drug_ids),
            ledger.create_time >= beginning,
            ledger.create_time < ending,
            or_(PharmaceuticalBatch.batch_id.is_(None), PharmaceuticalBatch.pharmaceutical_id != ledger.pharmaceutical_id),
        )
        .scalar()
        or 0
    )
    fields["excluded_inconsistent_ledger_links"] = invalid_links
    if invalid_links:
        bundle.data["missing_data"].append("所选药品存在批次关联不一致的台账，已排除，当前序列不完整")
    trace = ConsumableTrace
    trace_day = func.date(trace.action_time)
    action = case((trace.action.in_(["in", "out", "use", "return", "destroy"]), trace.action), else_="unknown")
    rows = (
        db.query(trace_day, trace.consumable_id, action, func.count(), func.sum(trace.quantity), func.sum(case((trace.quantity < 0, 1), else_=0)))
        .filter(trace.consumable_id.in_(consumable_ids), trace.action_time >= beginning, trace.action_time < ending)
        .group_by(trace_day, trace.consumable_id, action)
        .order_by(trace_day.desc(), trace.consumable_id, action)
        .limit(1001)
        .all()
    )
    fields["consumable_trace_daily"] = {
        "columns": ["date", "consumable_id", "recorded_action", "record_count", "raw_quantity_sum", "negative_quantity_record_count"],
        "rows": [[str(date), item_id, action, count, quantity, negative] for date, item_id, action, count, quantity, negative in reversed(rows[:1000])],
        "truncated": len(rows) > 1000,
        "definition_note": "追溯记录不是完整库存变更账；out和use可能描述同一过程，不能直接相加作为消耗，不推断无记录日为零消耗。不发送患者、操作者、流水关联或原始备注",
    }
    lines = (
        db.query(PurchaseOrderItem, PurchaseOrder)
        .join(PurchaseOrder)
        .filter(
            PurchaseOrder.create_time >= beginning,
            PurchaseOrder.create_time < ending,
            or_(
                and_(PurchaseOrderItem.item_type == "drug", PurchaseOrderItem.item_id_ref.in_(drug_ids)),
                and_(PurchaseOrderItem.item_type == "consumable", PurchaseOrderItem.item_id_ref.in_(consumable_ids)),
            ),
        )
        .order_by(PurchaseOrder.create_time.desc(), PurchaseOrderItem.item_id)
        .limit(101)
        .all()
    )
    fields["purchase_lines"] = [
        {
            "purchase_id": order.purchase_id,
            "item_type": line.item_type,
            "item_id_ref": line.item_id_ref,
            "ordered_quantity": line.quantity,
            "received_quantity": line.received_quantity,
            "order_status": order.status,
            "created_at": order.create_time,
            "approved_at": order.approve_time,
            "stored_at": order.storage_time,
        }
        for line, order in lines[:100]
    ]
    fields["purchase_lines_truncated"] = len(lines) > 100
    fields["purchase_note"] = "订单状态0待审批、1已审批、2已入库、3已取消；实收为空时未知，不按计划数量当实收。订单事件时间不是供应商承诺交期或完整库存周转周期"
    if fields["batch_rows_truncated"] or fields["drug_ledger_daily"]["truncated"] or fields["consumable_trace_daily"]["truncated"] or fields["purchase_lines_truncated"]:
        bundle.data["truncated_sources"].append({"source": "supply_inventory", "note": "批次、历史流水或订单清单已截断，请缩小日期或品种范围；不能作为完整训练序列"})
    bundle.data["missing_data"].extend(["未取得已验证的需求预测序列、采购交期约束或补货上下限；不能从当前库存自行推定采购量", "耗材未建立完整出入库台账；药品库存计数单位未记录时保持未知"])
    add("supply_inventory", "所选品种库存、批次和原始业务汇总", fields)
