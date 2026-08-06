import pytest

from app.models import Charge, Registration


@pytest.mark.asyncio
class TestChargeManagement:
    async def test_window_registration_patient_lookup(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["cashier_user"].username)
        found = await async_client.get(
            "/api/windowRegistration/patient",
            headers=headers,
            params={"identity": seed_data["patient"].identity},
        )
        assert found.status_code == 200
        assert found.json()["data"]["name"] == seed_data["patient"].name

        missing = await async_client.get(
            "/api/windowRegistration/patient",
            headers=headers,
            params={"identity": "110101200001010000"},
        )
        assert missing.status_code == 200
        assert missing.json() == {"code": 500, "msg": "病人信息不存在，请先注册"}

    async def test_window_registration_schedules_return_individual_slots(self, async_client, seed_data, auth_headers):
        r = await async_client.get(
            "/api/windowRegistration/schedules",
            headers=auth_headers(seed_data["cashier_user"].username),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert body["data"]
        assert {"schedule_id", "doctor_id", "department_id", "specialist", "number"}.issubset(body["data"][0])

    async def test_get_list_admin(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/chargeManagement/getList", headers=auth_headers(seed_data["admin_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1

    async def test_get_list_patient(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/chargeManagement/getList", headers=auth_headers(seed_data["patient_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200

    async def test_get_list_requires_auth(self, async_client, seed_data):
        r = await async_client.get("/api/chargeManagement/getList")
        assert r.status_code == 401

    async def test_charge_commit(self, async_client, seed_data, auth_headers):
        charge = seed_data["charge"]
        r = await async_client.post("/api/chargeManagement/charge", headers=auth_headers(seed_data["cashier_user"].username), json={"id": str(charge.charge_id)})
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_charge_commit_rejects_duplicate(self, async_client, seed_data, auth_headers):
        charge = seed_data["charge"]
        headers = auth_headers(seed_data["cashier_user"].username)
        payload = {"id": str(charge.charge_id)}

        first = await async_client.post("/api/chargeManagement/charge", headers=headers, json=payload)
        assert first.json()["code"] == 200

        second = await async_client.post("/api/chargeManagement/charge", headers=headers, json=payload)
        assert second.status_code == 200
        assert second.json() == {"code": 500, "msg": "该收费记录已缴费，不能重复收费"}

    async def test_charge_commit_rejects_missing_record(self, async_client, seed_data, auth_headers):
        r = await async_client.post(
            "/api/chargeManagement/charge",
            headers=auth_headers(seed_data["cashier_user"].username),
            json={"id": "missing-charge"},
        )
        assert r.status_code == 200
        assert r.json() == {"code": 500, "msg": "收费记录不存在"}

    async def test_charge_commit_rejects_patient(self, async_client, seed_data, auth_headers):
        charge = seed_data["charge"]
        r = await async_client.post("/api/chargeManagement/charge", headers=auth_headers(seed_data["patient_user"].username), json={"id": str(charge.charge_id)})
        assert r.status_code == 403

    async def test_refund(self, async_client, seed_data, auth_headers):
        # charge first, then refund
        charge = seed_data["charge"]
        headers = auth_headers(seed_data["cashier_user"].username)
        r = await async_client.post("/api/chargeManagement/charge", headers=headers, json={"id": str(charge.charge_id)})
        assert r.json()["code"] == 200

        r = await async_client.post("/api/chargeManagement/refund", json={
            "charge_id": str(charge.charge_id), "reason": "重复收费"
        }, headers=headers)
        assert r.status_code == 200
        assert r.json()["code"] == 200

        r = await async_client.post("/api/chargeManagement/charge", headers=headers, json={"id": str(charge.charge_id)})
        assert r.status_code == 200
        assert r.json() == {"code": 500, "msg": "该收费记录状态不允许收费"}

    async def test_refund_rejects_unpaid_charge(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["cashier_user"].username)
        r = await async_client.post(
            "/api/chargeManagement/refund",
            headers=headers,
            json={"charge_id": str(seed_data["charge"].charge_id), "reason": "误操作"},
        )
        assert r.status_code == 200
        assert r.json() == {"code": 500, "msg": "未缴费或已退费，无法退费"}

    async def test_refund_rejects_invalid_charge_amount(self, async_client, seed_data, auth_headers, db_session):
        headers = auth_headers(seed_data["cashier_user"].username)
        invalid_charge = Charge(
            charge_time=seed_data["charge"].charge_time,
            prescription_id=seed_data["prescription"].prescription_id,
            amount=0,
            status=1,
        )
        db_session.add(invalid_charge)
        db_session.commit()

        r = await async_client.post(
            "/api/chargeManagement/refund",
            headers=headers,
            json={"charge_id": str(invalid_charge.charge_id), "reason": "金额异常"},
        )
        assert r.status_code == 200
        assert r.json() == {"code": 500, "msg": "收费金额非法，无法退费"}
        db_session.refresh(invalid_charge)
        assert invalid_charge.status == 1

    async def test_refund_rejects_duplicate_refund(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["cashier_user"].username)
        payload = {"charge_id": str(seed_data["charge"].charge_id), "reason": "重复收费"}

        await async_client.post(
            "/api/chargeManagement/charge",
            headers=headers,
            json={"id": str(seed_data["charge"].charge_id)},
        )
        first = await async_client.post("/api/chargeManagement/refund", headers=headers, json=payload)
        assert first.status_code == 200
        assert first.json() == {"code": 200, "msg": "success"}

        second = await async_client.post("/api/chargeManagement/refund", headers=headers, json=payload)
        assert second.status_code == 200
        assert second.json() == {"code": 500, "msg": "未缴费或已退费，无法退费"}

    async def test_window_registration_rejects_invalid_schedule(self, async_client, seed_data, auth_headers):
        r = await async_client.post(
            "/api/windowRegistration/create",
            headers=auth_headers(seed_data["cashier_user"].username),
            json={
                "identity": seed_data["patient"].identity,
                "schedule_id": 999999,
                "doctor_id": seed_data["doctor"].doctor_id,
                "department_id": seed_data["department"].department_id,
                "specialist": 1,
            },
        )
        assert r.status_code == 200
        assert r.json() == {"code": 500, "msg": "排班不存在"}

    async def test_window_registration_rejects_mismatched_schedule_and_duplicate(self, async_client, seed_data, auth_headers, db_session):
        schedule = db_session.query(type(seed_data["doctor"].schedules[0])).filter_by(doctor_id=seed_data["doctor"].doctor_id).first()
        headers = auth_headers(seed_data["cashier_user"].username)
        mismatch = await async_client.post(
            "/api/windowRegistration/create",
            headers=headers,
            json={
                "identity": seed_data["patient"].identity,
                "schedule_id": schedule.schedule_id,
                "doctor_id": seed_data["director_doctor"].doctor_id,
                "department_id": seed_data["department"].department_id,
                "specialist": schedule.specialist,
            },
        )
        assert mismatch.json() == {"code": 500, "msg": "预约医生与排班不匹配"}

        first = await async_client.post(
            "/api/windowRegistration/create",
            headers=headers,
            json={
                "identity": seed_data["patient"].identity,
                "schedule_id": schedule.schedule_id,
                "doctor_id": schedule.doctor_id,
                "department_id": seed_data["department"].department_id,
                "specialist": schedule.specialist,
            },
        )
        assert first.json()["code"] == 200
        second = await async_client.post(
            "/api/windowRegistration/create",
            headers=headers,
            json={
                "identity": seed_data["patient"].identity,
                "schedule_id": schedule.schedule_id,
                "doctor_id": schedule.doctor_id,
                "department_id": seed_data["department"].department_id,
                "specialist": schedule.specialist,
            },
        )
        assert second.json() == {"code": 500, "msg": "该患者已存在同一医生的有效挂号"}


@pytest.mark.asyncio
class TestInvoice:
    async def test_get_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/invoice/getList", headers=auth_headers(seed_data["cashier_user"].username))
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_create_invoice(self, async_client, seed_data, auth_headers):
        charge = seed_data["charge"]
        headers = auth_headers(seed_data["cashier_user"].username)
        r = await async_client.post("/api/invoice/create", headers=headers, json={"charge_id": str(charge.charge_id)})
        assert r.status_code == 200
        assert r.json() == {"code": 500, "msg": "收费记录未缴费，无法开具发票"}

        r = await async_client.post("/api/chargeManagement/charge", headers=headers, json={"id": str(charge.charge_id)})
        assert r.json()["code"] == 200
        r = await async_client.post("/api/invoice/create", headers=headers, json={"charge_id": str(charge.charge_id)})
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "invoice_no" in body["data"]

    async def test_create_invoice_rejects_duplicate(self, async_client, seed_data, auth_headers):
        charge = seed_data["charge"]
        headers = auth_headers(seed_data["cashier_user"].username)
        payload = {"charge_id": str(charge.charge_id)}

        paid = await async_client.post("/api/chargeManagement/charge", headers=headers, json={"id": str(charge.charge_id)})
        assert paid.json()["code"] == 200
        first = await async_client.post("/api/invoice/create", headers=headers, json=payload)
        assert first.json()["code"] == 200

        second = await async_client.post("/api/invoice/create", headers=headers, json=payload)
        assert second.status_code == 200
        assert second.json() == {"code": 500, "msg": "该收费记录已开具发票，不能重复开票"}

    async def test_print_invoice(self, async_client, seed_data, auth_headers):
        # create invoice first
        charge = seed_data["charge"]
        headers = auth_headers(seed_data["cashier_user"].username)
        r = await async_client.post("/api/chargeManagement/charge", headers=headers, json={"id": str(charge.charge_id)})
        assert r.json()["code"] == 200
        r = await async_client.post("/api/invoice/create", headers=headers, json={"charge_id": str(charge.charge_id)})
        invoice_id = None
        r = await async_client.get("/api/invoice/getList", headers=headers)
        for inv in r.json()["data"]:
            if inv["charge_id"] == str(charge.charge_id):
                invoice_id = inv["id"]
                break
        if invoice_id:
            r = await async_client.post("/api/invoice/print", headers=headers, json={"invoice_id": invoice_id})
            assert r.status_code == 200
            body = r.json()
            assert body["code"] == 200
            assert "pdf_url" in body["data"]
