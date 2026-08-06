from sqlalchemy import create_engine, text

from app.schema_compat import ensure_operation_log_schema


def test_operation_log_schema_adds_missing_columns():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE hoimsystem_operation_log (
                    log_id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    action VARCHAR(50),
                    target VARCHAR(100),
                    result VARCHAR(20),
                    ip VARCHAR(40),
                    create_time DATETIME
                )
                """
            )
        )

    ensure_operation_log_schema(engine)
    ensure_operation_log_schema(engine)

    columns = {row[1] for row in engine.connect().execute(text("PRAGMA table_info(hoimsystem_operation_log)"))}
    assert {"username", "role", "detail", "status_code", "method", "path"} <= columns
