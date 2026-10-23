"""Actual old writer functions retain roles/state machine; no patient-purpose grant implied."""

# ruff: noqa: F811 -- importing the real fixture registers it.

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Query

from app.routers import infection
from tests.test_ai_infection_cluster_sources import infection_case  # noqa: F401


@pytest.mark.parametrize("function,roles", [(infection.create_infection_case, infection.OPERATE_ROLES), (infection.update_infection_case_status, infection.REPORT_ROLES)])
def test_original_role_epoch_rechecked_before_any_case_body(infection_case, function, roles):
    db, author, _, _, row = infection_case
    stale = SimpleNamespace(user_id=author.user_id, user_role="super_admin", token_invalid_before=None)
    db.query(type(author)).filter_by(user_id=author.user_id).update({"user_role": "patient"}, synchronize_session=False)
    db.commit()
    case_id = row.case_id
    statements = []

    def capture(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        with pytest.raises(HTTPException) as denied:
            function({"case_id": case_id, "status": 1}, current_user=stale, db=db)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
        db.rollback()
    assert denied.value.status_code == 403
    assert not any("hoimsystem_infection_case" in sql for sql in statements)
    assert "hoimsystem_ai_infection_write_gate" in statements[0]


def test_actual_old_create_and_status_keep_missing_codes_and_forward_state(infection_case):
    db, author, _, patient, _ = infection_case
    assert infection.create_infection_case({}, current_user=author, db=db)["code"] == 400
    result = infection.create_infection_case({"patient_id": patient.patient_id, "infection_type": "旧业务原类型", "onset_date": "2026-10-01", "pathogen": None}, current_user=author, db=db)
    assert result["code"] == 200
    rid = result["data"]["case_id"]
    assert infection.update_infection_case_status({"case_id": rid, "status": 2}, current_user=author, db=db)["code"] == 400
    assert infection.update_infection_case_status({"case_id": rid, "status": 1}, current_user=author, db=db)["code"] == 200
    assert infection.update_infection_case_status({"case_id": rid, "status": 2}, current_user=author, db=db)["code"] == 200
    assert infection.update_infection_case_status({"case_id": rid, "status": 1}, current_user=author, db=db)["code"] == 400
    assert infection.update_infection_case_status({"case_id": "missing", "status": 1}, current_user=author, db=db)["code"] == 400


def test_old_status_current_mysql_compilation_patient_before_body(infection_case, monkeypatch):
    db, author, _, _, row = infection_case
    row.status = 0
    db.commit()
    statements = []
    original = Query.first

    def record(query):
        statements.append(str(query.statement.compile(dialect=mysql.dialect())))
        return original(query)

    monkeypatch.setattr(Query, "first", record)
    assert infection.update_infection_case_status({"case_id": row.case_id, "status": 1}, current_user=author, db=db)["code"] == 200
    locator, body = statements[-2:]
    assert ".description" not in locator and "LOCK IN SHARE MODE" in locator
    assert ".description" in body and "FOR UPDATE" in body
