"""Real synthetic registration rows, immutable coverage and current-source authorization."""

import datetime
import hashlib
import json
import uuid

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from alembic import command
from app.ai import forecast_sources as sources
from app.ai.context import context_metadata
from app.ai.forecast_contract import ForecastSource
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIForecastSeries, AIRun
from app.database import get_db
from app.db_migrate import migrate
from app.models import Department, Registration
from app.routers import ai_forecast

NOTE = "合成测试已逐日核对两个真实挂号入口及补录情况，确认窗口完整，原钟点按声明时区解释。"
NOW = datetime.datetime(2026, 10, 20, 12, 30, 45, 123456)


@pytest.fixture
def forecast_case(db_session, seed_data, monkeypatch):
    monkeypatch.setattr(sources, "utcnow", lambda: NOW)
    db_session.query(AIForecastSeries).delete()
    db_session.query(AIFeatureConfig).filter_by(feature_key="visit_forecast").delete()
    db_session.query(Registration).delete()
    db_session.query(AIAuditEvent).filter(AIAuditEvent.action.like("forecast_series.%")).delete()
    start = datetime.date(2026, 6, 30)
    end = start + datetime.timedelta(days=111)
    foreign = Department(name="合成预测隔离科室")
    db_session.add(foreign)
    db_session.flush()
    records = [
        Registration(
            registration_uuid="00000000-0000-4000-8000-000000000001",
            department_id=seed_data["department"].department_id,
            patient_id=seed_data["patient"].patient_id,
            time=datetime.datetime.combine(start, datetime.time(0, 0, 0, 123456)),
            status=0,
        ),
        Registration(
            registration_uuid="00000000-0000-4000-8000-000000000002",
            department_id=seed_data["department"].department_id,
            patient_id=seed_data["patient"].patient_id,
            time=datetime.datetime.combine(start, datetime.time(23, 59, 59, 654321)),
            status=3,
        ),
        Registration(
            registration_uuid="00000000-0000-4000-8000-000000000003",
            department_id=seed_data["department"].department_id,
            patient_id=seed_data["patient2"].patient_id,
            time=datetime.datetime.combine(end, datetime.time(11)),
            status=None,
        ),
        Registration(registration_uuid="00000000-0000-4000-8000-000000000004", department_id=seed_data["department"].department_id, time=None, status=0),
        Registration(registration_uuid="00000000-0000-4000-8000-000000000005", department_id=foreign.department_id, time=datetime.datetime.combine(start, datetime.time(1)), status=1),
    ]
    db_session.add_all(records)
    db_session.commit()
    values = {"scope": "department", "department_id": seed_data["department"].department_id, "date_from": str(start), "date_to": str(end), "timezone": "Asia/Shanghai"}
    return {"values": values, "records": records, "foreign": foreign, "seed": seed_data}


@pytest_asyncio.fixture
async def forecast_client(db_session):
    # Exercise the real route/dependency/JWT paths without depending on main's
    # registration order while the parallel runtime integration is being built.
    app = FastAPI()
    app.include_router(ai_forecast.router, prefix="/api")

    def session_override():
        yield db_session

    app.dependency_overrides[get_db] = session_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def preview(db_session, case, **changes):
    return sources.preview_series(db_session, **{**case["values"], **changes})


def create(db_session, case, **changes):
    values = {**case["values"], **changes}
    observed = sources.preview_series(db_session, **{key: values[key] for key in case["values"]})
    row = sources.create_series(
        db_session,
        case["seed"]["super_admin_user"],
        {
            **values,
            "name": "合成每日挂号来源",
            "coverage_note": NOTE,
            "expected_digest": observed["expected_digest"],
            "coverage_confirmed": True,
            "days_ended_confirmed": True,
            "timezone_confirmed": True,
        },
    )
    db_session.commit()
    return row


def create_body(db_session, case, **changes):
    return {
        **case["values"],
        "name": "API合成挂号来源",
        "coverage_note": NOTE,
        "expected_digest": preview(db_session, case)["expected_digest"],
        "coverage_confirmed": True,
        "days_ended_confirmed": True,
        "timezone_confirmed": True,
        **changes,
    }


