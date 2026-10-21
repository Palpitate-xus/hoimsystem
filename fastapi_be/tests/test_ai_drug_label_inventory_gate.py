"""Compile the actual gate statement; actual lock waits live in private MySQL evidence."""

from contextlib import nullcontext
from types import SimpleNamespace

from sqlalchemy.dialects import mysql

from app.ai import inventory_write_guard as guard


def test_actual_mysql_gate_helper_acquires_duplicate_exclusive_lock_directly():
    statements = []
    trace = []
    row = object()

    class Query:
        def filter_by(self, **values):
            assert values == {"gate_id": 1}
            return self

        def populate_existing(self):
            trace.append("current")
            return self

        def with_for_update(self, *, read):
            assert not read
            trace.append("exclusive")
            return self

        def one(self):
            return row

    db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=mysql.dialect()), no_autoflush=nullcontext(), execute=statements.append, query=lambda _: Query())
    assert guard.lock_inventory_gate(db) is row
    assert len(statements) == 1 and trace == ["current", "exclusive"]
    actual = str(statements[0].compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "ON DUPLICATE KEY UPDATE revision = hoimsystem_ai_inventory_write_gate.revision" in actual
    assert "INSERT IGNORE" not in actual and "VALUES (1, 1)" in actual
