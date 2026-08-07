import pytest

from app.config import settings
from app.models import Charge, Payment


@pytest.mark.asyncio
class TestPaymentIntegration:
    async def test_payment_callback_is_authenticated_and_idempotent(self, async_client, seed_data, auth_headers, db_session, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_INTEGRATION_KEY", "payment-secret")
        created = await async_client.post(
            "/api/payment/create",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"charge_id": str(seed_data["charge"].charge_id), "channel": "wechat", "amount": 31},
        )
        assert created.json()["code"] == 200
        payment_no = created.json()["data"]["payment_no"]
        payload = {
            "payment_no": payment_no,
            "external_payment_id": "WX-20260810-001",
            "status": 1,
            "amount": 31,
        }
        denied = await async_client.post(
            "/api/integration/payment/notify",
            headers={"X-Integration-Key": "bad"},
            json=payload,
        )
        assert denied.status_code == 401
        synced = await async_client.post(
            "/api/integration/payment/notify",
            headers={"X-Integration-Key": "payment-secret"},
            json=payload,
        )
        assert synced.status_code == 200
        assert synced.json()["data"]["idempotent"] is False
        duplicate = await async_client.post(
            "/api/integration/payment/notify",
            headers={"X-Integration-Key": "payment-secret"},
            json=payload,
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["data"]["idempotent"] is True
        db_session.expire_all()
        payment = db_session.query(Payment).filter(Payment.payment_no == payment_no).one()
        charge = db_session.query(Charge).filter(Charge.charge_id == seed_data["charge"].charge_id).one()
        assert payment.status == 1
        assert payment.integration_status == "synced"
        assert charge.status == 1

    async def test_payment_callback_rejects_amount_mismatch(self, async_client, seed_data, auth_headers, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_INTEGRATION_KEY", "payment-secret")
        created = await async_client.post(
            "/api/payment/create",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"charge_id": str(seed_data["charge"].charge_id), "channel": "alipay", "amount": 31},
        )
        payment_no = created.json()["data"]["payment_no"]
        response = await async_client.post(
            "/api/integration/payment/notify",
            headers={"X-Integration-Key": "payment-secret"},
            json={"payment_no": payment_no, "status": 1, "amount": 30.99},
        )
        assert response.status_code == 400
        assert "金额" in response.json()["detail"]
