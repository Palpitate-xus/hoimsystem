"""Unknown nursing observations, explicit clock provenance and non-inventing migration."""

import datetime
import io
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import column, create_engine, inspect, text
from sqlalchemy.dialects import mysql

from alembic import command
from app.db_migrate import migrate
from app.models import Admission, CriticalCareRecord, IcuScoreRecord, NursingAssessment, NursingRecord, User

FIELDS = ("adl_score", "pressure_ulcer_risk", "fall_risk", "consciousness", "nutrition_risk")
NEW_REVISION = "20261020_ai_nursing_sources"
PRIOR_REVISION = "20261020_ai_image_assets"


@pytest.fixture
def nursing_case(seed_data, db_session):
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    admission = Admission(
        patient_id=seed_data["patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        department_id=seed_data["department"].department_id,
        admission_no="NS" + uuid.uuid4().hex[:16],
        status=1,
        admission_time=now,
        create_time=now,
    )
    db_session.add(admission)
    db_session.commit()
    return {"admission_id": admission.admission_id, "patient_id": admission.patient_id}


async def create_assessment(async_client, auth_headers, seed_data, case, **values):
    return await async_client.post("/api/nursingAssessment/create", headers=auth_headers(seed_data["nurse_user"].username), json={**case, **values})


@pytest.mark.asyncio
async def test_new_unknowns_are_preserved_and_empty_completion_does_not_validate_a_scale(nursing_case, seed_data, db_session, async_client, auth_headers):
    response = await create_assessment(async_client, auth_headers, seed_data, nursing_case, note="仅备注，不等于已评估", assessed_at="2026-10-20T12:00:00+08:00")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert all(data[name] is None for name in FIELDS)
    assert data["missing_fields"] == list(FIELDS)
    assert data["entry_version"] == "nullable_v1" and data["standard_scale_validated"] is False
    row = db_session.get(NursingAssessment, data["assessment_id"])
    assert all(getattr(row, name) is None for name in FIELDS)
    headers = auth_headers(seed_data["nurse_user"].username)
    rejected = await async_client.post("/api/nursingAssessment/complete", headers=headers, json={"assessment_id": row.assessment_id})
    assert rejected.status_code == 422 and "至少" in rejected.json()["detail"]
    db_session.refresh(row)
    assert row.status == 0 and row.assessed_at == datetime.datetime(2026, 10, 20, 4)
    updated = await async_client.put("/api/nursingAssessment/update", headers=headers, json={"assessment_id": row.assessment_id, "consciousness": 0})
    assert updated.json()["data"]["consciousness"] == 0
    complete = await async_client.post("/api/nursingAssessment/complete", headers=headers, json={"assessment_id": row.assessment_id})
    final = complete.json()["data"]
    assert final["status"] == 1 and final["consciousness"] == 0
    assert final["missing_fields"] == [name for name in FIELDS if name != "consciousness"]
    assert final["standard_scale_validated"] is False and final["entry_version"] == "nullable_v1"


@pytest.mark.asyncio
async def test_update_distinguishes_omission_null_and_zero_and_does_not_infer_assessment_time(nursing_case, seed_data, db_session, async_client, auth_headers):
    response = await create_assessment(async_client, auth_headers, seed_data, nursing_case, **dict.fromkeys(FIELDS, 1), note="保留原备注")
    row_id = response.json()["data"]["assessment_id"]
    headers = auth_headers(seed_data["nurse_user"].username)
    update = await async_client.put("/api/nursingAssessment/update", headers=headers, json={"assessment_id": row_id, "fall_risk": None, "pressure_ulcer_risk": 0})
    data = update.json()["data"]
    assert data["fall_risk"] is None and data["pressure_ulcer_risk"] == 0
    assert data["adl_score"] == data["consciousness"] == data["nutrition_risk"] == 1
    assert data["note"] == "保留原备注" and data["assessed_at"] is None
    assert data["missing_fields"] == ["fall_risk"]
    assert (await async_client.put("/api/nursingAssessment/update", headers=headers, json={"assessment_id": row_id, "note": None})).status_code == 422
    cleared = await async_client.put("/api/nursingAssessment/update", headers=headers, json={"assessment_id": row_id, "note": ""})
    assert cleared.json()["data"]["note"] == ""
    complete = await async_client.post("/api/nursingAssessment/complete", headers=headers, json={"assessment_id": row_id})
    assert complete.json()["data"]["assessed_at"] is None
    db_session.refresh(db_session.get(NursingAssessment, row_id))
    assert db_session.get(NursingAssessment, row_id).fall_risk is None


@pytest.mark.asyncio
async def test_assessed_at_is_explicit_utc_and_can_be_cleared_without_changing_version(nursing_case, seed_data, db_session, async_client, auth_headers):
    response = await create_assessment(
        async_client, auth_headers, seed_data, nursing_case, fall_risk=None, adl_score=0, assessed_at="2026-10-20T13:45:06.123456+08:00", entry_version="caller-cannot-certify"
    )
    data = response.json()["data"]
    assert data["entry_version"] == "nullable_v1" and data["fall_risk"] is None
    assert datetime.datetime.fromisoformat(data["assessed_at"]) == datetime.datetime(2026, 10, 20, 5, 45, 6, 123456, tzinfo=datetime.UTC)
    row = db_session.get(NursingAssessment, data["assessment_id"])
    assert row.assessed_at == datetime.datetime(2026, 10, 20, 5, 45, 6, 123456)
    headers = auth_headers(seed_data["nurse_user"].username)
    listed = await async_client.get("/api/nursingAssessment/list", headers=headers, params={"admission_id": nursing_case["admission_id"]})
    assert listed.json()["data"][0]["assessed_at"] == data["assessed_at"]
    changed = await async_client.put("/api/nursingAssessment/update", headers=headers, json={"assessment_id": row.assessment_id, "assessed_at": None})
    assert changed.json()["data"]["assessed_at"] is None and changed.json()["data"]["entry_version"] == "nullable_v1"
    changed = await async_client.put("/api/nursingAssessment/update", headers=headers, json={"assessment_id": row.assessment_id, "assessed_at": "2026-10-20T02:03:04.000789Z"})
    timestamp = changed.json()["data"]["assessed_at"]
    assert datetime.datetime.fromisoformat(timestamp) == datetime.datetime(2026, 10, 20, 2, 3, 4, 789, tzinfo=datetime.UTC)
    completed = await async_client.post("/api/nursingAssessment/complete", headers=headers, json={"assessment_id": row.assessment_id})
    assert completed.json()["data"]["assessed_at"] == timestamp


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["2026-10-20 12:00:00", "2026-10-20", "invalid", 1234567890, True, "0001-01-01T00:00:00+23:59", "2026-10-20T00:00:00.1234567Z"])
async def test_assessed_at_rejects_unstated_or_invalid_clock_before_inserting(value, nursing_case, seed_data, db_session, async_client, auth_headers):
    response = await create_assessment(async_client, auth_headers, seed_data, nursing_case, assessed_at=value)
    assert response.status_code == 422, response.text
    assert db_session.query(NursingAssessment).filter_by(admission_id=nursing_case["admission_id"]).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", [True, "0", 0.0])
