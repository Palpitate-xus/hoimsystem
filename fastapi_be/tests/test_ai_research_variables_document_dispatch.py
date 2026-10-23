"""Actual foreign opaque71 anchors precede unrelated76 JSON marker probes."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect

from app.ai import research_variables_task_routing as routing
from app.ai.document_extraction_models import AIDocumentExtractionRunAnchor
from tests.test_ai_document_evidence_sources import approved_original
from tests.test_ai_document_extraction_pipeline import document_pipeline as document_pipeline
from tests.test_ai_document_extraction_pipeline import queue
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import actual_task as actual_task


def observe(db):
    statements = []

    def seen(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", seen)
    return statements, seen


@pytest.mark.asyncio
async def test_actual_document_anchor_stripped_run_returns_foreign_identity_without_any_task_json_probe(async_client, auth_headers, document_pipeline):
    from app.ai.models import AIRun

    case = document_pipeline
    claim, _ = await queue(async_client, auth_headers(case["actor"].username), case)
    db = case["db"]
    db.query(AIRun).filter_by(run_id=claim[0]).update({"feature_key": "operations_qa", "input_json": "{}", "result_json": "{}", "context_metadata_json": "{}", "evidence_json": "[]"})
    db.commit()
    statements, seen = observe(db)
    try:
        assert routing.is_variable_task(db, claim[0]) is False
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", seen)
    assert any("hoimsystem_ai_document_extraction_run_anchor.original_id" in sql for sql in statements)
    assert not any("hoimsystem_ai_run." + field in sql for field in ("input_json", "result_json", "context_metadata_json", "evidence_json") for sql in statements)


def test_same_actual_run_with_both_foreign_and_variable_artifacts_is_409_before_any_task_body(db_session, actual_task, seed_data):
    _, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    original = approved_original(db_session, seed_data["super_admin_user"], "完整合成原件，仅用于双域技术锚冲突负控。")
    anchor = AIDocumentExtractionRunAnchor(
        run_id=identifier,
        original_id=original.snapshot.original_id,
        requested_by=staged.binding.request_authorization.requested_by,
        schema_version="document_extraction_run_anchor_v1",
        recorded_at=dt.datetime.now(dt.UTC).replace(tzinfo=None),
        **{name: "a" * 64 for name in ("original_content_hash", "original_governance_hash", "source_digest", "prompt_hash", "context_digest", "input_hash", "evidence_hash", "metadata_hash")},
    )
    db_session.add(anchor)
    db_session.commit()
    statements, seen = observe(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            routing.is_variable_task(db_session, identifier)
        assert error.value.status_code == 409
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", seen)
        db_session.delete(anchor)
        db_session.commit()
    assert not any("hoimsystem_ai_run." + field in sql for field in ("input_json", "result_json", "context_metadata_json", "evidence_json") for sql in statements)
