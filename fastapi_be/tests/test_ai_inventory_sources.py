"""Inventory AI retains quantity signs, trace limitations, ownership scope and missing values."""

import datetime
import uuid

import httpx
import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import encode_json
from app.ai.inventory_sources import inventory_selection
from app.ai.models import AIFeatureConfig, AIFeedback, AIProvider, AIRun
from app.ai.operational_sources import operational_context
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Consumable, ConsumableTrace, Pharmaceutical, PharmaceuticalBatch, PharmaceuticalStockLedger, PurchaseOrder, PurchaseOrderItem


@pytest.fixture(autouse=True)
def clean_ai_tasks(db_session):
    for model in (AIFeedback, AIRun, AIFeatureConfig, AIProvider):
        db_session.query(model).delete()
    db_session.commit()


@pytest.fixture
def inventory_case(seed_data, db_session):
    now = datetime.datetime.now()
    drug = seed_data["pharmaceutical"]
    drug.stock = 8
    batches = [
        PharmaceuticalBatch(pharmaceutical_id=drug.pharmaceutical_id, batch_no=uuid.uuid4().hex, stock=stock, status=status, expiry_date=expiry, create_time=now, update_time=now)
        for stock, status, expiry in ((5, 0, now.date() - datetime.timedelta(days=1)), (3, 1, None))
    ]
    consumable = Consumable(name="AI测试耗材", unit="支", stock=10, status=0, create_time=now)
    other_drug = Pharmaceutical(name="无批次且库存未知测试品种", stock=None, status=0)
    db_session.add_all([*batches, consumable, other_drug])
    db_session.flush()
    foreign_batch = PharmaceuticalBatch(pharmaceutical_id=other_drug.pharmaceutical_id, batch_no=uuid.uuid4().hex, stock=2, status=0, create_time=now, update_time=now)
    db_session.add(foreign_batch)
    db_session.flush()
    for kind, quantity, before, after, batch_id in (
        ("inbound", 10, 0, 10, batches[0].batch_id),
        ("outbound", 2, 10, 8, batches[0].batch_id),
        ("outbound", 9, 10, 20, batches[0].batch_id),
        ("adjustment", -1, 8, 7, batches[0].batch_id),
        ("return", 1, 7, 8, batches[0].batch_id),
        ("outbound", 1, 3, 2, foreign_batch.batch_id),
    ):
        db_session.add(
            PharmaceuticalStockLedger(
                pharmaceutical_id=drug.pharmaceutical_id,
                batch_id=batch_id,
                transaction_type=kind,
                quantity=quantity,
                before_stock=before,
                after_stock=after,
                reference_id="sensitive-prescription-ref",
                reference_type="prescription",
                operator_id=seed_data["pharmacist_user"].user_id,
                reason=seed_data["patient"].identity,
                create_time=now,
            )
        )
    for action in ("out", "use"):
        db_session.add(
            ConsumableTrace(
                consumable_id=consumable.consumable_id,
                batch_no="trace-test",
                action=action,
                quantity=2,
                patient_id=seed_data["patient"].patient_id,
                operator_id=seed_data["pharmacist_user"].user_id,
                action_time=now,
                remark="sensitive-trace-remark",
            )
        )
    purchase = PurchaseOrder(order_no=uuid.uuid4().hex, status=2, create_by=seed_data["pharmacist_user"].user_id, create_time=now)
    db_session.add(purchase)
    db_session.flush()
    db_session.add(PurchaseOrderItem(purchase_id=purchase.purchase_id, item_type="drug", item_id_ref=drug.pharmaceutical_id, item_name=drug.name, quantity=10, received_quantity=None))
    db_session.commit()
    return drug, batches, consumable, other_drug


def snapshot(db_session, seed_data, inventory_case, *, user=None, **extra):
    drug, _, consumable, _ = inventory_case
    values = {"drug_ids": [drug.pharmaceutical_id], "consumable_ids": [consumable.consumable_id], **extra}
    return operational_context(db_session, user or seed_data["pharmacist_user"], FEATURE_BY_KEY["inventory_optimization"], values)


def test_quantity_signs_invalid_links_and_trace_actions_remain_separate(seed_data, db_session, inventory_case):
    bundle = snapshot(db_session, seed_data, inventory_case)
    data = bundle.data["supply_inventory"]
    assert data["drugs"][0]["catalog_matches_batch_sum"] is True
    assert data["drugs"][0]["stock_count_unit"] is None
    assert data["batch_rows"][0]["expiry_before_business_date"] is True
    assert data["batch_rows"][1]["expiry_before_business_date"] is None
    assert data["batch_rows"][1]["status"] == 1
    ledger = data["drug_ledger_daily"]
    outbound = next(dict(zip(ledger["columns"], row)) for row in ledger["rows"] if row[2] == "outbound")
    assert outbound["raw_quantity_sum"] == 11
    assert outbound["recorded_stock_delta_sum"] == 8
    assert outbound["record_count"] == 2
    assert outbound["consistent_quantity_delta_count"] == 1
    assert data["loaded_quantity_delta_mismatch_count"] == 1
    adjustment = next(row for row in ledger["rows"] if row[2] == "adjustment")
    assert adjustment[4:6] == [-1, -1]
    assert data["excluded_inconsistent_ledger_links"] == 1
    assert {row[2] for row in data["consumable_trace_daily"]["rows"]} == {"out", "use"}
    assert data["purchase_lines"][0]["received_quantity"] is None
    for value in ("sensitive-prescription-ref", "sensitive-trace-remark", seed_data["patient"].identity):
        assert value not in encode_json({"context": bundle.data, "evidence": bundle.evidence})


