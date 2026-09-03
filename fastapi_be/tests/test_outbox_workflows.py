import pytest

from app.models import IntegrationOutbox


@pytest.mark.asyncio
async def test_lab_order_and_external_payment_stage_outbox_events(async_client, seed_data, auth_headers, db_session):
    doctor_headers = auth_headers(seed_data["doctor_user"].username)
    lab = await async_client.post(
        "/api/labOrder/create",
        headers=doctor_headers,
        json={
            "patient_id": seed_data["patient"].patient_id,
            "check_type": "血常规",
            "check_items": ["白细胞", "血红蛋白"],
            "urgent": 0,
        },
    )
    assert lab.status_code == 200
    lab_order_id = lab.json()["data"]["lab_order_id"]
    assert db_session.query(IntegrationOutbox).filter_by(
        destination="lis", aggregate_id=lab_order_id
    ).one().status == "pending"

    payment = await async_client.post(
        "/api/payment/create",
        headers=auth_headers(seed_data["patient_user"].username),
        json={
            "charge_id": seed_data["charge"].charge_id,
            "channel": "wechat",
            "amount": float(seed_data["charge"].amount),
        },
    )
    assert payment.status_code == 200
    payment_no = payment.json()["data"]["payment_no"]
    assert db_session.query(IntegrationOutbox).filter_by(
        destination="payment", aggregate_id=payment_no
    ).one().status == "pending"
