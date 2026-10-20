"""Actual scoped HTTP declaration, full projection, SQL CAS and audit rollback."""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Query

from app.ai import governance
from app.ai import roster_facts as facts
from app.ai import roster_plans as plans
from app.ai.roster_contract import hash_content
from app.ai.roster_plan_input import preview_input
from app.ai.roster_plan_models import AIRosterPlan
from app.models import Doctor
from tests.test_ai_roster_facts import NOTE, create
from tests.test_ai_roster_plan_input import plan_case as plan_case
from tests.test_ai_roster_plan_input import roster_case as roster_case


def create_plan(db, case):
    preview = preview_input(db, case["director"], case["plan_request"])
    row = plans.create_plan(db, case["director"], {"request": case["plan_request"], "expected_collection_digest": preview["collection_digest"]})
    db.commit()
    return row


def publish_plan(db, case, row, decision="publish"):
    plans.review_plan(db, case["super"], row.plan_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": decision, "review_basis_note": NOTE})
    db.commit()
    db.refresh(row)
    return row


@pytest.mark.asyncio
async def test_actual_http_complete_preview_draft_publish_revoke_and_frozen_ui_fixture(async_client, db_session, auth_headers, plan_case, tmp_path):
    case = plan_case
    headers = auth_headers(case["director"].username)
    response = await async_client.post("/api/ai/roster-plans/preview", headers=headers, json=case["plan_request"])
    assert response.status_code == 200, response.text
    preview = response.json()["data"]
    assert case["unscheduled"].doctor_id in {item["doctor_id"] for item in preview["cohort"]}
    response = await async_client.post("/api/ai/roster-plans", headers=headers, json={"request": case["plan_request"], "expected_collection_digest": preview["collection_digest"]})
    assert response.status_code == 200, response.text
    draft = response.json()["data"]
    assert draft["status"] == "draft" and draft["revision"] == 1 and draft["snapshot"] is not None and draft["public_source"] is None and draft["eligible"] is False
    assert hash_content(draft["snapshot"]) == draft["content_hash"]
    url = "/api/ai/roster-plans/" + draft["plan_id"]
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
    response = await async_client.get("/api/ai/roster-plans", headers=headers, params={"department_id": case["department"].department_id})
    assert response.status_code == 200
    listed = next(item for item in response.json()["data"]["items"] if item["plan_id"] == draft["plan_id"])
    assert all(key not in listed for key in ("snapshot", "public_source", "review_basis_note", "revoke_reason"))
    response = await async_client.post(url + "/revoke", headers=headers, json={"expected_revision": 2, "reason": "合成排班资料停止使用并重新核对"})
    assert response.status_code == 200, response.text
    revoked = response.json()["data"]
    assert revoked["revision"] == 3 and revoked["snapshot"] is revoked["public_source"] is revoked["review_basis_note"] is revoked["revoke_reason"] is None
    response = await async_client.get("/api/ai/admin/roster-plans/" + draft["plan_id"], headers=auth_headers(case["super"].username))
    assert response.status_code == 200, response.text
    frozen = response.json()["data"]
    assert frozen["snapshot"] == draft["snapshot"] and frozen["public_source"] == published["public_source"] and frozen["projection_hash"] == published["projection_hash"]
    fixture = {"request": case["plan_request"], "preview": preview, "draft": draft, "published": published, "ordinary_revoked": revoked, "super_revoked": frozen, "list_item": listed}
    path = tmp_path / "actual-roster-plan-ui.json"
    path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    assert json.loads(path.read_text())["super_revoked"] == frozen


@pytest.mark.parametrize("change", ["new_doctor", "new_fact", "revoke_fact", "move_doctor"])
def test_complete_current_collection_changes_block_new_execution_and_redact_ordinary_history(db_session, plan_case, change):
    case = plan_case
    row = publish_plan(db_session, case, create_plan(db_session, case))
    original = row.snapshot_json, row.projection_json
    if change == "new_doctor":
        db_session.add(Doctor(name="合成后来新增人员", department_id=case["department"].department_id))
    elif change == "new_fact":
        create(db_session, case)
    elif change == "revoke_fact":
        source = case["facts"]["qualification"]
        facts.revoke_source(db_session, case["super"], source.source_kind, source.source_record_id, {"expected_revision": 2, "reason": "合成原资格停止使用"})
    else:
        case["doctor"].department_id = case["foreign"].department_id
    db_session.commit()
    with pytest.raises(HTTPException, match="409"):
        plans.authorize_plan(db_session, case["director"], row.plan_id)
    ordinary = plans.plan_current(db_session, case["director"], row.plan_id)
    assert ordinary["snapshot"] is ordinary["public_source"] is None and ordinary["eligible"] is False
    frozen = plans.plan_current(db_session, case["super"], row.plan_id, audit_only=True)
    assert frozen["snapshot"] is not None and frozen["public_source"] is not None and frozen["eligible"] is False
    db_session.refresh(row)
    assert (row.snapshot_json, row.projection_json) == original


@pytest.mark.parametrize("column", ["snapshot_json", "content_hash", "collection_digest", "projection_json", "projection_hash", "review_basis_note"])
def test_own_corruption_never_uses_super_frozen_audit_bypass(db_session, plan_case, column):
    case = plan_case
    row = publish_plan(db_session, case, create_plan(db_session, case))
    setattr(row, column, "{}" if column.endswith("_json") else "a" * 64)
    db_session.commit()
    with pytest.raises(HTTPException, match="409"):
        plans.plan_current(db_session, case["super"], row.plan_id, audit_only=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "publish", "reject", "revoke"])
