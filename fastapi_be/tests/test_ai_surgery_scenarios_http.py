from tests.routing import api_routes

"""Real main/JWT/ASGI surgery scenarios, with only isolated synthetic SQL data."""

import copy
import datetime

import pytest
from sqlalchemy import text

from app.ai import surgery_facts as facts
from app.ai import surgery_scenarios as scenarios
from app.ai.models import AIAuditEvent
from app.ai.surgery_scenario_models import AISurgeryScenario
from app.models import SurgerySchedule
from tests.test_ai_surgery_facts import NOTE, NOW, create, publish, registry
from tests.test_ai_surgery_facts import surgery_case as surgery_case
from tests.test_ai_surgery_scenarios import draft_scenario, published_scenario, review_values, revoke_values
from tests.test_ai_surgery_snapshot import snapshot_case as snapshot_case

BASE = "/api/ai/surgery-scenarios"


def headers(auth_headers, case, role="director"):
    return auth_headers(case[role].username)


async def create_http(client, auth_headers, actual_case):
    response = await client.post(BASE, headers=headers(auth_headers, actual_case[3]), json=actual_case[2])
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_actual_main_five_routes_and_whole_jwt_lifecycle_never_make_booking(async_client, snapshot_case, auth_headers, db_session):
    from app.main import app

    case = snapshot_case[3]
    paths = [(route.path, method) for route in api_routes(app.routes) for method in getattr(route, "methods", ()) if route.path.startswith(BASE)]
    assert len(paths) == len(set(paths)) == 5
    before_schedule = db_session.query(SurgerySchedule).count()
    draft = await create_http(async_client, auth_headers, snapshot_case)
    original = draft["snapshot"], draft["content_hash"]
    assert draft["status"] == "draft" and draft["can_revoke"] and not draft["eligible"] and not draft["can_review"]
    assert draft["snapshot"] is not None and draft["public_source"] is None and not draft["automatic_booking"] and draft["candidate_only"]
    url = BASE + "/" + draft["scenario_id"]
    published = await async_client.post(
        url + "/review", headers=headers(auth_headers, case, "super"), json={"expected_revision": 1, "expected_content_hash": draft["content_hash"], "decision": "publish", "basis_note": NOTE}
    )
    assert published.status_code == 200, published.text
    current = published.json()["data"]
    assert current["status"] == "published" and current["eligible"] and current["public_source"] is not None
    assert current["snapshot"] == original[0] and current["content_hash"] == original[1]
    assert current["public_source"]["governance_hash"] == current["governance_hash"]
    resolution = current["local_resolution"]
    assert resolution["scenario_id"] == current["scenario_id"] and resolution["source_content_hash"] == current["content_hash"]
    assert resolution["cases"][0]["application_id"] == case["application"].application_id
    assert resolution["cases"][0]["patient_id"] == case["patient"].patient_id
    assert {item["resource_id"] for item in resolution["resources"]} == {item.resource_id for item in case["resources"].values()}
    assert {item["fact_token"] for item in resolution["facts"]} == {item["fact_id"] for item in current["public_source"]["manifest"]}
    assert "local_resolution" not in current["public_source"] and case["application"].application_id not in scenarios.bounded_json(current["public_source"])
    detail = await async_client.get(url, headers=headers(auth_headers, case))
    assert detail.status_code == 200 and detail.json()["data"]["projection_hash"] == current["projection_hash"]
    listing = await async_client.get(BASE, headers=headers(auth_headers, case), params={"pool_id": draft["pool_id"], "status": "published", "page_size": 1})
    assert listing.status_code == 200 and listing.json()["data"]["total"] == 1
    assert listing.json()["data"]["items"][0]["scenario_id"] == draft["scenario_id"]
    assert all(key not in listing.json()["data"]["items"][0] for key in ("snapshot", "public_source", "projection_issues", "review_basis_note", "revoke_reason"))
    revoke = await async_client.post(url + "/revoke", headers=headers(auth_headers, case), json={"expected_revision": 2, "expected_content_hash": draft["content_hash"], "basis_note": NOTE})
    assert revoke.status_code == 200 and revoke.json()["data"]["revision"] == 3
    assert revoke.json()["data"]["snapshot"] is None and revoke.json()["data"]["public_source"] is None and revoke.json()["data"]["local_resolution"] is None
    audit = await async_client.get(url, headers=headers(auth_headers, case, "super"), params={"audit_only": "true"})
    assert audit.status_code == 200 and audit.json()["data"]["snapshot"] == original[0]
    assert audit.json()["data"]["public_source"] == current["public_source"] and not audit.json()["data"]["eligible"]
    assert audit.json()["data"]["local_resolution"] == resolution
    assert db_session.query(SurgerySchedule).count() == before_schedule


