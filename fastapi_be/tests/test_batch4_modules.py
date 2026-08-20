"""第四批：ICD 编码工作台 + 围术期抗菌药依从 + 报损批次台账。"""
import datetime

import pytest

from app.models import Admission, SurgeryApplication, SurgerySchedule


@pytest.mark.asyncio
class TestHomeIcdWorkbench:
    async def test_icd_binding_flow(self, async_client, seed_data, auth_headers, db_session):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        director_headers = auth_headers(seed_data["director_user"].username)
        admission = Admission(
            admission_id="icd-admission", admission_no="ZYICD001",
            patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id,
            admission_diagnosis="肺炎", status=2,
            admission_time=datetime.datetime.now(), create_time=datetime.datetime.now())
        db_session.add(admission)
        db_session.commit()
        home = await async_client.post("/api/medicalRecordHome/create", headers=doctor_headers, json={
            "admission_id": admission.admission_id, "admission_diagnosis": "肺炎",
            "discharge_diagnosis": "细菌性肺炎", "other_diagnosis": "高血压"})
        home_id = home.json()["data"]["home_id"]
        await async_client.post("/api/medicalRecordHome/submit", headers=doctor_headers, json={"home_id": home_id})

        # 先维护字典（无预置数据，用户录入）
        assert (await async_client.post("/api/icd10/diagnosis/create", headers=director_headers, json={
            "code": "J15.900", "name": "细菌性肺炎", "category": "呼吸系统"})).json()["code"] == 200
        assert (await async_client.post("/api/icd10/diagnosis/create", headers=director_headers, json={
            "code": "I10.x00", "name": "原发性高血压", "category": "循环系统"})).json()["code"] == 200

        # 绑定主诊断 + 并发症诊断
        r = await async_client.post("/api/homeIcd/bind", headers=doctor_headers, json={
            "home_id": home_id, "kind": "diagnosis", "icd_code": "J15.900", "is_primary": True})
        assert r.json()["code"] == 200, r.json()
        r = await async_client.post("/api/homeIcd/bind", headers=doctor_headers, json={
            "home_id": home_id, "kind": "diagnosis", "icd_code": "I10.x00"})
        assert r.json()["code"] == 200

        # 重复绑定拒绝
        r = await async_client.post("/api/homeIcd/bind", headers=doctor_headers, json={
            "home_id": home_id, "kind": "diagnosis", "icd_code": "J15.900"})
        assert r.json()["code"] == 500
        # 字典外编码拒绝
        r = await async_client.post("/api/homeIcd/bind", headers=doctor_headers, json={
            "home_id": home_id, "kind": "diagnosis", "icd_code": "Z99.999"})
        assert r.json()["code"] == 500

        # 再设主诊断 → 旧主被清（主诊断唯一）
        bindings = (await async_client.get("/api/homeIcd/getList", headers=doctor_headers, params={"home_id": home_id})).json()["data"]
        second = [b for b in bindings if b["icd_code"] != "J15.900"][0]
        r = await async_client.post("/api/homeIcd/setPrimary", headers=doctor_headers, json={"binding_id": second["binding_id"]})
        assert r.json()["code"] == 200
        bindings = (await async_client.get("/api/homeIcd/getList", headers=doctor_headers, params={"home_id": home_id})).json()["data"]
        primaries = [b for b in bindings if b["is_primary"] == 1]
        assert len(primaries) == 1 and primaries[0]["binding_id"] == second["binding_id"]
        # 统计覆盖
        stats = (await async_client.get("/api/homeIcd/statistics", headers=doctor_headers)).json()["data"]
        assert stats["coded_homes"] >= 1 and stats["coverage_rate"] is not None

    async def test_uncoded_workbench(self, async_client, seed_data, auth_headers, db_session):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        admission = Admission(
            admission_id="icd-admission2", admission_no="ZYICD002",
            patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id,
            admission_diagnosis="阑尾炎", status=2,
            admission_time=datetime.datetime.now(), create_time=datetime.datetime.now())
        db_session.add(admission)
        db_session.commit()
        home = await async_client.post("/api/medicalRecordHome/create", headers=doctor_headers, json={
            "admission_id": admission.admission_id, "admission_diagnosis": "阑尾炎", "discharge_diagnosis": "急性阑尾炎"})
        submitted = await async_client.post("/api/medicalRecordHome/submit", headers=doctor_headers, json={"home_id": home.json()["data"]["home_id"]})
        assert submitted.json()["code"] == 200, submitted.json()

        r = await async_client.get("/api/homeIcd/uncoded", headers=doctor_headers)
        assert r.json()["code"] == 200
        assert any(a["admission_diagnosis"] == "阑尾炎" for a in r.json()["data"])


