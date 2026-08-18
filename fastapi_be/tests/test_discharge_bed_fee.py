"""出院床位费按天补记回归测试。"""
import datetime

import pytest

from app.models import Admission, Bed, InpatientCharge, Ward


@pytest.mark.asyncio
class TestBedFeeTopUp:
    async def test_discharge_tops_up_bed_fee_by_days(self, async_client, seed_data, auth_headers, db_session):
        """住院 3 天出院：入院收首日 1 天，出院应补记 2 天。"""
        ward = Ward(name="补记病区", status=0)
        db_session.add(ward)
        db_session.flush()
        bed = Bed(ward_id=ward.ward_id, bed_no="TOP1", bed_type="普通", price_per_day=100, status=0)
        db_session.add(bed)
        db_session.flush()
        admission = Admission(
            admission_no="ZY-TOP-1",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            bed_id=bed.bed_id,
            admission_time=datetime.datetime.now() - datetime.timedelta(days=2, hours=1),  # 3 天
            status=1,
            deposit_amount=1000,
            create_time=datetime.datetime.now(),
        )
        db_session.add(admission)
        db_session.flush()
        bed.status = 1
        # 模拟入院时收的首日床位费
        db_session.add(InpatientCharge(
            admission_id=admission.admission_id,
            patient_id=seed_data["patient"].patient_id,
            item_name="床位费(普通)",
            item_type="bed",
            quantity=1,
            unit_price=100,
            total_amount=100,
            charge_date=datetime.date.today(),
            status=0,
            create_time=datetime.datetime.now(),
        ))
        db_session.commit()

        r = await async_client.post(
            "/api/discharge/doDischarge",
            headers=auth_headers(seed_data["nurse_user"].username),
            json={"admission_id": admission.admission_id, "discharge_diagnosis": "痊愈"},
        )
        assert r.json()["code"] == 200, r.json()
        total = r.json()["data"]["total_amount"]
        assert total == 300, f"3 天床位费应为 300（首日 100 + 补记 200），实际 {total}"
        top_up = (
            db_session.query(InpatientCharge)
            .filter(InpatientCharge.admission_id == admission.admission_id, InpatientCharge.item_name.like("%补记%"))
            .first()
        )
        assert top_up is not None and top_up.quantity == 2
        assert float(top_up.total_amount) == 200
