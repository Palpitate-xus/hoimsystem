"""Small, idempotent schema compatibility updates for existing development databases."""

from sqlalchemy import Engine, inspect, text


OPERATION_LOG_COLUMNS = {
    "username": "VARCHAR(50)",
    "role": "VARCHAR(20)",
    "detail": "VARCHAR(500)",
    "status_code": "INTEGER",
    "method": "VARCHAR(10)",
    "path": "VARCHAR(200)",
}


def ensure_operation_log_schema(engine: Engine) -> None:
    """Add audit columns introduced after the original SQLite schema.

    ``Base.metadata.create_all`` does not alter an existing table, so older
    development databases need this idempotent compatibility step at startup.
    Production schema changes remain represented by the Alembic migration.
    """

    inspector = inspect(engine)
    table_name = "hoimsystem_operation_log"
    if not inspector.has_table(table_name):
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    missing_columns = {
        name: column_type
        for name, column_type in OPERATION_LOG_COLUMNS.items()
        if name not in existing_columns
    }
    if not missing_columns:
        return

    with engine.begin() as connection:
        for name, column_type in missing_columns.items():
            connection.execute(
                text(f'ALTER TABLE "{table_name}" ADD COLUMN "{name}" {column_type}')
            )
