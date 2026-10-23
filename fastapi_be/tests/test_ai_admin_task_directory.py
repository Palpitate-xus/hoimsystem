"""Technical supervision remains useful without granting any Source body purpose."""

import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, select, text, update

from app.ai.admin_read_snapshot import admin_read_snapshot
from app.ai.admin_task_directory import AdminTaskMetadata, DOMAIN_FEATURES, task_directory
from app.ai.models import AIFeedback, AIRun
from app.ai.native_task_routing import _domains
from app.ai.schemas import RunRequest
from app.models import User
from tests.test_ai_admin_write_authority import change_subject, restore_subject, subject
from tests.test_ai_rca_evidence_configuration import configured as rca_configuration
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import actual_task as actual_task

PRIVATE = "合成的患者原始病历、问题、来源以及模型输出，不得进入技术目录"


def generic(db, seed_data, count=1):
    owner = User(username="owner_" + uuid.uuid4().hex[:12], password="synthetic", user_role="doctor")
    db.add(owner)
    db.flush()
    rows = [AIRun(feature_key="operations_qa", requested_by=owner.user_id, patient_id=seed_data["patient"].patient_id, encounter_ref="private-encounter", prompt_hash="a" * 64, context_digest="b" * 64, input_json=json.dumps({"question": PRIVATE}), result_json=json.dumps({"answer": PRIVATE}), context_metadata_json=json.dumps({"source": PRIVATE}), evidence_json=json.dumps([PRIVATE]), error_message=PRIVATE, input_tokens=17, output_tokens=0) for _ in range(count)]
    db.add_all(rows)
    db.commit()
    return owner, [inspect(row).identity[0] for row in rows]


def observer(db):
    queries = []

    def seen(conn, cursor, statement, parameters, context, many):
        queries.append(statement)

    event.listen(db.bind, "before_cursor_execute", seen)
    return queries, seen


def assert_no_private_queries(queries):
    for sql in queries:
        assert not any(name in sql for name in (".input_json", ".result_json", ".evidence_json", ".context_metadata_json", ".source_json", ".binding_json", ".mapping_seed", ".detail_json", ".comment", ".patient_id", ".encounter_ref", ".error_message")), sql
        assert not any(name in sql for name in ("FOR UPDATE", "LOCK IN SHARE MODE", "write_gate")), sql


@pytest.mark.asyncio
async def test_main_technical_directory_is_super_only_and_exposes_no_patient_text(async_client, seed_data, db_session, auth_headers):
    owner, ids = generic(db_session, seed_data)
    for name in ("admin_user", "doctor_user", "director_user", "pharmacist_user", "nurse_user", "patient_user", "cashier_user", "guide_user", "lab_tech_user", "registrar_user"):
        username = seed_data[name].username
        response = await async_client.get("/api/ai/admin/task-directory", headers=auth_headers(username))
        assert response.status_code == 403, (username, response.text)
    assert (await async_client.get("/api/ai/admin/task-directory")).status_code == 401
    response = await async_client.get("/api/ai/admin/task-directory", headers=auth_headers("super01"), params={"requested_by": owner.user_id})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 1 and data["data"][0]["run_id"] == ids[0]
    row = AdminTaskMetadata.model_validate_json(json.dumps(data["data"][0]))
    assert row.native_identity_state == "unproven"
    assert row.usage_verification == "not_verified" and row.input_tokens is None and row.output_tokens is None
    assert PRIVATE not in response.text and "private-encounter" not in response.text
    assert not {"patient_id", "encounter_ref", "error_message", "result", "frozen_request"}.intersection(data["data"][0])


@pytest.mark.asyncio
@pytest.mark.parametrize("params", ({"patient_id": PRIVATE}, {"research_variable_batch_id": PRIVATE}, [("page", "1"), ("page", "2")], {"page": 0}))
async def test_technical_directory_rejects_foreign_and_ambiguous_filters(async_client, seed_data, auth_headers, params):
    response = await async_client.get("/api/ai/admin/task-directory", headers=auth_headers("super01"), params=params)
    assert response.status_code == 422
    assert PRIVATE not in response.text


