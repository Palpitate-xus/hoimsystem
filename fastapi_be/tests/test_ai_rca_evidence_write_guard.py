"""Actual legacy SQL state/ordering; SQLite does not prove lock waits or RR."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import Select, event, text
from sqlalchemy.dialects import mysql

from app.models import AdverseEvent, AdverseEventRca
from app.routers import adverse_event, quality_management


@pytest.fixture
def event_case(db_session, seed_data):
    row = AdverseEvent(
        event_type="合成事件",
        patient_id=seed_data["patient"].patient_id,
        description="未核实原陈述，不是因果结论",
        severity=0,
        reporter_id=seed_data["doctor_user"].user_id,
        report_time=dt.datetime(2026, 10, 21, 12),
        status=0,
    )
    db_session.add(row)
    db_session.commit()
    rca = AdverseEventRca(
        event_id=row.event_id,
        event_summary="合成原概述",
        timeline="未知发生时间，不把上报钟点冒充发生时间",
        root_cause="原填写文本尚未确认",
        corrective_actions="仅原计划",
        pdca_cycle="P",
        analyst_id=seed_data["doctor_user"].user_id,
        create_time=dt.datetime(2026, 10, 21, 12),
    )
    db_session.add(rca)
    db_session.commit()
    return db_session, seed_data, row, rca


def operation(case, path):
    db, users, original, rca = case
    if path == "status":
        return adverse_event.update_event_status, {"event_id": original.event_id, "status": 1}, users["admin_user"]
    if path == "create":
        # Use another actual Event; duplicate prevention remains unchanged.
        row = AdverseEvent(patient_id=original.patient_id, reporter_id=users["doctor_user"].user_id, status=0)
        db.add(row)
        db.commit()
        return quality_management.create_rca, {"event_id": row.event_id, "root_cause": "未核实原假设", "corrective_actions": "原计划未验证"}, users["doctor_user"]
    return quality_management.advance_rca, {"rca_id": rca.rca_id, "pdca_cycle": "D"}, users["doctor_user"]


@pytest.mark.parametrize("path", ["status", "create", "advance"])
def test_three_real_legacy_writers_lock_current_actor_then_event_before_child_body(event_case, path):
    db = event_case[0]
    handler, body, actor = operation(event_case, path)
    statements = []

    def observe(state):
        if state.is_select and isinstance(state.statement, Select):
            query = state.statement
            statements.append((str(query.compile(dialect=mysql.dialect())), {column.key for column in query.selected_columns}))

    # Avoid expired attribute fixture loads being mistaken for handler SQL.
    actor.user_role
    event.listen(db, "do_orm_execute", observe)
    try:
        response = handler(body, current_user=actor, db=db)
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert response["code"] == 200
    user_index = next(index for index, (sql, _) in enumerate(statements) if "FROM hoimsystem_users" in sql)
    parent_index = next(index for index, (sql, _) in enumerate(statements) if "FROM hoimsystem_adverse_event " in sql or "FROM hoimsystem_adverse_event\n" in sql)
    assert user_index < parent_index
    sql, columns = statements[parent_index]
    assert "FOR UPDATE" in sql and columns == {"event_id", "patient_id", "reporter_id"}
    for index, (sql, columns) in enumerate(statements):
        if "FROM hoimsystem_adverse_event_rca" not in sql:
            continue
        if index < parent_index:
            assert path == "advance" and columns == {"rca_id", "event_id"}
            assert "FOR UPDATE" not in sql and "LOCK IN SHARE MODE" not in sql
        else:
            assert "FOR UPDATE" in sql
    if path == "advance":
        assert db.get(AdverseEventRca, body["rca_id"]).pdca_cycle == "D"
    elif path == "status":
        assert db.get(AdverseEvent, body["event_id"]).status == 1
    else:
        assert db.query(AdverseEventRca).filter_by(event_id=body["event_id"]).one().root_cause == body["root_cause"]


@pytest.mark.parametrize("path", ["status", "create", "advance"])
@pytest.mark.parametrize("change", ["role", "token"])
def test_original_loaded_authority_epoch_is_not_replaced_by_same_object_refresh(event_case, path, change):
    db = event_case[0]
    handler, body, actor = operation(event_case, path)
    assert actor.user_role in {"admin", "doctor"} and actor.token_invalid_before is None
    if change == "role":
        db.execute(text("UPDATE hoimsystem_users SET user_role='super_admin' WHERE user_id=:id"), {"id": actor.user_id})
    else:
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before='2030-01-01 00:00:00.123456' WHERE user_id=:id"), {"id": actor.user_id})
    columns = []

    def observe(state):
        if state.is_select and isinstance(state.statement, Select):
            columns.extend(column.key for column in state.statement.selected_columns)

    event.listen(db, "do_orm_execute", observe)
    try:
        with pytest.raises(HTTPException) as error:
            handler(body, current_user=actor, db=db)
        assert error.value.status_code == 403
    finally:
        event.remove(db, "do_orm_execute", observe)
        db.rollback()
    assert "description" not in columns and "root_cause" not in columns and "timeline" not in columns


def test_current_event_status_refresh_preserves_old_transition_refusal(event_case):
    db, users, original, _ = event_case
    identifier = original.event_id
    assert original.status == 0
    db.execute(text("UPDATE hoimsystem_adverse_event SET status=2 WHERE event_id=:id"), {"id": identifier})
    response = adverse_event.update_event_status({"event_id": identifier, "status": 1}, current_user=users["admin_user"], db=db)
    assert response["code"] == 400 and db.get(AdverseEvent, identifier).status == 2
    db.rollback()


def test_current_rca_stage_refresh_preserves_old_pdca_transition_refusal(event_case):
    db, users, _, rca = event_case
    identifier = rca.rca_id
    assert rca.pdca_cycle == "P"
    db.execute(text("UPDATE hoimsystem_adverse_event_rca SET pdca_cycle='D' WHERE rca_id=:id"), {"id": identifier})
    response = quality_management.advance_rca({"rca_id": identifier, "pdca_cycle": "D"}, current_user=users["doctor_user"], db=db)
    assert response["code"] == 400 and db.get(AdverseEventRca, identifier).pdca_cycle == "D"
    db.rollback()


def test_technical_rca_locator_never_refreshes_full_expired_child(event_case):
    from app.ai.rca_evidence_write_guard import locate_rca_event

    db, _, _, rca = event_case
    identifier, event_id = rca.rca_id, rca.event_id
    db.expire(rca)
    columns = []

    def observe(state):
        if state.is_select and isinstance(state.statement, Select):
            columns.extend(column.key for column in state.statement.selected_columns)

    event.listen(db, "do_orm_execute", observe)
    try:
        assert locate_rca_event(db, identifier) == (identifier, event_id)
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert columns == ["rca_id", "event_id"]
    assert "root_cause" in __import__("sqlalchemy").inspect(rca).unloaded
