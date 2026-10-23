"""Real Main/JWT and exact direct-column observations, synthetic SQL only."""

import datetime as dt
import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, inspect, text
from sqlalchemy.orm import Session

from app.ai import research_variables_runtime as dedicated
from app.ai import runtime
from app.ai.models import AIRun
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_cohort_sources import utcnow
from app.ai.research_variables_batches import review_batch
from app.ai.research_variables_run_models import AIResearchVariableRunArtifact
from app.ai.research_variables_task_contract import FEATURE_KEY, SOURCE_DOMAIN
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import actual_task as actual_task

TASK_BODY = {"input_json", "result_json", "evidence_json", "context_metadata_json", "source_json", "binding_json"}
BATCH_BODY = {"snapshot_json", "projection_json", "dictionary_json", "parent_binding_json"}


def watch(extra=False):
    columns = []

    def seen(state):
        if state.is_select and hasattr(state.statement, "selected_columns"):
            for column in state.statement.selected_columns:
                table = getattr(getattr(column, "table", None), "name", None)
                task = table in {"hoimsystem_ai_run", "hoimsystem_ai_research_variable_run_artifact"} and column.key in TASK_BODY
                batch = extra and table in {"hoimsystem_ai_research_variable_batch", "hoimsystem_ai_research_variable_dictionary"} and column.key in BATCH_BODY
                if task or batch:
                    columns.append(table + "." + column.key)

    event.listen(Session, "do_orm_execute", seen)
    return columns, seen


@pytest.mark.asyncio
async def test_current_withdrawal_of_unselected_scope_patient_denies_every_main_piece_feedback_and_both_directories_before_private_body_even_super(db_session, actual_task, async_client, auth_headers):
    case, permissions, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    # Pure bound identity, captured before revocation commit expires the test's
    # fixture ORM object. No setup refresh may contaminate the HTTP observer.
    batch_identifier = staged.binding.batch_id
    admin, sup = (auth_headers(case[k].username) for k in ("admin_user", "super_admin_user"))
    review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    columns, seen = watch(True)
    try:
        for headers in (admin, sup):
            for suffix in ("", "/research-variables/binding", "/research-variables/source", "/research-variables/scope", "/research-variables/result", "/research-variables/receipt"):
                response = await async_client.get("/api/ai/runs/" + identifier + suffix, headers=headers)
                assert response.status_code == 403, (suffix, response.text)
            response = await async_client.post("/api/ai/runs/" + identifier + "/feedback", headers=headers, json={"outcome": "accepted", "comment": "不恢复原权"})
            assert response.status_code == 403, response.text
        trace = await async_client.get("/api/ai/admin/runs/" + identifier, headers=sup)
        assert trace.status_code == 403, trace.text
        params = {"feature_key": FEATURE_KEY, "research_variable_batch_id": batch_identifier}
        for path, headers in (("/api/ai/runs", admin), ("/api/ai/admin/runs", sup)):
            response = await async_client.get(path, headers=headers, params=params)
            assert response.status_code == 403, response.text
        ordinary = await async_client.post("/api/ai/runs/" + identifier + "/cancel", headers=admin)
        assert ordinary.status_code == 403, ordinary.text
        technical = await async_client.post("/api/ai/runs/" + identifier + "/cancel", headers=sup)
        assert technical.status_code == 200 and technical.json()["data"]["receipt_pending"] is False, technical.text
        still_denied = await async_client.get("/api/ai/admin/runs/" + identifier, headers=sup)
        assert still_denied.status_code == 403
    finally:
        event.remove(Session, "do_orm_execute", seen)
    assert not columns


@pytest.mark.asyncio
@pytest.mark.parametrize("axis,expected", [("role", 403), ("epoch", 401), ("username", 401)])
async def test_actual_authenticated_request_identity_change_clears_native_read_before_task_or_batch_body(db_session, actual_task, async_client, auth_headers, axis, expected):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    user = case["admin_user"]
    old = {"user_role": user.user_role, "username": user.username, "token_invalid_before": user.token_invalid_before}
    user_id = inspect(user).identity[0]
    headers = auth_headers(old["username"])
    field, value = {"role": ("user_role", "nurse"), "epoch": ("token_invalid_before", dt.datetime(2099, 1, 1)), "username": ("username", "changed_" + identifier)}[axis]
    db_session.execute(text("UPDATE hoimsystem_users SET " + field + "=:value WHERE user_id=:id"), {"value": value, "id": user_id})
    db_session.commit()
    columns, seen = watch(True)
    try:
        response = await async_client.get("/api/ai/runs/" + identifier, headers=headers)
        assert response.status_code == expected, response.text
        assert not columns
    finally:
        event.remove(Session, "do_orm_execute", seen)
        db_session.rollback()
        db_session.execute(text("UPDATE hoimsystem_users SET user_role=:user_role,username=:username,token_invalid_before=:token_invalid_before WHERE user_id=:id"), {**old, "id": user_id})
        db_session.commit()


