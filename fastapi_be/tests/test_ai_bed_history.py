"""Actual queued bed history, strict JSON predicates and current/frozen scope."""

import copy
import datetime
import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.orm import Session

from app.ai import bed_history as history
from app.ai import bed_series as series
from app.ai.bed_config import runtime_descriptor
from app.ai.bed_series_models import AIBedSeries
from app.ai.models import AIFeatureConfig, AIRun
from app.ai.runtime import create_run
from app.ai.schemas import RunRequest
from app.models import Doctor, User, Ward
from tests.test_ai_bed_facts import NOTE, NOW
from tests.test_ai_bed_facts import bed_case as bed_case
from tests.test_ai_bed_series import create_series, publish_series
from tests.test_ai_bed_series_input import original
from tests.test_ai_bed_series_input import series_case as series_case
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure


@pytest.fixture
def history_case(db_session, series_case, monkeypatch):
    case = series_case
    monkeypatch.setenv("AI_PROVIDER_LOCAL_BED_API_KEY", "synthetic-bed-history-key-for-queue-only-1234567890")
    provider, feature = configure(db_session, case["seed"], "bed_forecast")
    provider.kind, provider.model = "specialist", runtime_descriptor()["model_version"]
    provider.api_base, provider.api_key_env, provider.timeout_seconds = "http://localhost:8820", "AI_PROVIDER_LOCAL_BED_API_KEY", 110
    provider.supported_features_json = '["bed_forecast"]'
    provider.validation_report = "Synthetic queue and metadata checks only; not real hospital operational validation."
    feature.validation_status, feature.validation_note = "validated", "仅隔离合成病区工程历史验证，不代表真实医院运营效果或可收治能力已经验证。"
    feature.validated_by, feature.validated_at = case["super"].user_id, NOW
    db_session.commit()
    first = publish_series(db_session, case, create_series(db_session, case))
    second = publish_series(db_session, case, create_series(db_session, case))
    sibling_ward = Ward(name="合成同科另病区", department_id=case["department"].department_id, status=0)
    peer = User(username="hpeer" + uuid.uuid4().hex[:12], password=case["director"].password, user_role="director")
    db_session.add_all([sibling_ward, peer])
    db_session.flush()
    db_session.add(Doctor(name="合成同科历史请求人", department_id=case["department"].department_id, user_id=peer.user_id))
    db_session.commit()
    sibling_case = {**case, "ward": sibling_ward, "period": {**case["period"], "ward_id": sibling_ward.ward_id}}
    sibling = publish_series(db_session, sibling_case, create_series(db_session, sibling_case))
    foreign_case = {**case, "ward": case["foreign_ward"], "department": case["foreign"], "director": case["super"], "period": {**case["period"], "ward_id": case["foreign_ward"].ward_id}}
    foreign = publish_series(db_session, foreign_case, create_series(db_session, foreign_case))
    sources = [first, second, sibling, foreign, first]
    actors = [case["director"], case["director"], case["director"], case["super"], peer]
    runs = []
    for index, (row, actor) in enumerate(zip(sources, actors, strict=True)):
        other = sources[(index + 1) % len(sources)]
        text = json.dumps({"payload": {"context": {"bed_binding": {"department_id": other.department_id, "ward_id": other.ward_id, "series_id": other.series_id}}}, "other_source": foreign.series_id})
        run = create_run(db_session, actor, RunRequest(feature_key="bed_forecast", input={"bed_series_id": row.series_id, "horizon_days": 7, "question": text}))
        run.create_time = datetime.datetime(2026, 10, 20, 12, index, 0)
        runs.append(run)
    db_session.commit()
    case.update(history_series=sources[:4], history_runs=runs, peer=peer, sibling_ward=sibling_ward, provider=provider, feature=feature)
    return case


async def listing(client, headers, **filters):
    return await client.get("/api/ai/runs", headers=headers, params={"feature_key": "bed_forecast", **filters})


