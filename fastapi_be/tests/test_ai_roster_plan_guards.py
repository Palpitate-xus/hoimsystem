"""Independent collection races, immutable publication and historical guards."""

import copy
import datetime
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Query, Session

from app.ai import roster_facts as facts
from app.ai import roster_plan_input as inputs
from app.ai import roster_plans as plans
from app.ai.models import AIAuditEvent, AIFeedback, AIRun
from app.ai.roster_contract import canonical_json, hash_content
from app.ai.roster_models import AIRosterSource
from app.ai.roster_plan_models import AIRosterPlan, AIRosterRunResult
from app.ai.roster_storage import bounded_result
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.models import Doctor, User
from tests.test_ai_roster_facts import NOTE
from tests.test_ai_roster_facts import create as create_original
from tests.test_ai_roster_pipeline import RealRosterTransport, run_request
from tests.test_ai_roster_pipeline import pipeline_case as pipeline_case
from tests.test_ai_roster_plan_input import plan_case as plan_case
from tests.test_ai_roster_plan_input import roster_case as roster_case
from tests.test_ai_roster_plans import create_plan, publish_plan
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["new_person", "reviewer_role"])
async def test_http_publication_rechecks_collection_and_super_after_sql_precheck(change, async_client, db_session, auth_headers, plan_case, monkeypatch):
    case = plan_case
    row = create_plan(db_session, case)
    identifier, content_hash = row.plan_id, row.content_hash
    actual, injected = Query.update, False
    before_audit = db_session.query(AIAuditEvent).filter_by(action="roster.plan.publish", target=identifier).count()

    def race(query, values, *args, **kwargs):
        nonlocal injected
        if not injected and query.column_descriptions[0]["entity"] is AIRosterPlan:
            injected = True
            with Session(bind=db_session.get_bind()) as second:
                if change == "new_person":
                    second.add(Doctor(name="合成审核预检后新增人员", department_id=case["department"].department_id))
                else:
                    second.query(User).filter_by(user_id=case["super"].user_id).update({"user_role": "admin"})
                second.commit()
        return actual(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", race)
    response = await async_client.post(
        f"/api/ai/roster-plans/{identifier}/review",
        headers=auth_headers(case["super"].username),
        json={"expected_revision": 1, "expected_content_hash": content_hash, "decision": "publish", "review_basis_note": NOTE},
    )
    assert injected
    assert response.status_code == (409 if change == "new_person" else 403), (response.status_code, response.json().get("data", {}).get("status"))
    db_session.expire_all()
    saved = db_session.get(AIRosterPlan, identifier)
    assert saved.status == "draft" and saved.revision == 1 and saved.projection_json is saved.projection_hash is None
    assert db_session.query(AIAuditEvent).filter_by(action="roster.plan.publish", target=identifier).count() == before_audit


@pytest.mark.asyncio
async def test_rehashed_public_value_change_cannot_rewrite_original_private_publication(async_client, db_session, auth_headers, plan_case):
    case = plan_case
    row = publish_plan(db_session, case, create_plan(db_session, case))
    original_private = row.snapshot_json
    source = json.loads(row.projection_json)
    source["options"][0]["slot_capacity"]["value"] += 1
    row.projection_json, row.projection_hash = canonical_json(source), hash_content(source)
    db_session.commit()
    response = await async_client.get("/api/ai/admin/roster-plans/" + row.plan_id, headers=auth_headers(case["super"].username))
    assert response.status_code == 409, response.text
    db_session.refresh(row)
    assert row.snapshot_json == original_private


@pytest.mark.asyncio
async def test_elapsed_plan_is_readable_history_and_not_a_new_execution(async_client, db_session, auth_headers, plan_case, monkeypatch):
    case = plan_case
    row = publish_plan(db_session, case, create_plan(db_session, case))
    original = row.snapshot_json, row.projection_json, row.content_hash, row.projection_hash
    monkeypatch.setattr(inputs, "utcnow", lambda: datetime.datetime(2026, 11, 1, 9))
    response = await async_client.get("/api/ai/roster-plans/" + row.plan_id, headers=auth_headers(case["director"].username))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["snapshot"] == json.loads(original[0]) and data["public_source"] == json.loads(original[1])
    assert data["source_current"] is True and data["eligible"] is False
    assert "planning_period_or_algorithm_changed" in data["exclusion_reasons"]
    with pytest.raises(HTTPException, match="422"):
        plans.authorize_plan(db_session, case["director"], row.plan_id)
    assert plans.authorize_plan(db_session, case["director"], row.plan_id, execution=False)[2] == data["public_source"]
    db_session.refresh(row)
    assert (row.snapshot_json, row.projection_json, row.content_hash, row.projection_hash) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("date,zone", [("9999-12-31", "UTC"), ("0001-01-01", "Pacific/Kiritimati")])
async def test_unrepresentable_exclusive_local_midnight_is_validation_not_server_failure(date, zone, async_client, auth_headers, plan_case):
    case = plan_case
    values = copy.deepcopy(case["plan_request"])
    values.update(date_from=date, date_to=date, business_timezone=zone, sessions=[], options=[], submitted_candidate=None)
    response = await async_client.post("/api/ai/roster-plans/preview", headers=auth_headers(case["director"].username), json=values)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["missing_blob", "rehashed_false_proof"])
