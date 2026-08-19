"""出院自动生成随访计划回归测试。"""
import datetime

import pytest

from app.models import Admission, FollowUp


@pytest.mark.asyncio
class TestDischargeFollowUp:
    async def test_discharge_generates_followup_from_plan_text(self, async_client, seed_data, auth_headers, db_session):
        """出院小结带随访计划文本时应自动创建 FollowUp 记录（含天数解析）。"""
        admission = Admission(
            admission_no=f"ZY-FU-{datetime.datetime.now().strftime('%H%M%S%f')}",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            admission_time=datetime.datetime.now() - datetime.timedelta(days=3),
            status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(admission)
        db_session.commit()

        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/discharge/doDischarge",
            headers=headers,
            json={
                "admission_id": admission.admission_id,
                "discharge_diagnosis": "治愈",
                "treatment_summary": "抗感染治疗",
                "follow_up_plan": "2周后门诊复查血常规",
            },
        )
        assert r.json()["code"] == 200, r.json()

        plans = (
            db_session.query(FollowUp)
            .filter(FollowUp.patient_id == seed_data["patient"].patient_id)
            .all()
        )
        assert plans, "应自动生成随访计划"
        plan = plans[-1]
        assert plan.content == "2周后门诊复查血常规"
        assert plan.doctor_id == seed_data["doctor"].doctor_id
        expected = datetime.date.today() + datetime.timedelta(days=14)
        assert plan.plan_date == expected, "「2周后」应解析为出院日+14天"

    async def test_discharge_without_plan_text_no_followup(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(
            admission_no=f"ZY-FU2-{datetime.datetime.now().strftime('%H%M%S%f')}",
            patient_id=seed_data["patient2"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            admission_time=datetime.datetime.now() - datetime.timedelta(days=1),
            status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(admission)
        db_session.commit()

        before = (
            db_session.query(FollowUp)
            .filter(FollowUp.patient_id == seed_data["patient2"].patient_id)
            .count()
        )
        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/discharge/doDischarge",
            headers=headers,
            json={"admission_id": admission.admission_id, "discharge_diagnosis": "好转"},
        )
        assert r.json()["code"] == 200
        after = (
            db_session.query(FollowUp)
            .filter(FollowUp.patient_id == seed_data["patient2"].patient_id)
            .count()
        )
        assert after == before, "无随访计划文本不应生成记录"
