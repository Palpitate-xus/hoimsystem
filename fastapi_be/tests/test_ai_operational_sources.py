"""Operational assistants respect department boundaries and refresh facts around inference."""

import datetime
import json
import uuid

import httpx
import pytest
from fastapi import HTTPException

from app import database
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import encode_json
from app.ai.models import AIFeatureConfig, AIFeedback, AIProvider, AIRun
from app.ai.operational_sources import operational_context, operational_window
from app.ai.roster_sources import planning_window
from app.ai.runtime import authorize_run, claim_next_run, create_run, describe_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Admission, Bed, DailyOperationalMetric, Department, Doctor, DoctorSchedule, Registration, ScheduleChangeRequest, Ward


@pytest.fixture(autouse=True)
def clean_ai_tasks(db_session):
    for model in (AIFeedback, AIRun, AIFeatureConfig, AIProvider):
        db_session.query(model).delete()
    db_session.commit()


@pytest.fixture
def operational_case(seed_data, db_session):
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    timestamp = datetime.datetime.combine(yesterday, datetime.time(10))
    foreign_department = Department(name="运营隔离科室" + uuid.uuid4().hex[:6])
    db_session.add(foreign_department)
    db_session.flush()
    own_ward = Ward(name="运营本科病区", department_id=seed_data["department"].department_id, bed_count=99, status=0)
    foreign_ward = Ward(name="外科病区不应在本科出现", department_id=foreign_department.department_id, bed_count=1, status=0)
    db_session.add_all([own_ward, foreign_ward])
    db_session.flush()
    metric = db_session.get(DailyOperationalMetric, yesterday) or DailyOperationalMetric(metric_date=yesterday)
    metric.outpatient_visits = 987
    metric.revenue = "123456.78"
    metric.average_queue_wait_minutes = None
    metric.updated_at = timestamp
    future = db_session.get(DailyOperationalMetric, today + datetime.timedelta(days=1)) or DailyOperationalMetric(metric_date=today + datetime.timedelta(days=1))
    future.outpatient_visits = 54321
    future.updated_at = timestamp
    db_session.add_all(
        [
            metric,
            future,
            Bed(ward_id=own_ward.ward_id, bed_no="01", status=0),
            Bed(ward_id=own_ward.ward_id, bed_no="02", status=1),
            Bed(ward_id=foreign_ward.ward_id, bed_no="01", status=0),
            Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=timestamp, status=0),
            Registration(patient_id=seed_data["patient2"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=foreign_department.department_id, time=timestamp, status=1),
            Admission(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, admission_time=timestamp, status=1),
        ]
    )
    db_session.commit()
    return today, yesterday, metric, own_ward, foreign_department


def values_for(case, **extra):
    today, yesterday, _, _, _ = case
    return {"date_from": str(yesterday - datetime.timedelta(days=1)), "date_to": str(today), **extra}


def configure(db_session, seed_data):
    key = "operations_qa"
    provider = AIProvider(name="ops-test-" + uuid.uuid4().hex[:8], kind="chat", api_base="http://localhost:11434/v1", model="isolated", enabled=1, created_by=seed_data["super_admin_user"].user_id)
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key=key, provider_id=provider.provider_id, enabled=1, allowed_roles_json=encode_json(FEATURE_BY_KEY[key].default_roles), updated_by=seed_data["super_admin_user"].user_id
        )
    )
    db_session.commit()


