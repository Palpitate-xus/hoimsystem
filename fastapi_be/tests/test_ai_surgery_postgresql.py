"""Surgery gate SQL compatibility and actual isolated PostgreSQL transactions."""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.ai.surgery_facts import lock_write_gate
from app.ai.surgery_models import AISurgeryWriteGate


@pytest.mark.parametrize(
    ("name", "dialect", "expected"),
    [
        (
            "mysql", mysql.dialect(),
            "INSERT IGNORE INTO hoimsystem_ai_surgery_write_gate (gate_id, revision) VALUES (1, 1)",
        ),
        (
            "sqlite", sqlite.dialect(),
            "INSERT INTO hoimsystem_ai_surgery_write_gate (gate_id, revision) VALUES (1, 1) ON CONFLICT (gate_id) DO NOTHING",
        ),
        (
            "postgresql", postgresql.dialect(),
            "INSERT INTO hoimsystem_ai_surgery_write_gate (gate_id, revision) VALUES (1, 1) "
            "ON CONFLICT (gate_id) DO UPDATE SET revision = hoimsystem_ai_surgery_write_gate.revision",
        ),
    ],
)
def test_gate_uses_exact_supported_dialect_sql_and_current_exclusive_read(name, dialect, expected):
    db = MagicMock()
    db.get_bind.return_value.dialect.name = name
    query = db.query.return_value.filter_by.return_value
    query.populate_existing.return_value = query
    query.with_for_update.return_value = query
    result = SimpleNamespace(gate_id=1, revision=7)
    query.one.return_value = result

    assert lock_write_gate(db) is result
    statement = db.execute.call_args.args[0]
    assert str(statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True})) == expected
    query.populate_existing.assert_called_once_with()
    query.with_for_update.assert_called_once_with()
    db.commit.assert_not_called()


def test_unknown_dialect_is_rejected_before_any_gate_write():
    db = MagicMock()
    db.get_bind.return_value.dialect.name = "unsupported"
    with pytest.raises(HTTPException) as failure:
        lock_write_gate(db)
    assert failure.value.status_code == 409
    db.execute.assert_not_called()


@pytest.fixture
def surgery_postgresql_engine():
    value = os.getenv("HOIM_TEST_POSTGRES_URL")
    if not value:
        pytest.skip("set HOIM_TEST_POSTGRES_URL to the isolated local hoimsystem_benchmark database")
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or url.database != "hoimsystem_benchmark" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("refusing a surgery gate test outside the explicit local benchmark database")
    owner = create_engine(url, pool_pre_ping=True, connect_args={"options": "-c statement_timeout=10000"})
    schema = "surgery_gate_" + uuid.uuid4().hex
    engine = owner.execution_options(schema_translate_map={None: schema})
    with owner.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        # Only this gate table in our unique schema; never create/drop the
        # shared benchmark schema or its acceptance records.
        AISurgeryWriteGate.__table__.create(engine)
        yield engine
    finally:
        with owner.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        owner.dispose()


@pytest.mark.parametrize("existing", [False, True], ids=["empty_gate", "existing_epoch"])
@pytest.mark.parametrize("release", ["commit", "rollback"])
def test_actual_postgresql_gate_blocks_contender_until_transaction_release(surgery_postgresql_engine, existing, release):
    engine = surgery_postgresql_engine
    revision = 7 if existing else 1
    if existing:
        with Session(engine) as seed:
            seed.add(AISurgeryWriteGate(gate_id=1, revision=revision))
            seed.commit()
    entered, completed = threading.Event(), threading.Event()

    def contender():
        with Session(engine) as other:
            entered.set()
            row = lock_write_gate(other)
            actual = row.revision
            other.commit()
            completed.set()
            return actual

    with Session(engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
        assert lock_write_gate(first).revision == revision
        future = pool.submit(contender)
        try:
            assert entered.wait(timeout=3)
            assert not completed.wait(timeout=0.15), "contender escaped the first transaction's surgery gate"
        finally:
            getattr(first, release)()
        assert future.result(timeout=10) == revision
    with Session(engine) as check:
        assert check.query(AISurgeryWriteGate).count() == 1
        assert check.get(AISurgeryWriteGate, 1).revision == revision


def test_actual_postgresql_bootstrap_is_rolled_back_with_its_caller(surgery_postgresql_engine):
    with Session(surgery_postgresql_engine) as writer:
        assert lock_write_gate(writer).revision == 1
        writer.rollback()
    with Session(surgery_postgresql_engine) as reader:
        assert reader.query(AISurgeryWriteGate).count() == 0
        assert lock_write_gate(reader).revision == 1
        reader.commit()