def test_complete_page_counts_and_feedback_filter_never_duplicate_or_project_private_text(db_session, seed_data):
    owner, ids = generic(db_session, seed_data, 67)
    db_session.add_all([AIFeedback(run_id=ids[0], reviewer_id=seed_data["super_admin_user"].user_id, outcome="rejected", comment=PRIVATE), AIFeedback(run_id=ids[0], reviewer_id=seed_data["super_admin_user"].user_id, outcome="modified", comment=PRIVATE)])
    db_session.commit()
    queries, seen = observer(db_session)
    try:
        pages = [task_directory(db_session, seed_data["super_admin_user"], requested_by=owner.user_id, page=page, page_size=30) for page in (1, 2, 3, 4)]
        filtered = task_directory(db_session, seed_data["super_admin_user"], requested_by=owner.user_id, outcome="rejected")
    finally:
        event.remove(db_session.bind, "before_cursor_execute", seen)
    assert [len(page["data"]) for page in pages] == [30, 30, 7, 0]
    assert all(page["total"] == 67 for page in pages)
    assert {row["run_id"] for page in pages for row in page["data"]} == set(ids)
    assert filtered["total"] == 1 and filtered["data"][0]["feedback_count"] == 2
    assert PRIVATE not in json.dumps(pages, ensure_ascii=False)
    assert_no_private_queries(queries)
    anchor_query = next(sql for sql in queries if "UNION ALL" in sql)
    assert all(model.__tablename__ in anchor_query for _, model, _ in _domains())
    assert set(DOMAIN_FEATURES) == {domain for domain, _, _ in _domains()}


@pytest.mark.parametrize("axis", ("role", "epoch", "username"))
def test_old_authenticated_subject_is_denied_before_any_task_query(db_session, seed_data, axis):
    generic(db_session, seed_data)
    actor = seed_data["super_admin_user"]
    original = subject(actor)
    change_subject(db_session, original, axis)
    queries, seen = observer(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            task_directory(db_session, actor)
        assert error.value.status_code == 403
        assert len(queries) == 1 and "FROM hoimsystem_users" in queries[0]
    finally:
        event.remove(db_session.bind, "before_cursor_execute", seen)
        restore_subject(db_session, original)


@pytest.mark.parametrize("axis,assignment", (("role", "user_role='pharmacist'"), ("epoch", "token_invalid_before='2099-01-02 03:04:05.123456'"), ("username", "username='moved-during-read'")))
def test_subject_change_during_snapshot_denies_the_complete_response(db_session, seed_data, axis, assignment):
    owner, _ = generic(db_session, seed_data)
    actor = seed_data["super_admin_user"]
    original = subject(actor)
    changed = []

    def mutate(conn, cursor, sql, params, context, many):
        if not changed and "FROM hoimsystem_ai_run" in sql and "count(" not in sql.lower():
            changed.append(True)
            db_session.execute(text("UPDATE hoimsystem_users SET " + assignment + " WHERE user_id=:pk"), {"pk": original["user_id"]})

    event.listen(db_session.bind, "after_cursor_execute", mutate)
    try:
        with pytest.raises(HTTPException) as error:
            task_directory(db_session, actor, requested_by=owner.user_id)
        assert error.value.status_code == 403 and changed == [True]
    finally:
        event.remove(db_session.bind, "after_cursor_execute", mutate)
        restore_subject(db_session, original)


def test_snapshot_rejects_mutations_and_locks_without_committing_callers_transaction(db_session, seed_data):
    actor = seed_data["super_admin_user"]
    with admin_read_snapshot(db_session, actor) as snapshot:
        with pytest.raises(ValueError):
            snapshot.execute(update(User).values(user_role="pharmacist"))
        with pytest.raises(ValueError):
            snapshot.execute(select(User.user_id).with_for_update(read=True))
        with pytest.raises(ValueError):
            snapshot.execute(select(select(User.user_id).with_for_update(read=True).scalar_subquery()))
        changed = update(User).values(user_role="pharmacist").returning(User.user_id).cte()
        with pytest.raises(ValueError):
            snapshot.execute(select(changed.c.user_id))
        assert snapshot.scalar(select(User.user_role).where(User.user_id == actor.user_id)) == "super_admin"
    assert db_session.in_transaction()


@pytest.mark.asyncio
async def test_super_without_variable_purposes_can_see_technical_header_but_not_frozen_source(db_session, actual_task, async_client, auth_headers):
    _, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    actor = User(username="audit_" + uuid.uuid4().hex[:12], password="synthetic", user_role="super_admin")
    db_session.add(actor)
    db_session.commit()
    headers = auth_headers(actor.username)
    queries, seen = observer(db_session)
    try:
        response = await async_client.get("/api/ai/admin/task-directory", headers=headers, params={"page_size": 100})
    finally:
        event.remove(db_session.bind, "before_cursor_execute", seen)
    assert response.status_code == 200, response.text
    row = next(row for row in response.json()["data"] if row["run_id"] == identifier)
    assert row["native_domains"] == ["research_variables"] and row["native_identity_state"] == "unique"
    assert_no_private_queries([sql for sql in queries if sql.lstrip().startswith("SELECT") and "hoimsystem_users" not in sql])
    trace = await async_client.get("/api/ai/admin/runs/" + identifier, headers=headers)
    assert trace.status_code == 403


@pytest.mark.asyncio
async def test_super_without_rca_purposes_sees_global_header_without_a_source_grant(grant_case, async_client, auth_headers, monkeypatch):
    from app.ai.rca_evidence_runtime import create_rca_run
    from app.config import settings

    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "synthetic.invalid")
    case, db = grant_case, grant_case["db"]
    _, value, _ = rca_configuration(case)
    run = create_rca_run(db, case["actor"], RunRequest(feature_key="incident_rca", input={"rca_evidence_case_id": value.binding.case_id}, preview=True))
    identifier = inspect(run).identity[0]
    actor = User(username="audit_" + uuid.uuid4().hex[:12], password="synthetic", user_role="super_admin")
    db.add(actor)
    db.commit()
    headers = auth_headers(actor.username)
    queries, seen = observer(db)
    try:
        response = await async_client.get("/api/ai/admin/task-directory", headers=headers, params={"page_size": 100})
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert response.status_code == 200, response.text
    row = next(row for row in response.json()["data"] if row["run_id"] == identifier)
    assert row["native_domains"] == ["rca"] and row["native_identity_state"] == "unique"
    assert "rca_evidence_case_id" not in row
    assert_no_private_queries([sql for sql in queries if sql.lstrip().startswith("SELECT") and "hoimsystem_users" not in sql])
    trace = await async_client.get("/api/ai/admin/runs/" + identifier, headers=headers)
    assert trace.status_code == 403


