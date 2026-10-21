"""RCA technical exceptions retain the real legacy Gate/locator order."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.dialects import mysql

from app.ai.charge_reconciliation_runtime import create_charge_run
from app.ai.schemas import FeedbackWrite
from app.routers import ai, ai_admin
from tests.test_ai_charge_reconciliation_runtime import configured
from tests.test_ai_charge_reconciliation_sources import charge_case as charge_case  # noqa: F401


@pytest.mark.parametrize("path", ["cancel", "feedback", "trace"])
def test_charge_legacy_route_keeps_gates_before_foreign_anchor_locator(charge_case, path):
    actor, request, *_ = configured(charge_case)
    db = charge_case["db"]
    run = create_charge_run(db, actor, request)
    identifier = inspect(run).identity[0]
    statements = []

    def observe(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", observe)
    try:
        try:
            if path == "cancel":
                ai.cancel_run(identifier, db=db, user=actor)
            elif path == "feedback":
                ai.review_result(identifier, FeedbackWrite(outcome="accepted"), db=db, user=actor)
            else:
                ai_admin.inspect_run_trace(identifier, db=db, user=actor)
        except HTTPException as exc:
            assert path == "feedback" and exc.status_code == 409
    finally:
        event.remove(db, "do_orm_execute", observe)
    gate = next(i for i, sql in enumerate(statements) if "hoimsystem_ai_charge_write_gate" in sql)
    original = next(i for i, sql in enumerate(statements) if "hoimsystem_ai_document_extraction_run_anchor" in sql)
    assert gate < original, (gate, original, statements[: gate + 1])
