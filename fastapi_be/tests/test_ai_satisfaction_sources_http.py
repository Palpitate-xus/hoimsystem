"""Actual mounted app.main JWT/ASGI responses, including canonical UTC6 and privacy."""

import copy
import json

import pytest
from sqlalchemy import event, text

from app.ai.satisfaction_models import AISatisfactionCase
from app.ai.satisfaction_sources import hash_content
from app.models import Review
from tests.test_ai_satisfaction_sources import BASIS, period, satisfaction_case  # noqa: F401

BASE = "/api/ai/satisfaction-sources"


async def actual_request(client, case, auth_headers):
    headers = auth_headers(case["super_admin_user"].username)
    response = await client.post(BASE + "/cases/preview", headers=headers, json=period(case))
    assert response.status_code == 200, response.text
    capture = response.json()["data"]
    selected = next(o for o in capture["excerpt_options"] if o["excerpt_id"] == case["excerpt"].excerpt_id)
    body = {
        "request": period(case),
        "expected_collection_digest": capture["collection_digest"],
        "selected_excerpts": [{k: selected[k] for k in ("excerpt_id", "review_token", "content_hash", "governance_hash")}],
        "basis_note": BASIS,
    }
    return headers, body, capture


@pytest.mark.asyncio
async def test_actual_main_all_routes_private_public_sha_microseconds_and_no_business_write(async_client, db_session, satisfaction_case, auth_headers):  # noqa: F811
    case, db = satisfaction_case, db_session
    headers, body, capture = await actual_request(async_client, case, auth_headers)
    assert hash_content(capture["safe_snapshot"]) == capture["safe_projection_hash"]
    count = db.query(Review).count()
    for path in ("/options", "/doctors?page=1&page_size=100"):
        response = await async_client.get(BASE + path, headers=headers)
        assert response.status_code == 200, response.text
    response = await async_client.post(BASE + "/cases", headers=headers, json=body)
    assert response.status_code == 200, response.text
    draft = response.json()["data"]
    assert draft["created_at"].endswith("Z") and len(draft["created_at"].split(".")[1]) == 7
    identifier = draft["case_id"]
    reviewed = await async_client.post(BASE + f"/cases/{identifier}/review", headers=headers, json={"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    assert reviewed.status_code == 200, reviewed.text
    published = reviewed.json()["data"]
    assert hash_content(published["snapshot"]) == published["content_hash"]
    assert hash_content(published["public_source"]) == published["projection_hash"]
    assert hash_content(published["safe_snapshot"]) == published["safe_projection_hash"]
    ordinary = await async_client.get(BASE + f"/cases/{identifier}", headers=auth_headers(case["admin_user"].username))
    assert ordinary.status_code == 200 and ordinary.json()["data"]["snapshot"] is None
    assert case["review"].comment not in ordinary.text and case["patient"].identity not in ordinary.text
    queries = []

    def collect(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", collect)
    try:
        directory = await async_client.get(BASE + "/cases?audit_only=true", headers=headers)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", collect)
    assert directory.status_code == 200 and directory.json()["data"]["detail_required"]
    assert all("snapshot_json" not in sql and "projection_json" not in sql for sql in queries)
    assert "review_basis_note" not in json.dumps(directory.json()["data"]["items"])
    revoked = await async_client.post(BASE + f"/cases/{identifier}/revoke", headers=headers, json={"expected_revision": 2, "basis_note": BASIS})
    assert revoked.status_code == 200 and revoked.json()["data"]["public_source"] == published["public_source"]
    stale = await async_client.get(BASE + f"/cases/{identifier}", headers=auth_headers(case["admin_user"].username))
    assert stale.json()["data"]["snapshot"] is stale.json()["data"]["safe_snapshot"] is stale.json()["data"]["public_source"] is None
    assert db.query(Review).count() == count


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "director", "doctor", "nurse", "cashier", "pharmacist", "guide", "patient", "lab_technician", "registrar"])
async def test_actual_main_role_matrix_and_explicit_super_governance(async_client, satisfaction_case, auth_headers, role):  # noqa: F811
    case = satisfaction_case
    keys = {
        "admin": "admin_user",
        "director": "director_user",
        "doctor": "doctor_user",
        "nurse": "nurse_user",
        "cashier": "cashier_user",
        "pharmacist": "pharmacist_user",
        "guide": "guide_user",
        "patient": "patient_user",
        "lab_technician": "lab_tech_user",
        "registrar": "registrar_user",
    }
    headers = auth_headers(case[keys[role]].username)
    result = await async_client.get(BASE + "/options", headers=headers)
    assert result.status_code == (200 if role in {"admin", "director"} else 403)
    response = await async_client.post(BASE + "/cases/00000000-0000-0000-0000-000000000001/review", headers=headers, json={"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    assert response.status_code == 403
    response = await async_client.get(BASE + "/cases?audit_only=true", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_actual_main_strict_dates_fractional_query_unknown_keys_and_foreign_capture(async_client, satisfaction_case, auth_headers):  # noqa: F811
    headers, body, _ = await actual_request(async_client, satisfaction_case, auth_headers)
    for changed in ({**body["request"], "date_from": "2026-02-30"}, {**body["request"], "doctor_ids": [True]}, {**body["request"], "extra": 1}):
        response = await async_client.post(BASE + "/cases/preview", headers=headers, json=changed)
        assert response.status_code == 422, response.text
    for path in ("/doctors?page=1.0", "/cases/not-a-uuid", "/cases?doctor_ids=1.0"):
        response = await async_client.get(BASE + path, headers=headers)
        assert response.status_code == 422, response.text
    changed = copy.deepcopy(body)
    changed["selected_excerpts"][0]["review_token"] = "0" * 64
    response = await async_client.post(BASE + "/cases", headers=headers, json=changed)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_actual_main_postwrite_source_closure_change_rolls_back_publication_and_audit(async_client, db_session, satisfaction_case, auth_headers):  # noqa: F811
    headers, body, _ = await actual_request(async_client, satisfaction_case, auth_headers)
    response = await async_client.post(BASE + "/cases", headers=headers, json=body)
    identifier = response.json()["data"]["case_id"]
    db = db_session
    review_id = satisfaction_case["review"].review_id
    db.execute(
        text(
            f"CREATE TRIGGER mutate_satisfaction_source AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='satisfaction_case.review' BEGIN UPDATE hoimsystem_review SET score=1 WHERE review_id={int(review_id)}; END"
        )
    )
    db.commit()
    try:
        result = await async_client.post(BASE + f"/cases/{identifier}/review", headers=headers, json={"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
        assert result.status_code == 409, result.text
        db.expire_all()
        row = db.query(AISatisfactionCase).filter_by(case_id=identifier).one()
        assert row.status == "draft" and row.revision == 1 and row.projection_json is None
        assert db.query(Review).filter_by(review_id=review_id).one().score == 2
    finally:
        db.execute(text("DROP TRIGGER mutate_satisfaction_source"))
        db.commit()