async def test_assessment_items_require_actual_integers(field, value, nursing_case, seed_data, db_session, async_client, auth_headers):
    response = await create_assessment(async_client, auth_headers, seed_data, nursing_case, **{field: value})
    assert response.status_code == 422, response.text
    assert db_session.query(NursingAssessment).filter_by(admission_id=nursing_case["admission_id"]).count() == 0


@pytest.mark.asyncio
async def test_legacy_values_remain_legacy_after_edit_and_completed_records_remain_immutable(nursing_case, seed_data, db_session, async_client, auth_headers):
    now = datetime.datetime.now()
    row = NursingAssessment(**nursing_case, nurse_id=seed_data["nurse_user"].user_id, **dict.fromkeys(FIELDS, 0), note="原评估", create_time=now, update_time=now)
    db_session.add(row)
    db_session.commit()
    assert row.entry_version == "legacy_unverified" and row.assessed_at is None
    headers = auth_headers(seed_data["nurse_user"].username)
    response = await async_client.put("/api/nursingAssessment/update", headers=headers, json={"assessment_id": row.assessment_id, "note": "补充原记录说明"})
    data = response.json()["data"]
    assert data["entry_version"] == "legacy_unverified" and data["assessed_at"] is None
    assert all(data[name] == 0 for name in FIELDS) and data["standard_scale_validated"] is False
    assert (await async_client.post("/api/nursingAssessment/complete", headers=headers, json={"assessment_id": row.assessment_id})).json()["code"] == 200
    rejected = await async_client.put("/api/nursingAssessment/update", headers=headers, json={"assessment_id": row.assessment_id, "adl_score": None})
    assert rejected.status_code == 403 and rejected.json()["code"] == 403
    db_session.refresh(row)
    assert row.adl_score == 0 and row.entry_version == "legacy_unverified"


