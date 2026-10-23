"""Main/JWT exact usage responses and current authority on management reads."""

import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.models import User
from app.routers import ai_admin
from tests.test_ai_admin_task_directory import PRIVATE, generic, observer
from tests.test_ai_admin_usage_summary import independent_usage_tasks as independent_usage_tasks
from tests.test_ai_admin_write_authority import change_subject, restore_subject, subject
from tests.test_ai_charge_reconciliation_receipts import terminal
from tests.test_ai_charge_reconciliation_sources import charge_case as charge_case


@pytest.mark.asyncio
async def test_main_usage_is_super_only_and_legacy_counts_remain_unknown(async_client, db_session, seed_data, auth_headers):
    generic(db_session, seed_data)
    for name in ("admin_user", "doctor_user", "director_user", "pharmacist_user", "nurse_user", "patient_user", "cashier_user", "guide_user", "lab_tech_user", "registrar_user"):
        response = await async_client.get("/api/ai/admin/usage", headers=auth_headers(seed_data[name].username))
        assert response.status_code == 403
    assert (await async_client.get("/api/ai/admin/usage")).status_code == 401
    response = await async_client.get("/api/ai/admin/usage", headers=auth_headers("super01"))
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["schema_version"] == "global_ai_usage_summary_v2"
    assert value["coverage"] == {"total": 1, "scanned": 1, "complete": True}
    row = value["data"][0]
    assert row["count"] == row["unverified_count"] == 1
    assert row["input_tokens"] is row["output_tokens"] is None
    assert PRIVATE not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("inputs,outputs,attempted", ((13, 7, True), (13, None, True), (None, 7, True), (None, None, True), (0, 0, False)))
async def test_main_independent_super_reads_actual_receipt_counts_without_original_source_purposes(async_client, charge_case, auth_headers, inputs, outputs, attempted):
    db = charge_case["db"]
    terminal(charge_case, state="cancelled", inputs=inputs, outputs=outputs, attempted=attempted)
    actor = User(username="usage_main_" + uuid.uuid4().hex[:16], password="synthetic-only", user_role="super_admin")
    db.add(actor)
    db.commit()
    response = await async_client.get("/api/ai/admin/usage", headers=auth_headers(actor.username))
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["coverage"] == {"total": 1, "scanned": 1, "complete": True}
    row = value["data"][0]
    assert row["recorded_count"] == 1 and row["input_tokens"] == inputs and row["output_tokens"] == outputs
    assert row["model_call_attempted_count"] == int(attempted)
    assert row["model_call_unattempted_count"] == int(not attempted)
    assert not any(key in response.text for key in ('"patient_id"', '"source_json"', '"result_json"', '"error_message"'))


@pytest.mark.asyncio
async def test_main_mixed_known_partial_zero_and_unverified_task_populations(async_client, charge_case, auth_headers):
    db = charge_case["db"]
    terminal(charge_case, state="cancelled", inputs=13, outputs=None)
    terminal(charge_case, state="cancelled", inputs=0, outputs=0, attempted=False)
    terminal(charge_case, state="cancelled", inputs=5, outputs=7)
    generic(db, charge_case)
    response = await async_client.get("/api/ai/admin/usage", headers=auth_headers("super01"))
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["coverage"] == {"total": 4, "scanned": 4, "complete": True}
    row = next(row for row in value["data"] if row["feature_key"] == "charge_reconciliation")
    assert row["count"] == row["recorded_count"] == 3 and row["input_tokens"] == 18
    assert row["output_tokens"] is None and row["output_tokens_known_sum"] == 7 and row["output_tokens_known_count"] == 2 and row["output_tokens_unknown_count"] == 1
    assert row["model_call_attempted_count"] == 2 and row["model_call_unattempted_count"] == 1
    assert PRIVATE not in json.dumps(value, ensure_ascii=False)


@pytest.mark.parametrize("name", ("list_providers", "list_pathway_sources", "list_grants"))
@pytest.mark.parametrize("axis", ("role", "epoch", "username"))
def test_current_super_identity_is_required_before_each_generic_management_directory(db_session, seed_data, name, axis):
    actor = seed_data["super_admin_user"]
    original = subject(actor)
    change_subject(db_session, original, axis)
    queries, seen = observer(db_session)
    try:
        arguments = {"db": db_session, "user": actor}
        if name != "list_providers":
            arguments["limit"] = 100
        with pytest.raises(HTTPException) as caught:
            getattr(ai_admin, name)(**arguments)
        assert caught.value.status_code == 403
        assert len(queries) == 1 and "FROM hoimsystem_users" in queries[0]
    finally:
        event.remove(db_session.bind, "before_cursor_execute", seen)
        restore_subject(db_session, original)
