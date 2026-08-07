import datetime

import pytest

from app.models import Admission, InpatientCharge


@pytest.mark.asyncio
class TestInpatientChargeAudit:
    async def test_inpatient_charge_requires_auth_and_preserves_state_audit(
        self, async_client, seed_data, auth_headers, db_session
    ):
        admission = Admission(
            admission_no="ZY-AUDIT-001",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            admission_time=datetime.datetime.now(),
            deposit_amount=500,
            status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(admission)
        db_session.flush()
        pending = InpatientCharge(
            admission_id=admission.admission_id,
            patient_id=admission.patient_id,
            item_name="住院服务",
            item_type="service",
            quantity=1,
            unit_price=120,
            total_amount=120,
            charge_date=datetime.date.today(),
            status=0,
            create_time=datetime.datetime.now(),
        )
        already_settled = InpatientCharge(
            admission_id=admission.admission_id,
            patient_id=admission.patient_id,
            item_name="检查费",
            item_type="exam",
            quantity=1,
            unit_price=80,
            total_amount=80,
            charge_date=datetime.date.today(),
            status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add_all([pending, already_settled])
        db_session.commit()

        unauthenticated = await async_client.get("/api/inpatientCharge/getList")
        assert unauthenticated.status_code == 401
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        listed = await async_client.get(
            "/api/inpatientCharge/getList",
            headers=nurse_headers,
            params={"admission_id": admission.admission_id},
        )
        assert listed.json()["code"] == 200
        assert len(listed.json()["data"]) == 2

        cashier_headers = auth_headers(seed_data["cashier_user"].username)
        settled = await async_client.post(
            "/api/inpatientCharge/settle",
            headers=cashier_headers,
            json={"admission_id": admission.admission_id},
        )
        assert settled.json() == {"code": 200, "msg": "success", "data": {"settled_count": 1}}
        db_session.refresh(pending)
        assert pending.status == 1
        assert pending.settled_by == seed_data["cashier_user"].user_id
        assert pending.settled_time is not None

        repeated = await async_client.post(
            "/api/inpatientCharge/settle",
            headers=cashier_headers,
            json={"admission_id": admission.admission_id},
        )
        assert repeated.json() == {"code": 200, "msg": "success", "data": {"settled_count": 0}}

        refunded = await async_client.post(
            "/api/inpatientCharge/refund",
            headers=cashier_headers,
            json={"charge_id": pending.charge_id, "reason": "重复计费"},
        )
        assert refunded.json() == {"code": 200, "msg": "success"}
        db_session.refresh(pending)
        assert pending.status == 2
        assert pending.refunded_by == seed_data["cashier_user"].user_id
        assert pending.refunded_time is not None
        assert pending.refund_reason == "重复计费"

    async def test_inpatient_refund_rejects_unsettled_charge(self, async_client, seed_data, auth_headers, db_session):
        charge = InpatientCharge(
            patient_id=seed_data["patient"].patient_id,
            item_name="未结算项目",
            item_type="service",
            quantity=1,
            unit_price=10,
            total_amount=10,
            charge_date=datetime.date.today(),
            status=0,
            create_time=datetime.datetime.now(),
        )
        db_session.add(charge)
        db_session.commit()
        response = await async_client.post(
            "/api/inpatientCharge/refund",
            headers=auth_headers(seed_data["cashier_user"].username),
            json={"charge_id": charge.charge_id, "reason": "误计费"},
        )
        assert response.json() == {"code": 500, "msg": "未结算费用不可退费"}
        db_session.refresh(charge)
        assert charge.status == 0
