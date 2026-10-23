"""Other native domains retain their old Gate order when78 is installed."""

# ruff: noqa: F811 -- actual old Charge fixture is intentionally registered.

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.dialects import mysql

from app.ai.charge_reconciliation_runtime import create_charge_run
from app.ai.schemas import FeedbackWrite
from app.routers import ai, ai_admin
from tests.test_ai_charge_reconciliation_runtime import configured
from tests.test_ai_charge_reconciliation_sources import charge_case  # noqa: F401


@pytest.mark.parametrize("path", ["detail", "cancel", "feedback", "trace"])
def test_existing_charge_gate_precedes_foreign_document_anchor_queries_on_all_four_shared_routes(charge_case, path):
    actor, request, *_ = configured(charge_case)
    db = charge_case["db"]
    run = create_charge_run(db, actor, request)
    rid = inspect(run).identity[0]
    statements = []

    def capture(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", capture)
    try:
        try:
            if path == "detail":
                ai.run_detail(rid, db=db, user=actor)
            elif path == "cancel":
                ai.cancel_run(rid, db=db, user=actor)
            elif path == "feedback":
                ai.review_result(rid, FeedbackWrite(outcome="accepted"), db=db, user=actor)
            else:
                ai_admin.inspect_run_trace(rid, db=db, user=actor)
        except HTTPException as exc:
            assert path == "feedback" and exc.status_code == 409
    finally:
        event.remove(db, "do_orm_execute", capture)
    gate = next(index for index, sql in enumerate(statements) if "hoimsystem_ai_charge_write_gate" in sql)
    foreign = next(index for index, sql in enumerate(statements) if "hoimsystem_ai_document_extraction_run_anchor" in sql)
    assert gate < foreign
    before = statements[:gate]
    assert all("hoimsystem_ai_document_extraction_run_anchor" not in sql for sql in before)
    # Any new pre-dispatch probe is only78's own three technical columns, not
    # a retained Artifact/Run lock or a full all-domain UNION.
    for sql in before:
        if "hoimsystem_ai_infection_run_artifact" in sql:
            assert "UNION" not in sql and "source_json" not in sql and "result_json" not in sql
            assert "FOR UPDATE" not in sql and "LOCK IN SHARE MODE" not in sql
