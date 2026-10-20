"""Actual scoped roster history filters use JSON members before SQL pagination."""

import datetime
import json

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.orm import Session

from app.ai.models import AIRun
from app.ai.runtime import create_run
from app.ai.schemas import RunRequest
from tests.test_ai_roster_facts import create as create_original
from tests.test_ai_roster_pipeline import pipeline_case as pipeline_case
from tests.test_ai_roster_plan_input import plan_case as plan_case
from tests.test_ai_roster_plan_input import plan_request
from tests.test_ai_roster_plan_input import roster_case as roster_case
from tests.test_ai_roster_plans import create_plan, publish_plan
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks


@pytest.fixture
def history_case(db_session, pipeline_case):
    case = pipeline_case
    first_plan = case["plan"]
    second_plan = publish_plan(db_session, case, create_plan(db_session, case))
    foreign_case = {**case, "department": case["foreign"], "doctor": case["outsider"], "director": case["super"]}
    foreign_case["plan_request"] = plan_request(db_session, foreign_case)
    foreign_plan = publish_plan(db_session, foreign_case, create_plan(db_session, foreign_case))
    plans = [first_plan, second_plan, foreign_plan]
    runs = []
    for index, plan in enumerate(plans):
        other = plans[(index + 1) % 3]
        # These exact foreign UUIDs and JSON-looking scope keys are ordinary
        # local question text. They cannot be mistaken for the typed binding.
        question = json.dumps({"payload": {"context": {"roster_binding": {"department_id": other.department_id, "plan_id": other.plan_id}}}, "other_reference": plans[(index + 2) % 3].plan_id})
        run = create_run(
            db_session,
            case["super"] if index == 2 else case["director"],
            RunRequest(feature_key="roster_optimization", input={"roster_plan_id": plan.plan_id, "question": question}),
        )
        run.create_time = datetime.datetime(2026, 10, 20, 12, index, 0)
        runs.append(run)
    db_session.commit()
    assert len({row.run_id for row in runs}) == 3 and all(row.status == "queued" for row in runs)
    case.update(history_plans=plans, history_runs=runs)
    return case


async def listing(client, headers, **filters):
    return await client.get("/api/ai/runs", headers=headers, params={"feature_key": "roster_optimization", **filters})


@pytest.mark.asyncio
async def test_super_filters_exact_actual_department_and_plan_before_limit_without_text_false_matches(async_client, auth_headers, history_case):
    case = history_case
    first, second, foreign = case["history_runs"]
    plans = case["history_plans"]
    headers = auth_headers(case["super"].username)
    response = await listing(async_client, headers, department_id=case["department"].department_id)
    assert response.status_code == 200, response.text
    assert [item["run_id"] for item in response.json()["data"]] == [second.run_id, first.run_id]
    response = await listing(async_client, headers, department_id=case["department"].department_id, limit=1)
    assert response.status_code == 200, response.text
    assert [item["run_id"] for item in response.json()["data"]] == [second.run_id]
    for plan, run in zip(plans, [first, second, foreign], strict=True):
        response = await listing(async_client, headers, roster_plan_id=plan.plan_id, limit=1)
        assert response.status_code == 200, response.text
        assert [item["run_id"] for item in response.json()["data"]] == [run.run_id]
    response = await listing(async_client, headers, department_id=case["foreign"].department_id, roster_plan_id=plans[2].plan_id, limit=1)
    assert response.status_code == 200 and [item["run_id"] for item in response.json()["data"]] == [foreign.run_id]


