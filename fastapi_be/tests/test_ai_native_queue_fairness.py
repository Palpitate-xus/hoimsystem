"""Retained orphan tasks cannot starve an authentic later task or become generic."""

import datetime
import json
import uuid

import pytest
from sqlalchemy import event, inspect, select

from app.ai import runtime
from app.ai.models import AIAuditEvent, AIRun
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import actual_task as actual_task

ORPHANS = (
    ("variables_feature", "research_extraction", {}, {}),
    ("variables_null_input", "operations_qa", {"payload": {"input": {"research_variable_batch_id": None}}}, {}),
    ("variables_null_result", "operations_qa", {}, {"research_variable_extraction": None}),
    ("rca_feature", "incident_rca", {}, {}),
    ("rca_null_input", "operations_qa", {"payload": {"input": {"rca_evidence_case_id": None}}}, {}),
    ("rca_null_result", "operations_qa", {}, {"rca_evidence_draft": None}),
)


def orphan_rows(db, actor_id, variant):
    _, feature, payload, result = variant
    rows = [AIRun(run_id=str(uuid.uuid4()), feature_key=feature, requested_by=actor_id, prompt_hash="a" * 64, context_digest="b" * 64, input_json=json.dumps(payload), result_json=json.dumps(result), create_time=datetime.datetime(2020, 1, 1), input_tokens=17) for _ in range(129)]
    db.add_all(rows)
    db.commit()
    return [inspect(row).identity[0] for row in rows]


def orphan_state(db, ids):
    return sorted(tuple(row) for row in db.execute(select(AIRun.run_id, AIRun.status, AIRun.lease_token, AIRun.input_tokens, AIRun.output_tokens, AIRun.latency_ms, AIRun.error_code).where(AIRun.run_id.in_(ids))))


@pytest.mark.parametrize("variant", ORPHANS, ids=lambda item: item[0])
@pytest.mark.parametrize("valid_kind", ("generic", "actual_variables"))
def test_more_than_one_poll_of_orphans_cannot_block_later_authentic_work(db_session, seed_data, request, variant, valid_kind):
    if valid_kind == "actual_variables":
        _, _, _, staged = request.getfixturevalue("actual_task")
        valid_id = inspect(staged.run).identity[0]
    else:
        valid = AIRun(run_id=str(uuid.uuid4()), feature_key="operations_qa", requested_by=seed_data["super_admin_user"].user_id, prompt_hash="a" * 64, context_digest="b" * 64)
        db_session.add(valid)
        db_session.commit()
        valid_id = inspect(valid).identity[0]
    ids = orphan_rows(db_session, seed_data["super_admin_user"].user_id, variant)
    before = orphan_state(db_session, ids)
    try:
        claimed = runtime.claim_next_run(db_session)
        assert claimed is not None and claimed[0] == valid_id
        assert db_session.query(AIRun.status).filter_by(run_id=valid_id).scalar() == "running"
        assert orphan_state(db_session, ids) == before
        assert db_session.query(AIAuditEvent).filter(AIAuditEvent.target.in_(ids)).count() == 0
    finally:
        db_session.rollback()
        db_session.query(AIRun).filter(AIRun.run_id.in_(ids)).delete(synchronize_session=False)
        # Isolate a failed candidate's unclaimed fixture from the next case.
        # This is test cleanup, never an assertion of a settled native receipt.
        db_session.query(AIRun).filter_by(run_id=valid_id, status="queued").update({"status": "cancelled"}, synchronize_session=False)
        db_session.commit()


@pytest.mark.parametrize("variant", ORPHANS, ids=lambda item: item[0])
def test_only_orphans_leave_queue_intact_without_claim_usage_or_generic_execution(db_session, seed_data, variant):
    ids = orphan_rows(db_session, seed_data["super_admin_user"].user_id, variant)
    before = orphan_state(db_session, ids)
    try:
        assert runtime.claim_next_run(db_session) is None
        assert orphan_state(db_session, ids) == before
        assert db_session.query(AIAuditEvent).filter(AIAuditEvent.target.in_(ids)).count() == 0
    finally:
        db_session.rollback()
        db_session.query(AIRun).filter(AIRun.run_id.in_(ids)).delete(synchronize_session=False)
        db_session.commit()


@pytest.mark.parametrize("raw", ("not JSON", "null", "42", '"research_variable_binding"', "[]", '{"other":null}', '"rca_evidence_case_id"', '{"payload":{"input":{"other":null}}}'))
def test_nonmarker_json_is_not_misclassified_or_projected_as_task_text_during_poll(db_session, seed_data, raw):
    row = AIRun(run_id=str(uuid.uuid4()), feature_key="operations_qa", requested_by=seed_data["super_admin_user"].user_id, prompt_hash="a" * 64, context_digest="b" * 64, input_json=raw, result_json=raw, context_metadata_json=raw, evidence_json=raw)
    db_session.add(row)
    db_session.commit()
    identifier = inspect(row).identity[0]
    selected = []

    def observe(state):
        if state.is_select:
            selected.extend((column.table.name if getattr(column, "table", None) is not None else None, column.key) for column in state.statement.selected_columns)

    event.listen(db_session, "do_orm_execute", observe)
    try:
        claimed = runtime.claim_next_run(db_session)
    finally:
        event.remove(db_session, "do_orm_execute", observe)
    assert claimed is not None and claimed[0] == identifier
    assert not any(table == AIRun.__tablename__ and name in {"input_json", "result_json", "evidence_json", "context_metadata_json"} for table, name in selected)
    assert db_session.query(AIAuditEvent).filter_by(target=identifier).count() == 0
