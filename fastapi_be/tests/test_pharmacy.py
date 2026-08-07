import datetime

import pytest

from app.models import Pharmaceutical


@pytest.mark.asyncio
class TestPharmaceuticalManagement:
    async def test_get_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/pharmaceuticalManagement/getList", headers=auth_headers(seed_data["pharmacist_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1
        assert body["data"][0]["name"] == "阿司匹林"

    async def test_create(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post("/api/pharmaceuticalManagement/create", headers=headers, json={
            "name": "布洛芬", "stock": 200, "price": "20.0",
            "expireddate": "2028-01-01", "supplier": "测试供应商", "remark": "退烧药"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_update(self, async_client, seed_data, auth_headers):
        pha = seed_data["pharmaceutical"]
        headers = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post("/api/pharmaceuticalManagement/update", headers=headers, json={
            "pharmaceutical_id": pha.pharmaceutical_id, "name": "阿司匹林改",
            "stock": 150, "price": "18.0", "expireddate": "2027-12-01",
            "supplier": "新供应商", "remark": "备注改"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_delete(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post("/api/pharmaceuticalManagement/create", headers=headers, json={
            "name": "待删除药", "stock": 10, "price": "5.0",
            "expireddate": "2028-01-01", "supplier": "测试", "remark": ""
        })
        assert r.json()["code"] == 200
        r = await async_client.get("/api/pharmaceuticalManagement/getList", headers=headers)
        phas = r.json()["data"]
        target = [p for p in phas if p["name"] == "待删除药"][0]

        r = await async_client.post("/api/pharmaceuticalManagement/delete", headers=headers, json={"pharmaceutical_id": target["id"]})
        assert r.status_code == 200
        assert r.json()["code"] == 200
        listed = await async_client.get("/api/pharmaceuticalManagement/getList", headers=headers)
        deleted = next(item for item in listed.json()["data"] if item["id"] == target["id"])
        assert deleted["status"] == 1
        assert deleted["status_text"] == "已停用"
        repeated = await async_client.post("/api/pharmaceuticalManagement/delete", headers=headers, json={"pharmaceutical_id": target["id"]})
        assert repeated.json()["data"]["idempotent"] is True
        restored = await async_client.post("/api/pharmaceuticalManagement/restore", headers=headers, json={"pharmaceutical_id": target["id"]})
        assert restored.json()["code"] == 200
        restored_list = await async_client.get("/api/pharmaceuticalManagement/getList", headers=headers)
        restored_item = next(item for item in restored_list.json()["data"] if item["id"] == target["id"])
        assert restored_item["status"] == 0

    async def test_stock_query(self, async_client, seed_data, auth_headers):
        r = await async_client.post("/api/pharmaceuticalManagement/stock_query", headers=auth_headers(seed_data["pharmacist_user"].username), json={"id": seed_data["pharmaceutical"].pharmaceutical_id})
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "stock" in body["data"]

    async def test_stock_check_rejects_invalid_inventory_counts(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["pharmacist_user"].username)
        payload = {"items": [{"pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "actual_stock": -1}]}
        r = await async_client.post("/api/pharmacy/stockCheck", headers=headers, json=payload)
        assert r.status_code == 200
        assert r.json()["code"] == 500

        payload["items"][0]["actual_stock"] = 10.5
        r = await async_client.post("/api/pharmacy/stockCheck", headers=headers, json=payload)
        assert r.status_code == 200
        assert r.json()["code"] == 500

        duplicate = {
            "items": [
                {"pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "actual_stock": 10},
                {"pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "actual_stock": 11},
            ]
        }
        r = await async_client.post("/api/pharmacy/stockCheck", headers=headers, json=duplicate)
        assert r.status_code == 200
        assert r.json()["code"] == 500

    async def test_near_expiry_ignores_missing_dates_and_validates_range(self, async_client, seed_data, auth_headers, db_session):
        seed_data["pharmaceutical"].expireddate = None
        db_session.commit()
        headers = auth_headers(seed_data["pharmacist_user"].username)
        response = await async_client.get("/api/pharmaceuticalManagement/nearExpiry", headers=headers)
        assert response.status_code == 200
        assert response.json()["code"] == 200
        assert all(item["id"] != seed_data["pharmaceutical"].pharmaceutical_id for item in response.json()["data"])

        invalid = await async_client.get("/api/pharmaceuticalManagement/nearExpiry", headers=headers, params={"days": -1})
        assert invalid.status_code == 200
        assert invalid.json() == {"code": 400, "msg": "效期查询天数必须在0至3650之间"}

    async def test_prescription_cannot_use_expired_drug(self, async_client, seed_data, auth_headers, db_session):
        expired = Pharmaceutical(name="过期药", stock=10, price=1, expireddate=datetime.date.today() - datetime.timedelta(days=1), status=0)
        db_session.add(expired)
        db_session.commit()
        response = await async_client.post(
            "/api/prescriptionManagement/create",
            headers=auth_headers(seed_data["doctor_user"].username),
            json={"patient": seed_data["patient2"].patient_id, "phas": [{"id": expired.pharmaceutical_id, "number": 1}]},
        )
        assert response.status_code == 200
        assert response.json()["code"] == 500
        assert "过期" in response.json()["msg"]

    async def test_prescription_cannot_use_inactive_drug(self, async_client, seed_data, auth_headers, db_session):
        inactive = Pharmaceutical(name="停用药", stock=10, price=1, expireddate=datetime.date.today() + datetime.timedelta(days=30), status=1)
        db_session.add(inactive)
        db_session.commit()
        response = await async_client.post(
            "/api/prescriptionManagement/create",
            headers=auth_headers(seed_data["doctor_user"].username),
            json={"patient": seed_data["patient2"].patient_id, "phas": [{"id": inactive.pharmaceutical_id, "number": 1}]},
        )
        assert response.status_code == 200
        assert response.json()["code"] == 500
        assert "停用" in response.json()["msg"]


@pytest.mark.asyncio
class TestPharmacy:
    async def test_dispense_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/pharmacy/dispenseList", headers=auth_headers(seed_data["pharmacist_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1

    async def test_audit(self, async_client, seed_data, auth_headers):
        pre = seed_data["prescription"]
        headers = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post("/api/pharmacy/audit", headers=headers, json={"prescription_id": str(pre.prescription_id)})
        assert r.status_code == 200
        assert r.json()["code"] == 200

        # 审核是 0 -> 1 的单向状态迁移，重复审核必须失败。
        r = await async_client.post("/api/pharmacy/audit", headers=headers, json={"prescription_id": str(pre.prescription_id)})
        assert r.status_code == 200
        assert r.json()["code"] == 500


@pytest.mark.asyncio
class TestInventoryAdjustment:
    async def test_loss_requires_approval_and_updates_stock_atomically(self, async_client, seed_data, auth_headers, db_session):
        pharmacist_headers = auth_headers(seed_data["pharmacist_user"].username)
        admin_headers = auth_headers(seed_data["admin_user"].username)
        pha = seed_data["pharmaceutical"]
        initial_stock = pha.stock
        created = await async_client.post(
            "/api/pharmacy/inventoryAdjustment/create",
            headers=pharmacist_headers,
            json={"pharmaceutical_id": pha.pharmaceutical_id, "adjustment_type": "loss", "quantity": 3, "reason": "破损"},
        )
        assert created.status_code == 200
        adjustment_id = created.json()["data"]["adjustment_id"]
        db_session.refresh(pha)
        assert pha.stock == initial_stock

        approved = await async_client.post("/api/pharmacy/inventoryAdjustment/approve", headers=admin_headers, json={"adjustment_id": adjustment_id})
        assert approved.status_code == 200
        assert approved.json()["code"] == 200
        db_session.expire(pha)
        assert db_session.get(type(pha), pha.pharmaceutical_id).stock == initial_stock - 3

        duplicate = await async_client.post("/api/pharmacy/inventoryAdjustment/approve", headers=admin_headers, json={"adjustment_id": adjustment_id})
        assert duplicate.status_code == 200
        assert duplicate.json()["code"] == 500

    async def test_reject_keeps_stock_and_invalid_loss_is_blocked(self, async_client, seed_data, auth_headers, db_session):
        pharmacist_headers = auth_headers(seed_data["pharmacist_user"].username)
        admin_headers = auth_headers(seed_data["admin_user"].username)
        pha = seed_data["pharmaceutical"]
        initial_stock = pha.stock
        invalid = await async_client.post(
            "/api/pharmacy/inventoryAdjustment/create",
            headers=pharmacist_headers,
            json={"pharmaceutical_id": pha.pharmaceutical_id, "adjustment_type": "loss", "quantity": initial_stock + 1, "reason": "数量错误"},
        )
        adjustment_id = invalid.json()["data"]["adjustment_id"]
        rejected = await async_client.post("/api/pharmacy/inventoryAdjustment/reject", headers=admin_headers, json={"adjustment_id": adjustment_id})
        assert rejected.status_code == 200
        db_session.expire(pha)
        assert db_session.get(type(pha), pha.pharmaceutical_id).stock == initial_stock

        bad_type = await async_client.post(
            "/api/pharmacy/inventoryAdjustment/create",
            headers=pharmacist_headers,
            json={"pharmaceutical_id": pha.pharmaceutical_id, "adjustment_type": "unknown", "quantity": 1, "reason": "错误类型"},
        )
        assert bad_type.json()["code"] == 500

    async def test_dispense(self, async_client, seed_data, auth_headers):
        pharmacist_headers = auth_headers(seed_data["pharmacist_user"].username)
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        r = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json={
            "patient": seed_data["patient2"].patient_id,
            "phas": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 1}]
        })
        assert r.json()["code"] == 200
        r = await async_client.get("/api/prescriptionManagement/getList", headers=doctor_headers)
        pres = r.json()["data"]
        target = [p for p in pres if p["status"] == 0][0]

        r = await async_client.post("/api/pharmacy/audit", headers=pharmacist_headers, json={"prescription_id": target["uuid"]})
        assert r.json()["code"] == 200

        r = await async_client.post("/api/pharmacy/dispense", headers=pharmacist_headers, json={"prescription_id": target["uuid"]})
        assert r.status_code == 200
        assert r.json()["code"] == 200

        listed = await async_client.get(
            "/api/pharmacy/dispenseList",
            headers=auth_headers(seed_data["pharmacist_user"].username),
        )
        assert any(item["uuid"] == target["uuid"] and item["status"] == 2 for item in listed.json()["data"])

        # 发药是 1 -> 2 的单向状态迁移，重复发药必须失败。
        r = await async_client.post("/api/pharmacy/dispense", headers=pharmacist_headers, json={"prescription_id": target["uuid"]})
        assert r.status_code == 200
        assert r.json()["code"] == 500

    async def test_dispense_requires_nurse_verification(self, async_client, seed_data, auth_headers):
        pharmacist_headers = auth_headers(seed_data["pharmacist_user"].username)
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        created = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json={"patient": seed_data["patient2"].patient_id, "phas": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 1}]})
        prescription_id = created.json()["data"]["uuid"]
        assert (await async_client.post("/api/pharmacy/audit", headers=pharmacist_headers, json={"prescription_id": prescription_id})).json()["code"] == 200
        assert (await async_client.post("/api/pharmacy/dispense", headers=pharmacist_headers, json={"prescription_id": prescription_id})).json()["code"] == 200
        listed = await async_client.get("/api/pharmacy/verificationList", headers=nurse_headers)
        item = next(row for row in listed.json()["data"] if row["prescription_id"] == prescription_id)
        assert item["status"] == 0
        assert (await async_client.post("/api/pharmacy/verify", headers=nurse_headers, json={"verification_id": item["verification_id"], "note": "药品、剂量与处方一致"})).json()["code"] == 200
        assert (await async_client.post("/api/pharmacy/verify", headers=nurse_headers, json={"verification_id": item["verification_id"]})).json()["code"] == 500

    async def test_dispense_blocks_drug_that_expired_after_prescription(self, async_client, seed_data, auth_headers, db_session):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        pharmacist_headers = auth_headers(seed_data["pharmacist_user"].username)
        created = await async_client.post(
            "/api/prescriptionManagement/create",
            headers=doctor_headers,
            json={"patient": seed_data["patient2"].patient_id, "phas": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 1}]},
        )
        assert created.json()["code"] == 200
        prescription_id = created.json()["data"]["uuid"]
        seed_data["pharmaceutical"].expireddate = datetime.date.today() - datetime.timedelta(days=1)
        db_session.commit()
        assert (await async_client.post("/api/pharmacy/audit", headers=pharmacist_headers, json={"prescription_id": prescription_id})).json()["code"] == 200
        response = await async_client.post("/api/pharmacy/dispense", headers=pharmacist_headers, json={"prescription_id": prescription_id})
        assert response.status_code == 200
        assert response.json()["code"] == 400
        assert "过期" in response.json()["msg"]

    async def test_return_rejects_unreviewed_prescription(self, async_client, seed_data, auth_headers):
        r = await async_client.post("/api/pharmacy/return", headers=auth_headers(seed_data["pharmacist_user"].username), json={
            "prescription_id": str(seed_data["prescription"].prescription_id),
            "pha_id": seed_data["pharmaceutical"].pharmaceutical_id,
            "number": 1, "reason": "过敏"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 500

    async def test_return_rejects_audited_but_not_dispensed(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["pharmacist_user"].username)
        pre_id = str(seed_data["prescription"].prescription_id)
        r = await async_client.post("/api/pharmacy/audit", headers=headers, json={"prescription_id": pre_id})
        assert r.json()["code"] == 200

        r = await async_client.post("/api/pharmacy/return", headers=headers, json={
            "prescription_id": pre_id,
            "pha_id": seed_data["pharmaceutical"].pharmaceutical_id,
            "number": 1, "reason": "过敏"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 500

    async def test_return_and_reject_duplicate_return(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["pharmacist_user"].username)
        pre_id = str(seed_data["prescription"].prescription_id)
        pha_id = seed_data["pharmaceutical"].pharmaceutical_id

        for endpoint in ("audit", "dispense"):
            r = await async_client.post(f"/api/pharmacy/{endpoint}", headers=headers, json={"prescription_id": pre_id})
            assert r.json()["code"] == 200

        r = await async_client.post("/api/pharmacy/return", headers=auth_headers(seed_data["pharmacist_user"].username), json={
            "prescription_id": pre_id,
            "pha_id": pha_id,
            "number": 2, "reason": "过敏"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

        # 全量退药后处方进入已退药状态，不能再次退药。
        r = await async_client.post("/api/pharmacy/return", headers=headers, json={
            "prescription_id": pre_id,
            "pha_id": pha_id,
            "number": 1, "reason": "重复申请"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 500

    async def test_dispense_statistics_reports_dispensed_quantity(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        pharmacist_headers = auth_headers(seed_data["pharmacist_user"].username)
        created = await async_client.post(
            "/api/prescriptionManagement/create",
            headers=doctor_headers,
            json={"patient": seed_data["patient2"].patient_id, "phas": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 2}]},
        )
        prescription_id = created.json()["data"]["uuid"]
        await async_client.post("/api/pharmacy/audit", headers=pharmacist_headers, json={"prescription_id": prescription_id})
        await async_client.post("/api/pharmacy/dispense", headers=pharmacist_headers, json={"prescription_id": prescription_id})
        stats = await async_client.get("/api/pharmacy/dispenseStats", headers=pharmacist_headers)
        assert stats.status_code == 200
        body = stats.json()
        assert body["code"] == 200
        drug_stats = [item for item in body["data"]["by_drug"] if item["pharmaceutical_id"] == seed_data["pharmaceutical"].pharmaceutical_id]
        assert drug_stats and drug_stats[0]["quantity"] >= 2

    async def test_dispense_statistics_rejects_invalid_date(self, async_client, seed_data, auth_headers):
        response = await async_client.get("/api/pharmacy/dispenseStats", headers=auth_headers(seed_data["pharmacist_user"].username), params={"start_date": "bad"})
        assert response.status_code == 200
        assert response.json() == {"code": 500, "msg": "日期格式必须为 YYYY-MM-DD"}