@pytest.mark.asyncio
async def test_super_exact_department_ward_and_whole_series_filters_precede_limit(async_client, auth_headers, history_case):
    case = history_case
    first, second, sibling, foreign, peer = case["history_runs"]
    headers = auth_headers(case["super"].username)
    for filters, expected in [
        ({"department_id": case["department"].department_id}, [peer, sibling, second, first]),
        ({"ward_id": case["ward"].ward_id}, [peer, second, first]),
        ({"bed_series_id": case["history_series"][0].series_id}, [peer, first]),
        ({"bed_series_id": case["history_series"][1].series_id}, [second]),
        ({"ward_id": case["foreign_ward"].ward_id}, [foreign]),
        ({"department_id": case["foreign"].department_id, "ward_id": case["foreign_ward"].ward_id, "bed_series_id": case["history_series"][3].series_id}, [foreign]),
    ]:
        response = await listing(async_client, headers, **filters)
        assert response.status_code == 200, response.text
        assert [item["run_id"] for item in response.json()["data"]] == [row.run_id for row in expected]
        response = await listing(async_client, headers, limit=1, **filters)
        assert response.status_code == 200 and [item["run_id"] for item in response.json()["data"]] == [expected[0].run_id]


@pytest.mark.asyncio
async def test_same_department_peer_history_remains_owned_before_limit(async_client, auth_headers, history_case):
    case = history_case
    series_id = case["history_series"][0].series_id
    for actor, expected in [(case["director"], case["history_runs"][0]), (case["peer"], case["history_runs"][4])]:
        response = await listing(async_client, auth_headers(actor.username), bed_series_id=series_id, limit=1)
        assert response.status_code == 200, response.text
        assert [item["run_id"] for item in response.json()["data"]] == [expected.run_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("filter_kind", ["department", "ward", "series", "consistent_pair"])
async def test_director_foreign_original_scope_is_denied_before_history_reads(filter_kind, async_client, auth_headers, history_case):
    case = history_case
    filters = {
        "department": {"department_id": case["foreign"].department_id},
        "ward": {"ward_id": case["foreign_ward"].ward_id},
        "series": {"bed_series_id": case["history_series"][3].series_id},
        "consistent_pair": {"department_id": case["foreign"].department_id, "ward_id": case["foreign_ward"].ward_id},
    }[filter_kind]
    response = await listing(async_client, auth_headers(case["director"].username), **filters)
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["dept_ward", "dept_series", "ward_series"])
@pytest.mark.parametrize("actor", ["super", "director"])
async def test_explicit_metadata_scope_contradictions_are_422(mismatch, actor, async_client, auth_headers, history_case):
    case = history_case
    filters = {
        "dept_ward": {"department_id": case["department"].department_id, "ward_id": case["foreign_ward"].ward_id},
        "dept_series": {"department_id": case["department"].department_id, "bed_series_id": case["history_series"][3].series_id},
        "ward_series": {"ward_id": case["foreign_ward"].ward_id, "bed_series_id": case["history_series"][0].series_id},
    }[mismatch]
    response = await listing(async_client, auth_headers(case[actor].username), **filters)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("department_id", "1.0"),
        ("department_id", "true"),
        ("ward_id", "1e0"),
        ("ward_id", "0"),
        ("ward_id", "-1"),
        ("bed_series_id", "bad-uuid"),
        ("bed_series_id", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
        ("bed_series_id", "aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa"),
    ],
)
async def test_query_identity_lexemes_are_strict_before_sql(field, value, async_client, auth_headers, bed_case):
    response = await listing(async_client, auth_headers(bed_case["super"].username), **{field: value})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra", [{"feature_key": "visit_forecast"}, {"feature_key": ""}, {"patient_id": 1}, {"encounter_ref": "synthetic-patient-encounter"}, {"roster_plan_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}]
)
async def test_bed_filters_cannot_mix_features_roster_or_individual_encounter(extra, async_client, auth_headers, bed_case):
    case = bed_case
    response = await listing(async_client, auth_headers(case["super"].username), ward_id=case["ward"].ward_id, **extra)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_ward_transfer_keeps_super_original_series_audit_but_current_department_permissions_are_independent(async_client, db_session, auth_headers, history_case):
    case = history_case
    original_series = case["history_series"][0]
    case["ward"].department_id = case["foreign"].department_id
    db_session.commit()
    ordinary = auth_headers(case["director"].username)
    for filters in ({"ward_id": case["ward"].ward_id}, {"bed_series_id": original_series.series_id}):
        response = await listing(async_client, ordinary, **filters)
        assert response.status_code == 403, response.text
    superh = auth_headers(case["super"].username)
    response = await listing(async_client, superh, department_id=case["department"].department_id, ward_id=case["ward"].ward_id, bed_series_id=original_series.series_id)
    assert response.status_code == 200, response.text
    assert {item["run_id"] for item in response.json()["data"]} == {case["history_runs"][0].run_id, case["history_runs"][4].run_id}
    response = await listing(async_client, superh, department_id=case["department"].department_id, ward_id=case["ward"].ward_id)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_revoked_series_history_stays_ineligible_ordinary_skips_and_super_only_audits(async_client, db_session, auth_headers, history_case):
    case = history_case
    row = case["history_series"][0]
    series.revoke_series(db_session, case["super"], row.series_id, {"expected_revision": 2, "reason": NOTE})
    db_session.commit()
    ordinary = await listing(async_client, auth_headers(case["director"].username), bed_series_id=row.series_id)
    assert ordinary.status_code == 200 and ordinary.json()["data"] == []
    detail = await async_client.get("/api/ai/runs/" + case["history_runs"][0].run_id, headers=auth_headers(case["director"].username))
    assert detail.status_code == 409
    audit = await listing(async_client, auth_headers(case["super"].username), bed_series_id=row.series_id)
    assert audit.status_code == 200 and len(audit.json()["data"]) == 2
    assert series.series_row(db_session, row.series_id).status == "revoked"