@pytest.mark.asyncio
async def test_pool_member_without_actual_case_care_sees_only_technical_directory(async_client, snapshot_case, auth_headers, db_session):
    case = snapshot_case[3]
    row = published_scenario(db_session, snapshot_case)
    admin = case["seed"]["admin_user"]
    registry(db_session, case["super"], {"kind": "person_account", "resource_id": case["resources"]["person"].resource_id, "user_id": admin.user_id, "basis_note": NOTE})
    actual_headers = auth_headers(admin.username)
    listed = await async_client.get(BASE, headers=actual_headers, params={"pool_id": row.pool_id})
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["data"]["items"]) == 1
    item = listed.json()["data"]["items"][0]
    assert item["detail_required"] and item["scenario_id"] == row.scenario_id
    assert all(item.get(key) is None for key in ("snapshot", "public_source", "review_basis_note", "revoke_reason"))
    assert NOTE not in listed.text
    detail = await async_client.get(BASE + "/" + row.scenario_id, headers=actual_headers)
    # Detail may return a redacted technical record instead of exposing PHI.
    assert detail.status_code in {200, 403}
    if detail.status_code == 200:
        data = detail.json()["data"]
        assert data["snapshot"] is None and data["public_source"] is None and not data["eligible"]
        assert data["review_basis_note"] is None and data["revoke_reason"] is None and data["local_resolution"] is None
    forbidden_audit = await async_client.get(BASE + "/" + row.scenario_id, headers=actual_headers, params={"audit_only": "true"})
    assert forbidden_audit.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["doctor_user", "foreign_user"])
async def test_actual_clinical_signer_has_no_implicit_ops_or_foreign_scenario_authority(async_client, snapshot_case, auth_headers, role):
    case = snapshot_case[3]
    row = await create_http(async_client, auth_headers, snapshot_case)
    selected_headers = headers(auth_headers, case, role)
    created = await async_client.post(BASE, headers=selected_headers, json=snapshot_case[2])
    detail = await async_client.get(BASE + "/" + row["scenario_id"], headers=selected_headers)
    listed = await async_client.get(BASE, headers=selected_headers, params={"pool_id": row["pool_id"]})
    assert created.status_code == detail.status_code == listed.status_code == 403
    review = await async_client.post(
        BASE + "/" + row["scenario_id"] + "/review",
        headers=headers(auth_headers, case),
        json={"expected_revision": 1, "expected_content_hash": row["content_hash"], "decision": "publish", "basis_note": NOTE},
    )
    assert review.status_code == 403


@pytest.mark.asyncio
async def test_current_source_change_is_redacted_for_ordinary_and_auditable_for_super(async_client, snapshot_case, auth_headers, db_session):
    case = snapshot_case[3]
    row = published_scenario(db_session, snapshot_case)
    original = row.snapshot_json, row.projection_json
    create(db_session, case)
    ordinary = await async_client.get(BASE + "/" + row.scenario_id, headers=headers(auth_headers, case))
    assert ordinary.status_code == 200, ordinary.text
    data = ordinary.json()["data"]
    assert not data["source_current"] and not data["eligible"] and data["snapshot"] is None and data["public_source"] is None and data["local_resolution"] is None
    audit = await async_client.get(BASE + "/" + row.scenario_id, headers=headers(auth_headers, case, "super"), params={"audit_only": "true"})
    assert audit.status_code == 200 and audit.json()["data"]["snapshot"] is not None and not audit.json()["data"]["source_current"]
    assert (row.snapshot_json, row.projection_json) == original
    invalid_revoke = await async_client.post(BASE + "/" + row.scenario_id + "/revoke", headers=headers(auth_headers, case), json=revoke_values(row))
    assert invalid_revoke.status_code == 409


