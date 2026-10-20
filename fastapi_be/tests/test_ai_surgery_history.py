"""Real SQL scope predicates; not a stand-in for full per-run authorization."""

import datetime
import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.dialects import mysql

from app.ai.models import AIRun
from app.ai.surgery_contract import hash_content
from app.ai.surgery_history import filter_history
from app.ai.surgery_scenario_models import AISurgeryScenario
from tests.test_ai_surgery_facts import NOW
from tests.test_ai_surgery_facts import surgery_case as surgery_case


@pytest.fixture
def history_case(db_session, surgery_case):
    case = surgery_case
    source = AISurgeryScenario(
        scenario_id=str(uuid.uuid4()),
        pool_id=case["pool"].pool_id,
        department_id=case["department"].department_id,
        schema_version="surgery_scenario_private_v1",
        as_of=NOW,
        created_at=NOW,
        created_by=case["director"].user_id,
        snapshot_json='{"SQL_predicate_fixture_only":true}',
        content_hash=hash_content({}),
        collection_digest=hash_content({}),
        status="draft",
        revision=1,
    )
    db_session.add(source)
    db_session.commit()
    return {**case, "scenario": source}


def add_run(db, case, *, body=None, actor=None, feature="surgery_scheduling", later=0):
    binding = {"department_id": case["department"].department_id, "pool_id": case["pool"].pool_id, "scenario_id": case["scenario"].scenario_id}
    if body is None:
        body = {"payload": {"context": {"surgery_binding": binding}}}
    row = AIRun(
        run_id=str(uuid.uuid4()),
        feature_key=feature,
        requested_by=(actor or case["director"]).user_id,
        status="queued",
        prompt_hash=hash_content({}),
        context_digest=hash_content({}),
        input_json=body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        result_json="{}",
        evidence_json="[]",
        context_metadata_json="{}",
        create_time=NOW + datetime.timedelta(seconds=later),
    )
    db.add(row)
    db.flush()
    return row


def scoped(db, case, actor=None, **values):
    return filter_history(db, actor or case["director"], db.query(AIRun), **values)


@pytest.mark.parametrize(
    "change", ["bad_json", "boolean", "string_integer", "float_integer", "negative", "overflow", "wrong_pool", "wrong_scenario", "wrong_department", "legacy", "other_feature", "pool_type"]
)
def test_exact_native_original_scope_filters_bad_metadata_before_limit_one(db_session, history_case, change):
    db, case = db_session, history_case
    valid = add_run(db, case)
    body = json.loads(valid.input_json)
    bound = body["payload"]["context"]["surgery_binding"]
    if change == "bad_json":
        body = "{malformed"
    elif change == "boolean":
        bound["department_id"] = True
    elif change == "string_integer":
        bound["department_id"] = str(bound["department_id"])
    elif change == "float_integer":
        bound["department_id"] = float(bound["department_id"])
    elif change == "negative":
        bound["department_id"] = -1
    elif change == "overflow":
        bound["department_id"] = 2147483648
    elif change == "wrong_pool":
        bound["pool_id"] = str(uuid.uuid4())
    elif change == "wrong_scenario":
        bound["scenario_id"] = str(uuid.uuid4())
    elif change == "wrong_department":
        bound["department_id"] = case["foreign"].department_id
    elif change == "legacy":
        body = {"payload": {"context": {"surgical_schedules": []}}}
    elif change == "pool_type":
        bound["pool_id"] = 1
    invalid = add_run(db, case, body=body, later=1, feature="operations_qa" if change == "other_feature" else "surgery_scheduling")
    db.commit()
    rows = scoped(db, case, surgery_scenario_id=case["scenario"].scenario_id).order_by(AIRun.create_time.desc()).limit(1).all()
    assert [item.run_id for item in rows] == [valid.run_id] and invalid.run_id != valid.run_id


def test_pool_department_filters_are_exact_and_ordinary_history_stays_requester_only(db_session, history_case):
    db, case = db_session, history_case
    own = add_run(db, case)
    other = add_run(db, case, actor=case["super"], later=1)
    db.commit()
    values = {"department_id": case["department"].department_id, "surgery_pool_id": case["pool"].pool_id}
    assert [item.run_id for item in scoped(db, case, **values).all()] == [own.run_id]
    assert {item.run_id for item in scoped(db, case, actor=case["super"], **values).all()} == {own.run_id, other.run_id}


@pytest.mark.parametrize(
    "values", [{"department_id": True}, {"department_id": 1.0}, {"department_id": "1"}, {"department_id": 0}, {"surgery_pool_id": "not-uuid"}, {"surgery_scenario_id": "not-uuid"}]
)
def test_history_identifiers_are_not_coerced(values, db_session, history_case):
    with pytest.raises(HTTPException) as error:
        scoped(db_session, history_case, **values)
    assert error.value.status_code == 422


def test_mixed_original_scenario_scope_is_rejected_and_foreign_pool_is_not_authority(db_session, history_case):
    db, case = db_session, history_case
    with pytest.raises(HTTPException) as error:
        scoped(db, case, surgery_scenario_id=case["scenario"].scenario_id, department_id=case["foreign"].department_id)
    assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        scoped(db, case, actor=case["foreign_user"], surgery_scenario_id=case["scenario"].scenario_id)
    assert error.value.status_code == 403


def test_sqlite_predicate_compiles_as_real_mysql_json_type_and_exact_nested_members(db_session, history_case):
    query = scoped(db_session, history_case, surgery_scenario_id=history_case["scenario"].scenario_id)
    compiled = str(query.statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "JSON_TYPE(JSON_EXTRACT(" in compiled and "json_valid(" in compiled.lower()
    assert '"surgery_binding"' in compiled and '"scenario_id"' in compiled
    assert " LIKE " not in compiled and "REGEXP" not in compiled


def test_current_actor_role_revocation_is_checked_before_history_sql(db_session, history_case):
    case = history_case
    actor_id = case["director"].user_id
    db_session.execute(text("UPDATE hoimsystem_users SET user_role='nurse' WHERE user_id=:id"), {"id": actor_id})
    with pytest.raises(HTTPException) as error:
        scoped(db_session, case, actor=case["director"], surgery_pool_id=case["pool"].pool_id)
    assert error.value.status_code == 403
    db_session.rollback()
