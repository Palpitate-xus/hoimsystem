"""Expired ORM identities must not refresh private Task columns before authority."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.orm.exc import DetachedInstanceError

from app.ai import runtime
from app.ai.models import AIRun
from app.ai.research_cohort_cases import case_current
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_cohort_runtime import create_research_run
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_tasks_http import (
    artifact_foreign_keys as artifact_foreign_keys,
)
from tests.test_ai_research_cohort_tasks_http import (
    configured as configured,
)
from tests.test_ai_research_cohort_tasks_http import (
    research_case as research_case,
)
from tests.test_ai_research_cohort_tasks_http import (
    runtime_case as runtime_case,
)
from tests.test_ai_research_cohort_tasks_http import (
    storage_rows as storage_rows,
)

TASK_TEXT = {"input_json", "evidence_json", "context_metadata_json", "result_json"}


def task_text(columns):
    return any(name == field or name.endswith("_" + field) for name in columns for field in TASK_TEXT)


@pytest.mark.parametrize("operation", ["authorize", "describe-current", "describe-withdrawn", "no-user", "no-session"])
def test_actual_expired_shared_run_identity_preserves_source_before_task_text(runtime_case, operation):
    case, db = runtime_case, runtime_case["db"]
    full = case_current(db, case["actor"], case["case_id"])
    authorization_id = full["snapshot"]["capture"]["patient_authorizations"][0]["identity"]["source_record_id"]
    identifier = create_research_run(db, case["actor"], {"research_cohort_case_id": case["case_id"], "question": "原问题不得由过期主键刷新提前读取🧪"})
    run = db.get(AIRun, identifier)
    if operation in {"authorize", "describe-withdrawn"}:
        review_registry_original(db, case["identities"]["super_admin_user"], "authorization", authorization_id, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    db.expire(run)
    if operation == "no-session":
        db.expunge(run)
    returned = []

    def observe(conn, cursor, statement, params, context, many):
        if statement.lstrip().lower().startswith("select") and cursor.description:
            returned.append(tuple(column[0] for column in cursor.description))

    event.listen(db.bind, "after_cursor_execute", observe)
    try:
        if operation == "authorize":
            with pytest.raises(HTTPException) as rejected:
                runtime.authorize_run(db, case["actor"], run)
            assert rejected.value.status_code == 403
        elif operation == "no-user":
            with pytest.raises(HTTPException) as rejected:
                runtime.describe_run(run)
            assert rejected.value.status_code == 403
        elif operation == "no-session":
            # Preserve the pre-existing detached-object error, rather than
            # manufacturing an authorized metadata packet without a Session.
            with pytest.raises(DetachedInstanceError):
                runtime.describe_run(run, user=case["actor"])
        else:
            value = runtime.describe_run(run, user=case["actor"])
            assert value["run_id"] == identifier and value["split_artifacts"] is True
            assert value["clinical_parts_available"] is (operation == "describe-current")
            if operation == "describe-withdrawn":
                assert value["binding"] is None and value["protected_hashes_are_opaque"] is True
    finally:
        event.remove(db.bind, "after_cursor_execute", observe)

    if operation == "describe-current":
        # Full validation is permitted after actual Source authorization.
        # An expired primary-key refresh would instead be the very first read.
        body_index = next(index for index, columns in enumerate(returned) if task_text(columns))
        assert any(any(name == "snapshot_json" or name.endswith("_snapshot_json") for name in columns) for columns in returned[:body_index]), returned
    else:
        assert not any(task_text(columns) for columns in returned), returned
