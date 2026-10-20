"""Surgical optimization inputs retain scope, source state and unknown constraints."""

import datetime
import json
import uuid

import httpx
import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import encode_json
from app.ai.models import AIFeatureConfig, AIFeedback, AIProvider, AIRun
from app.ai.operational_sources import operational_context, operational_options
from app.ai.runtime import claim_next_run, create_run, describe_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Admission, Department, Doctor, SurgeryApplication, SurgerySchedule


@pytest.fixture(autouse=True)
def clean_tasks(db_session):
    for model in (AIFeedback, AIRun, AIFeatureConfig, AIProvider, SurgerySchedule, SurgeryApplication):
        db_session.query(model).delete()
    db_session.commit()


@pytest.fixture
def surgical_case(seed_data, db_session):
    today = datetime.date.today()
    foreign = Department(name="排台范围外" + uuid.uuid4().hex[:6])
    db_session.add(foreign)
    db_session.flush()
    foreign_doctor = Doctor(name="不发送的医生姓名", department_id=foreign.department_id)
    admission = Admission(patient_id=seed_data["patient"].patient_id, department_id=seed_data["department"].department_id, status=1)
    db_session.add_all([foreign_doctor, admission])
    db_session.flush()
    apps = [
        SurgeryApplication(patient_id=seed_data["patient"].patient_id, admission_id=admission.admission_id, doctor_id=foreign_doctor.doctor_id, surgery_name="手术甲", scheduled_date=today, status=1),
        SurgeryApplication(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, surgery_name="手术乙", scheduled_date=today, status=2),
        SurgeryApplication(patient_id=seed_data["patient2"].patient_id, doctor_id=foreign_doctor.doctor_id, surgery_name="外科手术", scheduled_date=today, status=1),
        SurgeryApplication(
            patient_id=seed_data["patient2"].patient_id, admission_id=admission.admission_id, doctor_id=seed_data["doctor"].doctor_id, surgery_name="错误住院关联", scheduled_date=today, status=1
        ),
    ]
    db_session.add_all(apps)
    db_session.flush()
    timestamp = datetime.datetime.combine(today, datetime.time(10))
    schedules = [
        SurgerySchedule(
            application_id=row.application_id,
            patient_id=row.patient_id,
            surgery_date=today,
            operating_room="室" + str(index),
            start_time=timestamp,
            end_time=timestamp + datetime.timedelta(hours=1),
            surgeon_id=seed_data["doctor"].doctor_id,
            status=0,
        )
        for index, row in enumerate(apps)
    ]
    # The same account is referenced as a doctor in one schedule and nurse in another.
    schedules[1].surgeon_id = None
    schedules[1].scrub_nurse_id = seed_data["doctor_user"].user_id
    schedules[1].assistant_ids = "未知," + str(seed_data["doctor"].doctor_id) + ",99999999"
    broken = SurgerySchedule(application_id=apps[0].application_id, patient_id=seed_data["patient2"].patient_id, surgery_date=today, operating_room="错误排台关联", status=0)
    db_session.add_all([*schedules, broken])
    db_session.commit()
    return today, apps, schedules


def snapshot(db_session, seed_data, *, user=None, **values):
    return operational_context(db_session, user or seed_data["director_user"], FEATURE_BY_KEY["surgery_scheduling"], values)


def records(bundle, key):
    data = bundle.data[key]
    return [dict(zip(data["columns"], row)) for row in data["rows"]]


def test_admission_department_wins_over_applicant_and_invalid_patient_links_are_excluded(seed_data, db_session, surgical_case):
    _, apps, schedules = surgical_case
    bundle = snapshot(db_session, seed_data)
    assert {row["application_id"] for row in records(bundle, "surgical_applications")} == {apps[0].application_id, apps[1].application_id}
    assert {row["schedule_id"] for row in records(bundle, "surgical_schedules")} == {schedules[0].schedule_id, schedules[1].schedule_id}
    serialized = encode_json({"context": bundle.data, "evidence": bundle.evidence})
    for forbidden in (seed_data["patient"].identity, seed_data["patient"].name, "不发送的医生姓名", "错误住院关联", "错误排台关联", "外科手术", "patient_id", "admission_id"):
        assert forbidden not in serialized
    assert bundle.data["surgical_schedules"]["malformed_assistant_lists"] == 1
    assert bundle.data["surgical_schedules"]["unresolved_staff_references"] == 1
    assert any("资质" in item for item in bundle.data["missing_data"])


