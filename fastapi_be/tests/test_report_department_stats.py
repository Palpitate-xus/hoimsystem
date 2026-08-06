import datetime

import pytest

from app.models import LabOrder, Review


@pytest.mark.asyncio
class TestDepartmentStats:
    async def test_director_can_view_department_summary(self, async_client, seed_data, auth_headers, db_session):
        seed_data["charge"].status = 1
        db_session.add(
            LabOrder(
                patient_id=seed_data["patient"].patient_id,
                doctor_id=seed_data["doctor"].doctor_id,
                check_type="检验",
                check_items="血常规",
                urgent=0,
                status=0,
                create_time=datetime.datetime.now(),
            )
        )
        db_session.add(
            Review(
                patient_id=seed_data["patient"].patient_id,
                doctor_id=seed_data["doctor"].doctor_id,
                score=4,
                comment="流程清晰",
                review_time=datetime.datetime.now(),
            )
        )
        db_session.commit()

        response = await async_client.post(
            "/api/report/departmentStats",
            headers=auth_headers(seed_data["director_user"].username),
            json={"start_date": str(datetime.date.today()), "end_date": str(datetime.date.today())},
        )

        body = response.json()
        assert body["code"] == 200
        item = next(item for item in body["data"]["items"] if item["department_id"] == seed_data["department"].department_id)
        assert item["visit_count"] >= 1
        assert item["prescription_count"] >= 1
        assert item["lab_order_count"] == 1
        assert item["income"] == 31.0
        assert item["satisfaction_score"] == 4.0

    async def test_patient_cannot_view_department_summary(self, async_client, seed_data, auth_headers):
        response = await async_client.post(
            "/api/report/departmentStats",
            headers=auth_headers(seed_data["patient_user"].username),
            json={},
        )
        assert response.status_code == 403