@pytest.mark.asyncio
async def test_old_invalid_and_new_current_sources_are_scoped_before_history_eligibility(async_client, db_session, auth_headers, history_case):
    case = history_case
    original(db_session, case, "census")
    fresh_series = publish_series(db_session, case, create_series(db_session, case))
    fresh = create_run(db_session, case["director"], RunRequest(feature_key="bed_forecast", input={"bed_series_id": fresh_series.series_id, "horizon_days": 14}))
    fresh.create_time = datetime.datetime(2026, 10, 20, 13, 0, 0)
    db_session.commit()
    response = await listing(async_client, auth_headers(case["director"].username), ward_id=case["ward"].ward_id)
    assert response.status_code == 200, response.text
    assert [item["run_id"] for item in response.json()["data"]] == [fresh.run_id]
    response = await listing(async_client, auth_headers(case["super"].username), ward_id=case["ward"].ward_id)
    assert response.status_code == 200 and len(response.json()["data"]) == 4


def test_helper_only_reads_series_metadata_and_compiles_precise_mysql_json_before_limit(db_session, history_case):
    case = history_case
    # Resolve an expired fixture PK before instrumentation. Real route filters
    # already arrive as scalar query values and cannot trigger this ORM load.
    target_series_id = case["history_series"][1].series_id
    queries = []

    def capture(state):
        if state.is_select:
            queries.append(state.statement)

    event.listen(Session, "do_orm_execute", capture)
    try:
        query = history.filter_history(db_session, case["super"], db_session.query(AIRun), department_id=case["department"].department_id, ward_id=case["ward"].ward_id, bed_series_id=target_series_id)
        value = query.order_by(AIRun.create_time.desc()).limit(1).all()
    finally:
        event.remove(Session, "do_orm_execute", capture)
    assert [row.run_id for row in value] == [case["history_runs"][1].run_id]
    metadata = [query for query in queries if AIBedSeries.__table__ in query.get_final_froms()]
    assert len(metadata) == 1
    assert "snapshot_json" not in str(metadata[0]) and "projection_json" not in str(metadata[0])
    for dialect in (sqlite.dialect(), mysql.dialect()):
        sql = str(query.statement.order_by(AIRun.create_time.desc()).limit(1).compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
        assert "JSON_EXTRACT" in sql and "JSON_TYPE" in sql and "json_valid" in sql and "CASE" in sql
        assert "bed_binding" in sql and all(key in sql for key in ("department_id", "ward_id", "series_id"))
        assert " LIKE " not in sql and sql.index("JSON_EXTRACT") < sql.index("ORDER BY") < sql.index("LIMIT")
        assert case["history_series"][1].series_id in sql


@pytest.mark.asyncio
async def test_malformed_json_and_typed_false_bindings_do_not_consume_limit_or_break_json_sql(async_client, db_session, auth_headers, history_case):
    case = history_case
    good = case["history_runs"][1]
    values = []
    for replacement in (str(case["department"].department_id), float(case["department"].department_id), True):
        value = json.loads(good.input_json)
        value["payload"]["context"]["bed_binding"]["department_id"] = replacement
        values.append(json.dumps(value))
    for key, replacement in (("ward_id", 0), ("ward_id", -1), ("ward_id", 2147483648), ("department_id", 0), ("department_id", 2147483648), ("series_id", 7)):
        value = json.loads(good.input_json)
        value["payload"]["context"]["bed_binding"][key] = replacement
        values.append(json.dumps(value))
    values.extend(("not valid json", "[]", "null", '{"payload":"JSON-looking question text only"}'))
    for index, value in enumerate(values):
        fields = {column.name: copy.deepcopy(getattr(good, column.name)) for column in AIRun.__table__.columns if column.name != "run_id"}
        fields.update(input_json=value, create_time=datetime.datetime(2026, 10, 20, 14, index, 0))
        db_session.add(AIRun(run_id=str(uuid.uuid4()), **fields))
    db_session.commit()
    for filters in ({"department_id": case["department"].department_id}, {"ward_id": case["ward"].ward_id}, {"bed_series_id": case["history_series"][1].series_id}):
        response = await listing(async_client, auth_headers(case["super"].username), limit=1, **filters)
        assert response.status_code == 200, response.text
        expected = good.run_id if "bed_series_id" in filters else case["history_runs"][4].run_id
        assert [row["run_id"] for row in response.json()["data"]] == [expected]


@pytest.mark.parametrize("field,bad", [("department_id", True), ("department_id", 1.0), ("ward_id", "1"), ("ward_id", False), ("ward_id", -1), ("bed_series_id", True)])
def test_direct_helper_rejects_noncanonical_scalar_identity(db_session, bed_case, field, bad):
    with pytest.raises(HTTPException, match="422"):
        history.filter_history(db_session, bed_case["super"], db_session.query(AIRun), **{field: bad})


def test_helper_rechecks_latest_role_config_and_real_affiliation(db_session, history_case):
    case = history_case
    feature = db_session.get(AIFeatureConfig, "bed_forecast")
    feature.allowed_roles_json = '["admin"]'
    db_session.commit()
    with pytest.raises(HTTPException, match="403"):
        history.filter_history(db_session, case["director"], db_session.query(AIRun), ward_id=case["ward"].ward_id)
    # Super metadata audit does not depend on feature enablement/validation.
    feature.enabled, feature.validation_status = 0, "unreviewed"
    db_session.commit()
    assert history.filter_history(db_session, case["super"], db_session.query(AIRun), ward_id=case["ward"].ward_id).count() == 3


@pytest.mark.asyncio
async def test_missing_original_ward_retains_super_frozen_metadata_without_restoring_ordinary_access(async_client, db_session, auth_headers, history_case):
    case = history_case
    ward_id, department_id = case["ward"].ward_id, case["department"].department_id
    series_id = case["history_series"][0].series_id
    ordinary, superh = auth_headers(case["director"].username), auth_headers(case["super"].username)
    # SQLite's isolated missing-parent fixture exercises the defensive read
    # boundary; it is not a claim that MySQL foreign keys allow this deletion.
    db_session.query(Ward).filter_by(ward_id=ward_id).delete(synchronize_session=False)
    db_session.commit()
    response = await listing(async_client, ordinary, bed_series_id=series_id)
    assert response.status_code == 403
    response = await listing(async_client, superh, department_id=department_id, ward_id=ward_id, bed_series_id=series_id)
    assert response.status_code == 200, response.text
    assert {row["run_id"] for row in response.json()["data"]} == {case["history_runs"][0].run_id, case["history_runs"][4].run_id}
    assert history.filter_history(db_session, case["super"], db_session.query(AIRun), department_id=2147483647).count() == 0


@pytest.mark.parametrize("change", ["role", "affiliation"])
def test_latest_actor_role_and_affiliation_are_rechecked_before_metadata(change, db_session, history_case):
    case = history_case
    ward_id = case["ward"].ward_id
    actor = case["director"]
    if change == "role":
        db_session.query(User).filter_by(user_id=actor.user_id).update({"user_role": "patient"}, synchronize_session=False)
    else:
        db_session.query(Doctor).filter_by(user_id=actor.user_id).update({"department_id": None}, synchronize_session=False)
    db_session.commit()
    with pytest.raises(HTTPException, match="403"):
        history.filter_history(db_session, actor, db_session.query(AIRun), ward_id=ward_id)
    assert history.filter_history(db_session, case["super"], db_session.query(AIRun), ward_id=ward_id).count() == 3