def test_unconfirmed_zero_and_real_counts_keep_original_clock_and_all_statuses(db_session, forecast_case):
    data = preview(db_session, forecast_case)
    assert len(data["observations"]) == 112
    assert data["observations"][0] == {"date": "2026-06-30", "observed_count": 2, "value": None}
    assert data["observations"][1] == {"date": "2026-07-01", "observed_count": 0, "value": None}
    assert data["observations"][-1]["observed_count"] == 1
    assert data["unassigned_time_records"] == 1
    assert data["quality"]["all_days_ended"] is True
    assert all(point["value"] is None for point in data["observations"])
    assert data["expected_digest"] == preview(db_session, forecast_case)["expected_digest"]
    # A timezone declaration does not shift a 00:00 database clock to another day.
    hawaii = preview(db_session, forecast_case, timezone="Pacific/Honolulu")
    assert hawaii["observations"] == data["observations"]
    assert hawaii["expected_digest"] != data["expected_digest"]


def test_streamed_digest_uses_original_microseconds_and_not_only_daily_count(db_session, forecast_case):
    initial = preview(db_session, forecast_case)
    expected = hashlib.sha256()
    for row in forecast_case["records"][:3]:
        expected.update((sources.canonical_json([row.registration_uuid, row.time.isoformat(timespec="microseconds"), row.department_id]) + "\n").encode())
    assert initial["registration_digest"] == expected.hexdigest()
    row = forecast_case["records"][0]
    row.registration_uuid = "10000000-0000-4000-8000-000000000001"
    db_session.commit()
    swapped = preview(db_session, forecast_case)
    assert swapped["observations"] == initial["observations"]
    assert swapped["registration_digest"] != initial["registration_digest"]
    assert swapped["expected_digest"] != initial["expected_digest"]


def test_status_only_change_does_not_redefine_all_records_target(db_session, forecast_case):
    initial = preview(db_session, forecast_case)
    forecast_case["records"][0].status = 3
    db_session.commit()
    assert preview(db_session, forecast_case)["expected_digest"] == initial["expected_digest"]


def test_attested_values_zero_and_private_fields_never_enter_source_or_evidence(db_session, forecast_case):
    row = create(db_session, forecast_case)
    source = sources.source_current(db_session, forecast_case["seed"]["admin_user"], row)
    assert ForecastSource.model_validate(source)
    assert source["observations"][0]["value"] == 2
    assert source["observations"][1]["value"] == 0
    assert source["unassigned_time_records"] == 1
    assert source["coverage_attested_at"] == "2026-10-20T12:30:45.123456+00:00"
    assert source["coverage_note_hash"] == hashlib.sha256(NOTE.encode()).hexdigest()
    context = sources.forecast_context(db_session, forecast_case["seed"]["director_user"], {"forecast_series_id": row.series_id, "horizon_days": 7, "question": "真实挂号数"})
    serialized = sources.canonical_json({"context": context.data, "evidence": context.evidence})
    assert NOTE not in serialized
    assert forecast_case["seed"]["patient"].identity not in serialized
    assert forecast_case["records"][0].registration_uuid not in serialized
    assert "saved_daily_metrics" not in context.data
    assert "recorded_hourly_registrations" not in context.data
    assert context.evidence[0]["observed_at"] == source["coverage_attested_at"]
    assert context.data["series_revision"] == 1
    assert (
        context_metadata(context)["clinical_context_fingerprint"]
        == context_metadata(sources.forecast_context(db_session, forecast_case["seed"]["director_user"], {"forecast_series_id": row.series_id, "horizon_days": 7}))["clinical_context_fingerprint"]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"date_to": "2026-10-21"},
        {"date_from": "2026/06/30"},
        {"date_from": "2026-07-01"},
        {"timezone": "not/a/timezone"},
        {"scope": "department", "department_id": None},
        {"scope": "hospital"},
        {"department_id": True},
        {"department_id": "1"},
    ],
)
def test_invalid_scope_dates_and_windows_are_rejected(db_session, forecast_case, changes):
    with pytest.raises(HTTPException) as failure:
        preview(db_session, forecast_case, **changes)
    assert failure.value.status_code == 422


