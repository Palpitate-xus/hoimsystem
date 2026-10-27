"""Actual SQL counts must lock filtered PK rows and retain old dialect SQL."""

import os
import uuid

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, event, func, text
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Query, Session

from app.sql_counts import locked_row_count


@pytest.fixture(params=("sqlite", "postgresql"))
def count_database(request):
    if request.param == "postgresql":
        configured = os.environ.get("HOIM_TEST_POSTGRES_DDL_URL")
        if not configured:
            pytest.skip("HOIM_TEST_POSTGRES_DDL_URL must select the isolated loopback benchmark database")
        url = make_url(configured)
        assert url.get_backend_name() == "postgresql" and url.host in {"localhost", "127.0.0.1", "::1"} and url.database == "hoimsystem_benchmark"
        engine = create_engine(url, connect_args={"options": "-c statement_timeout=10000"})
        schema = "validation_counts_" + uuid.uuid4().hex
        with engine.begin() as connection:
            connection.execute(text('CREATE SCHEMA "' + schema + '"'))
    else:
        engine, schema = create_engine("sqlite:///:memory:"), None
    metadata = MetaData(schema=schema)
    items = Table("count_items", metadata, Column("id", Integer, primary_key=True), Column("group_id", Integer, nullable=False))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(items.insert(), [{"id": 1, "group_id": 1}, {"id": 2, "group_id": 2}, {"id": 3, "group_id": 1}])
    try:
        yield engine, items
    finally:
        if schema:
            with engine.begin() as connection:
                connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
        engine.dispose()


@pytest.mark.parametrize("aggregate", (False, True))
@pytest.mark.parametrize(("group_id", "expected"), ((1, 2), (8, 0)))
def test_actual_current_count_filters_only_pk_and_keeps_requested_lock(count_database, aggregate, group_id, expected):
    engine, items = count_database
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with Session(engine) as db:
            query = db.query(items.c.id, items.c.group_id).filter(items.c.group_id == group_id).populate_existing().with_for_update(read=True)
            assert locked_row_count(query, items.c.id, aggregate=aggregate) == expected
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    if engine.dialect.name == "postgresql":
        assert "FOR SHARE" in statements[0] and "count(" not in statements[0].lower()
        assert "SELECT " + items.schema + ".count_items.id " in statements[0]
    else:
        assert "count(" in statements[0].lower()


@pytest.mark.parametrize("shared", (True, False))
@pytest.mark.parametrize("count_database", ("postgresql",), indirect=True)
def test_actual_postgresql_count_retains_row_lock_until_rollback(count_database, shared):
    engine, items = count_database
    from sqlalchemy.exc import OperationalError

    with Session(engine) as first:
        assert locked_row_count(first.query(items.c.id).filter(items.c.id == 1).with_for_update(read=shared), items.c.id, aggregate=True) == 1
        # A different filtered row remains writable; the matching row stays
        # locked even though the caller receives only a count.
        with engine.begin() as other:
            other.execute(text("SET LOCAL lock_timeout='150ms'"))
            other.execute(items.update().where(items.c.id == 2).values(group_id=7))
        with pytest.raises(OperationalError) as failure, engine.begin() as other:
            other.execute(text("SET LOCAL lock_timeout='150ms'"))
            other.execute(items.update().where(items.c.id == 1).values(group_id=7))
        assert failure.value.orig.pgcode == "55P03"
        first.rollback()
        with engine.begin() as other:
            other.execute(text("SET LOCAL lock_timeout='150ms'"))
            other.execute(items.update().where(items.c.id == 1).values(group_id=7))


@pytest.mark.parametrize("aggregate", (False, True))
def test_mysql_current_count_sql_and_index_hint_remain_identical(monkeypatch, aggregate):
    from types import SimpleNamespace

    items = Table("legacy_count_items", MetaData(), Column("id", Integer, primary_key=True))
    db = Session()
    monkeypatch.setattr(db, "get_bind", lambda **_kwargs: SimpleNamespace(dialect=mysql.dialect()))
    monkeypatch.setattr(Query, "scalar", lambda query: str(query.statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})))
    query = db.query(items.c.id).with_hint(items, "FORCE INDEX (PRIMARY)", dialect_name="mysql").filter(items.c.id > 2).with_for_update(read=True)
    expected = query.with_entities(func.count(items.c.id)).scalar() if aggregate else query.with_entities(items.c.id).count()
    actual = locked_row_count(query, items.c.id, aggregate=aggregate)
    assert actual == expected
    assert "FORCE INDEX (PRIMARY)" in actual and "LOCK IN SHARE MODE" in actual
