import pytest
from sqlalchemy import create_engine, inspect

from app.db_migrate import migrate


def test_migrate_bootstraps_fresh_database(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"

    assert migrate(database_url) == "bootstrapped"

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "alembic_version" in tables
        assert "hoimsystem_users" in tables
        assert "hoimsystem_scheduler_job_state" in tables
        assert "hoimsystem_integration_outbox" in tables
        assert "hoimsystem_medication_administration" in tables
        assert "hoimsystem_patient_clinical_profile" in tables
        assert "hoimsystem_drg_rule" in tables
        assert "hoimsystem_daily_operational_metric" in tables
        user_indexes = {item["name"] for item in inspect(engine).get_indexes("hoimsystem_users")}
        order_indexes = {item["name"] for item in inspect(engine).get_indexes("hoimsystem_inpatient_order")}
        assert "uq_users_username" in user_indexes
        assert "idx_inpatient_order_admission_status_time" in order_indexes
    finally:
        engine.dispose()


def test_migrate_refuses_unversioned_existing_database(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE legacy_data (id INTEGER PRIMARY KEY)")
    finally:
        engine.dispose()

    try:
        migrate(database_url)
    except RuntimeError as exc:
        assert "未纳入 Alembic 管理" in str(exc)
    else:
        raise AssertionError("unversioned legacy database must not be silently adopted")


@pytest.mark.parametrize("versions", [[], [""], [None], ["not-a-revision"], ["head"], ["1f24ea81"]])
def test_migrate_refuses_empty_or_invalid_version_records_before_schema_changes(tmp_path, versions):
    from sqlalchemy import create_engine, inspect, text

    from app.db_migrate import migrate

    database_url = f"sqlite:///{tmp_path / 'invalid-version.db'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE clinical_sentinel (id INTEGER PRIMARY KEY, note TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO clinical_sentinel VALUES (1, 'preserve existing records')"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) PRIMARY KEY)"))
        for version in versions:
            connection.execute(text("INSERT INTO alembic_version VALUES (:version)"), {"version": version})
    before = set(inspect(engine).get_table_names())
    with pytest.raises(RuntimeError, match="Alembic.*版本"):
        migrate(database_url)
    assert set(inspect(engine).get_table_names()) == before
    with engine.connect() as connection:
        assert connection.execute(text("SELECT note FROM clinical_sentinel WHERE id=1")).scalar_one() == "preserve existing records"
    engine.dispose()
