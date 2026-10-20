"""Exercise a real prior-head upgrade and rollback with existing business data."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command


def test_ai_upgrade_and_rollback_preserve_business_data(tmp_path):
    path = tmp_path / "ai-upgrade.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE hoimsystem_users (user_id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE hoimsystem_patient (patient_id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE hoimsystem_department (department_id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO hoimsystem_users VALUES (42)")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.stamp(config, "20260911_drg_rule_null_safe_unique")
    command.upgrade(config, "20261020_ai_platform")
    assert "hoimsystem_ai_feature_config" in inspect(engine).get_table_names()
    assert "hoimsystem_ai_run" in inspect(engine).get_table_names()
    command.upgrade(config, "20261020_ai_task_leases")
    assert "lease_token" in {item["name"] for item in inspect(engine).get_columns("hoimsystem_ai_run")}
    command.downgrade(config, "20261020_ai_platform")
    assert "lease_token" not in {item["name"] for item in inspect(engine).get_columns("hoimsystem_ai_run")}
    command.downgrade(config, "20260911_drg_rule_null_safe_unique")
    assert not any(name.startswith("hoimsystem_ai_") for name in inspect(engine).get_table_names())
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT user_id FROM hoimsystem_users")) == 42
    engine.dispose()
