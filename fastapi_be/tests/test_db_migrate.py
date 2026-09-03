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
