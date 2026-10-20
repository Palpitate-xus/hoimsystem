"""Only new temporary databases: extension migration preserves all legacy facts."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from alembic import command
from app.db_migrate import migrate
from app.models import InpatientObservation, InpatientUrineInterval


def test_new_extension_migration_preserves_unzoned_legacy_values_without_backfill(tmp_path):
    url = "sqlite:///" + str(tmp_path / "inpatient-observations-only.sqlite")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    command.downgrade(config, "20261020_ai_forecast_series")
    engine = create_engine(url)
    assert InpatientObservation.__tablename__ not in inspect(engine).get_table_names()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_patient(patient_id,name,identity) VALUES(91001,'synthetic immutable migration','migration-observation-only')"))
        connection.execute(text("INSERT INTO hoimsystem_admission(admission_id,patient_id,status,admission_time) VALUES('legacy-admission-not-uuid',91001,2,'2001-02-03 04:05:06.123456')"))
        connection.execute(text("INSERT INTO hoimsystem_vital_sign(vital_id,patient_id,pulse,temperature,check_time) VALUES(91001,91001,0,36.5,'2002-03-04 05:06:07.000001')"))
        connection.execute(
            text(
                "INSERT INTO hoimsystem_critical_care_record(record_id,admission_id,patient_id,nurse_id,record_time,consciousness,gcs_score,urine_output,note) VALUES('legacy-critical','legacy-admission-not-uuid',91001,91001,'2003-04-05 06:07:08',0,15,'原尿量无区间','retain original')"
            )
        )
    legacy_tables = ["hoimsystem_patient", "hoimsystem_admission", "hoimsystem_vital_sign", "hoimsystem_critical_care_record"]
    with engine.connect() as connection:
        before = {table: connection.execute(text("SELECT * FROM " + table)).all() for table in legacy_tables}
    command.upgrade(config, "20261020_inpatient_observations")
    for model in [InpatientObservation, InpatientUrineInterval]:
        assert {c["name"] for c in inspect(engine).get_columns(model.__tablename__)} == set(model.__table__.columns.keys())
        assert {c["name"] for c in inspect(engine).get_check_constraints(model.__tablename__)} == {c.name for c in model.__table__.constraints if c.__class__.__name__ == "CheckConstraint"}
        assert {c["name"] for c in inspect(engine).get_indexes(model.__tablename__)} == {c.name for c in model.__table__.indexes}
        assert {c["referred_table"] for c in inspect(engine).get_foreign_keys(model.__tablename__)} == {"hoimsystem_patient", "hoimsystem_admission", "hoimsystem_users"}
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM " + model.__tablename__)) == 0
    with engine.connect() as connection:
        assert {table: connection.execute(text("SELECT * FROM " + table)).all() for table in legacy_tables} == before
    command.downgrade(config, "20261020_ai_forecast_series")
    assert InpatientObservation.__tablename__ not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert {table: connection.execute(text("SELECT * FROM " + table)).all() for table in legacy_tables} == before
    engine.dispose()


def test_mysql_extension_clocks_retain_six_microseconds_and_governance_constraints():
    for model, time_fields in [(InpatientObservation, ["observed_at", "recorded_at", "revoked_at"]), (InpatientUrineInterval, ["start_at", "end_at", "recorded_at", "revoked_at"])]:
        ddl = str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
        for field in time_fields:
            assert field + " DATETIME(6)" in ddl
        assert "CHECK (status IN ('active', 'revoked'))" in ddl
        assert "revision = 1" in ddl and "revision = 2" in ddl