def test_cross_role_same_account_overlap_uses_only_recorded_intervals_and_active_states(seed_data, db_session, surgical_case):
    _, apps, schedules = surgical_case
    bundle = snapshot(db_session, seed_data)
    rows = records(bundle, "surgical_recorded_overlaps")
    assert len(rows) == 1
    assert rows[0]["shared_resource_references"] == ["user:" + str(seed_data["doctor_user"].user_id)]
    schedules[1].start_time = schedules[0].end_time
    schedules[1].end_time += datetime.timedelta(hours=1)
    db_session.commit()
    assert records(snapshot(db_session, seed_data), "surgical_recorded_overlaps") == []
    schedules[1].start_time = schedules[0].start_time
    apps[1].status = 4
    db_session.commit()
    assert records(snapshot(db_session, seed_data), "surgical_recorded_overlaps") == []
    apps[1].status = 2
    schedules[1].end_time = None
    db_session.commit()
    bundle = snapshot(db_session, seed_data)
    assert bundle.data["surgical_recorded_overlaps"]["checked_intervals"] == 1
    assert records(bundle, "surgical_recorded_overlaps") == []


def test_historical_completed_times_and_planning_dates_are_separate(seed_data, db_session, surgical_case):
    today, _, schedules = surgical_case
    past = today - datetime.timedelta(days=2)
    schedules[0].surgery_date = past
    schedules[0].start_time = datetime.datetime.combine(past, datetime.time(8))
    schedules[0].end_time = None
    schedules[0].status = 2
    db_session.commit()
    bundle = snapshot(db_session, seed_data, date_from=str(past), date_to=str(past))
    rows = records(bundle, "surgical_completed_intervals")
    assert len(rows) == 1 and rows[0]["recorded_end"] is None
    assert rows[0]["schedule_id"] not in {row["schedule_id"] for row in records(bundle, "surgical_schedules")}
    options = operational_options(db_session, seed_data["director_user"], FEATURE_BY_KEY["surgery_scheduling"])
    assert options["default_planning_window"][0] == str(today)
    with pytest.raises(HTTPException) as error:
        snapshot(db_session, seed_data, planning_date_from=str(past))
    assert error.value.status_code == 422


def configure(db_session, seed_data):
    provider = AIProvider(
        name="surgical-isolated",
        kind="specialist",
        api_base="http://localhost:11434",
        model="isolated",
        enabled=1,
        allows_patient_data=1,
        supported_features_json=encode_json(["surgery_scheduling"]),
        validation_report="isolated test adapter report",
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key="surgery_scheduling",
            enabled=1,
            provider_id=provider.provider_id,
            allowed_roles_json=encode_json(FEATURE_BY_KEY["surgery_scheduling"].default_roles),
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    return provider


@pytest.mark.asyncio
async def test_changed_surgical_resource_stops_queued_adapter_and_frozen_findings_remain_reviewable(seed_data, db_session, surgical_case):
    configure(db_session, seed_data)
    run = create_run(db_session, seed_data["super_admin_user"], RunRequest(feature_key="surgery_scheduling"))
    frozen = json.loads(run.input_json)
    surgical_case[2][0].operating_room = "改变的手术室"
    db_session.commit()
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(lambda request: (calls.append(request), httpx.Response(500))[1]))
    db_session.refresh(run)
    assert not calls and run.error_code == "TASK_OPERATIONAL_CONTEXT_CHANGED"
    findings = describe_run(run, include_result=True)["operational_findings"]
    assert findings["surgical_schedules"] == frozen["payload"]["context"]["surgical_schedules"]
    assert "改变的手术室" not in encode_json(findings)


def test_surgical_adapter_requires_patient_data_purpose(seed_data, db_session):
    provider = configure(db_session, seed_data)
    provider.allows_patient_data = 0
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        create_run(db_session, seed_data["super_admin_user"], RunRequest(feature_key="surgery_scheduling"))
    assert error.value.status_code == 409
