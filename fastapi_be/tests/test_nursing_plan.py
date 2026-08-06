import datetime

import pytest

from app.models import Admission


@pytest.mark.asyncio
class TestNursingPlan:
    async def test_plan_create_update_complete(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(admission_id="plan-admission", admission_no="ZYPLAN001", patient_id=seed_data["patient"].patient_id, status=1, admission_time=datetime.datetime.now(), create_time=datetime.datetime.now())
        db_session.add(admission)
        db_session.commit()
        headers = auth_headers(seed_data["nurse_user"].username)
        created = await async_client.post("/api/nursingPlan/create", headers=headers, json={"admission_id": admission.admission_id, "patient_id": admission.patient_id, "nursing_diagnosis": "活动耐力下降", "goal": "24小时内可在协助下下床", "measures": "协助翻身，监测生命体征"})
        assert created.json()["code"] == 200
        plan_id = created.json()["data"]["plan_id"]
        updated = await async_client.put("/api/nursingPlan/update", headers=headers, json={"plan_id": plan_id, "measures": "协助翻身并进行跌倒宣教", "status": 1})
        assert updated.json()["data"]["status_text"] == "已完成"
        blocked = await async_client.put("/api/nursingPlan/update", headers=headers, json={"plan_id": plan_id, "status": 0})
        assert blocked.json()["code"] == 500
