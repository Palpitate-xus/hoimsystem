"""Actual bodyless queries and MySQL compilation; real RR proof is separate."""

# ruff: noqa: F811 -- same-case actual Source fixture registration is intentional.

from sqlalchemy import event
from sqlalchemy.dialects import mysql

from app.ai import infection_cluster_registry as registry
from app.ai import infection_cluster_sources as sources
from tests.test_ai_infection_cluster_task_storage import profile_case, task_case  # noqa: F401


def test_registry_and_snapshot_totals_use_actual_current_share_query_without_clinical_body(task_case):
    db, actor = task_case["db"], task_case["author"]
    statements = []

    def capture(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", capture)
    try:
        definitions = registry.directory(db, actor, "definition", page=1, size=20)
        snapshots = sources.snapshot_directory(db, actor, page=1, size=20)
    finally:
        event.remove(db, "do_orm_execute", capture)
    assert definitions["total"] == len(definitions["items"]) == 1
    assert snapshots["total"] == len(snapshots["items"]) == 1
    counts = [sql for sql in statements if "count(" in sql.lower()]
    assert len(counts) == 2 and all("LOCK IN SHARE MODE" in sql for sql in counts)
    assert any("hoimsystem_ai_infection_definition" in sql for sql in counts)
    assert any("hoimsystem_ai_infection_snapshot" in sql for sql in counts)
    assert not any(".payload_json" in sql or ".private_json" in sql or ".public_json" in sql for sql in statements)
