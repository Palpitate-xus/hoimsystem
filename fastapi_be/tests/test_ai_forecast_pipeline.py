"""Run real statistical arithmetic through source, queue, gateway and result APIs."""

import datetime
import json
import uuid

import httpx
import pytest

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.forecast_config import ForecastSettings, runtime_descriptor
from app.ai.forecast_server import create_forecast_app
from app.ai.forecast_sources import create_series, preview_series
from app.ai.gateway import AIExecutionError, generate
from app.ai.governance import encode_json
from app.ai.models import AIFeatureConfig, AIFeedback, AIForecastSeries, AIProvider, AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Department, DoctorSchedule, MedicalRecord, Prescription, Registration

KEY = "synthetic-forecast-pipeline-key-not-a-live-credential"


class RealStatisticsTransport(httpx.AsyncBaseTransport):
    """Pass actual requests to the real service, with explicit test-only mutations."""

    def __init__(self, app, *, before=None, alter=None):
        self.inner = httpx.ASGITransport(app=app)
        self.requests = []
        self.before = before
        self.alter = alter

    async def handle_async_request(self, request):
        self.requests.append(json.loads(request.content))
        if self.before:
            self.before()
        response = await self.inner.handle_async_request(request)
        if self.alter:
            value = json.loads(await response.aread())
            self.alter(value)
            return httpx.Response(response.status_code, json=value, request=request)
        return response


