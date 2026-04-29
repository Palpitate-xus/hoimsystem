import pytest


@pytest.mark.asyncio
class TestChargeManagement:
    async def test_get_list_admin(self, async_client, seed_data):
        r = await async_client.get("/api/chargeManagement/getList", headers={"accesstoken": seed_data["admin_user"].username})
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1

    async def test_get_list_patient(self, async_client, seed_data):
        r = await async_client.get("/api/chargeManagement/getList", headers={"accesstoken": seed_data["patient_user"].username})
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200

    async def test_charge_commit(self, async_client, seed_data):
        charge = seed_data["charge"]
        r = await async_client.post("/api/chargeManagement/charge", json={"id": str(charge.charge_id)})
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_refund(self, async_client, seed_data):
        # charge first, then refund
        charge = seed_data["charge"]
        r = await async_client.post("/api/chargeManagement/charge", json={"id": str(charge.charge_id)})
        assert r.json()["code"] == 200

        r = await async_client.post("/api/chargeManagement/refund", json={
            "charge_id": str(charge.charge_id), "reason": "重复收费"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200


@pytest.mark.asyncio
class TestInvoice:
    async def test_get_list(self, async_client, seed_data):
        r = await async_client.get("/api/invoice/getList")
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_create_invoice(self, async_client, seed_data):
        charge = seed_data["charge"]
        r = await async_client.post("/api/invoice/create", json={"charge_id": str(charge.charge_id)})
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "invoice_no" in body["data"]

    async def test_print_invoice(self, async_client, seed_data):
        # create invoice first
        charge = seed_data["charge"]
        r = await async_client.post("/api/invoice/create", json={"charge_id": str(charge.charge_id)})
        invoice_id = None
        r = await async_client.get("/api/invoice/getList")
        for inv in r.json()["data"]:
            if inv["charge_id"] == str(charge.charge_id):
                invoice_id = inv["id"]
                break
        if invoice_id:
            r = await async_client.post("/api/invoice/print", json={"invoice_id": invoice_id})
            assert r.status_code == 200
            body = r.json()
            assert body["code"] == 200
            assert "pdf_url" in body["data"]
