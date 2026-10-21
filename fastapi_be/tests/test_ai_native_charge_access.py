"""Ordinary charge Source authority must precede the private task body."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, text
from sqlalchemy.dialects import mysql

from app.ai import charge_reconciliation_runtime as runtime
from app.ai import charge_reconciliation_sources as sources
from app.ai.models import AIFeatureConfig, AIRun
from app.routers import ai
from tests.test_ai_charge_reconciliation_runtime import configured
from tests.test_ai_charge_reconciliation_sources import NOTE, cas
from tests.test_ai_charge_reconciliation_sources import charge_case as charge_case  # noqa: F401


@pytest.mark.parametrize("loss", ["source", "role", "feature_roles"])
def test_ordinary_invalid_charge_stops_before_any_task_text(charge_case, loss):
    case, db = charge_case, charge_case["db"]
    actor, req, source, *_ = configured(case, actor=case["admin_user"], preview=False)
    run = runtime.create_charge_run(db, actor, req)
    identifier = inspect(run).identity[0]
    if loss == "source":
        sources.revoke_case(db, case["super_admin_user"], source["case_snapshot_id"], {**cas(source), "basis_note": NOTE})
    elif loss == "role":
        db.execute(text("UPDATE hoimsystem_users SET user_role='doctor' WHERE user_id=:u"), {"u": actor.user_id})
    else:
        db.get(AIFeatureConfig, "charge_reconciliation").allowed_roles_json = '["super_admin"]'
    db.commit()
    db.expire(run)
    sql = []

    def observe(state):
        if state.is_select:
            sql.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", observe)
    try:
        with pytest.raises(HTTPException) as error:
            ai.run_detail(identifier, db=db, user=actor)
        assert error.value.status_code in {403, 409}
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert not any(f"{AIRun.__tablename__}.{field}" in statement for field in ("input_json", "evidence_json", "context_metadata_json", "result_json") for statement in sql)


@pytest.mark.parametrize("revoked_frozen_super", [False, True])
def test_current_ordinary_or_explicit_super_frozen_read_remains_available(charge_case, revoked_frozen_super):
    case, db = charge_case, charge_case["db"]
    actor, req, source, *_ = configured(case, actor=case["admin_user"], preview=False)
    run = runtime.create_charge_run(db, actor, req)
    identifier = inspect(run).identity[0]
    if revoked_frozen_super:
        sources.revoke_case(db, case["super_admin_user"], source["case_snapshot_id"], {**cas(source), "basis_note": NOTE})
        db.commit()
        actor = case["super_admin_user"]
    db.expire(run)
    detail = ai.run_detail(identifier, db=db, user=actor)["data"]
    assert detail["run_id"] == identifier and detail["feature_key"] == "charge_reconciliation"
    assert detail["charge_findings"] is not None


@pytest.mark.parametrize("changed", ["user_role", "token_invalid_before"])
def test_loaded_authenticated_epoch_is_saved_before_refresh_and_before_private_text(charge_case, changed):
    import datetime

    case, db = charge_case, charge_case["db"]
    actor, req, *_ = configured(case, actor=case["admin_user"], preview=False)
    run = runtime.create_charge_run(db, actor, req)
    identifier = inspect(run).identity[0]
    # Keep the genuinely loaded request actor while the actual stored row
    # changes; current populate_existing refresh must not erase that epoch.
    assert actor.user_role == "admin" and actor.token_invalid_before is None
    db.expire_on_commit = False
    value = "cashier" if changed == "user_role" else datetime.datetime(2026, 10, 21, 18, 0)
    db.execute(text(f"UPDATE hoimsystem_users SET {changed}=:v WHERE user_id=:u"), {"v": value, "u": actor.user_id})
    db.commit()
    db.expire(run)
    sql = []

    def observe(state):
        if state.is_select:
            sql.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", observe)
    try:
        with pytest.raises(HTTPException) as error:
            ai.run_detail(identifier, db=db, user=actor)
        assert error.value.status_code == 403
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert not any(f"{AIRun.__tablename__}.{field}" in statement for field in ("input_json", "evidence_json", "context_metadata_json", "result_json") for statement in sql)