@pytest.mark.asyncio
async def test_director_own_history_scope_and_department_plan_mismatch_are_independently_checked(async_client, auth_headers, history_case):
    case = history_case
    director = auth_headers(case["director"].username)
    response = await listing(async_client, director, department_id=case["department"].department_id)
    assert response.status_code == 200, response.text
    assert {item["run_id"] for item in response.json()["data"]} == {item.run_id for item in case["history_runs"][:2]}
    for filters in ({"department_id": case["foreign"].department_id}, {"roster_plan_id": case["history_plans"][2].plan_id}):
        response = await listing(async_client, director, **filters)
        assert response.status_code == 403, response.text
    response = await listing(async_client, auth_headers(case["super"].username), department_id=case["department"].department_id, roster_plan_id=case["history_plans"][2].plan_id)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("department_id", "1.0"),
        ("department_id", "1e0"),
        ("department_id", "true"),
        ("department_id", "0"),
        ("department_id", "-1"),
        ("department_id", ""),
        ("roster_plan_id", "not-a-uuid"),
        ("roster_plan_id", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
        ("roster_plan_id", "aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa"),
    ],
)
async def test_filter_ids_are_canonical_scalars_before_history_queries(field, value, async_client, auth_headers, pipeline_case):
    response = await listing(async_client, auth_headers(pipeline_case["super"].username), **{field: value})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"feature_key": "visit_forecast"}, {"feature_key": ""}, {"patient_id": 1}, {"encounter_ref": "synthetic-unrelated-encounter"}])
async def test_roster_filters_cannot_mix_other_features_or_patient_encounters(extra, async_client, auth_headers, pipeline_case):
    case = pipeline_case
    response = await listing(async_client, auth_headers(case["super"].username), department_id=case["department"].department_id, **extra)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_ordinary_list_skips_stale_originals_and_preserves_fresh_plan_while_detail_stays_conflict(async_client, db_session, auth_headers, history_case):
    case = history_case
    originals = case["history_runs"][:2]
    create_original(db_session, case)  # A draft also changes the complete collection.
    fresh_plan = publish_plan(db_session, case, create_plan(db_session, case))
    fresh_run = create_run(db_session, case["director"], RunRequest(feature_key="roster_optimization", input={"roster_plan_id": fresh_plan.plan_id}))
    director = auth_headers(case["director"].username)
    response = await listing(async_client, director, department_id=case["department"].department_id)
    assert response.status_code == 200, response.text
    assert [item["run_id"] for item in response.json()["data"]] == [fresh_run.run_id]
    for original, plan in zip(originals, case["history_plans"][:2], strict=True):
        response = await listing(async_client, director, roster_plan_id=plan.plan_id)
        assert response.status_code == 200 and response.json()["data"] == []
        response = await async_client.get("/api/ai/runs/" + original.run_id, headers=director)
        assert response.status_code == 409, response.text
    response = await listing(async_client, auth_headers(case["super"].username), department_id=case["department"].department_id)
    assert response.status_code == 200, response.text
    assert {item["run_id"] for item in response.json()["data"]} == {fresh_run.run_id, *(row.run_id for row in originals)}


@pytest.mark.asyncio
async def test_executed_sqlite_json_predicates_and_compiled_mysql_json_members_precede_pagination(async_client, auth_headers, history_case):
    case = history_case
    captured = []

    def statement(state):
        if state.is_select and AIRun.__table__ in state.statement.get_final_froms():
            captured.append(state.statement)

    event.listen(Session, "do_orm_execute", statement)
    try:
        response = await listing(
            async_client,
            auth_headers(case["super"].username),
            department_id=case["department"].department_id,
            roster_plan_id=case["history_plans"][0].plan_id,
            limit=1,
        )
    finally:
        event.remove(Session, "do_orm_execute", statement)
    assert response.status_code == 200, response.text
    assert [item["run_id"] for item in response.json()["data"]] == [case["history_runs"][0].run_id]
    queries = [query for query in captured if "JSON_EXTRACT" in str(query.compile(dialect=sqlite.dialect()))]
    assert len(queries) == 1
    for dialect in (sqlite.dialect(), mysql.dialect()):
        sql = str(queries[0].compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
        assert "JSON_EXTRACT" in sql and "roster_binding" in sql and "department_id" in sql and "plan_id" in sql
        assert " LIKE " not in sql and sql.index("JSON_EXTRACT") < sql.index("ORDER BY") < sql.index("LIMIT")
        assert case["history_plans"][0].plan_id in sql
