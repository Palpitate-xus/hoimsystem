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
from app.ai.runtime import authorize_run, claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Admission, Bed, DailyOperationalMetric, Department, Doctor, Registration, Ward


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
