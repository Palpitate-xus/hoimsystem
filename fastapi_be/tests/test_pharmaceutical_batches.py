import datetime
from decimal import Decimal

import pytest

from app.models import PharmaceuticalBatch, PharmaceuticalStockLedger, PurchaseOrder


@pytest.mark.asyncio
class TestPharmaceuticalBatches:
    async def test_purchase_storage_creates_batch_and_ledger(self, async_client, seed_data, auth_headers, db_session):
        admin_headers = auth_headers(seed_data["admin_user"].username)
        pharmacist_headers = auth_headers(seed_data["pharmacist_user"].username)
        pharmaceutical_id = seed_data["pharmaceutical"].pharmaceutical_id
        expiry_date = (datetime.date.today() + datetime.timedelta(days=180)).isoformat()

        created = await async_client.post(
            "/api/purchase/create",
            headers=admin_headers,
            json={
                "supplier": "批次供应商",
                "items": [{
                    "item_type": "drug",
                    "item_id_ref": pharmaceutical_id,
                    "item_name": "阿司匹林",
                    "quantity": 12,
                    "unit_price": "15.55",
                    "batch_no": "BATCH-2026-01",
                    "expiry_date": expiry_date,
                    "location": "A-01-02",
                }],
            },
        )
        assert created.json()["code"] == 200
        order = db_session.query(PurchaseOrder).filter(PurchaseOrder.order_no == created.json()["data"]["order_no"]).one()
        assert order.total_amount == Decimal("186.60")

        assert (await async_client.post("/api/purchase/approve", headers=admin_headers, json={"purchase_id": order.purchase_id})).json()["code"] == 200
        stored = await async_client.post("/api/purchase/storage", headers=admin_headers, json={"purchase_id": order.purchase_id})
        assert stored.json()["code"] == 200

        batch = db_session.query(PharmaceuticalBatch).filter(
            PharmaceuticalBatch.pharmaceutical_id == pharmaceutical_id,
            PharmaceuticalBatch.batch_no == "BATCH-2026-01",
        ).one()
        assert batch.stock == 12
        assert batch.expiry_date.isoformat() == expiry_date
        assert batch.location == "A-01-02"
        ledger = db_session.query(PharmaceuticalStockLedger).filter(
            PharmaceuticalStockLedger.batch_id == batch.batch_id,
            PharmaceuticalStockLedger.reference_id == str(order.purchase_id),
        ).one()
        assert (ledger.transaction_type, ledger.quantity, ledger.before_stock, ledger.after_stock) == ("inbound", 12, 0, 12)
        db_session.refresh(seed_data["pharmaceutical"])
        assert seed_data["pharmaceutical"].stock == 112

        listed = await async_client.get("/api/pharmacy/batch/list", headers=pharmacist_headers, params={"pharmaceutical_id": pharmaceutical_id})
        assert listed.json()["code"] == 200
        assert listed.json()["data"] == [{
            "batch_id": batch.batch_id,
            "pharmaceutical_id": pharmaceutical_id,
            "pharmaceutical_name": "阿司匹林",
            "batch_no": "BATCH-2026-01",
            "expiry_date": expiry_date,
            "stock": 12,
            "location": "A-01-02",
            "status": 0,
            "status_text": "在用",
        }]
        ledger_response = await async_client.get("/api/pharmacy/batch/ledger", headers=pharmacist_headers, params={"batch_id": batch.batch_id})
        assert ledger_response.json()["data"][0]["reference_id"] == str(order.purchase_id)

        duplicate = await async_client.post("/api/purchase/storage", headers=admin_headers, json={"purchase_id": order.purchase_id})
        assert duplicate.json()["code"] == 500
        db_session.expire_all()
        assert db_session.query(PharmaceuticalBatch).filter(PharmaceuticalBatch.batch_id == batch.batch_id).one().stock == 12
        assert db_session.query(PharmaceuticalStockLedger).filter(PharmaceuticalStockLedger.batch_id == batch.batch_id).count() == 1

    async def test_purchase_rejects_expired_batch(self, async_client, seed_data, auth_headers):
        response = await async_client.post(
            "/api/purchase/create",
            headers=auth_headers(seed_data["admin_user"].username),
            json={
                "supplier": "过期供应商",
                "items": [{
                    "item_type": "drug",
                    "item_id_ref": seed_data["pharmaceutical"].pharmaceutical_id,
                    "quantity": 1,
                    "unit_price": "1.00",
                    "batch_no": "EXPIRED-2026",
                    "expiry_date": (datetime.date.today() - datetime.timedelta(days=1)).isoformat(),
                }],
            },
        )
        assert response.json() == {"code": 500, "msg": "采购药品效期不能早于当前日期"}