async def test_feedback_requires_complete_verified_result_and_cannot_accept_broken_or_rehashed_false_proof(change, async_client, db_session, auth_headers, pipeline_case):
    case = pipeline_case
    run = create_run(db_session, case["director"], run_request(case))
    await execute_claimed(*claim_next_run(db_session), transport=RealRosterTransport(case["service"]))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", (stored.error_code, stored.error_message)
    blob = db_session.get(AIRosterRunResult, run.run_id)
    if change == "missing_blob":
        db_session.delete(blob)
    else:
        value = json.loads(blob.result_json)
        value["roster_analysis"].update(solve_status="optimal_proven", optimality_proven=True)
        blob.result_json, blob.content_hash, blob.result_bytes = bounded_result(value)
        reference = json.loads(stored.result_json)
        reference.update(content_hash=blob.content_hash, result_bytes=blob.result_bytes)
        stored.result_json = canonical_json(reference)
    db_session.commit()
    before = db_session.query(AIFeedback).filter_by(run_id=run.run_id).count()
    before_audit = db_session.query(AIAuditEvent).filter_by(action="run.feedback", target=run.run_id).count()
    response = await async_client.post(
        f"/api/ai/runs/{run.run_id}/feedback",
        headers=auth_headers(case["director"].username),
        json={"outcome": "accepted", "comment": "合成损坏结果不得被反馈为已接受"},
    )
    assert response.status_code == 409, response.text
    assert db_session.query(AIFeedback).filter_by(run_id=run.run_id).count() == before
    assert db_session.query(AIAuditEvent).filter_by(action="run.feedback", target=run.run_id).count() == before_audit


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["prompt", "clock", "count", "provider", "tools", "cross_feature"])
async def test_frozen_task_anchors_checked_on_super_reads_before_exposing_original_plan(change, async_client, db_session, auth_headers, pipeline_case):
    case = pipeline_case
    run = create_run(db_session, case["director"], run_request(case))
    snapshot, metadata = json.loads(run.input_json), json.loads(run.context_metadata_json)
    if change == "prompt":
        snapshot["task_prompt"] += "合成篡改原Prompt"
    elif change == "clock":
        metadata["snapshot_time"] = "2026-10-20T09:10:12.123456Z"
    elif change == "count":
        metadata["source_count"] += 1
    elif change == "provider":
        snapshot["provider_snapshot"]["revision"] += 1
    elif change == "tools":
        snapshot["payload"]["tools"]["unbound_tool"] = {"raw_private_note": NOTE}
    else:
        run.feature_key = "visit_forecast"
    run.input_json, run.context_metadata_json = canonical_json(snapshot), canonical_json(metadata)
    db_session.commit()
    response = await async_client.get(f"/api/ai/admin/runs/{run.run_id}", headers=auth_headers(case["super"].username))
    assert response.status_code == 409, response.text
    assert "frozen_request" not in response.json() and "roster_findings" not in response.json()