def test_current_day_preview_is_unknown_and_cannot_be_attested(db_session, forecast_case):
    values = {**forecast_case["values"], "date_from": "2026-07-01", "date_to": "2026-10-20"}
    data = sources.preview_series(db_session, **values)
    assert data["quality"]["all_days_ended"] is False
    with pytest.raises(HTTPException) as failure:
        sources.create_series(db_session, forecast_case["seed"]["super_admin_user"], {**create_body(db_session, forecast_case), **values, "expected_digest": data["expected_digest"]})
    assert failure.value.status_code == 422
    assert db_session.query(AIForecastSeries).count() == 0


def test_day_closure_uses_declared_timezone_not_host_calendar(db_session, forecast_case, monkeypatch):
    monkeypatch.setattr(sources, "utcnow", lambda: datetime.datetime(2026, 10, 20, 0, 1))
    assert preview(db_session, forecast_case, timezone="Pacific/Honolulu")["quality"]["all_days_ended"] is False
    assert preview(db_session, forecast_case, timezone="Asia/Shanghai")["quality"]["all_days_ended"] is True


def test_row_bound_rejects_instead_of_truncating_and_never_creates_series(db_session, forecast_case, monkeypatch):
    monkeypatch.setattr(sources, "MAX_REGISTRATION_ROWS", 2)
    with pytest.raises(HTTPException) as failure:
        preview(db_session, forecast_case)
    assert failure.value.status_code == 422
    assert "截断" in failure.value.detail
    assert db_session.query(AIForecastSeries).count() == 0


@pytest.mark.parametrize("mutation", ["row_identity", "microsecond", "department", "new_timed", "new_untimed", "note", "table_clock", "source_json"])
def test_changed_actual_rows_or_declaration_invalidates_current_and_ordinary_history(db_session, forecast_case, mutation):
    series = create(db_session, forecast_case)
    user = forecast_case["seed"]["director_user"]
    context = sources.forecast_context(db_session, user, {"forecast_series_id": series.series_id, "horizon_days": 14}).data
    row = forecast_case["records"][0]
    if mutation == "row_identity":
        row.registration_uuid = str(uuid.uuid4())
    elif mutation == "microsecond":
        row.time += datetime.timedelta(microseconds=1)
    elif mutation == "department":
        row.department_id = forecast_case["foreign"].department_id
    elif mutation == "new_timed":
        db_session.add(Registration(department_id=row.department_id, time=row.time, status=0))
    elif mutation == "new_untimed":
        db_session.add(Registration(department_id=row.department_id, time=None, status=0))
    elif mutation == "note":
        series.coverage_note += "更正"
    elif mutation == "table_clock":
        series.timezone = "UTC"
    else:
        content = json.loads(series.source_json)
        content["observations"][1]["value"] = 123
        series.source_json = sources.canonical_json(content)
    db_session.commit()
    with pytest.raises(HTTPException) as current:
        sources.source_current(db_session, user, series.series_id)
    assert current.value.status_code == 409
    with pytest.raises(HTTPException) as historical:
        sources.authorize_forecast_snapshot(db_session, user, context)
    assert historical.value.status_code == 403
    sources.authorize_forecast_snapshot(db_session, forecast_case["seed"]["super_admin_user"], context)


@pytest.mark.parametrize("horizon", [None, True, 7.0, "7", 1, 8, 15])
def test_horizon_is_explicit_strict_and_cannot_be_coerced(db_session, forecast_case, horizon):
    series = create(db_session, forecast_case)
    with pytest.raises(HTTPException) as failure:
        sources.forecast_context(db_session, forecast_case["seed"]["admin_user"], {"forecast_series_id": series.series_id, "horizon_days": horizon})
    assert failure.value.status_code == 422


@pytest.mark.parametrize("extra", [{"observations": []}, {"forecast_source": {}}, {"date_from": "2026-06-29"}, {"department_id": True}, {"department_id": None}])
def test_client_cannot_override_frozen_values_or_scope(db_session, forecast_case, extra):
    series = create(db_session, forecast_case)
    with pytest.raises(HTTPException) as failure:
        sources.forecast_context(db_session, forecast_case["seed"]["admin_user"], {"forecast_series_id": series.series_id, "horizon_days": 7, **extra})
    assert failure.value.status_code == 422