@pytest.mark.asyncio
async def test_assessment_owner_and_patient_admission_binding_remain_enforced(nursing_case, seed_data, db_session, async_client, auth_headers):
    other = User(username="nursing" + uuid.uuid4().hex[:10], password="isolated-unusable-password", user_role="nurse")
    db_session.add(other)
    db_session.commit()
    response = await create_assessment(async_client, auth_headers, seed_data, nursing_case, fall_risk=0)
    row_id = response.json()["data"]["assessment_id"]
    other_headers = auth_headers(other.username)
    for method, url in (("put", "/api/nursingAssessment/update"), ("post", "/api/nursingAssessment/complete")):
        result = await getattr(async_client, method)(url, headers=other_headers, json={"assessment_id": row_id})
        assert result.status_code == 403 and result.json()["code"] == 403
    mismatch = await create_assessment(async_client, auth_headers, seed_data, {**nursing_case, "patient_id": seed_data["patient2"].patient_id}, adl_score=20)
    assert mismatch.status_code == 400 and mismatch.json()["code"] == 500
    assert db_session.query(NursingAssessment).filter_by(admission_id=nursing_case["admission_id"]).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("record_time", "basis", "expected"),
    [
        ("2026-10-20T13:45:06.123456+08:00", "utc", datetime.datetime(2026, 10, 20, 5, 45, 6, 123456)),
        ("2026-10-20T05:45:06Z", "utc", datetime.datetime(2026, 10, 20, 5, 45, 6)),
        ("2026-10-20 13:45:06", "unspecified", datetime.datetime(2026, 10, 20, 13, 45, 6)),
        (None, "recorded_at_only", None),
    ],
)
async def test_critical_records_keep_unknowns_and_actual_time_basis(record_time, basis, expected, nursing_case, seed_data, db_session, async_client, auth_headers):
    before = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    headers = auth_headers(seed_data["nurse_user"].username)
    response = await async_client.post("/api/criticalCareRecord/create", headers=headers, json={**nursing_case, "record_time": record_time})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["consciousness"] is None and data["gcs_score"] is None
    assert data["entry_version"] == "nullable_v1" and data["time_basis"] == basis
    row = db_session.get(CriticalCareRecord, data["record_id"])
    assert row.consciousness is None and row.gcs_score is None
    assert row.record_time == expected if expected is not None else before <= row.record_time <= datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    if expected is not None:
        parsed = datetime.datetime.fromisoformat(data["record_time"])
        assert parsed.replace(tzinfo=None) == expected
        assert parsed.tzinfo == datetime.UTC if basis == "utc" else parsed.tzinfo is None
    listed = await async_client.get("/api/criticalCareRecord/list", headers=headers, params={"admission_id": nursing_case["admission_id"]})
    assert listed.json()["data"] == [data]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["consciousness", "gcs_score"])
@pytest.mark.parametrize("value", [True, "3", 3.0])
async def test_critical_assessment_values_do_not_coerce_types(field, value, nursing_case, seed_data, db_session, async_client, auth_headers):
    response = await async_client.post("/api/criticalCareRecord/create", headers=auth_headers(seed_data["nurse_user"].username), json={**nursing_case, field: value})
    assert response.status_code == 422, response.text
    assert db_session.query(CriticalCareRecord).filter_by(admission_id=nursing_case["admission_id"]).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("record_time", ["invalid", "", "2026-02-30 12:00:00", "2026-10-20", "2026-10-20T24:00:00Z", "0001-01-01T00:00:00+23:59"])
@pytest.mark.parametrize(("url", "model"), [("/api/criticalCareRecord/create", CriticalCareRecord), ("/api/nursingRecord/create", NursingRecord)])
async def test_invalid_record_time_never_silently_becomes_now(record_time, url, model, nursing_case, seed_data, db_session, async_client, auth_headers):
    response = await async_client.post(url, headers=auth_headers(seed_data["nurse_user"].username), json={**nursing_case, "record_time": record_time})
    assert response.status_code == 422, response.text
    assert db_session.query(model).filter_by(admission_id=nursing_case["admission_id"]).count() == 0