def test_actual_anchor_still_selects_its_domain_after_mutable_feature_and_markers_erased(db_session, actual_task):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    db_session.execute(text("UPDATE hoimsystem_ai_run SET feature_key='operations_qa',input_json='{}',result_json='{}',context_metadata_json='{}',evidence_json='[]' WHERE run_id=:pk"), {"pk": identifier})
    db_session.commit()
    response = task_directory(db_session, case["super_admin_user"], feature_key="research_extraction")
    row = next(row for row in response["data"] if row["run_id"] == identifier)
    assert row["native_domains"] == ["research_variables"] and row["native_identity_state"] == "unique"
    assert row["native_feature_key"] == "research_extraction" and row["feature_matches_native_contract"] is False
    other = task_directory(db_session, case["super_admin_user"], feature_key="operations_qa", page_size=100)
    assert identifier not in {row["run_id"] for row in other["data"]}


def test_invalid_native_owner_remains_visible_without_source_or_generic_fallback(db_session, actual_task):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    original_owner = staged.artifact.requested_by
    db_session.execute(text("UPDATE hoimsystem_ai_research_variable_run_artifact SET requested_by=:owner WHERE run_id=:pk"), {"owner": case["super_admin_user"].user_id, "pk": identifier})
    db_session.commit()
    try:
        response = task_directory(db_session, case["super_admin_user"], feature_key="research_extraction", page_size=100)
        row = next(row for row in response["data"] if row["run_id"] == identifier)
        assert row["native_domains"] == ["research_variables"] and row["native_identity_state"] == "invalid"
        assert row["usage_verification"] == "not_verified" and row["input_tokens"] is None
    finally:
        db_session.rollback()
        db_session.execute(text("UPDATE hoimsystem_ai_research_variable_run_artifact SET requested_by=:owner WHERE run_id=:pk"), {"owner": original_owner, "pk": identifier})
        db_session.commit()


def test_conflicting_actual_domains_do_not_hide_any_global_task(db_session, actual_task, grant_case, monkeypatch):
    from app.ai.rca_evidence_runtime import create_rca_run
    from app.config import settings

    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "synthetic.invalid")
    case, _, _, staged = actual_task
    variable_id = inspect(staged.run).identity[0]
    _, value, _ = rca_configuration(grant_case)
    rca = create_rca_run(db_session, grant_case["actor"], RunRequest(feature_key="incident_rca", input={"rca_evidence_case_id": value.binding.case_id}, preview=True))
    rca_id = inspect(rca).identity[0]
    db_session.execute(text("UPDATE hoimsystem_ai_rca_evidence_run_artifact SET run_id=:variable WHERE run_id=:rca"), {"variable": variable_id, "rca": rca_id})
    db_session.commit()
    try:
        response = task_directory(db_session, case["super_admin_user"], page_size=100)
        rows = {row["run_id"]: row for row in response["data"]}
        assert rows[variable_id]["native_domains"] == ["rca", "research_variables"]
        assert rows[variable_id]["native_identity_state"] == "conflicting"
        assert rows[rca_id]["native_identity_state"] == "unproven"
        assert rows[variable_id]["input_tokens"] is None and rows[rca_id]["input_tokens"] is None
    finally:
        db_session.rollback()
        db_session.execute(text("UPDATE hoimsystem_ai_rca_evidence_run_artifact SET run_id=:rca WHERE run_id=:variable"), {"variable": variable_id, "rca": rca_id})
        db_session.commit()
