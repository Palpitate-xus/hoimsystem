"""Actual scoped HTTP declaration, full projection, SQL CAS and audit rollback."""

import datetime
import json

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Query

from app.ai import bed_facts as facts
from app.ai import bed_series as plans
from app.ai import governance
from app.ai.bed_contract import hash_content
from app.ai.bed_series_input import preview_input
from app.ai.bed_series_models import AIBedSeries
from app.database import get_db
from app.models import Bed
from app.routers import ai_bed_series as routes
from tests.conftest import override_get_db
from tests.test_ai_bed_facts import NOTE, NOW
from tests.test_ai_bed_facts import bed_case as bed_case
from tests.test_ai_bed_series_input import original as register_original
from tests.test_ai_bed_series_input import series_case as series_case
from tests.test_ai_bed_series_input import series_request


@pytest_asyncio.fixture
async def async_client():
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated-bed-series.test") as client:
        yield client


def create_series(db, case):
    request = series_request(db, case)
    preview = preview_input(db, case["director"], case["period"])
    row = plans.create_series(db, case["director"], {"request": request, "expected_collection_digest": preview["collection_digest"]})
    db.commit()
    return row


def publish_series(db, case, row, decision="publish"):
    plans.review_series(db, case["super"], row.series_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": decision, "review_basis_note": NOTE})
    db.commit()
    db.refresh(row)
    return row


@pytest.mark.asyncio
async def test_actual_http_complete_preview_draft_publish_revoke_and_frozen_ui_fixture(async_client, db_session, auth_headers, series_case, tmp_path):
    case = series_case
    headers = auth_headers(case["director"].username)
    request = series_request(db_session, case)
    response = await async_client.post("/api/ai/bed-series/preview", headers=headers, json=case["period"])
    assert response.status_code == 200, response.text
    preview = response.json()["data"]
    assert case["bed"].bed_id in {item["bed_id"] for item in preview["bed_cohort"]}
    response = await async_client.post("/api/ai/bed-series", headers=headers, json={"request": request, "expected_collection_digest": preview["collection_digest"]})
    assert response.status_code == 200, response.text
    draft = response.json()["data"]
    assert draft["status"] == "draft" and draft["revision"] == 1 and draft["snapshot"] is not None and draft["public_source"] is None and draft["eligible"] is False
    assert hash_content(draft["snapshot"]) == draft["content_hash"]
    url = "/api/ai/bed-series/" + draft["series_id"]
    review = {"expected_revision": 1, "expected_content_hash": draft["content_hash"], "decision": "publish", "review_basis_note": NOTE}
    denied = await async_client.post(url + "/review", headers=headers, json=review)
    assert denied.status_code == 403
    response = await async_client.post(url + "/review", headers=auth_headers(case["super"].username), json=review)
    assert response.status_code == 200, response.text
    published = response.json()["data"]
    assert published["eligible"] is True and published["revision"] == 2 and published["snapshot"] == draft["snapshot"]
    assert hash_content(published["public_source"]) == published["projection_hash"]
    assert published["public_source"]["content_hash"] == draft["content_hash"]
    repeat = await async_client.post(url + "/review", headers=auth_headers(case["super"].username), json=review)
    assert repeat.status_code == 409
    response = await async_client.get("/api/ai/bed-series", headers=headers, params={"ward_id": case["ward"].ward_id})
    assert response.status_code == 200
    listed = next(item for item in response.json()["data"]["items"] if item["series_id"] == draft["series_id"])
    assert all(key not in listed for key in ("snapshot", "public_source", "review_basis_note", "revoke_reason"))
    response = await async_client.post(url + "/revoke", headers=headers, json={"expected_revision": 2, "reason": "合成床位序列资料停止使用并重新核对"})
    assert response.status_code == 200, response.text
    revoked = response.json()["data"]
    assert revoked["revision"] == 3 and revoked["snapshot"] is revoked["public_source"] is revoked["review_basis_note"] is revoked["revoke_reason"] is None
    response = await async_client.get("/api/ai/admin/bed-series/" + draft["series_id"], headers=auth_headers(case["super"].username))
    assert response.status_code == 200, response.text
    frozen = response.json()["data"]
    assert frozen["snapshot"] == draft["snapshot"] and frozen["public_source"] == published["public_source"] and frozen["projection_hash"] == published["projection_hash"]
    fixture = {"request": request, "preview": preview, "draft": draft, "published": published, "ordinary_revoked": revoked, "super_revoked": frozen, "list_item": listed}
    path = tmp_path / "actual-bed-series-ui.json"
    path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    assert json.loads(path.read_text())["super_revoked"] == frozen


@pytest.mark.parametrize("change", ["new_bed", "new_fact", "revoke_fact", "move_ward"])
def test_complete_current_collection_changes_block_new_execution_and_redact_ordinary_history(db_session, series_case, change):
    case = series_case
    row = publish_series(db_session, case, create_series(db_session, case))
    original = row.snapshot_json, row.projection_json
    if change == "new_bed":
        db_session.add(Bed(ward_id=case["ward"].ward_id, bed_no="later", status=0))
    elif change == "new_fact":
        register_original(db_session, case, "census")
    elif change == "revoke_fact":
        source = case["census"]
        facts.revoke_source(db_session, case["super"], source.source_kind, source.source_record_id, {"expected_revision": 2, "reason": "合成原资格停止使用"})
    else:
        case["ward"].department_id = case["foreign"].department_id
    db_session.commit()
    with pytest.raises(HTTPException) as denied:
        plans.authorize_series(db_session, case["director"], row.series_id)
    assert denied.value.status_code == (403 if change == "move_ward" else 409)
    ordinary = plans.series_current(db_session, case["director"], row.series_id)
    assert ordinary["snapshot"] is ordinary["public_source"] is None and ordinary["eligible"] is False
    frozen = plans.series_current(db_session, case["super"], row.series_id, audit_only=True)
    assert frozen["snapshot"] is not None and frozen["public_source"] is not None and frozen["eligible"] is False
    db_session.refresh(row)
    assert (row.snapshot_json, row.projection_json) == original


@pytest.mark.parametrize("column", ["snapshot_json", "content_hash", "collection_digest", "projection_json", "projection_hash", "review_basis_note"])
def test_own_corruption_never_uses_super_frozen_audit_bypass(db_session, series_case, column):
    case = series_case
    row = publish_series(db_session, case, create_series(db_session, case))
    setattr(row, column, "{}" if column.endswith("_json") else "a" * 64)
    db_session.commit()
    with pytest.raises(HTTPException, match="409"):
        plans.series_current(db_session, case["super"], row.series_id, audit_only=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "publish", "reject", "revoke"])
