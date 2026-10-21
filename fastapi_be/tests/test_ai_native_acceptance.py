"""Actual SQL triggers cannot change native acceptance anchors or complete proof."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.ai.models import AIAuditEvent, AIRun
from app.ai.runtime import execute_claimed
from app.ai.supply_series_models import AISupplyRunResult
from tests.test_ai_supply_pipeline import NativeSupplyTransport, queued_and_claimed
from tests.test_ai_supply_pipeline import clear_supply_tasks as clear_supply_tasks
from tests.test_ai_supply_pipeline import pipeline_case as pipeline_case
from tests.test_ai_supply_pipeline import series_case as series_case
from tests.test_ai_supply_pipeline import supply_case as supply_case


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["task_metadata", "task_owner", "task_lease", "task_pointer", "task_status", "task_feature", "blob_body", "blob_delete", "audit_detail", "audit_delete"])
async def test_postwrite_database_mutations_roll_back_the_complete_acceptance(fault, async_client, auth_headers, db_session, pipeline_case):
    case, db = pipeline_case, db_session
    claim = await queued_and_claimed(async_client, auth_headers(case["admin"].username), db, case)
    run_id, lease = claim
    changes = {
        "task_metadata": f"UPDATE hoimsystem_ai_run SET context_metadata_json='{{}}' WHERE run_id='{run_id}'",
        "task_owner": f"UPDATE hoimsystem_ai_run SET requested_by={case['super'].user_id} WHERE run_id='{run_id}'",
        "task_lease": f"UPDATE hoimsystem_ai_run SET lease_token='{uuid4()}' WHERE run_id='{run_id}'",
        "task_pointer": f"UPDATE hoimsystem_ai_run SET result_json='{{}}' WHERE run_id='{run_id}'",
        "task_status": f"UPDATE hoimsystem_ai_run SET status='cancelled' WHERE run_id='{run_id}'",
        "task_feature": f"UPDATE hoimsystem_ai_run SET feature_key='operations_qa' WHERE run_id='{run_id}'",
        "blob_body": f"UPDATE hoimsystem_ai_supply_run_result SET result_json='{{}}' WHERE run_id='{run_id}'",
        "blob_delete": f"DELETE FROM hoimsystem_ai_supply_run_result WHERE run_id='{run_id}'",
        "audit_detail": "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id",
        "audit_delete": "DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id",
    }
    trigger = "supply_owned_current_acceptance_fault"
    if fault in {"task_pointer", "task_status"}:
        timing = f"AFTER UPDATE ON hoimsystem_ai_run WHEN NEW.run_id='{run_id}' AND NEW.status='succeeded'"
    elif fault in {"blob_body", "blob_delete"}:
        timing = f"AFTER INSERT ON hoimsystem_ai_supply_run_result WHEN NEW.run_id='{run_id}'"
    else:
        timing = "AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.supply_result.accept'"
    db.execute(text(f"CREATE TRIGGER {trigger} {timing} BEGIN {changes[fault]}; END"))
    db.commit()
    try:
        wire = NativeSupplyTransport(case["service"])
        await execute_claimed(*claim, transport=wire)
        db.expire_all()
        run = db.get(AIRun, run_id)
        assert len(wire.requests) == 1 and (run.status, run.error_code, run.result_json) == ("failed", "RESULT_STORAGE_ERROR", "{}"), (run.status, run.error_code, run.error_message)
        assert run.requested_by == case["admin"].user_id and run.lease_token == lease and run.feature_key == "supply_forecast"
        assert json.loads(run.context_metadata_json)["source_count"] == 1
        assert db.query(AISupplyRunResult).filter_by(run_id=run_id).count() == 0
        assert db.query(AIAuditEvent).filter_by(action="run.supply_result.accept", target=run_id).count() == 0
    finally:
        db.rollback()
        db.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
        db.commit()
