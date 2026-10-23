"""A real prior claim cannot monopolize bounded polling after header damage."""

import datetime as dt
import uuid

from sqlalchemy import event, select, update

from app.ai import research_variables_attempts as attempts
from app.ai import research_variables_storage as storage
from app.ai import runtime
from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_variables_run_models import AIResearchVariableRunArtifact as Artifact
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_storage import prepare
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory


def state(db, ids):
    return [
        tuple(row)
        for row in db.execute(
            select(
                AIRun.run_id,
                AIRun.status,
                AIRun.lease_token,
                AIRun.start_time,
                AIRun.input_tokens,
                AIRun.output_tokens,
                Artifact.create_event_id,
                Artifact.claim_event_id,
                Artifact.claim_lease,
                Artifact.claimed_at,
                Artifact.dispatch_event_id,
                Artifact.usage_event_id,
            )
            .join(Artifact, Artifact.run_id == AIRun.run_id)
            .where(AIRun.run_id.in_(ids))
            .order_by(AIRun.run_id)
        )
    ]


def test_129_actual_claimed_variable_tasks_with_damaged_queued_status_cannot_starve_later_work(db_session, configured, task_factory):
    db = db_session
    case, _, _, prepared, snapshot = prepare(db, configured, task_factory)
    ids = []
    for _ in range(129):
        task = storage.stage_run(db, case["admin_user"], AIRun(run_id=str(uuid.uuid4()), preview=0), prepared, snapshot)
        identifier = task.run.run_id
        claim = attempts.stage_claim(db, case["admin_user"], identifier)
        assert claim is not None
        db.commit()
        ids.append(identifier)
    # Keep every genuine Source, creation and durable claim record intact.
    # Only a corrupted mutable status now says queued; no receipt is invented.
    db.execute(update(AIRun).where(AIRun.run_id.in_(ids)).values(status="queued"))
    later = AIRun(
        run_id=str(uuid.uuid4()),
        feature_key="operations_qa",
        requested_by=case["super_admin_user"].user_id,
        prompt_hash="a" * 64,
        context_digest="b" * 64,
        create_time=dt.datetime.now(dt.UTC).replace(tzinfo=None),
    )
    db.add(later)
    db.commit()
    later_id, before = later.run_id, state(db, ids)
    audit_count = db.query(AIAuditEvent).count()
    projected = []

    def observe(execution):
        if execution.is_select and hasattr(execution.statement, "selected_columns"):
            projected.extend((getattr(column, "table", None), column.key) for column in execution.statement.selected_columns)

    event.listen(db, "do_orm_execute", observe)
    try:
        claim = runtime.claim_next_run(db)
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert claim is not None and claim[0] == later_id
    assert state(db, ids) == before
    assert db.query(AIAuditEvent).count() == audit_count
    assert not any(table is AIRun.__table__ and key in {"input_json", "evidence_json", "context_metadata_json", "result_json"} for table, key in projected)
