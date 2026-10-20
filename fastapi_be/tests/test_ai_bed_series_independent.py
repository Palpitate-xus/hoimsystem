"""Independent actual lifecycle checks beyond the primary bed-series owner tests."""

import copy
import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.orm import Query

from app.ai import bed_contract as core
from app.ai import bed_series as series
from app.ai.bed_contract import canonical_json, hash_content
from app.ai.bed_series_models import AIBedSeries
from app.ai.models import AIAuditEvent
from app.models import Doctor, User
from tests.test_ai_bed_facts import NOTE
from tests.test_ai_bed_facts import bed_case as bed_case
from tests.test_ai_bed_series import async_client as async_client
from tests.test_ai_bed_series import create_series, publish_series
from tests.test_ai_bed_series_input import original
from tests.test_ai_bed_series_input import series_case as series_case


@pytest.mark.parametrize("mutation", ["changed_quantity", "withheld_original"])
def test_rehashed_schema_valid_false_public_projection_is_rejected_even_for_super(db_session, series_case, mutation):
    case = series_case
    row = publish_series(db_session, case, create_series(db_session, case))
    public = json.loads(row.projection_json)
    if mutation == "changed_quantity":
        public["census_observations"][0]["occupied_beds"] = {"value": 999, "absent_reason": None}
    else:
        item = public["census_observations"].pop()
        next(entry for entry in public["member_manifest"] if entry["source_id"] == item["ref"]["source_id"])["selection"] = "excluded"
        next(day for day in public["days"] if day["census_source_id"] == item["ref"]["source_id"]).update(census_source_id=None, census_selection_reason="missing")
        public["member_manifest_hash"] = hash_content(public["member_manifest"])
    # This is a real, internally well-typed public source with both rewritten
    # digests, rather than an obviously malformed JSON corruption fixture.
    core.BedSource.model_validate(public)
    row.projection_json, row.projection_hash = canonical_json(public), hash_content(public)
    db_session.commit()
    with pytest.raises(HTTPException, match="409"):
        series.series_current(db_session, case["super"], row.series_id, audit_only=True)
    with pytest.raises(HTTPException, match="409"):
        series.authorize_series(db_session, case["director"], row.series_id, execution=False)


def test_current_recipe_change_preserves_exact_own_history_and_denies_new_math(db_session, series_case, monkeypatch):
    case = series_case
    row = publish_series(db_session, case, create_series(db_session, case))
    original_body, original_projection = row.snapshot_json, row.projection_json
    changed = copy.deepcopy(core.RECIPE)
    changed["version"] = "future-engineering-version"
    monkeypatch.setattr(core, "RECIPE", changed)
    assert series.series_proof(row)[1] == json.loads(original_projection)
    historical = series.series_current(db_session, case["director"], row.series_id)
    assert historical["snapshot"] is not None and historical["public_source"] == json.loads(original_projection)
    assert historical["source_current"] is True and historical["eligible"] is False
    assert historical["exclusion_reasons"] == ["series_period_or_algorithm_changed"]
    assert series.authorize_series(db_session, case["director"], row.series_id, execution=False)[0].series_id == row.series_id
    with pytest.raises(HTTPException, match="409"):
        series.authorize_series(db_session, case["super"], row.series_id)
    assert (row.snapshot_json, row.projection_json) == (original_body, original_projection)


def test_new_equal_count_source_after_review_precheck_prevents_publication_and_keeps_committed_original(db_session, series_case, monkeypatch):
    case = series_case
    row = create_series(db_session, case)
    row_id, body_hash = row.series_id, row.content_hash
    real_update, injected = Query.update, False
    new_source_ids = []

    def add_after_precheck(query, values, *args, **kwargs):
        nonlocal injected
        if not injected and query.column_descriptions[0]["entity"] is AIBedSeries:
            injected = True
            # This actual source transaction commits BEFORE the series CAS.
            # The subsequent series rollback must preserve that prior original.
            new_source_ids.append(original(db_session, case, "census").source_record_id)
        return real_update(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", add_after_precheck)
    with pytest.raises(HTTPException, match="409"):
        series.review_series(db_session, case["super"], row_id, {"expected_revision": 1, "expected_content_hash": body_hash, "decision": "publish", "review_basis_note": NOTE})
    db_session.rollback()
    assert injected and series.series_row(db_session, row_id).status == "draft"
    from app.ai.bed_models import AIBedSource

    assert db_session.get(AIBedSource, new_source_ids[0]).status == "published"
    assert db_session.query(AIAuditEvent).filter_by(action="bed.series.publish", target=row_id).count() == 0


@pytest.mark.asyncio
async def test_actual_actor_affiliation_loss_denies_http_without_invalidating_historical_author_facts(async_client, db_session, series_case, auth_headers):
    case = series_case
    row = publish_series(db_session, case, create_series(db_session, case))
    row_id, original = row.series_id, (row.snapshot_json, row.projection_json)
    headers = auth_headers(case["director"].username)
    db_session.query(Doctor).filter_by(user_id=case["director"].user_id).update({"department_id": case["foreign"].department_id}, synchronize_session=False)
    db_session.commit()
    response = await async_client.get("/api/ai/bed-series/" + row_id, headers=headers)
    assert response.status_code == 403
    response = await async_client.get("/api/ai/bed-series", headers=headers, params={"ward_id": case["ward"].ward_id})
    assert response.status_code == 403
    frozen = series.series_current(db_session, case["super"], row_id, audit_only=True)
    assert frozen["snapshot"] is not None and frozen["source_current"] is frozen["eligible"] is True
    assert series.authorize_series(db_session, case["super"], row_id)[0].series_id == row_id
    db_session.refresh(row)
    assert (row.snapshot_json, row.projection_json) == original


@pytest.mark.asyncio
async def test_actual_department_peer_can_read_but_cannot_revoke_another_authors_series(async_client, db_session, series_case, auth_headers):
    case = series_case
    row = publish_series(db_session, case, create_series(db_session, case))
    peer = User(username="bedpeer" + uuid.uuid4().hex[:12], password=case["director"].password, user_role="director")
    db_session.add(peer)
    db_session.flush()
    db_session.add(Doctor(name="合成同科运营只读人", user_id=peer.user_id, department_id=case["department"].department_id))
    db_session.commit()
    headers = auth_headers(peer.username)
    response = await async_client.get("/api/ai/bed-series/" + row.series_id, headers=headers)
    assert response.status_code == 200 and response.json()["data"]["snapshot"] is not None
    assert response.json()["data"]["can_revoke"] is False
    response = await async_client.post("/api/ai/bed-series/" + row.series_id + "/revoke", headers=headers, json={"expected_revision": 2, "reason": "同科非作者不应撤销原记录"})
    assert response.status_code == 403
    db_session.refresh(row)
    assert row.status == "published" and row.revision == 2


def test_series_lifecycle_writes_only_own_series_and_atomic_ai_audit_tables(db_session, series_case):
    writes = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(context.compiled.statement.table.name)

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        row = publish_series(db_session, series_case, create_series(db_session, series_case))
        series.revoke_series(db_session, series_case["director"], row.series_id, {"expected_revision": 2, "reason": "独立实际SQL写入范围审查工程验证"})
        db_session.commit()
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)
    assert writes and set(writes) == {AIBedSeries.__tablename__, AIAuditEvent.__tablename__}