@pytest.mark.asyncio
async def test_late_original_requires_cutoff_refresh_and_old_period_never_becomes_new_execution(async_client, snapshot_case, auth_headers, db_session, monkeypatch):
    case = snapshot_case[3]
    monkeypatch.setattr(facts, "utcnow", lambda: NOW + datetime.timedelta(seconds=1))
    publish(db_session, case, create(db_session, case))
    before = db_session.query(AISurgeryScenario).filter_by(pool_id=case["pool"].pool_id).count()
    response = await async_client.post(BASE, headers=headers(auth_headers, case), json=snapshot_case[2])
    assert response.status_code == 409
    assert db_session.query(AISurgeryScenario).filter_by(pool_id=case["pool"].pool_id).count() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("page", "1.0"), ("page", "true"), ("page_size", "1e0"), ("page_size", "0"), ("status", "not_a_status"), ("pool_id", "not_uuid")])
async def test_scenario_sql_directory_filters_reject_ambiguous_scalar_values(async_client, snapshot_case, auth_headers, field, value):
    case = snapshot_case[3]
    params = {"pool_id": case["pool"].pool_id, field: value}
    response = await async_client.get(BASE, headers=headers(auth_headers, case), params=params)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["extra_private_patient", "wrong_digest", "cost_number", "missing_members", "bool_revision"])
async def test_strict_full_scenario_body_and_cas_never_accept_partially_bound_input(async_client, snapshot_case, auth_headers, change):
    case = snapshot_case[3]
    request = copy.deepcopy(snapshot_case[2])
    if change == "extra_private_patient":
        request["patient_id"] = case["patient"].patient_id
    elif change == "wrong_digest":
        request["expected_capture_digest"] = "0" * 64
    elif change == "cost_number":
        request["cases"][0]["penalty_if_scheduled"]["value"] = 0
    elif change == "missing_members":
        request["members"] = [item for item in request["members"] if item["source_kind"] != "equipment_identity_capability"]
    else:
        row = await create_http(async_client, auth_headers, snapshot_case)
        response = await async_client.post(
            BASE + "/" + row["scenario_id"] + "/review",
            headers=headers(auth_headers, case, "super"),
            json={"expected_revision": True, "expected_content_hash": row["content_hash"], "decision": "publish", "basis_note": NOTE},
        )
        assert response.status_code == 422
        return
    response = await async_client.post(BASE, headers=headers(auth_headers, case), json=request)
    assert response.status_code == (409 if change in {"wrong_digest", "missing_members"} else 422), response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "publish", "revoke"])
async def test_http_actual_sql_audit_error_rolls_back_both_row_and_full_projection(async_client, snapshot_case, auth_headers, db_session, operation):
    case = snapshot_case[3]
    row = None if operation == "create" else draft_scenario(db_session, snapshot_case)
    if operation == "revoke":
        scenarios.review_scenario(db_session, case["super"], row.scenario_id, review_values(row))
        db_session.commit()
    previous = None if row is None else (row.status, row.revision, row.snapshot_json, row.projection_json, row.projection_hash)
    count = db_session.query(AISurgeryScenario).filter_by(pool_id=case["pool"].pool_id).count()
    action = "surgery.scenario." + operation
    trigger = "test_reject_http_surgery_audit"
    db_session.execute(
        text(f"CREATE TEMP TRIGGER {trigger} BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='{action}' BEGIN SELECT RAISE(ABORT, 'isolated synthetic SQL audit rejected'); END")
    )
    try:
        if operation == "create":
            response = await async_client.post(BASE, headers=headers(auth_headers, case), json=snapshot_case[2])
        elif operation == "publish":
            response = await async_client.post(BASE + "/" + row.scenario_id + "/review", headers=headers(auth_headers, case, "super"), json=review_values(row))
        else:
            response = await async_client.post(BASE + "/" + row.scenario_id + "/revoke", headers=headers(auth_headers, case, "super"), json=revoke_values(row))
        assert response.status_code == 409, response.text
    finally:
        db_session.rollback()
        db_session.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
        db_session.commit()
    assert db_session.query(AISurgeryScenario).filter_by(pool_id=case["pool"].pool_id).count() == count
    if row is not None:
        db_session.refresh(row)
        assert (row.status, row.revision, row.snapshot_json, row.projection_json, row.projection_hash) == previous
        assert db_session.query(AIAuditEvent).filter_by(target=row.scenario_id, action=action).count() == 0
