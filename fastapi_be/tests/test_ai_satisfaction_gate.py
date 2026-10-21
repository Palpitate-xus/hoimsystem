"""Actual emitted first-lock SQL and SQLite idempotence; MySQL race is external."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import mysql

from app.ai.satisfaction_models import AISatisfactionWriteGate
from app.ai.satisfaction_write_guard import lock_satisfaction_gate


def test_actual_mysql_first_statement_requests_direct_exclusive_duplicate_update():
    statements = []

    class CapturedError(Exception):
        pass

    class CaptureFirstStatement:
        no_autoflush = nullcontext()

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="mysql"))

        def execute(self, statement):
            statements.append(str(statement.compile(dialect=mysql.dialect())))
            raise CapturedError()

    with pytest.raises(CapturedError):
        lock_satisfaction_gate(CaptureFirstStatement())
    assert len(statements) == 1 and statements[0].startswith("INSERT INTO hoimsystem_ai_satisfaction_write_gate")
    assert "ON DUPLICATE KEY UPDATE revision = hoimsystem_ai_satisfaction_write_gate.revision" in statements[0]
    assert "IGNORE" not in statements[0]


def test_actual_sqlite_reentrant_gate_retains_singleton_and_original_revision(db_session):
    first = lock_satisfaction_gate(db_session)
    second = lock_satisfaction_gate(db_session)
    assert first is second and first.gate_id == 1 and first.revision == 1
    assert db_session.query(AISatisfactionWriteGate).count() == 1
    db_session.rollback()
