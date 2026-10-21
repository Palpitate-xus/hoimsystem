"""Real existing Charge routes retain Billing Gate before foreign classification."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.dialects import mysql

from app.ai.charge_reconciliation_runtime import create_charge_run
from app.ai.schemas import FeedbackWrite
from app.routers import ai, ai_admin
from tests.test_ai_charge_reconciliation_runtime import configured
from tests.test_ai_charge_reconciliation_sources import charge_case as charge_case


@pytest.mark.parametrize("path", ["detail", "cancel", "feedback", "trace"])
def test_actual_charge_routes_keep_billing_gate_before_foreign_anchor(charge_case, path):
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
            if path == "detail":
                ai.run_detail(identifier, db=db, user=actor)
            elif path == "cancel":
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
    foreign = next(i for i, sql in enumerate(statements) if "hoimsystem_ai_document_extraction_run_anchor" in sql)
    assert gate < foreign, (gate, foreign, statements[: gate + 1])