@pytest.mark.asyncio
class TestAntibioticCompliance:
    async def test_compliance_statistics(self, async_client, seed_data, auth_headers, db_session):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        start = datetime.datetime.now() - datetime.timedelta(hours=2)
        # 两台手术：一台术前 60min 给药（依从），一台术前 10min（过晚）
        for i, offset_min in enumerate((60, 10)):
            app_obj = SurgeryApplication(
                application_id=f"ab-comp{i}", admission_id=None,
                patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id,
                surgery_name=f"阑尾切除术{i}", surgery_level=2, status=3,
                create_time=datetime.datetime.now())
            db_session.add(app_obj)
            db_session.flush()
            db_session.add(SurgerySchedule(
                application_id=app_obj.application_id, patient_id=seed_data["patient"].patient_id,
                operating_room="1", surgery_date=start.date(), start_time=start, end_time=None,
                surgeon_id=seed_data["doctor"].doctor_id))
        db_session.commit()
        from app.models import PerioperativeAntibiotic

        for i, offset_min in enumerate((60, 10)):
            db_session.add(PerioperativeAntibiotic(
                application_id=f"ab-comp{i}", patient_id=seed_data["patient"].patient_id,
                pharmaceutical_id=seed_data["pharmaceutical"].pharmaceutical_id,
                prescriber_id=seed_data["doctor_user"].user_id, dose="1g",
                timing_minutes=offset_min, status=1,
                administered_time=start - datetime.timedelta(minutes=offset_min),
                create_time=datetime.datetime.now()))
        db_session.commit()

        r = await async_client.get("/api/surgery/antibioticCompliance", headers=doctor_headers)
        assert r.json()["code"] == 200, r.json()
        data = r.json()["data"]
        assert data["total_executed"] >= 2
        assert data["compliant"] >= 1
        assert data["too_late_lt30min"] >= 1
        assert data["compliance_rate"] is not None


@pytest.mark.asyncio
class TestScrapBatchLedger:
    async def test_loss_approval_deducts_batches(self, async_client, seed_data, auth_headers, db_session):
        from app.models import PharmaceuticalBatch, PharmaceuticalStockLedger

        pha = seed_data["pharmaceutical"]
        db_session.add(PharmaceuticalBatch(
            pharmaceutical_id=pha.pharmaceutical_id, batch_no="SCRAP-B1",
            expiry_date=datetime.date.today() + datetime.timedelta(days=10),
            stock=5, status=0, create_time=datetime.datetime.now(), update_time=datetime.datetime.now()))
        db_session.add(PharmaceuticalBatch(
            pharmaceutical_id=pha.pharmaceutical_id, batch_no="SCRAP-B2",
            expiry_date=datetime.date.today() + datetime.timedelta(days=100),
            stock=5, status=0, create_time=datetime.datetime.now(), update_time=datetime.datetime.now()))
        pha.stock = 10
        db_session.commit()

        pharm_headers = auth_headers(seed_data["pharmacist_user"].username)
        admin_headers = auth_headers("admin")
        r = await async_client.post("/api/pharmacy/inventoryAdjustment/create", headers=pharm_headers, json={
            "pharmaceutical_id": pha.pharmaceutical_id, "adjustment_type": "loss", "quantity": 7, "reason": "效期近报废"})
        assert r.json()["code"] == 200
        aid = r.json()["data"]["adjustment_id"]

        r = await async_client.post("/api/pharmacy/inventoryAdjustment/approve", headers=admin_headers, json={"adjustment_id": aid})
        assert r.json()["code"] == 200, r.json()

        db_session.expire_all()
        b1 = db_session.query(PharmaceuticalBatch).filter(PharmaceuticalBatch.batch_no == "SCRAP-B1").first()
        b2 = db_session.query(PharmaceuticalBatch).filter(PharmaceuticalBatch.batch_no == "SCRAP-B2").first()
        # FEFO：先扣近效期 B1 全部 5，再扣 B2 的 2
        assert b1.stock == 0 and b2.stock == 3
        assert pha.stock == 3
        ledgers = db_session.query(PharmaceuticalStockLedger).filter(
            PharmaceuticalStockLedger.reference_id == str(aid)).all()
        assert len(ledgers) == 2
        assert {row.quantity for row in ledgers} == {-5, -2}

        # 批次不足拒绝（总量够但批次不够：总量调到 10，批次仅剩 3）
        pha.stock = 10
        db_session.commit()
        r = await async_client.post("/api/pharmacy/inventoryAdjustment/create", headers=pharm_headers, json={
            "pharmaceutical_id": pha.pharmaceutical_id, "adjustment_type": "loss", "quantity": 5, "reason": "批次不足场景"})
        aid2 = r.json()["data"]["adjustment_id"]
        r = await async_client.post("/api/pharmacy/inventoryAdjustment/approve", headers=admin_headers, json={"adjustment_id": aid2})
        assert r.json()["code"] == 500
        assert "批次库存不足" in r.json()["msg"]


@pytest.mark.asyncio
class TestVersionEndpoint:
    async def test_public_version(self, async_client):
        """版本端点公开可访问，返回语义化版本与环境。"""
        r = await async_client.get("/api/version")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["version"] == "2.0.0"
        assert "environment" in data
