"""Only temporary databases: actual extension migration leaves every legacy lab fact intact."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from alembic import command
from app.db_migrate import migrate
from app.models import InpatientLabSource


def test_actual_extension_upgrade_downgrade_preserves_original_labs_and_unknown_clocks(tmp_path):
    url = "sqlite:///" + str(tmp_path / "inpatient-laboratory.sqlite")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    command.downgrade(config, "20261020_ai_lab_mappings")
    engine = create_engine(url)
    table = InpatientLabSource.__tablename__
    assert table not in inspect(engine).get_table_names()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_patient(patient_id,name,identity) VALUES(92001,'synthetic immutable lab','migration-laboratory-only')"))
        connection.execute(text("INSERT INTO hoimsystem_admission(admission_id,patient_id,status,admission_time) VALUES('legacy-admission-not-uuid',92001,2,'2001-02-03 04:05:06.123456')"))
        connection.execute(
            text(
                "INSERT INTO hoimsystem_lab_order(lab_order_id,patient_id,status,check_items,create_time,integration_status) VALUES('opaque-old-order',92001,2,'原项目不自动映射','2002-03-04 05:06:07.000001','pending')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO hoimsystem_lab_result(lab_result_id,lab_order_id,result,audit_status,report_time,critical_status) VALUES('opaque-old-report','opaque-old-order','原中文报告',1,'2003-04-05 06:07:08.654321',0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO hoimsystem_lab_observation(observation_id,lab_result_id,code_system,code,display,value_num,unit,collected_at,method,specimen_type,flag) VALUES('opaque-old-observation','opaque-old-report','local','SYN','原显示名','0.00000000','mg/dL','2004-05-06 07:08:09.123456','','','unknown')"
            )
        )
    legacy = ["hoimsystem_patient", "hoimsystem_admission", "hoimsystem_lab_order", "hoimsystem_lab_result", "hoimsystem_lab_observation", "hoimsystem_ai_lab_mapping"]
    with engine.connect() as connection:
        before = {name: connection.execute(text("SELECT * FROM " + name)).all() for name in legacy}
    command.upgrade(config, "20261020_inpatient_laboratory")
    inspector = inspect(engine)
    assert {c["name"] for c in inspector.get_columns(table)} == set(InpatientLabSource.__table__.columns.keys())
    assert {i["name"] for i in inspector.get_indexes(table)} == {i.name for i in InpatientLabSource.__table__.indexes}
    assert {c["name"] for c in inspector.get_check_constraints(table)} == {c.name for c in InpatientLabSource.__table__.constraints if c.__class__.__name__ == "CheckConstraint"}
    assert {c["name"] for c in inspector.get_unique_constraints(table)} == {"uq_inpatient_lab_active_observation"}
    assert {c["referred_table"] for c in inspector.get_foreign_keys(table)} == {
        "hoimsystem_patient",
        "hoimsystem_admission",
        "hoimsystem_lab_observation",
        "hoimsystem_users",
        "hoimsystem_ai_lab_mapping",
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM " + table)) == 0
        assert {name: connection.execute(text("SELECT * FROM " + name)).all() for name in legacy} == before
    command.downgrade(config, "20261020_ai_lab_mappings")
    assert table not in inspect(engine).get_table_names()
    command.upgrade(config, "20261020_inpatient_laboratory")
    with engine.connect() as connection:
        assert {name: connection.execute(text("SELECT * FROM " + name)).all() for name in legacy} == before
    engine.dispose()


def test_mysql_source_clocks_and_database_constraints_match_migration_contract():
    ddl = str(CreateTable(InpatientLabSource.__table__).compile(dialect=mysql.dialect()))
    for key in ("collected_at_utc", "registered_at", "available_at", "revoked_at"):
        assert f"{key} DATETIME(6)" in ddl
    assert "UNIQUE (active_observation_id)" in ddl
    assert "available_at = registered_at" in ddl and "revision = 1" in ddl and "revision = 2" in ddl
