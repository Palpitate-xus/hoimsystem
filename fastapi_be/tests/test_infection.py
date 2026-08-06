import datetime

import pytest


@pytest.mark.asyncio
class TestInfection:
    async def test_infection_case_and_disinfection_flow(self, async_client, seed_data, auth_headers):
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        case = await async_client.post(
            "/api/infection/case/create",
            headers=nurse_headers,
            json={"patient_id": seed_data["patient"].patient_id, "department_id": seed_data["department"].department_id, "infection_type": "呼吸道感染", "pathogen": "流感病毒", "onset_date": str(datetime.date.today()), "severity": 2},
        )
        assert case.json()["code"] == 200
        monitor = await async_client.post(
            "/api/infection/disinfection/create",
            headers=nurse_headers,
            json={"area": "治疗室", "item": "空气培养", "result": "合格", "standard": "≤500 CFU/m³"},
        )
        assert monitor.json()["code"] == 200
        exposure = await async_client.post(
            "/api/infection/exposure/create",
            headers=nurse_headers,
            json={"exposure_type": "针刺伤", "body_site": "右手食指", "description": "采血后针头刺伤"},
        )
        assert exposure.json()["code"] == 200
        report = await async_client.get("/api/infection/report", headers=auth_headers(seed_data["director_user"].username))
        assert report.json()["data"]["total_cases"] >= 1

    async def test_patient_cannot_report_infection(self, async_client, seed_data, auth_headers):
        response = await async_client.post("/api/infection/case/create", headers=auth_headers(seed_data["patient_user"].username), json={})
        assert response.status_code == 403
