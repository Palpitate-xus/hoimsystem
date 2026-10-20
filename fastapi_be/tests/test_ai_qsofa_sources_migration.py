"""Actual isolated SQLite upgrade/downgrade and MySQL source DDL without hospital connections."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from alembic import command
from app.ai.models import AIQsofaAssessment
from app.db_migrate import migrate
from app.models import InpatientGcsObservation


def test_qsofa_extension_up_down_up_only_adds_two_tables_and_preserves_legacy_defaults_clocks_and_facts(tmp_path):
    url = "sqlite:///" + str(tmp_path / "qsofa-extension.sqlite")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    command.downgrade(config, "20261020_ai_aki_sources")
    engine = create_engine(url)
    before_tables = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_patient(patient_id,name,identity) VALUES(95001,'synthetic preserved qSOFA','migration-qsofa')"))
        connection.execute(text("INSERT INTO hoimsystem_admission(admission_id,patient_id,status,admission_time) VALUES('legacy-original-admission',95001,2,'2001-02-03 04:05:06.123456')"))
        connection.execute(text("INSERT INTO hoimsystem_vital_sign(vital_id,patient_id,pulse,temperature,check_time) VALUES(95001,95001,0,36.5,'2002-03-04 05:06:07.654321')"))
        connection.execute(
            text(
                "INSERT INTO hoimsystem_icu_score(score_id,patient_id,admission_id,score_type,total_score,assess_time,create_time) VALUES(95001,95001,'legacy-original-admission','gcs',15,'2003-04-05 06:07:08.123456','2003-04-06 06:07:08.654321')"
            )
        )
    legacy = [
        "hoimsystem_patient",
        "hoimsystem_admission",
        "hoimsystem_vital_sign",
        "hoimsystem_icu_score",
        "hoimsystem_critical_care_record",
        "hoimsystem_inpatient_observation",
        "hoimsystem_ai_observation_window",
        "hoimsystem_inpatient_lab_source",
        "hoimsystem_ai_news2_assessment",
        "hoimsystem_ai_aki_assessment",
    ]
    with engine.connect() as connection:
        before = {name: connection.execute(text("SELECT * FROM " + name)).all() for name in legacy}
        before_ddl = {name: connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name}).scalar_one() for name in legacy}
    command.upgrade(config, "20261020_qsofa_sources")
    assert set(inspect(engine).get_table_names()) - before_tables == {AIQsofaAssessment.__tablename__, InpatientGcsObservation.__tablename__}
    for model in (AIQsofaAssessment, InpatientGcsObservation):
        table = model.__tablename__
        inspector = inspect(engine)
        assert {column["name"] for column in inspector.get_columns(table)} == set(model.__table__.columns.keys())
        assert {constraint["name"] for constraint in inspector.get_check_constraints(table)} == {
            constraint.name for constraint in model.__table__.constraints if constraint.__class__.__name__ == "CheckConstraint"
        }
        assert {index["name"] for index in inspector.get_indexes(table)} == {index.name for index in model.__table__.indexes}
        assert {constraint["name"] for constraint in inspector.get_unique_constraints(table)} == {
            constraint.name for constraint in model.__table__.constraints if constraint.__class__.__name__ == "UniqueConstraint"
        }
    command.downgrade(config, "20261020_ai_aki_sources")
    assert set(inspect(engine).get_table_names()) == before_tables
    command.upgrade(config, "20261020_qsofa_sources")
    with engine.connect() as connection:
        assert {name: connection.execute(text("SELECT * FROM " + name)).all() for name in legacy} == before
        assert {name: connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name}).scalar_one() for name in legacy} == before_ddl
        assert all(connection.scalar(text("SELECT COUNT(*) FROM " + model.__tablename__)) == 0 for model in (AIQsofaAssessment, InpatientGcsObservation))
        icu = connection.execute(text("SELECT total_score,assessed_at,calculation_version FROM hoimsystem_icu_score WHERE score_id=95001")).one()
        assert icu == (15, None, "legacy_unverified")
    engine.dispose()


def test_mysql_qsofa_gcs_six_new_clocks_preserve_microseconds_and_original_payload_capacity():
    for model, clocks, body in [
        (InpatientGcsObservation, ("observed_at", "recorded_at", "revoked_at"), "payload_json"),
        (AIQsofaAssessment, ("evaluation_at", "created_at", "revoked_at"), "snapshot_json"),
    ]:
        ddl = str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
        for name in clocks:
            assert f"{name} DATETIME(6)" in ddl
        assert f"{body} {'MEDIUMTEXT' if model is AIQsofaAssessment else 'TEXT'} NOT NULL" in ddl
        assert "revision = 1" in ddl and "revision = 2" in ddl
    assert "evaluation_at = created_at" in str(CreateTable(AIQsofaAssessment.__table__).compile(dialect=mysql.dialect()))
    assert "total_score" not in InpatientGcsObservation.__table__.columns
