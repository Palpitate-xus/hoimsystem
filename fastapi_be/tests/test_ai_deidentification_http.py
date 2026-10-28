from tests.routing import api_routes

"""Actual product Main/JWT with18 Source routes; no live model or MySQL proof."""

import datetime as dt
import json

import pytest
from fastapi import HTTPException

from app.ai import deidentification_collection as collection
from app.ai import deidentification_exports as exports
from app.ai import deidentification_sources as sources
from app.ai.deidentification_http import MAX_BYTES, parse_json, response_bytes
from app.ai.deidentification_models import AIDeidentificationCase
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_sources import utcnow
from tests.test_ai_deidentification_exports import authority_review, release_request
from tests.test_ai_deidentification_reviews import residual, review_request
from tests.test_ai_deidentification_sources import deid_case as deid_case  # noqa: F401
from tests.test_ai_deidentification_sources import grant_super, selection
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import anchors
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


@pytest.fixture
def mounted_deidentification_router():
    from app.main import app
    from app.routers.ai_deidentification import router

    expected = {(tuple(sorted(route.methods)), "/api" + route.path) for route in router.routes}
    actual = [(tuple(sorted(route.methods)), route.path) for route in api_routes(app.routes) if route.path.startswith("/api/ai/deidentification/") and "/tasks" not in route.path]
    assert len(expected) == len(actual) == 18 and set(actual) == expected
    yield


@pytest.mark.asyncio
async def test_actual_main_jwt_whole_source_review_and_one_json_release_preserve_literal_utf8_and_utc6(db_session, deid_case, async_client, auth_headers, mounted_deidentification_router, monkeypatch):
    from app.ai import deidentification_lifecycle as life

    db, case = db_session, deid_case[0]
    grant_super(db, deid_case)
    now = (utcnow() + dt.timedelta(seconds=1)).replace(microsecond=123456)
    for module in (sources, collection, life, exports):
        monkeypatch.setattr(module, "utcnow", lambda: now)
    # Review creation uses its own imported clock and keeps the same UTC6 basis.
    from app.ai import deidentification_reviews as reviews

    monkeypatch.setattr(reviews, "utcnow", lambda: now)
    ordinary, sup = auth_headers(case["admin_user"].username), auth_headers(case["super_admin_user"].username)

    async def post(path, body, headers=ordinary):
        response = await async_client.post("/api/ai/deidentification/" + path, headers=headers, json=body)
        assert response.status_code == 200, response.text
        return response.json()["data"]

    scope = {**anchors(deid_case[1]), "patient_id": case["patient"].patient_id}
    available = await post("fields", scope)
    assert available["complete"] and any(row["field"] == "symptom" for row in available["items"])
    request = selection(db, deid_case)
    preview = await post("cases/preview", request)
    source = await post("cases", dict(request=request, expected_collection_digest=preview["expected_collection_digest"], basis_note=BASIS))
    assert source["recorded_at"].endswith(".123456Z")
    assert source["snapshot"]["capture"]["selected_documents"][0]["document"]["text"] == deid_case[-1][0].symptom
    assert ".123456Z" in source["public_source"]["documents"][0]["text"]
    directory = await post("cases/directory", scope)
    assert directory["complete"] and directory["total"] == 1 and directory["items"][0]["detail_required"]
    await post("cases/" + source["case_id"] + "/review", dict(expected_revision=1, expected_content_hash=source["content_hash"], decision="publish", basis_note=BASIS), sup)
    response = await async_client.get("/api/ai/deidentification/cases/" + source["case_id"], headers=ordinary)
    assert response.status_code == 200
    source = response.json()["data"]
    review = await post("reviews", review_request(source))
    await post("reviews/" + review["review_id"] + "/residual-review", residual(review), sup)
    review = await post("reviews/" + review["review_id"] + "/review", dict(expected_revision=1, expected_content_hash=review["content_hash"], decision="publish", basis_note=BASIS), sup)
    release = await post("releases", release_request(review))
    await post("releases/" + release["release_id"] + "/authority-review", authority_review(release), sup)
    release = await post("releases/" + release["release_id"] + "/review", dict(expected_revision=1, expected_content_hash=release["content_hash"], decision="publish", basis_note=BASIS), sup)
    result = await async_client.post("/api/ai/deidentification/releases/" + release["release_id"] + "/download", headers=ordinary, json={})
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert result.json() == release["artifact"] and result.json()["anonymity_guaranteed"] is False
    assert result.headers["x-artifact-sha256"] == __import__("hashlib").sha256(result.content).hexdigest()
    assert "\ufeff[已遮蔽]\r\n😀é" in result.json()["documents"][0]["text"]
    assert "13800138000" in result.json()["documents"][0]["text"]
    assert deid_case[-1][0].symptom.startswith("\ufeff张三")  # original clinical value unchanged
    result = await async_client.post("/api/ai/deidentification/releases/" + release["release_id"] + "/download", headers=ordinary, json={})
    assert result.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["patient_user", "super_admin_user"])