def test_scope_and_current_feature_role_remain_authoritative_without_model_enabled(db_session, forecast_case):
    seed = forecast_case["seed"]
    own = create(db_session, forecast_case)
    hospital = create(db_session, forecast_case, scope="hospital", department_id=None)
    foreign = create(db_session, forecast_case, department_id=forecast_case["foreign"].department_id)
    assert sources.source_current(db_session, seed["director_user"], own)
    for inaccessible in (hospital, foreign):
        with pytest.raises(HTTPException) as denied:
            sources.source_current(db_session, seed["director_user"], inaccessible)
        assert denied.value.status_code == 403
    snapshot = sources.forecast_context(db_session, seed["director_user"], {"forecast_series_id": own.series_id, "horizon_days": 7}).data
    seed["director_doctor"].department_id = forecast_case["foreign"].department_id
    db_session.commit()
    with pytest.raises(HTTPException):
        sources.authorize_forecast_snapshot(db_session, seed["director_user"], snapshot)
    db_session.add(AIFeatureConfig(feature_key="visit_forecast", enabled=0, allowed_roles_json='["admin"]', updated_by=seed["super_admin_user"].user_id))
    db_session.commit()
    with pytest.raises(HTTPException):
        sources.forecast_scope(db_session, seed["director_user"])
    assert sources.source_current(db_session, seed["admin_user"], hospital)


@pytest.mark.asyncio
async def test_real_admin_api_preview_create_list_revoke_are_immutable_and_audited_without_inference(forecast_client, db_session, forecast_case, auth_headers):
    seed = forecast_case["seed"]
    super_headers = auth_headers(seed["super_admin_user"].username)
    initial_runs = db_session.query(AIRun).count()
    observed = await forecast_client.post("/api/ai/admin/forecast-series/preview", headers=super_headers, json=forecast_case["values"])
    assert observed.status_code == 200, observed.text
    assert observed.json()["data"]["observations"][1]["value"] is None
    response = await forecast_client.post("/api/ai/admin/forecast-series", headers=super_headers, json=create_body(db_session, forecast_case))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    series_id, frozen = data["series_id"], db_session.get(AIForecastSeries, data["series_id"]).source_json
    assert data["current"] is True
    assert data["source"]["observations"][1]["value"] == 0
    listing = await forecast_client.get("/api/ai/forecast-series", headers=auth_headers(seed["director_user"].username))
    assert listing.status_code == 200
    assert listing.json()["data"]["items"][0]["freshness"] == "not_checked"
    assert "coverage_note" not in listing.json()["data"]["items"][0]
    assert "source" not in listing.json()["data"]["items"][0]
    revoked = await forecast_client.post(f"/api/ai/admin/forecast-series/{series_id}/revoke", headers=super_headers, json={"expected_revision": 1, "reason": "合成来源完整性声明撤回"})
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["data"]["status"] == "revoked"
    assert revoked.json()["data"]["revision"] == 2
    assert revoked.json()["data"]["current"] is False
    assert db_session.get(AIForecastSeries, series_id).source_json == frozen
    retry = await forecast_client.post(f"/api/ai/admin/forecast-series/{series_id}/revoke", headers=super_headers, json={"expected_revision": 2, "reason": "不能再次修改"})
    assert retry.status_code == 409
    assert (await forecast_client.get("/api/ai/forecast-series", headers=auth_headers(seed["director_user"].username))).json()["data"]["items"] == []
    assert (await forecast_client.get("/api/ai/admin/forecast-series", headers=super_headers)).json()["data"]["items"][0]["status"] == "revoked"
    logs = db_session.query(AIAuditEvent).filter(AIAuditEvent.action.like("forecast_series.%")).all()
    assert [event.action for event in logs] == ["forecast_series.create", "forecast_series.revoke"]
    assert NOTE not in str([event.detail_json for event in logs])
    assert forecast_case["records"][0].registration_uuid not in str([event.detail_json for event in logs])
    assert db_session.query(AIRun).count() == initial_runs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"coverage_confirmed": 1},
        {"days_ended_confirmed": "true"},
        {"timezone_confirmed": False},
        {"coverage_note": "太短"},
        {"coverage_note": " " * 25},
        {"name": " "},
        {"observations": []},
        {"department_id": True},
    ],
)
async def test_api_rejects_coerced_attestations_and_client_supplied_series(forecast_client, db_session, forecast_case, auth_headers, changes):
    response = await forecast_client.post(
        "/api/ai/admin/forecast-series", headers=auth_headers(forecast_case["seed"]["super_admin_user"].username), json=create_body(db_session, forecast_case, **changes)
    )
    assert response.status_code == 422, response.text
    assert db_session.query(AIForecastSeries).count() == 0


