"""Actual Source/config/Task SQL reads, purpose-first guards and frozen proof.

SQLite observations establish SQL ordering and state only, not MySQL lock wait.
"""

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import Select, event, inspect, text

from app.ai import research_variables_storage as storage
from app.ai import research_variables_task_reader as reader
from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_variables_batches import review_batch
from app.ai.research_variables_task_contract import canonical, digest
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_storage import prepare
from tests.test_ai_research_variables_task_context import PRIVATE
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory

TASK_TEXT = set(storage.RUN_TEXT + storage.ART_TEXT)


@pytest.fixture
def actual_task(db_session, configured, task_factory):
    case, permissions, batch, prepared, snapshot = prepare(db_session, configured, task_factory)
    staged = storage.stage_run(db_session, case["admin_user"], AIRun(run_id=str(uuid.uuid4()), preview=0), prepared, snapshot)
    db_session.commit()
    return case, permissions, batch, staged


def observations(db):
    columns, sql = [], []

    def seen(state):
        if state.is_select and isinstance(state.statement, Select):
            columns.extend((column.table.name if getattr(column, "table", None) is not None else None, str(column.key)) for column in state.statement.selected_columns)

    def emitted(conn, cursor, statement, params, context, many):
        sql.append(statement)

    event.listen(db, "do_orm_execute", seen)
    event.listen(db.bind, "before_cursor_execute", emitted)
    return columns, sql, seen, emitted


def stop(db, seen, emitted):
    event.remove(db, "do_orm_execute", seen)
    event.remove(db.bind, "before_cursor_execute", emitted)


def test_actual_short_task_current_source_full_reprojection_and_all_eight_anchors_before_any_task_text(db_session, actual_task):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    before = db_session.query(AIAuditEvent).count()
    columns, sql, seen, emitted = observations(db_session)
    try:
        loaded = reader.load_task(db_session, case["admin_user"], identifier, for_execution=True)
    finally:
        stop(db_session, seen, emitted)
    assert not loaded.frozen_audit and loaded.run.status == "queued"
    assert loaded.binding == staged.binding and loaded.snapshot == staged.snapshot
    assert canonical(loaded.source) == staged.artifact.source_json
    assert digest(loaded.private_scope) == loaded.binding.private_scope_hash
    assert db_session.query(AIAuditEvent).count() == before
    first_task = next(index for index, statement in enumerate(sql) if "hoimsystem_ai_run.input_json AS hoimsystem_ai_run_input_json" in statement)
    assert any("hoimsystem_ai_research_variable_batch.snapshot_json" in statement for statement in sql[:first_task])
    assert any("hoimsystem_ai_audit_event.detail_json" in statement and "event_id =" in statement for statement in sql[:first_task])
    assert any(key in TASK_TEXT for _, key in columns)


