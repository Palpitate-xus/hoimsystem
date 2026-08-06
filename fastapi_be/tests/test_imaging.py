import pytest

from app.models import ImagingOrder


@pytest.mark.asyncio
class TestImaging:
    async def test_imaging_order_report_and_review_flow(self, async_client, seed_data, auth_headers, db_session):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        created = await async_client.post(
            "/api/imaging/order/create",
            headers=doctor_headers,
            json={"patient_id": seed_data["patient"].patient_id, "modality": "CT", "body_part": "胸部", "clinical_diagnosis": "咳嗽"},
        )
        assert created.json()["code"] == 200
        order_id = created.json()["data"]["imaging_order_id"]
        saved = await async_client.post(
            "/api/imaging/report/save",
            headers=auth_headers(seed_data["lab_tech_user"].username),
            json={"imaging_order_id": order_id, "findings": "未见明显异常", "impression": "胸部CT未见明显异常"},
        )
        assert saved.json()["code"] == 200
        report_id = saved.json()["data"]["report_id"]
        submitted = await async_client.post("/api/imaging/report/submit", headers=doctor_headers, json={"report_id": report_id})
        assert submitted.json()["code"] == 200
        reviewed = await async_client.post(
            "/api/imaging/report/review",
            headers=auth_headers(seed_data["director_user"].username),
            json={"report_id": report_id, "status": 2, "note": "审核通过"},
        )
        assert reviewed.json()["code"] == 200
        db_session.expire_all()
        assert db_session.query(ImagingOrder).filter(ImagingOrder.imaging_order_id == order_id).one().status == 4

        patient_view = await async_client.get(
            f"/api/imaging/viewer/{order_id}",
            headers=auth_headers(seed_data["patient_user"].username),
        )
        assert patient_view.json()["data"]["integration_status"] == "not_configured"

    async def test_patient_cannot_create_imaging_order(self, async_client, seed_data, auth_headers):
        response = await async_client.post(
            "/api/imaging/order/create",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"patient_id": seed_data["patient"].patient_id, "body_part": "胸部"},
        )
        assert response.status_code == 403