async def test_actual_sql_audit_failure_rolls_back_each_plan_write(async_client, db_session, auth_headers, series_case, monkeypatch, action):
    from app.ai.models import AIAuditEvent

    case = series_case
    row = create_series(db_session, case) if action != "create" else None
    before_count, before_audits = db_session.query(AIBedSeries).count(), db_session.query(AIAuditEvent).count()
    original = (row.status, row.revision, row.snapshot_json, row.projection_json) if row is not None else None
    request = series_request(db_session, case)
    preview = preview_input(db_session, case["director"], case["period"])

    def bad_sql(db, actor_id, *args, **kwargs):
        db.add(AIAuditEvent(actor_id=actor_id, action=None, target="synthetic-bed-series-bad-audit", detail_json="{}"))

    monkeypatch.setattr(governance, "audit", bad_sql)
    actor = case["director"]
    if action == "create":
        url, body = "/api/ai/bed-series", {"request": request, "expected_collection_digest": preview["collection_digest"]}
    elif action == "revoke":
        url, body = f"/api/ai/bed-series/{row.series_id}/revoke", {"expected_revision": 1, "reason": "实际失败SQL审计须原子回滚"}
    else:
        actor = case["super"]
        url, body = f"/api/ai/bed-series/{row.series_id}/review", {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": action, "review_basis_note": NOTE}
    response = await async_client.post(url, headers=auth_headers(actor.username), json=body)
    assert response.status_code == 409, response.text
    assert db_session.query(AIBedSeries).count() == before_count and db_session.query(AIAuditEvent).count() == before_audits
    if row is not None:
        db_session.refresh(row)
        assert (row.status, row.revision, row.snapshot_json, row.projection_json) == original


def test_actual_plan_cas_detects_second_transaction_publication_after_precheck(db_session, series_case, monkeypatch):
    from sqlalchemy.orm import Session

    case = series_case
    row = create_series(db_session, case)
    called = False
    actual = Query.update

    def race(query, values, *args, **kwargs):
        nonlocal called
        if not called and query.column_descriptions[0]["entity"] is AIBedSeries:
            called = True
            with Session(bind=db_session.get_bind()) as second:
                plans.review_series(
                    second,
                    second.get(type(case["super"]), case["super"].user_id),
                    row.series_id,
                    {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": "publish", "review_basis_note": NOTE + "第二事务"},
                )
                second.commit()
        return actual(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", race)
    with pytest.raises(HTTPException, match="409"):
        plans.review_series(db_session, case["super"], row.series_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": "publish", "review_basis_note": NOTE})
    db_session.rollback()
    db_session.refresh(row)
    assert called and row.status == "published" and row.review_basis_note.endswith("第二事务")


def test_old_calendar_still_has_frozen_history_but_cannot_create_a_new_forecast(db_session, series_case, monkeypatch):
    from app.ai import bed_series_input

    case = series_case
    row = publish_series(db_session, case, create_series(db_session, case))
    body = row.snapshot_json, row.projection_json
    monkeypatch.setattr(bed_series_input, "utcnow", lambda: NOW + datetime.timedelta(days=1))
    with pytest.raises(HTTPException, match="409"):
        plans.authorize_series(db_session, case["director"], row.series_id)
    assert plans.authorize_series(db_session, case["director"], row.series_id, execution=False)[0].series_id == row.series_id
    history = plans.series_current(db_session, case["director"], row.series_id)
    assert history["source_current"] is True and history["eligible"] is False and history["snapshot"] is not None
    assert history["exclusion_reasons"] == ["series_period_or_algorithm_changed"]
    assert (row.snapshot_json, row.projection_json) == body


def test_live_bed_status_and_ward_display_configuration_do_not_erase_observed_history(db_session, series_case):
    case = series_case
    row = publish_series(db_session, case, create_series(db_session, case))
    body = row.snapshot_json, row.projection_json
    case["bed"].status = 2
    case["bed"].price_per_day = 123
    case["ward"].status = 1
    case["ward"].bed_count = 0
    db_session.commit()
    assert plans.authorize_series(db_session, case["director"], row.series_id)[0].series_id == row.series_id
    assert plans.series_current(db_session, case["director"], row.series_id)["source_current"] is True
    assert (row.snapshot_json, row.projection_json) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "publish", "reject", "revoke"])
@pytest.mark.parametrize("change", ["role", "bed_cohort"])
async def test_locked_postwrite_role_or_cohort_changes_roll_back_actual_http_transition(async_client, db_session, auth_headers, series_case, monkeypatch, action, change):
    from app.ai.models import AIAuditEvent
    from app.models import User

    case = series_case
    row = create_series(db_session, case) if action != "create" else None
    actor = case["super"] if action in {"publish", "reject"} else case["director"]
    actor_id, actor_role = actor.user_id, actor.user_role
    headers = auth_headers(actor.username)
    row_id = row.series_id if row is not None else None
    original = (row.status, row.revision, row.snapshot_json, row.projection_json) if row is not None else None
    before_series = db_session.query(AIBedSeries).count()
    before_audits = db_session.query(AIAuditEvent).count()
    before_beds = db_session.query(Bed).count()
    if action == "create":
        request = series_request(db_session, case)
        preview = preview_input(db_session, actor, case["period"])
        url, body = "/api/ai/bed-series", {"request": request, "expected_collection_digest": preview["collection_digest"]}
    elif action == "revoke":
        url, body = f"/api/ai/bed-series/{row_id}/revoke", {"expected_revision": 1, "reason": "合成序列最终锁前资料变化须整体回滚"}
    else:
        url, body = f"/api/ai/bed-series/{row_id}/review", {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": action, "review_basis_note": NOTE}
    actual, injected = facts.current_actor, False

    def changed_before_current_lock(db, candidate, *, locking=False):
        nonlocal injected
        if locking and not injected:
            injected = True
            if change == "role":
                db.query(User).filter_by(user_id=actor_id).update({"user_role": "patient"}, synchronize_session=False)
            else:
                db.add(Bed(ward_id=case["ward"].ward_id, bed_no="postwrite-bed", status=0))
            db.flush()
        return actual(db, candidate, locking=locking)

    monkeypatch.setattr(facts, "current_actor", changed_before_current_lock)
    response = await async_client.post(url, headers=headers, json=body)
    assert injected and response.status_code == (403 if change == "role" else 409), response.text
    assert db_session.query(AIBedSeries).count() == before_series
    assert db_session.query(AIAuditEvent).count() == before_audits
    assert db_session.query(Bed).count() == before_beds
    assert db_session.query(User).filter_by(user_id=actor_id).one().user_role == actor_role
    if row is not None:
        db_session.refresh(row)
        assert (row.status, row.revision, row.snapshot_json, row.projection_json) == original