@pytest.mark.parametrize("change", ["role", "epoch", "patient", "acl"])
def test_original_permission_or_actor_loss_denies_all_task_and_first_batch_text_including_unselected_patient(db_session, actual_task, change):
    case, permissions, _, staged = actual_task
    user = case["admin_user"]
    identifier = inspect(staged.run).identity[0]
    if change in {"patient", "acl"}:
        original = staged.binding.request_authorization
        kind, original_id = ("authorization", permissions[1]["source_record_id"]) if change == "patient" else ("acl", original.acl_id)
        review_registry_original(db_session, case["super_admin_user"], kind, original_id, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    else:
        if change == "role":
            user.user_role = "director"
        else:
            user.token_invalid_before = dt.datetime(2026, 10, 21, 23)
        db_session.commit()
    columns, sql, seen, emitted = observations(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            reader.load_task(db_session, user, identifier)
        assert error.value.status_code == 403
    finally:
        stop(db_session, seen, emitted)
    assert not any(key in TASK_TEXT for _, key in columns)
    assert not any(key in statement for key in PRIVATE for statement in sql)


def test_revoked_batch_denies_ordinary_but_explicit_super_frozen_audit_rebuilds_original_publication_and_does_not_restore_execution(db_session, actual_task):
    case, _, batch, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    published_gov = staged.binding.batch_governance_hash
    revoked = review_batch(db_session, case["super_admin_user"], batch["batch_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    assert revoked["governance_hash"] != published_gov
    columns, _, seen, emitted = observations(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            reader.load_task(db_session, case["admin_user"], identifier)
        assert error.value.status_code == 409 and not any(key in TASK_TEXT for _, key in columns)
    finally:
        stop(db_session, seen, emitted)
    loaded = reader.load_task(db_session, case["super_admin_user"], identifier, frozen_audit=True)
    assert loaded.frozen_audit and loaded.snapshot.batch_publication.status == "published"
    assert loaded.private_scope["proof"]["governance"]["status"] == "published"
    assert loaded.private_scope["proof"]["governance_hash"] == published_gov
    assert digest(loaded.private_scope) == staged.binding.private_scope_hash
    assert loaded.authority.actor.user_role == "super_admin"
    with pytest.raises(HTTPException) as error:
        reader.load_task(db_session, case["super_admin_user"], identifier, frozen_audit=True, for_execution=True)
    assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        reader.load_task(db_session, case["admin_user"], identifier, frozen_audit=True)
    assert error.value.status_code == 403


def test_super_frozen_audit_has_no_patient_purpose_exemption_before_task_or_batch_text(db_session, actual_task):
    case, permissions, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    columns, sql, seen, emitted = observations(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            reader.load_task(db_session, case["super_admin_user"], identifier, frozen_audit=True)
        assert error.value.status_code == 403
    finally:
        stop(db_session, seen, emitted)
    assert not any(key in TASK_TEXT for _, key in columns)
    assert not any(key in statement for key in PRIVATE for statement in sql)


@pytest.mark.parametrize("damage", ["feature", "owner", "input_hash", "audit", "source_hash"])
def test_actual_short_header_or_exact_creation_pk_damage_rejects_before_task_text(db_session, actual_task, damage):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    if damage == "feature":
        statement, params = "UPDATE hoimsystem_ai_run SET feature_key='patient_summary' WHERE run_id=:id", {"id": identifier}
    elif damage == "owner":
        statement, params = "UPDATE hoimsystem_ai_run SET requested_by=:owner WHERE run_id=:id", {"owner": case["super_admin_user"].user_id, "id": identifier}
    elif damage == "audit":
        statement, params = "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=:id", {"id": staged.artifact.create_event_id}
    else:
        field, value = damage, "f" * 64
        statement, params = f"UPDATE hoimsystem_ai_research_variable_run_artifact SET {field}=:value WHERE run_id=:id", {"value": value, "id": identifier}
    db_session.execute(text(statement), params)
    columns, _, seen, emitted = observations(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            reader.load_task(db_session, case["admin_user"], identifier)
        assert error.value.status_code == 409
    finally:
        stop(db_session, seen, emitted)
        db_session.rollback()
    assert not any(key in TASK_TEXT for _, key in columns)


@pytest.mark.parametrize("damage", ["input", "binding", "source", "evidence", "metadata"])
def test_complete_body_or_both_mutable_copy_rehash_attack_cannot_replace_original_eight_sql_anchors(db_session, actual_task, damage):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    table, field = (
        ("hoimsystem_ai_research_variable_run_artifact", damage + "_json")
        if damage in {"source", "binding"}
        else ("hoimsystem_ai_run", {"input": "input_json", "evidence": "evidence_json", "metadata": "context_metadata_json"}[damage])
    )
    raw = "[]" if damage == "evidence" else "{}"
    if damage in {"source", "binding"}:
        # Deliberately change both mutable JSON and its declared byte count.
        # Its independently recorded creation audit still anchors original SHA.
        db_session.execute(text(f"UPDATE {table} SET {field}=:value,{damage}_bytes=:size WHERE run_id=:id"), {"value": raw, "size": len(raw.encode()), "id": identifier})
    else:
        db_session.execute(text(f"UPDATE {table} SET {field}=:value WHERE run_id=:id"), {"value": raw, "id": identifier})
    with pytest.raises(HTTPException) as error:
        reader.load_task(db_session, case["admin_user"], identifier)
    assert error.value.status_code == 409
    db_session.rollback()


def test_non_uuid_generic_identifier_locator_issues_no_sql_and_no_source_or_task_lock(db_session):
    _, sql, seen, emitted = observations(db_session)
    try:
        assert reader.locate_artifact(db_session, "legacy-non-uuid-run") is None
        assert reader.locate_artifact(db_session, None) is None
    finally:
        stop(db_session, seen, emitted)
    assert sql == []
