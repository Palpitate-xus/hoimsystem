"""Actual Main/JWT shared routes cannot bypass withdrawn research purposes."""

import json

import pytest
from sqlalchemy import event

from tests.test_ai_research_cohort_storage import capture_sql, task_body_selects
from tests.test_ai_research_cohort_tasks_states_http import (
    actual_task_routes as actual_task_routes,
)
from tests.test_ai_research_cohort_tasks_states_http import (
    artifact_foreign_keys as artifact_foreign_keys,
)
from tests.test_ai_research_cohort_tasks_states_http import (
    configured as configured,
)
from tests.test_ai_research_cohort_tasks_states_http import (
    research_case as research_case,
)
from tests.test_ai_research_cohort_tasks_states_http import (
    runtime_case as runtime_case,
)
from tests.test_ai_research_cohort_tasks_states_http import (
    storage_rows as storage_rows,
)
from tests.test_ai_research_cohort_tasks_states_http import (
    test_actual_main_same_case_all_states_directory20_and_research_withdrawal_never_restore_task_text as prepare_actual_states,
)


def contains(value, text):
    if isinstance(value, str):
        return text in value
    if isinstance(value, dict):
        return any(contains(v, text) for v in value.values())
    if isinstance(value, list):
        return any(contains(v, text) for v in value)
    return False


@pytest.mark.asyncio
async def test_shared_main_details_trace_cancel_feedback_and_directories_keep_research_revocation_before_task_text(runtime_case, async_client, auth_headers, actual_task_routes, tmp_path):
    await prepare_actual_states(runtime_case, async_client, auth_headers, actual_task_routes, tmp_path)
    packet = json.loads((tmp_path / "actual-research-main-five-states.json").read_text())
    identifier = packet["succeeded"]["run_id"]
    case = runtime_case
    actor_headers = auth_headers(case["actor"].username)
    super_headers = auth_headers(case["identities"]["super_admin_user"].username)
    requests = [
        ("GET", f"/api/ai/runs/{identifier}", actor_headers, None),
        ("GET", f"/api/ai/runs/{identifier}", super_headers, None),
        ("GET", f"/api/ai/admin/runs/{identifier}", super_headers, None),
        ("POST", f"/api/ai/runs/{identifier}/feedback", actor_headers, {"outcome": "accepted", "comment": "不得恢复研究权限"}),
        ("POST", f"/api/ai/runs/{identifier}/feedback", super_headers, {"outcome": "accepted", "comment": "技术身份不恢复研究权限"}),
    ]
    for method, path, headers, body in requests:
        statements, close = capture_sql(case["db"])
        try:
            response = await async_client.request(method, path, headers=headers, **({"json": body} if body is not None else {}))
        finally:
            close()
        assert response.status_code == 403, (path, response.status_code, response.text)
        assert task_body_selects(statements) == [], path
        assert not contains(response.json(), packet["selection"]["question"])

    for headers in (actor_headers, super_headers):
        statements, close = capture_sql(case["db"])
        try:
            response = await async_client.post(f"/api/ai/runs/{identifier}/cancel", headers=headers)
        finally:
            close()
        assert response.status_code == 409, response.text
        assert task_body_selects(statements) == []
    for path, headers in (("/api/ai/runs?feature_key=research_cohort", actor_headers), ("/api/ai/admin/runs?feature_key=research_cohort", super_headers)):
        selected_columns = []

        def returned_columns(conn, cursor, statement, params, context, many):
            if statement.lstrip().lower().startswith("select"):
                selected_columns.extend(column[0] for column in cursor.description or ())

        event.listen(case["db"].bind, "after_cursor_execute", returned_columns)
        statements, close = capture_sql(case["db"])
        try:
            response = await async_client.get(path, headers=headers)
        finally:
            close()
            event.remove(case["db"].bind, "after_cursor_execute", returned_columns)
        assert response.status_code == 200, response.text
        assert not {"input_json", "evidence_json", "context_metadata_json", "result_json", "source_json", "source_binding_json", "prompt_snapshot_json", "execution_snapshot_json"}.intersection(
            selected_columns
        )
        assert not contains(response.json(), packet["selection"]["question"])
        for item in response.json()["data"]:
            assert item["clinical_parts_available"] is False
            assert item["binding"] is None
