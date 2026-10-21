"""Actual expired75 routing keeps current purpose before private Task bytes."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai import runtime
from app.ai.deidentification_runtime import create_deidentification_run
from app.ai.research_cohort_registry import review_registry_original
from tests.test_ai_deidentification_storage import task_case as task_case
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import research_case as research_case


@pytest.mark.parametrize("operation", ["authorize", "describe-current", "describe-withdrawn"])
def test_actual_expired75_object_never_refreshes_task_before_current_purpose(task_case, operation):
    case, db = task_case, task_case["db"]
    run = create_deidentification_run(db, case["actor"], case["input"])
    if operation != "describe-current":
        review_registry_original(db, case["users"]["super_admin_user"], "authorization", case["values"][3]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    db.expire(run)
    selected = []

    def observe(conn, cursor, sql, args, context, many):
        if sql.lstrip().upper().startswith("SELECT") and cursor.description:
            selected.append(tuple(c[0] for c in cursor.description))

    event.listen(db.bind, "after_cursor_execute", observe)
    try:
        if operation == "authorize":
            with pytest.raises(HTTPException) as rejected:
                runtime.authorize_run(db, case["actor"], run)
            assert rejected.value.status_code == 403
        else:
            value = runtime.describe_run(run, user=case["actor"])
            assert value["schema_version"] == "deidentification_shared_task_metadata_v1"
            assert value["clinical_parts_available"] is (operation == "describe-current")
            if operation == "describe-withdrawn":
                assert value["binding"] is value["part_hashes"] is None
                assert value["source"] is value["result"] is value["raw_frozen_json"] is None
    finally:
        event.remove(db.bind, "after_cursor_execute", observe)
    private = ("input_json", "evidence_json", "context_metadata_json", "result_json", "source_json")

    def task_read(columns):
        return any(c == name or c.endswith("_" + name) for c in columns for name in private)

    if operation == "describe-current":
        first = next(index for index, columns in enumerate(selected) if task_read(columns))
        assert any(any(c == "snapshot_json" or c.endswith("_snapshot_json") for c in columns) for columns in selected[:first]), selected
    else:
        assert not any(task_read(columns) for columns in selected), selected