def test_director_gets_only_scoped_raw_facts_and_no_hospital_financial_aggregate(seed_data, db_session, operational_case):
    _, _, _, own_ward, foreign_department = operational_case
    spec = FEATURE_BY_KEY["operations_qa"]
    bundle = operational_context(db_session, seed_data["director_user"], spec, values_for(operational_case, department_id=seed_data["department"].department_id))
    serialized = encode_json(bundle.data)
    assert bundle.data["scope"] == "department"
    assert "saved_daily_metrics" not in bundle.data
    assert "123456.78" not in serialized
    assert "外科病区不应在本科出现" not in serialized
    assert bundle.data["ward_capacity"]["wards"][0]["ward_id"] == own_ward.ward_id
    assert bundle.data["ward_capacity"]["wards"][0]["loaded_bed_record_count"] == 2
    assert bundle.data["ward_capacity"]["wards"][0]["configured_count_matches_loaded"] is False
    assert bundle.data["ward_capacity"]["wards"][0]["recorded_free_beds_in_active_ward"] == 1
    assert bundle.data["recorded_registrations"]["rows"] == [[str(operational_case[1]), 0, 1]]
    assert seed_data["patient"].identity not in serialized
    with pytest.raises(HTTPException) as denied:
        operational_context(db_session, seed_data["director_user"], spec, values_for(operational_case, department_id=foreign_department.department_id))
    assert denied.value.status_code == 403


def test_preaggregated_gaps_null_wait_and_future_dates_remain_explicit(seed_data, db_session, operational_case):
    today, yesterday, _, _, _ = operational_case
    bundle = operational_context(db_session, seed_data["super_admin_user"], FEATURE_BY_KEY["operations_qa"], values_for(operational_case))
    metrics = bundle.data["saved_daily_metrics"]
    assert metrics["rows"][0][0] == str(yesterday)
    assert len(metrics["rows"]) == 1
    assert str(today) in metrics["missing_dates"]
    assert metrics["rows"][0][metrics["columns"].index("average_queue_wait_minutes")] is None
    assert "54321" not in encode_json(bundle.data)
    assert bundle.evidence and all(item["kind"] == "operational_record" for item in bundle.evidence)