async def test_actual_main_no_role_only_clinical_body_and_no_rejected_input_echo(db_session, deid_case, async_client, auth_headers, mounted_deidentification_router, who):
    case = deid_case[0]
    request = selection(db_session, deid_case)
    before = db_session.query(AIAuditEvent).count()
    response = await async_client.post("/api/ai/deidentification/cases/preview", headers=auth_headers(case[who].username), json=request)
    assert response.status_code == 403 and "张三" not in response.text
    response = await async_client.post(
        "/api/ai/deidentification/cases/preview", headers=auth_headers(case["admin_user"].username), json={**request, "private_unexpected": "敏感原文不得出现在错误回显"}
    )
    assert response.status_code == 422 and "敏感原文" not in response.text
    assert db_session.query(AIAuditEvent).count() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("wire", ["duplicate", "surrogate", "nonfinite", "size"])
async def test_actual_main_whole_request_boundary_rejects_before_source_audit(db_session, deid_case, async_client, auth_headers, mounted_deidentification_router, wire):
    case = deid_case[0]
    body = {"duplicate": b'{"scope_id":1,"scope_id":2}', "surrogate": b'{"text":"\\ud800"}', "nonfinite": b'{"value":1e999}', "size": b'{"text":"' + b"a" * MAX_BYTES + b'"}'}[wire]
    before = db_session.query(AIAuditEvent).count()
    response = await async_client.post("/api/ai/deidentification/cases/preview", headers={**auth_headers(case["admin_user"].username), "Content-Type": "application/json"}, content=body)
    assert response.status_code == (413 if wire == "size" else 422)
    assert db_session.query(AIAuditEvent).count() == before


def test_whole_response_budget_before_source_commit_rolls_back_even_when_source_alone_fits(db_session, deid_case):
    db, case = db_session, deid_case[0]
    deid_case[-1][0].symptom = "x" * (3 * 1024 * 1024)
    db.commit()
    request = selection(db, deid_case)
    preview = sources.preview_input(db, case["admin_user"], request)
    before = (db.query(AIDeidentificationCase).count(), db.query(AIAuditEvent).count())
    with pytest.raises(HTTPException) as error:
        sources.create_case(db, case["admin_user"], dict(request=request, expected_collection_digest=preview["expected_collection_digest"], basis_note=BASIS))
    assert error.value.status_code == 413
    assert (db.query(AIDeidentificationCase).count(), db.query(AIAuditEvent).count()) == before


def test_parser_and_exact_whole_wire_cap_preserve_original_literals():
    raw = '{"text":"原文2026-10-21T12:00:00.123456Z\\r\\n😀"}'.encode()
    assert parse_json(raw)["text"] == "原文2026-10-21T12:00:00.123456Z\r\n😀"
    assert json.loads(response_bytes({"text": parse_json(raw)["text"]}))["data"]["text"] == parse_json(raw)["text"]
    with pytest.raises(HTTPException):
        response_bytes({"text": "x" * MAX_BYTES})
