import pytest


@pytest.mark.asyncio
class TestPaymentFlow:
    async def test_payment_rejects_amount_mismatch(self, async_client, seed_data, auth_headers):
        r = await async_client.post(
            "/api/payment/create",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"charge_id": str(seed_data["charge"].charge_id), "channel": "wechat", "amount": 1},
        )
        assert r.status_code == 200
        assert r.json() == {"code": 500, "msg": "支付金额与收费金额不一致"}

    async def test_payment_rejects_duplicate_pending_order(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["patient_user"].username)
        payload = {"charge_id": str(seed_data["charge"].charge_id), "channel": "wechat", "amount": 31}
        first = await async_client.post("/api/payment/create", headers=headers, json=payload)
        assert first.status_code == 200
        assert first.json()["code"] == 200
        second = await async_client.post("/api/payment/create", headers=headers, json=payload)
        assert second.status_code == 200
        assert second.json() == {"code": 500, "msg": "该收费记录已有待支付订单"}

    async def test_mock_payment_notify_pays_charge_once(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["patient_user"].username)
        cashier_headers = auth_headers(seed_data["cashier_user"].username)
        created = await async_client.post(
            "/api/payment/create",
            headers=headers,
            json={"charge_id": str(seed_data["charge"].charge_id), "channel": "alipay", "amount": 31},
        )
        payment_no = created.json()["data"]["payment_no"]
        paid = await async_client.post(
            "/api/payment/mockNotify",
            headers=cashier_headers,
            json={"payment_no": payment_no},
        )
        assert paid.status_code == 200
        assert paid.json()["code"] == 200
        repeated = await async_client.post(
            "/api/payment/mockNotify",
            headers=cashier_headers,
            json={"payment_no": payment_no},
        )
        assert repeated.status_code == 200
        assert repeated.json() == {"code": 500, "msg": "支付单状态异常"}
