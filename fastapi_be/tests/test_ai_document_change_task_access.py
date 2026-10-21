"""Real SQLite SQL boundaries, not evidence of MySQL waits or old-RR visibility."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, text

from app.ai import document_change_sources as sources
from app.ai import document_change_storage as storage
from app.ai.document_change_access import locate_artifact
from app.ai.models import AIRun
from tests.test_ai_document_change_sources import change_case as change_case  # noqa: F401
from tests.test_ai_document_change_storage import remove_prior_tasks as remove_prior_tasks  # noqa: F401
from tests.test_ai_document_change_storage import task
from tests.test_ai_document_evidence_contract import NOTE
from tests.test_ai_document_evidence_sources import cas


def observed(db, callback):
    statements = []

    def record(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        return callback(), statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def no_task_text(statements):
    assert not any("hoimsystem_ai_run.input_json" in item or "hoimsystem_ai_run.evidence_json" in item or "hoimsystem_ai_run.context_metadata_json" in item for item in statements)
    assert not any("hoimsystem_ai_document_change_run_artifact.source_json" in item for item in statements)


@pytest.mark.parametrize("loss", ["scope", "original", "role"])
def test_current_source_loss_precedes_every_task_text_select(change_case, loss):
    db, actor, original, *_ = change_case
    case = task(change_case)
    identifier = inspect(case["run"]).identity[0]
    if loss == "scope":
        sources.revoke_scope(db, actor, case["scope"].snapshot.scope_id, {**cas(case["scope"]), "basis_note": NOTE})
    elif loss == "original":
        sources.originals.revoke_original(db, actor, original.snapshot.original_id, {**cas(original), "basis_note": NOTE})
    else:
        actor.user_role = "admin"
    db.commit()
    db.expire_all()

    def rejected():
        with pytest.raises(HTTPException):
            storage.load_snapshot(db, identifier, user=actor)

    _, statements = observed(db, rejected)
    no_task_text(statements)


def test_locator_queries_exact_three_opaque_columns_and_preserves_sqlite_transaction(change_case):
    db, actor, *_ = change_case
    case = task(change_case)
    identifier = inspect(case["run"]).identity[0]
    db.connection()  # Establish an actual caller transaction before the locator.
    transaction = db.get_transaction()
    identity, statements = observed(db, lambda: locate_artifact(db, identifier))
    assert identity == (identifier, case["scope"].snapshot.scope_id, actor.user_id)
    assert len(statements) == 1
    columns = statements[0].split("FROM")[0]
    assert "source_json" not in columns and "scope_json" not in columns and "input_json" not in columns
    assert db.get_transaction() is transaction


def test_actual_staged_uncommitted_artifact_is_resolvable_before_commit(change_case):
    db, actor, *_ = change_case
    case = task(change_case, stage=False)
    identifier = inspect(case["run"]).identity[0]
    storage.stage_artifact(db, actor, case["run"])
    identity = locate_artifact(db, identifier)
    assert identity[0] == identifier and storage.load_snapshot(db, identifier, user=actor)[5] == case["source"]
    db.rollback()
    assert locate_artifact(db, identifier) is None


def test_damaged_feature_and_all_json_markers_cannot_hide_actual_artifact(change_case):
    db, actor, *_ = change_case
    case = task(change_case)
    identifier = inspect(case["run"]).identity[0]
    db.execute(
        text("UPDATE hoimsystem_ai_run SET feature_key='patient_summary', input_json='{}', evidence_json='[]', context_metadata_json='{}', result_json='{}' WHERE run_id=:id"), {"id": identifier}
    )
    db.commit()
    db.expire_all()
    assert storage.is_document_change_run(db, identifier)
    with pytest.raises(HTTPException):
        storage.authorize_run_id(db, actor, identifier)


def test_non_uuid_generic_identifier_is_not_subject_to_native_uuid_rules(change_case):
    db = change_case[0]
    run = AIRun(run_id="legacy-generic-id", feature_key="patient_summary")
    assert locate_artifact(db, run.run_id) is None
    assert not storage.is_document_change_run(db, run)
