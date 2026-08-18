"""床位与入院状态守卫回归测试。

对应业务审计发现：
1. bed/update 允许把占用中(status=1)的床位直接改为空闲/禁用，造成
   "床位空闲但入院记录仍指向它"的脏数据，可被再次入院形成双占。
2. admission/update 允许把在院记录直接置为已出院(2)/已退院(3)，
   绕过 doDischarge 的费用结算、医嘱停止与出院小结生成。
"""
import datetime

import pytest
from fastapi import UploadFile  # noqa: F401

from app.models import Admission, Bed, Ward


@pytest.mark.asyncio
class TestBedStatusGuard:
    async def test_cannot_free_occupied_bed_via_update(self, async_client, seed_data, auth_headers, db_session):
        ward = Ward(name="守卫测试病区", status=0)
        db_session.add(ward)
        db_session.flush()
        bed = Bed(ward_id=ward.ward_id, bed_no="G01", bed_type="普通", price_per_day=50, status=1)
        db_session.add(bed)
        db_session.flush()
        admission = Admission(
            admission_no="ZY-GUARD-001",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            bed_id=bed.bed_id,
            ward_id=ward.ward_id,
            admission_time=datetime.datetime.now(),
            status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(admission)
        db_session.commit()

        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/bed/update",
            headers=headers,
            json={"bed_id": bed.bed_id, "status": 0},
        )
        assert r.json()["code"] == 500
        assert "占用" in r.json()["msg"]
        db_session.refresh(bed)
        assert bed.status == 1, "占用中的床位状态不应被修改"

    async def test_can_still_edit_occupied_bed_price(self, async_client, seed_data, auth_headers, db_session):
        """占用中床位允许改价格等属性，仅状态受保护。"""
        ward = Ward(name="守卫测试病区2", status=0)
        db_session.add(ward)
        db_session.flush()
        bed = Bed(ward_id=ward.ward_id, bed_no="G02", bed_type="普通", price_per_day=50, status=1)
        db_session.add(bed)
        db_session.commit()

        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/bed/update",
            headers=headers,
            json={"bed_id": bed.bed_id, "price_per_day": 80},
        )
        assert r.json()["code"] == 200
        db_session.refresh(bed)
        assert bed.status == 1
        assert float(bed.price_per_day) == 80

    async def test_free_bed_status_change_allowed(self, async_client, seed_data, auth_headers, db_session):
        ward = Ward(name="守卫测试病区3", status=0)
        db_session.add(ward)
        db_session.flush()
        bed = Bed(ward_id=ward.ward_id, bed_no="G03", bed_type="普通", price_per_day=50, status=0)
        db_session.add(bed)
        db_session.commit()

        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/bed/update",
            headers=headers,
            json={"bed_id": bed.bed_id, "status": 2},
        )
        assert r.json()["code"] == 200
        db_session.refresh(bed)
        assert bed.status == 2


@pytest.mark.asyncio
class TestAdmissionStatusGuard:
    async def test_cannot_discharge_via_admission_update(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(
            admission_no="ZY-GUARD-101",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            admission_time=datetime.datetime.now(),
            status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(admission)
        db_session.commit()

        headers = auth_headers(seed_data["nurse_user"].username)
        for bad_status in (2, 3):
            r = await async_client.post(
                "/api/admission/update",
                headers=headers,
                json={"admission_id": admission.admission_id, "status": bad_status},
            )
            assert r.json()["code"] == 500, f"status={bad_status} 不应允许直接修改"
            assert "出院" in r.json()["msg"]

        db_session.refresh(admission)
        assert admission.status == 1, "在院状态不应被绕过修改"

    async def test_transfer_bed_still_works(self, async_client, seed_data, auth_headers, db_session):
        """换床（bed_id 修改）不受状态守卫影响。"""
        ward = Ward(name="换床测试病区", status=0)
        db_session.add(ward)
        db_session.flush()
        bed1 = Bed(ward_id=ward.ward_id, bed_no="T01", bed_type="普通", price_per_day=50, status=1)
        bed2 = Bed(ward_id=ward.ward_id, bed_no="T02", bed_type="普通", price_per_day=50, status=0)
        db_session.add_all([bed1, bed2])
        db_session.flush()
        admission = Admission(
            admission_no="ZY-GUARD-102",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            bed_id=bed1.bed_id,
            ward_id=ward.ward_id,
            admission_time=datetime.datetime.now(),
            status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(admission)
        db_session.commit()

        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/admission/update",
            headers=headers,
            json={"admission_id": admission.admission_id, "bed_id": bed2.bed_id},
        )
        assert r.json()["code"] == 200
        db_session.refresh(bed1)
        db_session.refresh(bed2)
        db_session.refresh(admission)
        assert bed1.status == 0
        assert bed2.status == 1
        assert admission.bed_id == bed2.bed_id
