import datetime

import pytest

from app.models import Pharmaceutical


@pytest.mark.asyncio
class TestSkinTest:
    async def test_skin_test_lifecycle(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        created = await async_client.post(
            "/api/skinTest/create",
            headers=doctor_headers,
            json={"patient_id": seed_data["patient"].patient_id, "pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "dose": "0.1ml", "site": "左前臂"},
        )
        assert created.json()["code"] == 200
        skin_test_id = created.json()["data"]["skin_test_id"]
        assert (await async_client.post("/api/skinTest/administer", headers=nurse_headers, json={"skin_test_id": skin_test_id})).json()["code"] == 200
        assert (await async_client.post("/api/skinTest/assess", headers=nurse_headers, json={"skin_test_id": skin_test_id, "result": "negative", "note": "未见红晕"})).json()["code"] == 200
        listed = await async_client.get("/api/skinTest/list", headers=nurse_headers)
        item = next(row for row in listed.json()["data"] if row["skin_test_id"] == skin_test_id)
        assert item["status"] == 2
        assert item["result_note"] == "未见红晕"

    async def test_skin_test_validates_result_and_executor(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        created = await async_client.post(
            "/api/skinTest/create",
            headers=doctor_headers,
            json={"patient_id": seed_data["patient"].patient_id, "pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "dose": "0.1ml", "site": "右前臂"},
        )
        skin_test_id = created.json()["data"]["skin_test_id"]
        invalid = await async_client.post("/api/skinTest/assess", headers=nurse_headers, json={"skin_test_id": skin_test_id, "result": "unknown"})
        assert invalid.json()["code"] == 500
        assert (await async_client.post("/api/skinTest/administer", headers=nurse_headers, json={"skin_test_id": skin_test_id})).json()["code"] == 200
        forbidden_executor = await async_client.post("/api/skinTest/assess", headers=auth_headers(seed_data["admin_user"].username), json={"skin_test_id": skin_test_id, "result": "positive"})
        assert forbidden_executor.json()["code"] == 500

    async def test_skin_test_rejects_inactive_medication(self, async_client, seed_data, auth_headers, db_session):
        inactive = Pharmaceutical(name="皮试停用药", stock=10, price=1, expireddate=datetime.date.today() + datetime.timedelta(days=30), status=1)
        db_session.add(inactive)
        db_session.commit()
        response = await async_client.post("/api/skinTest/create", headers=auth_headers(seed_data["doctor_user"].username), json={
            "patient_id": seed_data["patient"].patient_id,
            "pharmaceutical_id": inactive.pharmaceutical_id,
            "dose": "0.1ml",
            "site": "左前臂",
        })
        assert response.json()["code"] == 500
        assert "停用" in response.json()["msg"]
