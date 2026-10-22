"""Real SQL boolean markers and immutable dispatch, not body authorization."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, text
from sqlalchemy.dialects import mysql

from app.ai import research_variables_task_routing as routing
from app.ai.models import AIRun
from app.ai.research_variables_task_contract import SOURCE_DOMAIN, canonical
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import TASK_TEXT, observations, stop
from tests.test_ai_research_variables_task_reader import actual_task as actual_task


def store(db, seed_data, *, payload=None, result=None, metadata=None, feature="operations_qa"):
    run = AIRun(
        feature_key=feature,
        requested_by=seed_data["super_admin_user"].user_id,
        prompt_hash="a" * 64,
        context_digest="b" * 64,
        input_json=canonical(payload) if payload is not None else "{}",
        result_json=canonical(result) if result is not None else "{}",
        context_metadata_json=canonical(metadata) if metadata is not None else "{}",
    )
    db.add(run)
    db.commit()
    return inspect(run).identity[0]


@pytest.mark.parametrize(
    "content",
    [
        {"feature": "research_extraction"},
        {"payload": {"schema_version": "research_variable_task_snapshot_v1"}},
        {"payload": {"payload": {"input": {"research_variable_batch_id": None}}}},
        {"payload": {"payload": {"input": {"research_variable_batch_id": str(uuid.UUID(int=1))}}}},
        {"payload": {"payload": {"context": {"research_variable_binding": None}}}},
        {"payload": {"payload": {"context": {"research_variable_binding": {}}}}},
        {"payload": {"payload": {"context": {"scope": {"source_domain": SOURCE_DOMAIN}}}}},
        {"payload": {"payload": {"context": {"scope": {"selected_sources": {"research_variable_batch_id": None}}}}}},
        {"metadata": {"source_domain": SOURCE_DOMAIN}},
        {"metadata": {"research_variable_binding": None}},
        {"result": {"schema_version": "research_variable_result_ref_v1"}},
        {"result": {"research_variable_extraction": None}},
        {"result": {"research_variable_extraction": {}}},
    ],
)
def test_each_orphan_native_marker_including_null_presence_is_409_from_one_boolean_probe_without_any_body_column_projection(db_session, seed_data, content):
    identifier = store(db_session, seed_data, **content)
    columns, _, seen, emitted = observations(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            routing.is_variable_task(db_session, identifier)
        assert error.value.status_code == 409
    finally:
        stop(db_session, seen, emitted)
    assert not any(name in TASK_TEXT for _, name in columns)


@pytest.mark.parametrize("raw", ["not JSON", "null", "42", '"research_variable_binding"', "[]", '{"payload":{"input":{"other":null}}}'])
def test_truly_generic_invalid_or_scalar_json_does_not_become_a_native_marker_or_raise_json_sql_error(db_session, seed_data, raw):
    identifier = store(db_session, seed_data)
    db_session.execute(text("UPDATE hoimsystem_ai_run SET input_json=:raw,result_json=:raw,context_metadata_json=:raw WHERE run_id=:id"), {"raw": raw, "id": identifier})
    db_session.commit()
    assert routing.is_variable_task(db_session, identifier) is False


def test_existing_artifact_remains_native_when_terminal_feature_erased_and_all_markers_removed_without_reading_body(db_session, actual_task):
    _, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    db_session.execute(
        text("UPDATE hoimsystem_ai_run SET feature_key='operations_qa',status='failed',input_json='{}',result_json='{}',context_metadata_json='{}' WHERE run_id=:id"), {"id": identifier}
    )
    db_session.commit()
    columns, _, seen, emitted = observations(db_session)
    try:
        assert routing.is_variable_task(db_session, identifier) is True
    finally:
        stop(db_session, seen, emitted)
    assert not any(name in TASK_TEXT for _, name in columns)


def test_non_uuid_generic_identifier_does_not_open_an_opaque_session_or_issue_sql(db_session):
    emitted = []

    def observed(conn, cursor, statement, parameters, ctx, many):
        emitted.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", observed)
    try:
        assert routing.is_variable_task(db_session, "not-read") is False
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observed)
    assert emitted == []


def test_mysql_boolean_probe_uses_valid_json_case_and_exact_presence_not_like():
    db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
    statement = routing._marker_statement(db, str(uuid.UUID(int=1)))
    sql = str(statement.compile(dialect=mysql.dialect()))
    assert "CASE WHEN" in sql and "json_valid" in sql and " LIKE " not in sql and "FOR UPDATE" not in sql and "FOR SHARE" not in sql
    assert "json_contains_path" in sql and "json_unquote" in sql
    assert len(statement.selected_columns) == 1


def test_uppercase_standard_uuid_still_discovers_actual_native_artifact_without_body_or_generic_fallback(db_session, actual_task):
    _, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    columns, _, seen, emitted = observations(db_session)
    try:
        assert routing.is_variable_task(db_session, identifier.upper()) is True
    finally:
        stop(db_session, seen, emitted)
    assert not any(name in TASK_TEXT for _, name in columns)


@pytest.mark.parametrize("identifier", ["not-read", "0123456789abcdef0123456789abcdef", "{01234567-89ab-cdef-0123-456789abcdef}"])
def test_nonstandard_generic_identifier_is_not_uuid_rewritten_or_queried(db_session, identifier):
    columns, statements, seen, emitted = observations(db_session)
    try:
        assert routing.is_variable_task(db_session, identifier) is False
    finally:
        stop(db_session, seen, emitted)
    assert not columns and not statements


@pytest.mark.parametrize("alias", ["á0000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000001\x00", "æ000000-0000-0000-0000-000000000001"])
def test_unicode_and_control_alias_discovery_uses_raw_bounded_three_columns_under_db_comparator_not_private_body(db_session, alias):
    statements = []

    def seen(state):
        if state.is_select:
            statements.append(state.statement)

    event.listen(db_session, "do_orm_execute", seen)
    try:
        assert routing.identifier_for(alias) == alias
        assert routing.is_variable_task(db_session, alias) is False
    finally:
        event.remove(db_session, "do_orm_execute", seen)
    assert [column.key for column in statements[0].selected_columns] == ["run_id", "batch_id", "requested_by"]
    assert next(iter(statements[0].compile().params.values())) == alias
    assert all(column.key not in TASK_TEXT for statement in statements for column in statement.selected_columns)


@pytest.mark.parametrize("alias", ["é" * 200, "a" * 257, "a\ud800"])
def test_unrepresentable_or_oversized_technical_alias_is_rejected_before_sql(db_session, alias):
    columns, statements, seen, emitted = observations(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            routing.is_variable_task(db_session, alias)
        assert error.value.status_code == 422
    finally:
        stop(db_session, seen, emitted)
    assert not columns and not statements