async def test_actual_sql_audit_failure_rolls_back_each_plan_write(async_client, db_session, auth_headers, plan_case, monkeypatch, action):
    from app.ai.models import AIAuditEvent

    case = plan_case
    row = create_plan(db_session, case) if action != "create" else None
    before_count, before_audits = db_session.query(AIRosterPlan).count(), db_session.query(AIAuditEvent).count()
    original = (row.status, row.revision, row.snapshot_json, row.projection_json) if row is not None else None
    preview = preview_input(db_session, case["director"], case["plan_request"])

    def bad_sql(db, actor_id, *args, **kwargs):
        db.add(AIAuditEvent(actor_id=actor_id, action=None, target="synthetic-roster-plan-bad-audit", detail_json="{}"))

    monkeypatch.setattr(governance, "audit", bad_sql)
    actor = case["director"]
    if action == "create":
        url, body = "/api/ai/roster-plans", {"request": case["plan_request"], "expected_collection_digest": preview["collection_digest"]}
    elif action == "revoke":
        url, body = f"/api/ai/roster-plans/{row.plan_id}/revoke", {"expected_revision": 1, "reason": "实际失败SQL审计须原子回滚"}
    else:
        actor = case["super"]
        url, body = f"/api/ai/roster-plans/{row.plan_id}/review", {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": action, "review_basis_note": NOTE}
    response = await async_client.post(url, headers=auth_headers(actor.username), json=body)
    assert response.status_code == 409, response.text
    assert db_session.query(AIRosterPlan).count() == before_count and db_session.query(AIAuditEvent).count() == before_audits
    if row is not None:
        db_session.refresh(row)
        assert (row.status, row.revision, row.snapshot_json, row.projection_json) == original


def test_actual_plan_cas_detects_second_transaction_publication_after_precheck(db_session, plan_case, monkeypatch):
    from sqlalchemy.orm import Session

    case = plan_case
    row = create_plan(db_session, case)
    called = False
    actual = Query.update

    def race(query, values, *args, **kwargs):
        nonlocal called
        if not called and query.column_descriptions[0]["entity"] is AIRosterPlan:
            called = True
            with Session(bind=db_session.get_bind()) as second:
                plans.review_plan(
                    second,
                    second.get(type(case["super"]), case["super"].user_id),
                    row.plan_id,
                    {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": "publish", "review_basis_note": NOTE + "第二事务"},
                )
                second.commit()
        return actual(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", race)
    with pytest.raises(HTTPException, match="409"):
        plans.review_plan(db_session, case["super"], row.plan_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": "publish", "review_basis_note": NOTE})
    db_session.rollback()
    db_session.refresh(row)
    assert called and row.status == "published" and row.review_basis_note.endswith("第二事务")