@pytest.mark.parametrize("locking", [False, True])
def test_complete_collection_locking_covers_actual_actor_config_department_people_and_all_facts(db_session, plan_case, locking):
    statements = []
    actor, department_id = plan_case["director"], plan_case["department"].department_id
    assert actor.user_id > 0

    def capture_statement(state):
        if state.is_select:
            statements.append((state.statement, state.load_options._populate_existing))

    event.listen(db_session, "do_orm_execute", capture_statement)
    try:
        current = inputs.current_collection(db_session, actor, department_id, locking=locking)
    finally:
        event.remove(db_session, "do_orm_execute", capture_statement)
    assert current["collection_digest"] and len(current["facts"]) == 4
    assert statements
    tables = {table.name for statement, _ in statements for table in statement.get_final_froms()}
    assert {User.__tablename__, Doctor.__tablename__, AIRosterSource.__tablename__, "hoimsystem_department", "hoimsystem_ai_feature_config"} <= tables
    for statement, populate_existing in statements:
        compiled = str(statement.compile(dialect=mysql.dialect()))
        assert compiled.rstrip().endswith("FOR UPDATE") is locking
        assert populate_existing is True
    source_queries = [str(statement.compile(dialect=mysql.dialect())) for statement, _ in statements if AIRosterSource.__table__ in statement.get_final_froms()]
    assert any("ORDER BY" in query and ".status =" not in query for query in source_queries)


def test_locking_collection_refreshes_an_existing_orm_identity_after_real_second_transaction(db_session, plan_case):
    """SQLite proves fresh reads here; MySQL lock behavior requires its own runner."""
    case = plan_case
    row = case["facts"]["qualification"]
    identifier = row.source_record_id
    assert db_session.get(AIRosterSource, identifier).status == "published"
    with Session(bind=db_session.get_bind()) as second:
        facts.revoke_source(second, second.get(User, case["super"].user_id), "qualification", identifier, {"expected_revision": 2, "reason": "合成独立事务更新须绕过旧identity缓存"})
        second.commit()
    assert row.status == "published"
    result = inputs.current_collection(db_session, case["director"], case["department"].department_id, locking=True)
    refreshed = next(item for item in result["facts"] if item["source_record_id"] == identifier)
    assert refreshed["status"] == "revoked" and refreshed["payload"] is None and refreshed["eligible"] is False
    assert row.status == "revoked"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["subject_move", "reviewer_role"])
async def test_original_fact_publication_also_rechecks_actual_parent_and_super_after_precheck(change, async_client, db_session, auth_headers, plan_case, monkeypatch):
    case = plan_case
    row = create_original(db_session, case)
    identifier, original_body = row.source_record_id, (row.payload_json, row.parent_binding_json, row.content_hash)
    actual, injected = Query.update, False
    before_audit = db_session.query(AIAuditEvent).filter_by(action="roster_source.publish", target=identifier).count()

    def race(query, values, *args, **kwargs):
        nonlocal injected
        if not injected and query.column_descriptions[0]["entity"] is AIRosterSource:
            injected = True
            with Session(bind=db_session.get_bind()) as second:
                if change == "subject_move":
                    second.query(Doctor).filter_by(doctor_id=case["doctor"].doctor_id).update({"department_id": case["foreign"].department_id})
                else:
                    second.query(User).filter_by(user_id=case["super"].user_id).update({"user_role": "admin"})
                second.commit()
        return actual(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", race)
    response = await async_client.post(
        f"/api/ai/roster-sources/qualification/{identifier}/review",
        headers=auth_headers(case["super"].username),
        json={"expected_revision": 1, "expected_content_hash": original_body[2], "decision": "publish", "review_basis_note": NOTE},
    )
    assert injected and response.status_code == (409 if change == "subject_move" else 403), (response.status_code, response.text[:200])
    db_session.expire_all()
    saved = db_session.get(AIRosterSource, identifier)
    assert saved.status == "draft" and saved.revision == 1
    assert (saved.payload_json, saved.parent_binding_json, saved.content_hash) == original_body
    assert db_session.query(AIAuditEvent).filter_by(action="roster_source.publish", target=identifier).count() == before_audit