@pytest.fixture
def forecast_case(db_session, seed_data, monkeypatch):
    for model in (AIFeedback, AIRun, AIFeatureConfig, AIProvider):
        db_session.query(model).delete()
    department = Department(name="合成预测科室" + uuid.uuid4().hex[:8])
    db_session.add(department)
    db_session.flush()
    end = datetime.date.today() - datetime.timedelta(days=2)
    start = end - datetime.timedelta(days=111)
    rows = [
        Registration(
            registration_uuid=str(uuid.uuid4()),
            department_id=department.department_id,
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            time=datetime.datetime.combine(start + datetime.timedelta(days=offset), datetime.time(10, 15)) + datetime.timedelta(seconds=index),
            status=index % 4,
        )
        for offset in range(112)
        for index in range((offset % 7) + offset // 28)
    ]
    db_session.add_all(rows)
    db_session.flush()
    filters = {"scope": "department", "department_id": department.department_id, "date_from": str(start), "date_to": str(end), "timezone": "Asia/Shanghai"}
    candidate = preview_series(db_session, **filters)
    series = create_series(
        db_session,
        seed_data["super_admin_user"],
        {
            **filters,
            "name": "仅合成数据的实际统计链路",
            "expected_digest": candidate["expected_digest"],
            "coverage_confirmed": True,
            "days_ended_confirmed": True,
            "timezone_confirmed": True,
            "coverage_note": "此处仅确认本测试生成的完整合成历史，不使用任何实际医院资料或临床验证结论。",
        },
    )
    config = ForecastSettings(AI_PROVIDER_LOCAL_FORECAST_API_KEY=KEY)
    descriptor = runtime_descriptor(config)
    monkeypatch.setenv("AI_PROVIDER_LOCAL_FORECAST_API_KEY", KEY)
    provider = AIProvider(
        name="real-statistics-" + uuid.uuid4().hex[:8],
        kind="specialist",
        api_base="http://localhost:8813",
        api_key_env="AI_PROVIDER_LOCAL_FORECAST_API_KEY",
        model=descriptor["model_version"],
        enabled=1,
        allows_patient_data=0,
        supported_features_json=encode_json(["visit_forecast"]),
        validation_report="Only synthetic engineering arithmetic; no real operational effectiveness evaluation.",
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    feature = AIFeatureConfig(
        feature_key="visit_forecast",
        provider_id=provider.provider_id,
        enabled=1,
        validation_status="validated",
        validation_note="Synthetic test-only permission fixture; not production validation.",
        allowed_roles_json=encode_json(FEATURE_BY_KEY["visit_forecast"].default_roles),
        updated_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(feature)
    db_session.commit()
    return {"series": series, "rows": rows, "provider": provider, "feature": feature, "app": create_forecast_app(config), "department": department}


def request_for(case, *, preview=False, **extra):
    return RunRequest(feature_key="visit_forecast", preview=preview, input={"forecast_series_id": case["series"].series_id, "horizon_days": 14, **extra})


def change_source(db, case, variant):
    row = db.get(Registration, case["rows"][0].registration_uuid)
    if variant == "same_day_time":
        row.time += datetime.timedelta(microseconds=1)
    elif variant == "delete":
        db.delete(row)
    elif variant == "same_count_replacement":
        replacement = Registration(registration_uuid=str(uuid.uuid4()), time=row.time, department_id=row.department_id, patient_id=row.patient_id, doctor_id=row.doctor_id, status=row.status)
        db.delete(row)
        db.add(replacement)
    elif variant == "department":
        row.department_id = None
    elif variant == "unassigned_time":
        db.add(Registration(registration_uuid=str(uuid.uuid4()), department_id=case["department"].department_id, time=None))
    elif variant == "revoke":
        source = db.get(AIForecastSeries, case["series"].series_id)
        source.status, source.revision = "revoked", 2
    elif variant == "frozen_tamper":
        source = db.get(AIForecastSeries, case["series"].series_id)
        value = json.loads(source.source_json)
        value["observations"][0]["value"] += 1
        source.source_json = encode_json(value)
    else:
        raise AssertionError(variant)
    db.commit()


@pytest.mark.asyncio
async def test_real_source_to_worker_to_statistics_preserves_numeric_evidence_and_business_data(async_client, db_session, seed_data, forecast_case, auth_headers):
    case = forecast_case
    original_counts = {model: db_session.query(model).count() for model in (Registration, MedicalRecord, Prescription, DoctorSchedule)}
    extra_question = "PRIVATE-QUESTION-MUST-STAY-IN-HOSPITAL"
    response = await async_client.post("/api/ai/runs", headers=auth_headers(seed_data["admin_user"].username), json=request_for(case, question=extra_question).model_dump())
    assert response.status_code == 200, response.text
    run_id = response.json()["data"]["run_id"]
    transport = RealStatisticsTransport(case["app"])
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    detail = await async_client.get("/api/ai/runs/" + run_id, headers=auth_headers(seed_data["admin_user"].username))
    assert detail.status_code == 200, detail.text
    frozen = detail.json()["data"]
    assert frozen["status"] == "succeeded" and frozen["input_tokens"] == frozen["output_tokens"] == 0
    analysis = frozen["result"]["forecast_analysis"]
    source = frozen["forecast_findings"]["forecast_source"]
    assert analysis["source_binding"]["content_hash"] == source["content_hash"]
    assert analysis["history_days"] == 112 and len(analysis["forecast"]) == 14
    assert analysis["forecast"][0]["date"] == str(datetime.date.fromisoformat(source["date_to"]) + datetime.timedelta(days=1))
    assert analysis["backtest"]["forecast_pair_count"] == 392 and analysis["backtest"]["unique_target_dates"] == 41
    assert analysis["backtest"]["data_basis"] == "current_snapshot_retrospective"
    assert all(point["calibration_last_target_date"] <= source["date_to"] for point in analysis["forecast"])
    assert len(transport.requests) == 1
    outbound = transport.requests[0]
    assert outbound["schema_version"] == "5" and outbound["store"] is False
    assert outbound["instructions"].startswith(COMMON_SYSTEM_PROMPT)
    assert set(outbound["input"]) == {"context", "horizon_days"} and set(outbound["input"]["context"]) == {"forecast_source"}
    assert extra_question not in encode_json(outbound) and "coverage_note" not in outbound["input"]["context"]["forecast_source"]
    assert all(db_session.query(model).count() == count for model, count in original_counts.items())
    assert db_session.get(AIForecastSeries, source["series_id"]).status == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight"])
@pytest.mark.parametrize("variant", ["same_day_time", "delete", "same_count_replacement", "department", "unassigned_time", "revoke", "frozen_tamper"])
async def test_changed_sources_stop_queued_calls_or_reject_actual_inflight_arithmetic(db_session, seed_data, forecast_case, phase, variant):
    case = forecast_case
    run = create_run(db_session, seed_data["admin_user"], request_for(case))
    claim = claim_next_run(db_session)
    if phase == "queued":
        change_source(db_session, case, variant)
    transport = RealStatisticsTransport(case["app"], before=(lambda: change_source(db_session, case, variant)) if phase == "inflight" else None)
    await execute_claimed(*claim, transport=transport)
    db_session.expire_all()
    saved = db_session.get(AIRun, run.run_id)
    assert saved.status == "failed" and json.loads(saved.result_json) == {}
    assert len(transport.requests) == (0 if phase == "queued" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["same_day_time", "delete", "same_count_replacement", "department", "unassigned_time", "revoke", "frozen_tamper"])
async def test_completed_source_changes_block_ordinary_reads_but_preserve_super_frozen_audit(async_client, db_session, seed_data, forecast_case, auth_headers, variant):
    run = create_run(db_session, seed_data["admin_user"], request_for(forecast_case))
    await execute_claimed(*claim_next_run(db_session), transport=RealStatisticsTransport(forecast_case["app"]))
    db_session.expire_all()
    saved = db_session.get(AIRun, run.run_id)
    assert saved.status == "succeeded"
    immutable = (saved.input_json, saved.result_json, saved.context_digest, saved.evidence_json)
    path = "/api/ai/runs/" + run.run_id
    assert (await async_client.get(path, headers=auth_headers(seed_data["admin_user"].username))).status_code == 200
    change_source(db_session, forecast_case, variant)
    assert (await async_client.get(path, headers=auth_headers(seed_data["admin_user"].username))).status_code == 403
    audit_response = await async_client.get(path, headers=auth_headers(seed_data["super_admin_user"].username))
    assert audit_response.status_code == 200 and audit_response.json()["data"]["status"] == "succeeded"
    db_session.expire_all()
    saved = db_session.get(AIRun, run.run_id)
    assert (saved.input_json, saved.result_json, saved.context_digest, saved.evidence_json) == immutable


@pytest.mark.asyncio
async def test_status_only_change_does_not_rewrite_all_status_count_target(db_session, seed_data, forecast_case):
    run = create_run(db_session, seed_data["admin_user"], request_for(forecast_case))
    claim = claim_next_run(db_session)
    row = db_session.get(Registration, forecast_case["rows"][0].registration_uuid)
    row.status = 3
    db_session.commit()
    transport = RealStatisticsTransport(forecast_case["app"])
    await execute_claimed(*claim, transport=transport)
    db_session.expire_all()
    assert db_session.get(AIRun, run.run_id).status == "succeeded" and len(transport.requests) == 1


@pytest.mark.asyncio
async def test_unreviewed_forecast_can_only_be_super_preview_and_confirmation_does_not_validate(async_client, db_session, seed_data, forecast_case, auth_headers):
    feature = forecast_case["feature"]
    feature.enabled, feature.validation_status = 0, "unreviewed"
    db_session.commit()
    regular = await async_client.post("/api/ai/runs", headers=auth_headers(seed_data["admin_user"].username), json=request_for(forecast_case).model_dump())
    assert regular.status_code == 409
    enable = await async_client.put(
        "/api/ai/admin/features/visit_forecast", headers=auth_headers(seed_data["super_admin_user"].username), json={"expected_revision": feature.revision, "enabled": True}
    )
    assert enable.status_code == 422 and "验证" in enable.json()["detail"]
    db_session.rollback()
    preview = create_run(db_session, seed_data["super_admin_user"], request_for(forecast_case, preview=True))
    await execute_claimed(*claim_next_run(db_session), transport=RealStatisticsTransport(forecast_case["app"]))
    db_session.expire_all()
    assert db_session.get(AIRun, preview.run_id).status == "succeeded"
    feature = db_session.get(AIFeatureConfig, "visit_forecast")
    assert feature.validation_status == "unreviewed" and feature.enabled == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["point", "date", "interval", "denominator", "coverage", "calibration", "source", "prompt", "basis", "recipe", "runtime", "schema", "missing_typed"])
async def test_gateway_recomputes_actual_fixed_result_and_rejects_tampered_numbers(db_session, seed_data, forecast_case, variant):
    run = create_run(db_session, seed_data["admin_user"], request_for(forecast_case))
    snapshot = json.loads(run.input_json)

    def alter(value):
        analysis = value["forecast_analysis"]
        if variant == "point":
            analysis["forecast"][0]["point"] += 0.25
        elif variant == "date":
            analysis["forecast"][0]["date"] = analysis["forecast"][1]["date"]
        elif variant == "interval":
            analysis["forecast"][0]["upper"] += 1.0
        elif variant == "denominator":
            analysis["backtest"]["primary_metrics"]["wape_denominator_actual"] += 1
        elif variant == "coverage":
            analysis["backtest"]["intervals"]["covered_count"] += 1
        elif variant == "calibration":
            analysis["forecast"][0]["calibration_last_target_date"] = analysis["forecast"][0]["date"]
        elif variant == "source":
            analysis["source_binding"]["registration_digest"] = "0" * 64
        elif variant == "prompt":
            analysis["instructions_digest"] = "0" * 64
        elif variant == "basis":
            analysis["backtest"]["data_basis"] = "real_as_of_replay"
        elif variant == "recipe":
            analysis["recipe"] = "best_model_selected_after_backtest"
        elif variant == "runtime":
            analysis["local_runtime"]["runtime_digest"] = "0" * 64
        elif variant == "schema":
            value["schema_version"] = "1"
        elif variant == "missing_typed":
            del value["forecast_analysis"]
        value["usage"] = {"input_tokens": 17, "output_tokens": 19}

    transport = RealStatisticsTransport(forecast_case["app"], alter=alter)
    with pytest.raises(AIExecutionError) as exc:
        await generate(forecast_case["provider"], FEATURE_BY_KEY["visit_forecast"], snapshot["task_prompt"], snapshot["payload"], transport=transport)
    assert len(transport.requests) == 1
    if variant not in {"schema", "missing_typed"}:
        assert exc.value.input_tokens == 17 and exc.value.output_tokens == 19