@pytest.mark.asyncio
async def test_preview_digest_change_or_wrong_revision_cannot_save_or_revoke(forecast_client, db_session, forecast_case, auth_headers):
    headers = auth_headers(forecast_case["seed"]["super_admin_user"].username)
    body = create_body(db_session, forecast_case)
    forecast_case["records"][0].time += datetime.timedelta(microseconds=1)
    db_session.commit()
    failed = await forecast_client.post("/api/ai/admin/forecast-series", headers=headers, json=body)
    assert failed.status_code == 409
    assert db_session.query(AIForecastSeries).count() == 0
    created = await forecast_client.post("/api/ai/admin/forecast-series", headers=headers, json=create_body(db_session, forecast_case))
    series_id = created.json()["data"]["series_id"]
    failed = await forecast_client.post(f"/api/ai/admin/forecast-series/{series_id}/revoke", headers=headers, json={"expected_revision": 2, "reason": "旧管理页面"})
    assert failed.status_code == 409
    assert db_session.get(AIForecastSeries, series_id).status == "active"


@pytest.mark.asyncio
async def test_directory_filters_current_scope_and_management_is_super_only(forecast_client, db_session, forecast_case, auth_headers):
    own = create(db_session, forecast_case)
    create(db_session, forecast_case, scope="hospital", department_id=None)
    create(db_session, forecast_case, department_id=forecast_case["foreign"].department_id)
    seed = forecast_case["seed"]
    listed = await forecast_client.get("/api/ai/forecast-series", headers=auth_headers(seed["director_user"].username))
    assert [row["series_id"] for row in listed.json()["data"]["items"]] == [own.series_id]
    denied = await forecast_client.get("/api/ai/forecast-series", headers=auth_headers(seed["director_user"].username), params={"department_id": forecast_case["foreign"].department_id})
    assert denied.status_code == 403
    for role in ("admin_user", "director_user", "doctor_user", "patient_user"):
        headers = auth_headers(seed[role].username)
        assert (await forecast_client.get("/api/ai/admin/forecast-series", headers=headers)).status_code == 403
        assert (await forecast_client.post("/api/ai/admin/forecast-series/preview", headers=headers, json=forecast_case["values"])).status_code == 403
        assert (await forecast_client.get(f"/api/ai/admin/forecast-series/{own.series_id}", headers=headers)).status_code == 403
    assert (await forecast_client.get("/api/ai/forecast-series", headers=auth_headers(seed["doctor_user"].username))).status_code == 403


def test_migration_real_upgrade_downgrade_preserves_legacy_records_and_matches_model(tmp_path):
    url = "sqlite:///" + str(tmp_path / "forecast-migration.sqlite")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_registration(registration_uuid,time,status) VALUES('synthetic-legacy-registration','2001-02-03 04:05:06.123456',3)"))
    command.downgrade(config, "20261020_ai_nursing_sources")
    assert AIForecastSeries.__tablename__ not in inspect(engine).get_table_names()
    command.upgrade(config, "20261020_ai_forecast_series")
    engine.dispose()
    assert {column["name"] for column in inspect(engine).get_columns(AIForecastSeries.__tablename__)} == set(AIForecastSeries.__table__.columns.keys())
    assert {index["name"] for index in inspect(engine).get_indexes(AIForecastSeries.__tablename__)} == {"idx_ai_forecast_scope_status", "idx_ai_forecast_created"}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT time,status FROM hoimsystem_registration WHERE registration_uuid='synthetic-legacy-registration'")).one() == ("2001-02-03 04:05:06.123456", 3)
    engine.dispose()
    ddl = str(CreateTable(AIForecastSeries.__table__).compile(dialect=mysql.dialect()))
    assert "create_time DATETIME(6) NOT NULL" in ddl
    assert "revoked_at DATETIME(6)" in ddl