def test_no_batches_is_unknown_and_current_stock_changes_do_not_write_back(seed_data, db_session, inventory_case):
    drug, batches, _, _ = inventory_case
    db_session.query(PharmaceuticalStockLedger).filter_by(pharmaceutical_id=drug.pharmaceutical_id).delete()
    for batch in batches:
        db_session.delete(batch)
    drug.stock = None
    db_session.commit()
    bundle = snapshot(db_session, seed_data, inventory_case)
    row = bundle.data["supply_inventory"]["drugs"][0]
    assert row["recorded_batch_count"] == 0
    assert row["all_batch_stock_sum"] is None
    assert row["catalog_stock"] is None
    assert row["catalog_matches_batch_sum"] is None
    db_session.refresh(drug)
    assert drug.stock is None


def test_director_does_not_receive_global_inventory_without_department_ownership(seed_data, db_session, inventory_case):
    bundle = snapshot(db_session, seed_data, inventory_case, user=seed_data["director_user"])
    assert "supply_inventory" not in bundle.data
    assert any("未保存可核实的科室归属" in value for value in bundle.data["missing_data"])
    with pytest.raises(HTTPException) as denied:
        operational_context(db_session, seed_data["pharmacist_user"], FEATURE_BY_KEY["operations_qa"], {})
    assert denied.value.status_code == 403


def test_item_selection_is_explicit_typed_and_bounded():
    for values in ({"drug_ids": [True]}, {"consumable_ids": ["1"]}, {"drug_ids": list(range(1, 22))}, {"drug_ids": "1"}):
        with pytest.raises(HTTPException) as invalid:
            inventory_selection(values)
        assert invalid.value.status_code == 422


@pytest.mark.asyncio
async def test_pharmacist_can_preview_selected_inventory_without_loading_hospital_or_patient_history(async_client, seed_data, db_session, auth_headers, inventory_case):
    headers = auth_headers(seed_data["pharmacist_user"].username)
    options = await async_client.get("/api/ai/service-options", headers=headers, params={"feature_key": "inventory_optimization"})
    assert options.status_code == 200, options.text
    assert options.json()["data"]["departments"] == []
    assert options.json()["data"]["inventory_scope_available"] is True
    drug = inventory_case[0]
    response = await async_client.post("/api/ai/operational-context", headers=headers, json={"feature_key": "inventory_optimization", "input": {"drug_ids": [drug.pharmaceutical_id]}})
    assert response.status_code == 200, response.text
    context = response.json()["data"]["context"]
    assert context["source_domain"] == "inventory"
    assert "saved_daily_metrics" not in context
    assert "outpatient_records" not in context
    assert "patient_id" not in context
    invalid = await async_client.post("/api/ai/operational-context", headers=headers, json={"feature_key": "inventory_optimization", "patient_id": seed_data["patient"].patient_id})
    assert invalid.status_code == 422
    assert db_session.query(AIRun).count() == 0


@pytest.mark.asyncio
async def test_inventory_change_while_queued_stops_specialist_inference(seed_data, db_session, inventory_case):
    key = "inventory_optimization"
    provider = AIProvider(
        name="inventory-test-" + uuid.uuid4().hex[:8],
        kind="specialist",
        api_base="http://localhost:11434",
        model="isolated-test-adapter",
        supported_features_json=encode_json([key]),
        validation_report="仅隔离契约测试，不代表真实优化已验证",
        enabled=1,
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key=key, provider_id=provider.provider_id, enabled=1, allowed_roles_json=encode_json(FEATURE_BY_KEY[key].default_roles), updated_by=seed_data["super_admin_user"].user_id
        )
    )
    db_session.commit()
    with pytest.raises(HTTPException) as missing:
        create_run(db_session, seed_data["pharmacist_user"], RunRequest(feature_key=key))
    assert missing.value.status_code == 409
    drug, batches, _, _ = inventory_case
    run = create_run(db_session, seed_data["pharmacist_user"], RunRequest(feature_key=key, input={"drug_ids": [drug.pharmaceutical_id]}))
    batches[0].stock += 1
    db_session.commit()
    calls = []
    claim = claim_next_run(db_session)
    await execute_claimed(*claim, transport=httpx.MockTransport(lambda request: (calls.append(request), httpx.Response(500))[1]))
    db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_code == "TASK_OPERATIONAL_CONTEXT_CHANGED"
    assert calls == []
