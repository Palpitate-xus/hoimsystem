"""Actual SQL current routing and Source authority before private task TEXT.

SQLite checks statements and scope semantics. MySQL current-read isolation is
verified separately by the private two-connection runner, not claimed here.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql

from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_runtime import authorize_satisfaction_run
from app.ai.satisfaction_sources import revoke_case
from app.ai.satisfaction_storage import authorize_run_scope, guard_satisfaction_run_id, is_satisfaction_run
from tests.test_ai_satisfaction_legacy_read import legacy_run, legacy_snapshot
from tests.test_ai_satisfaction_sources import BASIS
from tests.test_ai_satisfaction_sources import satisfaction_case as satisfaction_case  # noqa: F401
from tests.test_ai_satisfaction_storage import configured_run


def capture_sql(db):
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, None if context.compiled is None else context.compiled.statement))

    event.listen(db.get_bind(), "before_cursor_execute", record)
    return statements, record


def task_text(statements):
    return [sql for sql, _ in statements if "SELECT" in sql.upper() and any("hoimsystem_ai_run." + key in sql for key in ("input_json", "evidence_json", "context_metadata_json", "result_json"))]


def whole_artifact(statements):
    return [sql for sql, _ in statements if "SELECT" in sql.upper() and "hoimsystem_ai_satisfaction_run_artifact.input_hash" in sql]


def test_durable_locator_precedes_expired_private_json_and_uses_only_three_current_identity_columns(db_session, satisfaction_case):
    db = db_session
    case = configured_run(db, satisfaction_case)
    run = case["run"]
    run.feature_key, run.input_json, run.result_json = "another-feature", '{"forged":true}', "{}"
    db.commit()
    db.expire(run)
    statements, listener = capture_sql(db)
    try:
        assert is_satisfaction_run(db, run) is True
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert not task_text(statements) and not whole_artifact(statements)
    assert statements[0][0].startswith("INSERT INTO hoimsystem_ai_satisfaction_write_gate")
    locator = next((sql, stmt) for sql, stmt in statements if sql.startswith("SELECT") and "hoimsystem_ai_satisfaction_run_artifact" in sql)
    assert "case_id" in locator[0] and "requested_by" in locator[0]
    compiled = str(locator[1].compile(dialect=mysql.dialect()))
    assert compiled.endswith("LOCK IN SHARE MODE")
    assert not any(key in compiled for key in ("result_json", "input_hash", "source_binding_hash"))


@pytest.mark.parametrize("call", ["guard", "scope", "runtime"])
def test_foreign_current_doctor_scope_rejected_before_any_task_text_or_full_artifact(db_session, satisfaction_case, call):
    db = db_session
    case = configured_run(db, satisfaction_case, actor=satisfaction_case["director_user"])
    identifier = case["run"].run_id
    case["doctor"].department_id = None
    db.commit()
    db.expire_all()
    statements, listener = capture_sql(db)
    try:
        with pytest.raises(HTTPException) as error:
            if call == "guard":
                guard_satisfaction_run_id(db, case["director_user"], identifier)
            elif call == "scope":
                authorize_run_scope(db, case["director_user"], SimpleNamespace(run_id=identifier))
            else:
                authorize_satisfaction_run(db, case["director_user"], identifier)
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert not task_text(statements) and not whole_artifact(statements)
    assert not any("hoimsystem_ai_satisfaction_case.snapshot_json" in sql for sql, _ in statements)


def test_current_complete_source_is_verified_before_first_private_task_read(db_session, satisfaction_case):
    db = db_session
    case = configured_run(db, satisfaction_case)
    identifier = case["run"].run_id
    db.expire_all()
    statements, listener = capture_sql(db)
    try:
        authorized = authorize_satisfaction_run(db, case["admin_user"], identifier)
        assert authorized[2]["case_id"] == case["made"]["case_id"]
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    source_index = next(i for i, (sql, _) in enumerate(statements) if "SELECT" in sql.upper() and "hoimsystem_ai_satisfaction_case.snapshot_json" in sql)
    task_index = next(i for i, (sql, _) in enumerate(statements) if sql in task_text(statements))
    assert source_index < task_index
    locator_index = next(i for i, (sql, _) in enumerate(statements) if "SELECT" in sql.upper() and "hoimsystem_ai_satisfaction_run_artifact" in sql)
    assert locator_index < source_index
    assert not whole_artifact(statements[:source_index])


@pytest.mark.parametrize("audit", [False, True])
def test_super_frozen_audit_is_explicit_and_independent_of_revoked_source_and_malformed_live_roles(db_session, satisfaction_case, audit):
    db = db_session
    case = configured_run(db, satisfaction_case)
    identifier = case["run"].run_id
    revoke_case(db, case["super_admin_user"], case["made"]["case_id"], {"expected_revision": 2, "basis_note": BASIS})
    case["config"].allowed_roles_json = "malformed live JSON"
    db.commit()
    statements, listener = capture_sql(db)
    try:
        if audit:
            assert guard_satisfaction_run_id(db, case["super_admin_user"], identifier, audit_only=True) is True
        else:
            with pytest.raises(HTTPException) as error:
                guard_satisfaction_run_id(db, case["super_admin_user"], identifier)
            assert error.value.status_code == 409
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert not task_text(statements) and not whole_artifact(statements)


def test_ordinary_malformed_live_roles_fails_before_case_or_task_body(db_session, satisfaction_case):
    db = db_session
    case = configured_run(db, satisfaction_case)
    identifier = case["run"].run_id
    case["config"].allowed_roles_json = "malformed live JSON"
    db.commit()
    statements, listener = capture_sql(db)
    try:
        with pytest.raises(HTTPException) as error:
            guard_satisfaction_run_id(db, case["admin_user"], identifier)
        assert error.value.status_code == 409
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert not task_text(statements) and not whole_artifact(statements)
    assert not any("hoimsystem_ai_satisfaction_case.snapshot_json" in sql for sql, _ in statements)


def test_false_locator_does_not_authorize_explicit_legacy_or_grant_native_read(db_session, seed_data):
    db = db_session
    from app.ai.catalog import FEATURE_BY_KEY
    from app.ai.models import AIFeatureConfig
    from app.ai.satisfaction_draft import canonical_json

    config = db.get(AIFeatureConfig, "feedback_analysis")
    if config is not None:
        config.allowed_roles_json = canonical_json(list(FEATURE_BY_KEY["feedback_analysis"].default_roles))
        db.commit()
    run = legacy_run(db, seed_data["admin_user"])
    identifier = run.run_id
    db.expire_all()
    statements, listener = capture_sql(db)
    try:
        assert guard_satisfaction_run_id(db, seed_data["admin_user"], identifier) is False
        with pytest.raises(HTTPException) as error:
            authorize_run_scope(db, seed_data["admin_user"], identifier)
        assert error.value.status_code == 409
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert not task_text(statements)
    assert is_satisfaction_run(db, run) is False


def test_ordinary_audit_and_foreign_owner_rejected_before_locator_or_private_original(db_session, satisfaction_case):
    db = db_session
    case = configured_run(db, satisfaction_case)
    identifier = case["run"].run_id
    for user, audit in ((case["admin_user"], True), (case["director_user"], False)):
        statements, listener = capture_sql(db)
        try:
            with pytest.raises(HTTPException) as error:
                guard_satisfaction_run_id(db, user, identifier, audit_only=audit)
            assert error.value.status_code == 403
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", listener)
        assert not task_text(statements) and not whole_artifact(statements)
        assert not any("hoimsystem_ai_satisfaction_run_artifact" in sql for sql, _ in statements)


def test_native_locator_requester_mismatch_rejected_without_loading_task_body(db_session, satisfaction_case):
    db = db_session
    case = configured_run(db, satisfaction_case)
    identifier, other = case["run"].run_id, case["super_admin_user"].user_id
    db.execute(text("UPDATE hoimsystem_ai_satisfaction_run_artifact SET requested_by=:actor WHERE run_id=:run"), {"actor": other, "run": identifier})
    db.commit()
    statements, listener = capture_sql(db)
    try:
        with pytest.raises(HTTPException) as error:
            guard_satisfaction_run_id(db, case["admin_user"], identifier)
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert not task_text(statements) and not whole_artifact(statements)


def test_erased_all_native_json_and_feature_still_requires_current_source_via_artifact(db_session, satisfaction_case):
    from app.ai.satisfaction_draft import canonical_json

    db = db_session
    case = configured_run(db, satisfaction_case, actor=satisfaction_case["director_user"])
    identifier = case["run"].run_id
    case["run"].input_json, case["run"].result_json, case["run"].feature_key = canonical_json(legacy_snapshot()), "{}", "another-feature"
    case["doctor"].department_id = None
    db.commit()
    assert is_satisfaction_run(db, case["run"]) is True
    with pytest.raises(HTTPException) as error:
        guard_satisfaction_run_id(db, case["director_user"], identifier)
    assert error.value.status_code == 403


def test_missing_artifact_never_turns_native_authorization_into_legacy_permission(db_session, satisfaction_case):
    db = db_session
    case = configured_run(db, satisfaction_case)
    identifier = case["run"].run_id
    db.query(AISatisfactionRunArtifact).filter_by(run_id=identifier).delete(synchronize_session=False)
    db.commit()
    with pytest.raises(HTTPException) as error:
        authorize_satisfaction_run(db, case["admin_user"], identifier)
    assert error.value.status_code == 409
    assert is_satisfaction_run(db, case["run"]) is True


def test_current_loaded_actor_epoch_change_rejected_before_locator(db_session, satisfaction_case):
    db = db_session
    case = configured_run(db, satisfaction_case)
    user = case["admin_user"]
    identifier, uid = case["run"].run_id, user.user_id
    assert user.user_role == "admin"
    db.execute(text("UPDATE hoimsystem_users SET token_invalid_before='2026-10-22 00:00:00' WHERE user_id=:id"), {"id": uid})
    # Preserve the old request object's already loaded epoch until actual guard.
    statements, listener = capture_sql(db)
    try:
        with pytest.raises(HTTPException) as error:
            guard_satisfaction_run_id(db, user, identifier)
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert not task_text(statements)
    assert not any("hoimsystem_ai_satisfaction_run_artifact" in sql for sql, _ in statements)
    db.rollback()


def test_other_feature_without_artifact_keeps_its_own_role_and_owner_authorizer(db_session, seed_data):
    from app.ai.models import AIRun

    db = db_session
    run = AIRun(run_id="legacy-non-canonical-id", feature_key="synthetic-unrelated-task", requested_by=seed_data["admin_user"].user_id, prompt_hash="a" * 64, context_digest="b" * 64)
    db.add(run)
    db.commit()
    identifier = run.run_id
    # The satisfaction guard is a router locator, not a role restriction on
    # unrelated document or clinical features. No private JSON is read here.
    statements, listener = capture_sql(db)
    try:
        assert guard_satisfaction_run_id(db, seed_data["patient_user"], identifier) is False
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert not task_text(statements) and not whole_artifact(statements)


def test_no_artifact_unrelated_or_missing_run_never_takes_a_run_lock_or_imposes_uuid_semantics(db_session, seed_data):
    db = db_session
    statements, listener = capture_sql(db)
    try:
        assert guard_satisfaction_run_id(db, seed_data["patient_user"], "unknown-legacy-id") is False
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    for sql, statement in statements:
        if "SELECT" in sql.upper() and "hoimsystem_ai_run" in sql:
            compiled = str(statement.compile(dialect=mysql.dialect()))
            assert "FOR UPDATE" not in compiled and "LOCK IN SHARE MODE" not in compiled
    assert not task_text(statements) and not whole_artifact(statements)


@pytest.mark.parametrize("marker", ["satisfaction_artifact", "frozen_satisfaction_audit", "recorded_source_domain"])
def test_structural_native_markers_never_downgrade_without_a_durable_artifact(db_session, seed_data, marker):
    from app.ai.satisfaction_draft import canonical_json

    run = legacy_run(db_session, seed_data["admin_user"])
    snapshot = legacy_snapshot()
    if marker == "recorded_source_domain":
        snapshot["payload"]["context"]["source_domain"] = "recorded_satisfaction_review_case"
    else:
        snapshot["payload"][marker] = None
    run.feature_key, run.input_json = "another-feature", canonical_json(snapshot)
    db_session.commit()
    assert is_satisfaction_run(db_session, run) is True