def test_equal_counts_in_different_departments_have_distinct_scoped_evidence(seed_data, db_session, operational_case):
    department = operational_case[4]
    db_session.add(
        Admission(patient_id=seed_data["patient2"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=department.department_id, admission_time=datetime.datetime.now(), status=1)
    )
    db_session.commit()
    bundles = [
        operational_context(db_session, seed_data["super_admin_user"], FEATURE_BY_KEY["operations_qa"], values_for(operational_case, department_id=department_id))
        for department_id in (seed_data["department"].department_id, department.department_id)
    ]
    left, right = [bundle.data["current_active_admissions"] for bundle in bundles]
    assert left["record_count"] == right["record_count"] == 1
    assert left["source_id"] != right["source_id"]
    evidence = next(item for item in bundles[0].evidence if item["source_id"] == left["source_id"])
    assert json.loads(evidence["content"])["department_ids"] == [seed_data["department"].department_id]
    assert evidence["observed_at"] == bundles[0].data["snapshot_time"]


def test_invalid_windows_and_unscoped_roles_cannot_load_operational_data(seed_data, db_session):
    today = datetime.date.today()
    for values in (
        {"date_to": str(today + datetime.timedelta(days=1))},
        {"date_from": "2026/10/20"},
        {"date_from": False},
        {"date_from": str(today - datetime.timedelta(days=400))},
        {"date_from": str(today), "date_to": str(today - datetime.timedelta(days=1))},
    ):
        with pytest.raises(HTTPException) as invalid:
            operational_window(values)
        assert invalid.value.status_code == 422
    with pytest.raises(HTTPException) as denied:
        operational_context(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["operations_qa"], {})
    assert denied.value.status_code == 403


def test_hourly_series_retains_original_clock_and_status_without_zero_filling(seed_data, db_session, operational_case):
    yesterday = operational_case[1]
    db_session.add(
        Registration(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            time=datetime.datetime.combine(yesterday, datetime.time(11, 10)),
            status=1,
        )
    )
    db_session.commit()
    bundle = operational_context(db_session, seed_data["director_user"], FEATURE_BY_KEY["visit_forecast"], values_for(operational_case, department_id=seed_data["department"].department_id))
    source = bundle.data["recorded_hourly_registrations"]
    assert source["rows"] == [[str(yesterday), 10, 0, 1], [str(yesterday), 11, 1, 1]]
    assert source["truncated"] is False
    assert seed_data["patient"].identity not in encode_json(bundle.data)


def test_roster_retains_scoped_raw_periods_and_planning_changes_without_invented_credentials(seed_data, db_session, operational_case):
    today, _, _, _, foreign_department = operational_case
    foreign_doctor = Doctor(name="外科医生不应加载", department_id=foreign_department.department_id)
    db_session.add(foreign_doctor)
    db_session.flush()
    own = DoctorSchedule(doctor_id=seed_data["doctor"].doctor_id, week="星期三", time="原始编码", specialist=1, number=None)
    foreign = DoctorSchedule(doctor_id=foreign_doctor.doctor_id, week="星期三", time="02", specialist=1, number=10)
    db_session.add_all([own, foreign])
    db_session.flush()
    requests = []
    for doctor_id, schedule_id, kind, status in (
        (own.doctor_id, own.schedule_id, "stop", 1),
        (own.doctor_id, own.schedule_id, "add", 0),
        (own.doctor_id, foreign.schedule_id, "stop", 1),
        (foreign.doctor_id, foreign.schedule_id, "stop", 1),
    ):
        row = ScheduleChangeRequest(
            doctor_id=doctor_id,
            schedule_id=schedule_id,
            request_type=kind,
            status=status,
            extra_slots=5 if kind == "add" else 0,
            target_date=today + datetime.timedelta(days=1),
            reason="sensitive-staff-reason-" + seed_data["patient"].identity,
            applicant_id=seed_data["doctor_user"].user_id,
            create_time=datetime.datetime.now(),
        )
        requests.append(row)
        db_session.add(row)
    db_session.commit()
    values = values_for(operational_case, department_id=seed_data["department"].department_id, planning_date_from=str(today), planning_date_to=str(today + datetime.timedelta(days=3)))
    bundle = operational_context(db_session, seed_data["director_user"], FEATURE_BY_KEY["roster_optimization"], values)
    schedule_data = bundle.data["recorded_schedules"]
    row = next(dict(zip(schedule_data["columns"], row)) for row in schedule_data["rows"] if row[0] == own.schedule_id)
    assert row["recorded_period"] == "原始编码"
    assert row["current_shared_stock"] is None
    assert schedule_data["planning_window"] == [str(today), str(today + datetime.timedelta(days=3))]
    assert all(row[0] != foreign.schedule_id for row in schedule_data["rows"])
    changes = bundle.data["recorded_schedule_changes"]
    assert {row[0] for row in changes["rows"]} == {row.request_id for row in requests[:2]}
    assert changes["excluded_inconsistent_links"] == 1
    assert any("不得宣称候选排班已满足全部约束" in note for note in bundle.data["missing_data"])
    assert "sensitive-staff-reason" not in encode_json(bundle.data)
    db_session.refresh(own)
    assert own.number is None


def test_planning_window_rejects_past_oversized_and_untyped_dates():
    today = datetime.date.today()
    for values in (
        {"planning_date_from": str(today - datetime.timedelta(days=1))},
        {"planning_date_to": str(today + datetime.timedelta(days=31))},
        {"planning_date_to": str(today + datetime.timedelta(days=400))},
        {"planning_date_from": False},
    ):
        with pytest.raises(HTTPException) as invalid:
            planning_window(values)
        assert invalid.value.status_code == 422


@pytest.mark.asyncio
async def test_changed_metric_while_queued_stops_before_inference(seed_data, db_session, operational_case):
    configure(db_session, seed_data)
    run = create_run(db_session, seed_data["super_admin_user"], RunRequest(feature_key="operations_qa", input=values_for(operational_case)))
    metric = operational_case[2]
    metric.outpatient_visits += 1
    db_session.commit()
    calls = []
    claim = claim_next_run(db_session)
    await execute_claimed(*claim, transport=httpx.MockTransport(lambda request: (calls.append(request), httpx.Response(500))[1]))
    db_session.refresh(run)
    assert calls == []
    assert run.status == "failed"
    assert run.error_code == "TASK_OPERATIONAL_CONTEXT_CHANGED"


def test_retained_results_do_not_retain_department_access_after_reassignment(seed_data, db_session, operational_case):
    configure(db_session, seed_data)
    user = seed_data["director_user"]
    run = create_run(db_session, user, RunRequest(feature_key="operations_qa", input=values_for(operational_case, department_id=seed_data["department"].department_id)))
    authorize_run(db_session, user, run)
    seed_data["director_doctor"].department_id = operational_case[4].department_id
    db_session.commit()
    with pytest.raises(HTTPException) as denied:
        authorize_run(db_session, user, run)
    assert denied.value.status_code == 403


def test_previous_hospital_scope_cannot_be_read_using_new_department_only_role(seed_data, db_session, operational_case):
    configure(db_session, seed_data)
    user = seed_data["admin_user"]
    run = create_run(db_session, user, RunRequest(feature_key="operations_qa", input=values_for(operational_case)))
    user.user_role = "director"
    db_session.add(Doctor(name="运营角色变更测试", department_id=seed_data["department"].department_id, user_id=user.user_id))
    db_session.commit()
    with pytest.raises(HTTPException) as denied:
        authorize_run(db_session, user, run)
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_operational_preview_and_options_use_real_scope_without_creating_inference(async_client, seed_data, db_session, auth_headers, operational_case):
    headers = auth_headers(seed_data["director_user"].username)
    options = await async_client.get("/api/ai/service-options", headers=headers, params={"feature_key": "operations_qa"})
    assert options.status_code == 200, options.text
    assert options.json()["data"]["allow_hospital_scope"] is False
    department_ids = {row["department_id"] for row in options.json()["data"]["departments"]}
    assert seed_data["department"].department_id in department_ids
    assert operational_case[4].department_id not in department_ids
    response = await async_client.post(
        "/api/ai/operational-context", headers=headers, json={"feature_key": "operations_qa", "input": values_for(operational_case, department_id=seed_data["department"].department_id)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["context"]["department_ids"] == [seed_data["department"].department_id]
    assert "saved_daily_metrics" not in response.json()["data"]["context"]
    assert response.json()["data"]["evidence"]
    denied = await async_client.post("/api/ai/operational-context", headers=auth_headers(seed_data["patient_user"].username), json={"feature_key": "operations_qa"})
    assert denied.status_code == 403
    assert db_session.query(AIRun).count() == 0


def test_business_result_projects_only_allowlisted_operational_context():
    run = AIRun(
        feature_key="operations_qa",
        input_json=encode_json(
            {
                "system_prompt": "private-system",
                "provider_snapshot": {"api_base": "private-endpoint"},
                "payload": {"context": {"scope": "hospital", "saved_daily_metrics": {"rows": []}, "unapproved_secret": "private-context"}},
            }
        ),
        result_json="{}",
        evidence_json="[]",
        context_metadata_json="{}",
    )
    data = describe_run(run)
    assert data["operational_findings"] == {"scope": "hospital", "saved_daily_metrics": {"rows": []}}
    assert "private-context" not in encode_json(data)
    assert "private-system" not in encode_json(data)
    assert "private-endpoint" not in encode_json(data)


@pytest.mark.asyncio
async def test_changed_capacity_during_inference_rejects_old_result_and_retains_frozen_input(seed_data, db_session, operational_case):
    configure(db_session, seed_data)
    run = create_run(db_session, seed_data["super_admin_user"], RunRequest(feature_key="operations_qa", input=values_for(operational_case)))
    original_input = run.input_json
    ward_id = operational_case[3].ward_id
    calls = []

    def reply(request):
        calls.append(request)
        with database.SessionLocal() as session:
            bed = session.query(Bed).filter_by(ward_id=ward_id, status=0).one()
            bed.status = 2
            session.commit()
        result = {"summary": "隔离测试旧容量", "sections": [], "warnings": [], "missing_data": []}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}})

    claim = claim_next_run(db_session)
    await execute_claimed(*claim, transport=httpx.MockTransport(reply))
    db_session.refresh(run)
    assert len(calls) == 1
    assert run.status == "failed"
    assert run.error_code == "TASK_OPERATIONAL_CONTEXT_CHANGED"
    assert run.input_json == original_input
    assert run.result_json == "{}"
