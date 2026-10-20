"""Service assistants ground public information in configured routes and shared schedule stock."""

import datetime
import uuid

import httpx
import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import encode_json
from app.ai.models import AIFeatureConfig, AIProvider
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.ai.service_sources import appointment_candidates, hospital_navigation
from app.models import DoctorSchedule, GuideFaq, NavigationEdge, NavigationNode, ScheduleChangeRequest


@pytest.fixture
def service_schedule(seed_data, db_session):
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    week = "星期" + "一二三四五六日"[tomorrow.weekday()]
    schedule = DoctorSchedule(doctor_id=seed_data["doctor"].doctor_id, week=week, time="02", specialist=1, number=10)
    db_session.add(schedule)
    db_session.flush()
    db_session.add(
        ScheduleChangeRequest(
            doctor_id=schedule.doctor_id,
            schedule_id=schedule.schedule_id,
            request_type="add",
            target_date=tomorrow,
            extra_slots=7,
            status=1,
            reason="测试已审批加号，已计入共享库存",
            applicant_id=seed_data["doctor_user"].user_id,
            create_time=datetime.datetime.now(),
        )
    )
    db_session.commit()
    return today, tomorrow, schedule


def test_candidates_preserve_real_stock_without_double_counting_approved_adds(seed_data, db_session, service_schedule):
    today, tomorrow, schedule = service_schedule
    result, evidence = appointment_candidates(db_session, {"schedule_id": schedule.schedule_id, "appointment_date": str(tomorrow)}, today=today)
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["current_shared_stock"] == 10
    assert result["candidates"][0]["recorded_period"] == "02"
    assert result["candidates"][0]["appointment_date"] == str(tomorrow)
    assert result["changes_written"] == []
    assert result["candidates"][0]["source_id"] == evidence[0]["source_id"]
    db_session.refresh(schedule)
    assert schedule.number == 10


def test_approved_stop_excludes_all_periods_of_that_doctor_on_that_date(seed_data, db_session, service_schedule):
    today, tomorrow, schedule = service_schedule
    other_period = DoctorSchedule(doctor_id=schedule.doctor_id, week=schedule.week, time="01", specialist=1, number=5)
    db_session.add(other_period)
    stop = ScheduleChangeRequest(
        doctor_id=schedule.doctor_id,
        schedule_id=schedule.schedule_id,
        request_type="stop",
        target_date=tomorrow,
        extra_slots=0,
        status=0,
        reason="测试停诊",
        applicant_id=seed_data["doctor_user"].user_id,
        create_time=datetime.datetime.now(),
    )
    db_session.add(stop)
    db_session.commit()
    values = {"doctor_id": schedule.doctor_id, "appointment_date": str(tomorrow)}
    pending, _ = appointment_candidates(db_session, values, today=today)
    assert {schedule.schedule_id, other_period.schedule_id} <= {row["schedule_id"] for row in pending["candidates"]}
    stop.status = 1
    db_session.commit()
    approved, _ = appointment_candidates(db_session, values, today=today)
    assert approved["candidates"] == []
    assert approved["excluded_approved_stops"] >= 2


def test_unsupported_dates_and_invalid_identifiers_are_not_reinterpreted(db_session, service_schedule):
    today, tomorrow, schedule = service_schedule
    for values in ({"appointment_date": str(today)}, {"appointment_date": str(today + datetime.timedelta(days=7))}, {"appointment_date": "2026/10/21"}, {"appointment_date": False}, {"doctor_id": True}, {"schedule_id": "1"}):
        with pytest.raises(HTTPException) as invalid:
            appointment_candidates(db_session, values, today=today)
        assert invalid.value.status_code == 422
    schedule.number = 0
    db_session.commit()
    result, _ = appointment_candidates(db_session, {"schedule_id": schedule.schedule_id, "appointment_date": str(tomorrow)}, today=today)
    assert result["candidates"] == []


def test_navigation_reuses_real_directional_graph_and_only_active_faq(seed_data, db_session):
    now = datetime.datetime.now()
    nodes = [NavigationNode(code=uuid.uuid4().hex, name=name, status=1, create_time=now, update_time=now) for name in ("测试入口", "测试收费处")]
    db_session.add_all(nodes)
    db_session.flush()
    edge = NavigationEdge(from_node_id=nodes[0].node_id, to_node_id=nodes[1].node_id, distance=12.5, instruction="沿原有路线前行", bidirectional=0, status=1, create_time=now, update_time=now)
    db_session.add_all(
        [
            edge,
            GuideFaq(question="缴费流程", answer="请依已配置窗口办理", status=1, create_time=now, update_time=now),
            GuideFaq(question="缴费旧流程", answer="已停用内容不应加载", status=0, create_time=now, update_time=now),
        ]
    )
    db_session.commit()
    result, evidence = hospital_navigation(db_session, seed_data["patient_user"], {"start_node_id": nodes[0].node_id, "end_node_id": nodes[1].node_id, "question": "缴费"})
    assert result["route"]["total_distance"] == 12.5
    assert result["route"]["steps"][0]["instruction"] == "沿原有路线前行"
    assert "已停用内容不应加载" not in encode_json(result)
    assert any(item["source_id"] == result["route"]["source_id"] for item in evidence)
    reverse, _ = hospital_navigation(db_session, seed_data["patient_user"], {"start_node_id": nodes[1].node_id, "end_node_id": nodes[0].node_id})
    assert reverse["route"] is None
    assert reverse["missing_data"]
    edge.status = 0
    db_session.commit()
    disabled, _ = hospital_navigation(db_session, seed_data["patient_user"], {"start_node_id": nodes[0].node_id, "end_node_id": nodes[1].node_id})
    assert disabled["route"] is None


@pytest.mark.asyncio
async def test_service_options_are_authorized_and_do_not_expose_personal_doctor_contacts(async_client, seed_data, auth_headers):
    headers = auth_headers(seed_data["patient_user"].username)
    response = await async_client.get("/api/ai/service-options", headers=headers, params={"feature_key": "appointment_assistant"})
    assert response.status_code == 200, response.text
    assert "13900139000" not in response.text
    assert any(row["doctor_id"] == seed_data["doctor"].doctor_id for row in response.json()["data"]["doctors"])
    denied = await async_client.get("/api/ai/service-options", headers=headers, params={"feature_key": "treatment_pathway"})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_appointment_stock_change_while_queued_prevents_model_call(seed_data, db_session, service_schedule):
    _, tomorrow, schedule = service_schedule
    user = seed_data["patient_user"]
    provider = AIProvider(
        name="schedule-test-" + uuid.uuid4().hex[:8],
        kind="chat",
        api_base="http://localhost:11434/v1",
        model="isolated",
        enabled=1,
        allows_patient_data=1,
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key="appointment_assistant",
            provider_id=provider.provider_id,
            enabled=1,
            allowed_roles_json=encode_json(FEATURE_BY_KEY["appointment_assistant"].default_roles),
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    run = create_run(db_session, user, RunRequest(feature_key="appointment_assistant", input={"schedule_id": schedule.schedule_id, "appointment_date": str(tomorrow)}))
    schedule.number = 0
    db_session.commit()
    claim = claim_next_run(db_session)
    assert claim[0] == run.run_id
    calls = []
    await execute_claimed(*claim, transport=httpx.MockTransport(lambda request: (calls.append(request), httpx.Response(500))[1]))
    db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_code == "TASK_TOOLS_CHANGED"
    assert calls == []