def migration_config(tmp_path):
    url = "sqlite:///" + str(tmp_path / "nursing-migration.sqlite")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    return url, config


def test_nursing_migration_preserves_legacy_values_and_has_matching_new_schema(tmp_path):
    url, config = migration_config(tmp_path)
    command.downgrade(config, PRIOR_REVISION)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_patient(patient_id,name,identity) VALUES(90001,'synthetic nursing legacy','nursing-migration-only')"))
        connection.execute(text("INSERT INTO hoimsystem_users(user_id,username,user_role) VALUES(90001,'synthetic_nurse','nurse')"))
        connection.execute(text("INSERT INTO hoimsystem_admission(admission_id,patient_id,status) VALUES('legacy-admission',90001,1)"))
        connection.execute(
            text(
                "INSERT INTO hoimsystem_nursing_assessment(assessment_id,admission_id,patient_id,nurse_id,adl_score,note,status,create_time,update_time) VALUES('legacy-assessment','legacy-admission',90001,90001,100,'retain original',0,'2001-01-01','2002-02-02')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO hoimsystem_critical_care_record(record_id,admission_id,patient_id,nurse_id,record_time,gcs_score) VALUES('legacy-critical','legacy-admission',90001,90001,'2001-01-01',15)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO hoimsystem_icu_score(patient_id,admission_id,score_type,scene,total_score,detail_json,interpretation,assess_time,create_time) VALUES(90001,'legacy-admission','sofa','icu',0,'{}','original legacy interpretation','2001-01-01','2002-02-02')"
            )
        )
    assert migrate(url) == "upgraded"
    engine.dispose()
    for model in (NursingAssessment, CriticalCareRecord, IcuScoreRecord):
        columns = {item["name"]: item for item in inspect(engine).get_columns(model.__tablename__)}
        assert set(columns) == set(model.__table__.columns.keys())
    with engine.connect() as connection:
        assessment = connection.execute(text("SELECT * FROM hoimsystem_nursing_assessment")).mappings().one()
        assert assessment["adl_score"] == 100 and all(assessment[name] == 0 for name in FIELDS if name != "adl_score")
        assert assessment["entry_version"] == "legacy_unverified" and assessment["assessed_at"] is None
        assert assessment["create_time"] == "2001-01-01" and assessment["update_time"] == "2002-02-02" and assessment["note"] == "retain original"
        critical = connection.execute(text("SELECT * FROM hoimsystem_critical_care_record")).mappings().one()
        assert critical["consciousness"] == 0 and critical["gcs_score"] == 15
        assert critical["entry_version"] == "legacy_unverified" and critical["time_basis"] == "unspecified"
        score = connection.execute(text("SELECT * FROM hoimsystem_icu_score")).mappings().one()
        assert score["total_score"] == 0 and score["interpretation"] == "original legacy interpretation" and score["detail_json"] == "{}"
        assert score["calculation_version"] == "legacy_unverified" and score["assessed_at"] is None
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == ScriptDirectory.from_config(config).get_current_head()
    columns = {item["name"]: item for item in inspect(engine).get_columns(NursingAssessment.__tablename__)}
    assert all(columns[name]["nullable"] and columns[name]["default"] is None for name in FIELDS)
    assert next(item for item in inspect(engine).get_columns(CriticalCareRecord.__tablename__) if item["name"] == "consciousness")["nullable"]
    assert {fk["referred_table"] for fk in inspect(engine).get_foreign_keys(NursingAssessment.__tablename__)} == {"hoimsystem_patient", "hoimsystem_users", "hoimsystem_admission"}
    command.downgrade(config, PRIOR_REVISION)
    engine.dispose()
    assert "entry_version" not in {item["name"] for item in inspect(engine).get_columns(NursingAssessment.__tablename__)}
    assert migrate(url) == "upgraded"
    engine.dispose()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT adl_score FROM hoimsystem_nursing_assessment")) == 100
        assert connection.scalar(text("SELECT total_score FROM hoimsystem_icu_score")) == 0
    engine.dispose()