@pytest.mark.asyncio
async def test_revoked_batch_has_no_ordinary_task_body_and_explicit_super_frozen_parts_preserve_original_publication_without_reexecution(db_session, actual_task, async_client, auth_headers):
    case, _, batch, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    admin, sup = (auth_headers(case[k].username) for k in ("admin_user", "super_admin_user"))
    frozen_governance = staged.binding.batch_governance_hash
    review_batch(db_session, case["super_admin_user"], batch["batch_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    columns, seen = watch()
    try:
        ordinary = await async_client.get("/api/ai/runs/" + identifier, headers=admin)
        assert ordinary.status_code == 409, ordinary.text
        assert dedicated.claim_variable_run(db_session, identifier) is None
    finally:
        event.remove(Session, "do_orm_execute", seen)
    assert not columns
    trace = await async_client.get("/api/ai/admin/runs/" + identifier, headers=sup)
    assert trace.status_code == 200, trace.text
    value = trace.json()["data"]
    assert value["frozen_audit"] is True and value["execution_current"] is False
    assert value["run"]["status"] == "failed" and value["run"]["usage_receipt"]["model_call_attempted"] is False
    bound = await async_client.get("/api" + value["parts"]["binding"], headers=sup)
    assert bound.status_code == 200 and bound.json()["binding"]["batch_governance_hash"] == frozen_governance
    source = await async_client.get("/api" + value["parts"]["source"], headers=sup)
    assert source.status_code == 200, source.text
    assert source.json()["source"]["governance_hash"] == frozen_governance
    result = await async_client.get("/api" + value["parts"]["result"], headers=sup)
    assert result.status_code == 409


@pytest.mark.asyncio
async def test_actual_foreign_or_null_batch_reference_and_extra_patient_context_never_enter_generic_source_helpers_or_task_body(db_session, configured, async_client, auth_headers):
    headers = auth_headers(configured[0]["super_admin_user"].username)
    columns, seen = watch(True)
    try:
        for value in (None, "00000000-0000-0000-0000-000000000001"):
            response = await async_client.post("/api/ai/runs", headers=headers, json={"feature_key": "operations_qa", "input": {"research_variable_batch_id": value}})
            assert response.status_code == 422, response.text
            response = await async_client.post("/api/ai/operational-context", headers=headers, json={"feature_key": "operations_qa", "input": {"research_variable_batch_id": value}})
            assert response.status_code == 422, response.text
        response = await async_client.get("/api/ai/service-options", headers=headers, params={"feature_key": "operations_qa", "research_variable_batch_id": ""})
        assert response.status_code == 422, response.text
        for body in (
            {"research_variable_batch_id": None},
            {"research_variable_batch_id": "00000000-0000-0000-0000-000000000001", "patient_id": 1},
            {"research_variable_batch_id": "00000000-0000-0000-0000-000000000001", "source": {"text": "caller private text"}},
        ):
            response = await async_client.post("/api/ai/research-variables/context", headers=headers, json=body)
            assert response.status_code == 422, response.text
    finally:
        event.remove(Session, "do_orm_execute", seen)
    assert not columns


@pytest.mark.asyncio
async def test_each_remaining_native_orphan_marker_including_null_fails_all_shared_routes_and_worker_before_task_body(db_session, actual_task, async_client, auth_headers):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    admin, sup = (auth_headers(case[k].username) for k in ("admin_user", "super_admin_user"))
    artifact = dict(db_session.execute(AIResearchVariableRunArtifact.__table__.select().where(AIResearchVariableRunArtifact.run_id == identifier)).one()._mapping)
    run = db_session.get(AIRun, identifier)
    original = {key: getattr(run, key) for key in ("feature_key", "input_json", "result_json", "evidence_json", "context_metadata_json")}
    db_session.execute(delete(AIResearchVariableRunArtifact).where(AIResearchVariableRunArtifact.run_id == identifier))
    db_session.commit()
    markers = [
        {"feature_key": FEATURE_KEY},
        {"input_json": {"schema_version": "research_variable_task_snapshot_v1"}},
        {"input_json": {"payload": {"input": {"research_variable_batch_id": None}}}},
        {"input_json": {"payload": {"context": {"research_variable_binding": None}}}},
        {"input_json": {"payload": {"context": {"scope": {"selected_sources": {"research_variable_batch_id": None}}}}}},
        {"input_json": {"payload": {"context": {"scope": {"source_domain": SOURCE_DOMAIN}}}}},
        {"context_metadata_json": {"source_domain": SOURCE_DOMAIN}},
        {"context_metadata_json": {"research_variable_binding": None}},
        {"result_json": {"schema_version": "research_variable_result_ref_v1"}},
        {"result_json": {"research_variable_extraction": None}},
    ]
    calls = []

    async def forbidden(request):
        calls.append(request.url.path)
        raise AssertionError("No orphan model call")

    columns, seen = watch()
    try:
        for marker in markers:
            fields = {"feature_key": "operations_qa", "input_json": "{}", "result_json": "{}", "evidence_json": "[]", "context_metadata_json": "{}"}
            fields.update({key: json.dumps(value, separators=(",", ":")) if isinstance(value, dict) else value for key, value in marker.items()})
            db_session.execute(text("UPDATE hoimsystem_ai_run SET " + ",".join(key + "=:" + key for key in fields) + " WHERE run_id=:id"), {**fields, "id": identifier})
            db_session.commit()
            for path, headers in (("/api/ai/runs/" + identifier, admin), ("/api/ai/admin/runs/" + identifier, sup)):
                response = await async_client.get(path, headers=headers)
                assert response.status_code == 409, (marker, response.text)
            for suffix, body in (("cancel", None), ("feedback", {"outcome": "accepted", "comment": "不得降级"})):
                response = await async_client.post("/api/ai/runs/" + identifier + "/" + suffix, headers=admin, json=body)
                assert response.status_code == 409, (marker, response.text)
            with pytest.raises(HTTPException) as error:
                await runtime.execute_claimed(identifier, "wrong-lease", transport=httpx.MockTransport(forbidden))
            assert error.value.status_code == 409
        assert not columns and not calls
    finally:
        event.remove(Session, "do_orm_execute", seen)
        db_session.rollback()
        db_session.execute(text("UPDATE hoimsystem_ai_run SET " + ",".join(key + "=:" + key for key in original) + " WHERE run_id=:id"), {**original, "id": identifier})
        db_session.execute(AIResearchVariableRunArtifact.__table__.insert().values(**artifact))
        db_session.commit()


def test_generic_interrupted_recovery_does_not_rewrite_an_orphan_native_task_after_feature_erasure(db_session, actual_task, monkeypatch):
    _, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    artifact = dict(db_session.execute(AIResearchVariableRunArtifact.__table__.select().where(AIResearchVariableRunArtifact.run_id == identifier)).one()._mapping)
    db_session.execute(delete(AIResearchVariableRunArtifact).where(AIResearchVariableRunArtifact.run_id == identifier))
    db_session.execute(
        text("UPDATE hoimsystem_ai_run SET feature_key='operations_qa',status='running',start_time=:start,lease_token='orphan-lease' WHERE run_id=:id"), {"start": utcnow(), "id": identifier}
    )
    db_session.commit()
    monkeypatch.setattr(runtime, "utcnow", lambda: utcnow() + dt.timedelta(minutes=11))
    columns, seen = watch()
    try:
        assert runtime.expire_interrupted_runs(db_session) == 0
        assert not columns
        assert db_session.query(AIRun.status).filter_by(run_id=identifier).scalar() == "running"
    finally:
        event.remove(Session, "do_orm_execute", seen)
        db_session.rollback()
        db_session.execute(
            text("UPDATE hoimsystem_ai_run SET feature_key=:feature,status='queued',start_time=NULL,lease_token=NULL,error_code=NULL,error_message=NULL,finish_time=NULL WHERE run_id=:id"),
            {"feature": FEATURE_KEY, "id": identifier},
        )
        db_session.execute(AIResearchVariableRunArtifact.__table__.insert().values(**artifact))
        db_session.commit()