@pytest.mark.parametrize("table", ["hoimsystem_nursing_assessment", "hoimsystem_critical_care_record"])
def test_downgrade_refuses_unknown_values_before_any_schema_or_data_change(table, tmp_path):
    url, config = migration_config(tmp_path)
    engine = create_engine(url)
    with engine.begin() as connection:
        if table == "hoimsystem_nursing_assessment":
            connection.execute(
                text(
                    "INSERT INTO hoimsystem_nursing_assessment(assessment_id,admission_id,patient_id,nurse_id,note,status,create_time,update_time) VALUES('unknown','synthetic',1,1,'missing is not normal',0,'2001-01-01','2001-01-01')"
                )
            )
        else:
            connection.execute(text("INSERT INTO hoimsystem_critical_care_record(record_id,admission_id,patient_id,nurse_id,record_time) VALUES('unknown','synthetic',1,1,'2001-01-01')"))
    before = {name: {column["name"] for column in inspect(engine).get_columns(name)} for name in (NursingAssessment.__tablename__, CriticalCareRecord.__tablename__, IcuScoreRecord.__tablename__)}
    with pytest.raises(RuntimeError, match="unknown assessment values"):
        command.downgrade(config, PRIOR_REVISION)
    engine.dispose()
    assert before == {name: {column["name"] for column in inspect(engine).get_columns(name)} for name in before}
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == NEW_REVISION
        assert connection.scalar(text("SELECT consciousness FROM " + table)) is None
    engine.dispose()


def test_mysql_nullable_migration_uses_native_ddl_with_explicit_integer_types():
    # Exercise the same upgrade with Alembic's real MySQL compiler, without any
    # database or driver connection. SQLite roundtrips above exercise data copy.
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261020_ai_nursing_sources.py"
    spec = importlib.util.spec_from_file_location("nursing_source_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert "MODIFY adl_score INTEGER NULL" in sql and "MODIFY consciousness INTEGER NULL" in sql
    assert "DEFAULT 'legacy_unverified'" in sql and "ADD COLUMN assessed_at DATETIME(6)" in sql
    assert "CHANGE record_time record_time DATETIME(6) NOT NULL" in sql
    assert "UPDATE " not in sql and "INSERT " not in sql
    for model, name in ((NursingAssessment, "assessed_at"), (CriticalCareRecord, "record_time"), (IcuScoreRecord, "assessed_at")):
        assert str(model.__table__.c[name].type.compile(dialect=mysql.dialect())) == "DATETIME(6)"
        predicate = str(module._nonzero_microseconds(column(name), "mysql").compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})).upper()
        assert f"MICROSECOND({name.upper()}) != 0" == predicate


@pytest.mark.parametrize(("table", "field"), [("hoimsystem_nursing_assessment", "assessed_at"), ("hoimsystem_critical_care_record", "record_time"), ("hoimsystem_icu_score", "assessed_at")])
def test_downgrade_refuses_even_one_microsecond_before_altering_sources(table, field, tmp_path):
    url, config = migration_config(tmp_path)
    engine = create_engine(url)
    precise = "2026-10-20 01:02:03.000001"
    with engine.begin() as connection:
        if table == "hoimsystem_nursing_assessment":
            connection.execute(
                text(
                    "INSERT INTO hoimsystem_nursing_assessment(assessment_id,admission_id,patient_id,nurse_id,adl_score,pressure_ulcer_risk,fall_risk,consciousness,nutrition_risk,status,assessed_at,create_time,update_time) VALUES('precise','synthetic',1,1,0,0,0,0,0,0,:precise,'2001-01-01','2001-01-01')"
                ),
                {"precise": precise},
            )
        elif table == "hoimsystem_critical_care_record":
            connection.execute(
                text("INSERT INTO hoimsystem_critical_care_record(record_id,admission_id,patient_id,nurse_id,record_time,consciousness) VALUES('precise','synthetic',1,1,:precise,0)"),
                {"precise": precise},
            )
        else:
            connection.execute(
                text("INSERT INTO hoimsystem_icu_score(patient_id,score_type,total_score,assessed_at,assess_time,create_time) VALUES(1,'gcs',15,:precise,'2001-01-01','2001-01-01')"),
                {"precise": precise},
            )
    before = {name: {item["name"] for item in inspect(engine).get_columns(name)} for name in (NursingAssessment.__tablename__, CriticalCareRecord.__tablename__, IcuScoreRecord.__tablename__)}
    with pytest.raises(RuntimeError, match="nonzero microsecond"):
        command.downgrade(config, PRIOR_REVISION)
    engine.dispose()
    assert before == {name: {item["name"] for item in inspect(engine).get_columns(name)} for name in before}
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT " + field + " FROM " + table)) == precise
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == NEW_REVISION
    engine.dispose()
