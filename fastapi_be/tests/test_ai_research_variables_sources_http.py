from tests.routing import api_routes

"""76 real Main/JWT with a temporary dedicated router, never fake authority."""

import datetime as dt
import uuid
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai.models import AIAuditEvent
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_cohort_sources import hash_content
from app.ai.research_variables_batches import create_batch, review_batch
from app.ai.research_variables_dictionary import create_dictionary, review_dictionary, verify_dictionary_proof
from app.ai.research_variables_models import MAX_BYTES, AIResearchVariableBatch, AIResearchVariableDictionary
from app.models import MedicalRecord, Patient, Registration
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401
from tests.test_ai_research_variables_collection import variable_capture_case as variable_capture_case  # noqa: F401
from tests.test_ai_research_variables_dictionary import definition_review, technical_review
from tests.test_ai_research_variables_dictionary import variable_dictionary_case as variable_dictionary_case  # noqa: F401

BASE = "/api/ai/research-variables"
PRIVATE = (
    "hoimsystem_ai_research_variable_dictionary.dictionary_json",
    "hoimsystem_ai_research_variable_dictionary.parent_binding_json",
    "hoimsystem_ai_research_variable_dictionary.review_basis_note",
    "hoimsystem_ai_research_variable_dictionary.definition_review_basis",
    "hoimsystem_ai_research_variable_batch.snapshot_json",
    "hoimsystem_ai_research_variable_batch.projection_json",
    "hoimsystem_ai_research_variable_batch.review_basis_note",
    "hoimsystem_ai_research_variable_batch.revoke_reason",
)


@pytest.fixture
def mounted_variable_router():

    from app.main import app
    from app.routers.ai_research_variables_sources import router

    original = list(app.router.routes)
    existing = [r for r in api_routes(original) if r.endpoint.__module__ == "app.routers.ai_research_variables_sources"]
    if existing:
        assert len(existing) == 17 and len({(m, r.path) for r in existing for m in r.methods}) == 17
        assert ("GET", "/api/ai/research-variables/scopes/{scope_id}") in {(m, r.path) for r in existing for m in r.methods}
        yield
        return
    source_routes = [r for r in api_routes(original) if r.endpoint.__module__ == "app.routers.ai_research_cohort_sources"]
    assert len(source_routes) == 23
    app.include_router(router, prefix="/api")
    try:
        mounted = [r for r in api_routes(app.router.routes) if r.endpoint.__module__ == "app.routers.ai_research_variables_sources"]
        assert len(mounted) == 17 and len({(m, r.path) for r in mounted for m in r.methods}) == 17
        yield
    finally:
        app.router.routes[:] = original


def observe(db):
    statements = []

    def record(conn, cursor, sql, params, context, many):
        if sql.lstrip().upper().startswith("SELECT"):
            statements.append(sql)

    event.listen(db.bind, "before_cursor_execute", record)
    return statements, record


def bodyless(value):
    assert "eligible" not in value and "original" in value and value["original"] is None
    assert value["body_included"] is False and value["detail_required"] is True
    assert value["review_basis_note"] is value["revoke_reason"] is None


def reference(request):
    return {key: request[key] for key in ("scope_id", "scope_content_hash", "scope_governance_hash")}


@pytest.mark.asyncio
@pytest.mark.parametrize("microseconds", [0, 123456])
async def test_actual_main_dictionary_ack_independent_review_and_split_proof_preserve_whole_utc6_literal(
    db_session, variable_dictionary_case, async_client, auth_headers, mounted_variable_router, monkeypatch, microseconds
):
    from app.ai import research_variables_dictionary as dictionaries
    from app.ai.research_cohort_sources import utcnow

    db = db_session
    case, _, _, request = variable_dictionary_case
    moment = utcnow().replace(microsecond=microseconds) + dt.timedelta(seconds=1)
    monkeypatch.setattr(dictionaries, "utcnow", lambda: moment)
    request["variables"][0]["extraction_instruction"] += "\ufeff\r\n🧪否定原文"
    business = {model: db.query(model).count() for model in (Patient, MedicalRecord, Registration)}
    admin, reviewer, sup = (auth_headers(case[k].username) for k in ("admin_user", "reviewer", "super_admin_user"))
    made = await async_client.post(BASE + "/dictionaries", headers=admin, json=request)
    assert made.status_code == 200, made.text
    ack = made.json()["data"]
    metadata = ack["metadata"]
    bodyless(metadata)
    assert ack["fresh_parts_required"] is True and len(made.content) < 3000
    assert metadata["created_at"].endswith(f".{microseconds:06}Z")
    identifier = metadata["dictionary_id"]
    path = BASE + "/dictionaries/" + identifier
    original = (await async_client.get(path + "/parts/definition", headers=admin)).json()["data"]
    parent = (await async_client.get(path + "/parts/scope", headers=admin)).json()["data"]
    assert original["metadata"] == parent["metadata"] == metadata
    proof = {**original["value"], "parent_binding": parent["value"]}
    assert verify_dictionary_proof(proof) == proof and proof["payload"] == request
    signed = await async_client.post(path + "/definition-review", headers=reviewer, json=definition_review({"content_hash": metadata["content_hash"]}))
    assert signed.status_code == 200, signed.text
    signed_metadata = signed.json()["data"]["metadata"]
    assert signed_metadata["definition_reviewed_by"] != metadata["created_by"]
    # Independent review has its own exact receipt even before revision2.
    assert signed_metadata["revision"] == metadata["revision"] == 1
    assert signed_metadata["content_hash"] == metadata["content_hash"]
    assert signed_metadata["last_event_id"] != metadata["last_event_id"]
    denied = await async_client.post(path + "/review", headers=admin, json=technical_review())
    assert denied.status_code == 403
    published = await async_client.post(path + "/review", headers=sup, json=technical_review())
    assert published.status_code == 200, published.text
    fresh = (await async_client.get(path, headers=admin)).json()["data"]
    assert fresh == published.json()["data"]["metadata"] and fresh["revision"] == 2
    assert fresh != metadata and fresh["content_hash"] == metadata["content_hash"]
    part = await async_client.get(path + "/parts/definition", headers=admin)
    assert part.status_code == 200 and part.json()["data"]["current_validation"]["eligible"] is True
    revoked = await async_client.post(path + "/revoke", headers=sup, json={"expected_revision": 2, "basis_note": BASIS})
    assert revoked.status_code == 200 and revoked.json()["data"]["metadata"]["revision"] == 3
    assert {model: db.query(model).count() for model in business} == business


@pytest.mark.asyncio
async def test_actual_main_preview_create_publish_split_source_snapshot_and_revoke_are_same_original_not_aggregate(
    db_session, variable_capture_case, async_client, auth_headers, mounted_variable_router
):
    case, _, request, _, _ = variable_capture_case
    admin, sup = (auth_headers(case[k].username) for k in ("admin_user", "super_admin_user"))
    before = {model: db_session.query(model).count() for model in (Patient, MedicalRecord, Registration)}
    audit_before = db_session.query(AIAuditEvent).count()
    preview = await async_client.post(BASE + "/batches/preview", headers=admin, json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["schema_version"] == "research_variable_capture_v1" and db_session.query(AIAuditEvent).count() == audit_before
    created = await async_client.post(BASE + "/batches", headers=admin, json={**request, "basis_note": BASIS})
    assert created.status_code == 200, created.text
    ack = created.json()["data"]
    bodyless(ack["metadata"])
    identifier = ack["metadata"]["batch_id"]
    path = BASE + "/batches/" + identifier
    published = await async_client.post(path + "/review", headers=sup, json=technical_review())
    assert published.status_code == 200, published.text
    summary = (await async_client.get(path, headers=admin)).json()["data"]
    source = (await async_client.get(path + "/parts/source", headers=admin)).json()["data"]
    private = (await async_client.get(path + "/parts/snapshot", headers=admin)).json()["data"]
    assert source["metadata"] == private["metadata"] == summary == published.json()["data"]["metadata"]
    assert source["current_validation"]["eligible"] is private["current_validation"]["eligible"] is True
    assert hash_content(source["value"]) == summary["projection_hash"]
    assert hash_content(private["value"]["snapshot"]) == summary["content_hash"]
    assert "snapshot" not in source["value"] and "source" not in private["value"]["proof"]
    assert source["value"]["documents"] and "否认既往原症状\r\n🧪" in canonical_json(private["value"]["snapshot"]).replace("\\r\\n", "\r\n")
    directory = await async_client.get(BASE + "/batches", headers=admin, params={**reference(request), "size": 1})
    assert directory.status_code == 200, directory.text
    assert any(item["batch_id"] == identifier for item in directory.json()["data"]["items"])
    revoked = await async_client.post(path + "/revoke", headers=sup, json={"expected_revision": 2, "basis_note": BASIS})
    assert revoked.status_code == 200 and revoked.json()["data"]["metadata"]["revision"] == 3
    later = await async_client.get(path + "/parts/source", headers=admin)
    assert later.status_code == 200 and not later.json()["data"]["current_validation"]["eligible"]
    assert later.json()["data"]["metadata"] != source["metadata"]
    assert {model: db_session.query(model).count() for model in before} == before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dictionary", "batch"])
async def test_actual_normal_metadata_page_and_detail_never_select_variable_body_or_notes(db_session, variable_capture_case, async_client, auth_headers, mounted_variable_router, kind):
    case, _, request, _, _ = variable_capture_case
    made = create_batch(db_session, case["admin_user"], {**request, "basis_note": BASIS})
    identifier = made["batch_id"] if kind == "batch" else made["dictionary_id"]
    plural = "batches" if kind == "batch" else "dictionaries"
    headers = auth_headers(case["admin_user"].username)
    statements, record = observe(db_session)
    try:
        listed = await async_client.get(BASE + "/" + plural, headers=headers, params={**reference(request), "size": 1})
        current = await async_client.get(BASE + "/" + plural + "/" + identifier, headers=headers)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)
    assert listed.status_code == current.status_code == 200
    bodyless(current.json()["data"])
    for item in listed.json()["data"]["items"]:
        bodyless(item)
    assert not any(column in sql for sql in statements for column in PRIVATE)


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_name", ["admin_user", "super_admin_user"])
async def test_actual_withdrawal_denies_metadata_and_every_part_before_body_even_super_but_technical_remains_bodyless(
    db_session, variable_capture_case, async_client, auth_headers, mounted_variable_router, actor_name
):
    case, permission, request, _, _ = variable_capture_case
    made = create_batch(db_session, case["admin_user"], {**request, "basis_note": BASIS})
    review_registry_original(db_session, case["super_admin_user"], "authorization", permission["source_record_id"], dict(expected_revision=2, basis_note=BASIS), revoke=True)
    headers = auth_headers(case[actor_name].username)
    paths = [
        ("/dictionaries", reference(request)),
        ("/batches", reference(request)),
        ("/dictionaries/" + made["dictionary_id"], None),
        ("/batches/" + made["batch_id"], None),
        ("/dictionaries/" + made["dictionary_id"] + "/parts/definition", None),
        ("/dictionaries/" + made["dictionary_id"] + "/parts/scope", None),
        ("/batches/" + made["batch_id"] + "/parts/source", None),
        ("/batches/" + made["batch_id"] + "/parts/snapshot", None),
    ]
    statements, record = observe(db_session)
    try:
        for suffix, params in paths:
            response = await async_client.get(BASE + suffix, headers=headers, params=params)
            assert response.status_code == 403, (suffix, response.text)
        for plural, identifier in (("dictionaries", made["dictionary_id"]), ("batches", made["batch_id"])):
            for suffix in ("/technical/" + plural, "/technical/" + plural + "/" + identifier):
                response = await async_client.get(BASE + suffix, headers=headers)
                assert response.status_code == (200 if actor_name == "super_admin_user" else 403), response.text
                if response.status_code == 200:
                    data = response.json()["data"]
                    for item in data.get("items", [data]):
                        bodyless(item)
                        assert item["technical_only"] is True
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)
    assert not any(column in sql for sql in statements for column in PRIVATE)


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["size=0", "size=101", "size=true", "page=01", "scope_id=NOT-A-UUID", "size=1&size=2", "audit_only=true", "unknown=null"])
async def test_actual_closed_queries_reject_duplicate_unknown_noncanonical_and_missing_scope_anchors(db_session, variable_dictionary_case, async_client, auth_headers, mounted_variable_router, query):
    case, _, _, request = variable_dictionary_case
    response = await async_client.get(BASE + "/dictionaries?" + urlencode(reference(request)) + "&" + query, headers=auth_headers(case["admin_user"].username))
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_name", ["patient_user", "nurse_user", "cashier_user", "pharmacist_user", "director_user", "doctor_user"])
async def test_actual_role_alone_and_super_technical_route_do_not_grant_project_body(db_session, variable_dictionary_case, async_client, auth_headers, mounted_variable_router, actor_name):
    case, _, _, request = variable_dictionary_case
    made = create_dictionary(db_session, case["admin_user"], request)
    statements, record = observe(db_session)
    try:
        headers = auth_headers(case[actor_name].username)
        for suffix in ("/dictionaries/" + made["dictionary_id"], "/dictionaries/" + made["dictionary_id"] + "/parts/definition", "/technical/dictionaries"):
            response = await async_client.get(BASE + suffix, headers=headers)
            assert response.status_code == 403, response.text
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)
    assert not any(column in sql for sql in statements for column in PRIVATE)


@pytest.mark.asyncio
async def test_actual_boolean_cas_and_extra_patient_or_model_arguments_never_write_source_or_audit(db_session, variable_dictionary_case, async_client, auth_headers, mounted_variable_router):
    case, _, _, request = variable_dictionary_case
    made = create_dictionary(db_session, case["admin_user"], request)
    headers = auth_headers(case["super_admin_user"].username)
    before = {model: db_session.query(model).count() for model in (AIResearchVariableDictionary, AIResearchVariableBatch, AIAuditEvent)}
    invalid = [
        ("/dictionaries", {**request, "patient_id": 1}),
        ("/dictionaries/" + made["dictionary_id"] + "/review", {**technical_review(), "expected_revision": True}),
        ("/dictionaries/" + made["dictionary_id"] + "/review", {**technical_review(), "model": "not-an-authority"}),
    ]
    for suffix, body in invalid:
        response = await async_client.post(BASE + suffix, headers=headers, json=body)
        assert response.status_code == 422, response.text
    assert {model: db_session.query(model).count() for model in before} == before


@pytest.mark.asyncio
async def test_actual_large_batch_source_and_snapshot_each_fit_8m_while_old_combined_packet_exceeds_it(
    db_session, variable_capture_case, async_client, auth_headers, mounted_variable_router, tmp_path
):
    case, _, request, _, _ = variable_capture_case
    literal = "原" * 19000 + "\ufeff\r\n🧪否定"
    for _ in range(80):
        db_session.add(
            MedicalRecord(
                medical_record_id=str(uuid.uuid4()),
                patient_id=request["patient_ids"][0],
                doctor_id=case["doctor"].doctor_id,
                consultation_time=dt.datetime(2026, 10, 5),
                symptom=literal,
                result=None,
                status=0,
            )
        )
    db_session.commit()
    made = create_batch(db_session, case["admin_user"], {**request, "basis_note": BASIS})
    made = review_batch(db_session, case["super_admin_user"], made["batch_id"], technical_review())
    combined_bytes = len(canonical_json(made).encode("utf-8"))
    assert made["eligible"] is True and combined_bytes > MAX_BYTES
    sizes = {"actual_published_combined_internal_packet_bytes": combined_bytes, "parts": {}}
    headers = auth_headers(case["admin_user"].username)
    for part in ("source", "snapshot"):
        response = await async_client.get(BASE + "/batches/" + made["batch_id"] + "/parts/" + part, headers=headers)
        assert response.status_code == 200 and len(response.content) <= MAX_BYTES, (part, response.status_code, len(response.content))
        value = response.json()["data"]["value"]
        assert response.json()["data"]["current_validation"]["eligible"] is True
        assert hash_content(value if part == "source" else value["snapshot"]) == made["projection_hash" if part == "source" else "content_hash"]
        import hashlib

        sizes["parts"][part] = {"whole_http_response_bytes": len(response.content), "sha256": hashlib.sha256(response.content).hexdigest()}
    import json

    (tmp_path / "actual-large-variable-source-capacity.json").write_text(json.dumps(sizes, ensure_ascii=False, indent=2) + "\n")


@pytest.mark.parametrize("technical,change", [(False, "role"), (False, "epoch"), (True, "role"), (True, "epoch")])
def test_loaded_original_role_or_token_epoch_change_rejects_before_any_variable_body(db_session, variable_dictionary_case, technical, change):
    from app.ai.research_variables_views import source_metadata

    case, _, _, request = variable_dictionary_case
    made = create_dictionary(db_session, case["admin_user"], request)
    actor = case["super_admin_user"] if technical else case["admin_user"]
    actor_id, old_role, old_epoch = actor.user_id, actor.user_role, actor.token_invalid_before
    if change == "role":
        db_session.execute(text("UPDATE hoimsystem_users SET user_role='director' WHERE user_id=:id"), {"id": actor_id})
    else:
        db_session.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:id"), {"id": actor_id, "clock": "2099-01-01 00:00:00.000000"})
    assert actor.__dict__["user_role"] == old_role and actor.__dict__["token_invalid_before"] == old_epoch
    statements, record = observe(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            source_metadata(db_session, actor, "dictionary", made["dictionary_id"], technical=technical)
        assert error.value.status_code == 403
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)
        db_session.rollback()
    assert not any(column in sql for sql in statements for column in PRIVATE)


@pytest.mark.asyncio
async def test_unselected_scope_patient_withdrawal_also_blocks_short_summary_and_parts_even_super(db_session, research_case, async_client, auth_headers, mounted_variable_router):
    from app.ai.research_cohort_registry import create_registry_original
    from tests.test_ai_research_cohort_registry import acl_request, anchors, auth_request, permitted, publish
    from tests.test_ai_research_variables_contract import definition

    db, case = db_session, research_case
    case["scope_request"]["permitted_uses"] = ["research_variable_extraction"]
    case["scope_request"]["patient_ids"] = sorted([case["patient"].patient_id, case["patient2"].patient_id])
    scope, _, _ = permitted(db, case)
    for actor in (case["super_admin_user"], case["reviewer"]):
        publish(db, case, "acl", create_registry_original(db, case["super_admin_user"], "acl", {**acl_request(case, scope), "user_id": actor.user_id}))
    other = publish(
        db, case, "authorization", create_registry_original(db, case["super_admin_user"], "authorization", {**auth_request(case, scope), "patient_id": case["patient2"].patient_id}), manual=True
    )
    dictionary = create_dictionary(db, case["admin_user"], {**anchors(scope), "title": "明确全Scope范围的字典", "purpose": BASIS, "variables": [definition()], "basis_note": BASIS})
    review_dictionary(db, case["reviewer"], dictionary["dictionary_id"], definition_review(dictionary), definition=True)
    dictionary = review_dictionary(db, case["super_admin_user"], dictionary["dictionary_id"], technical_review())
    made = create_batch(
        db,
        case["admin_user"],
        {
            **anchors(scope),
            "variable_dictionary_id": dictionary["dictionary_id"],
            "dictionary_content_hash": dictionary["content_hash"],
            "dictionary_governance_hash": dictionary["governance_hash"],
            "patient_ids": [case["patient"].patient_id],
            "basis_note": BASIS,
        },
    )
    review_registry_original(db, case["super_admin_user"], "authorization", other["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    statements, record = observe(db)
    try:
        for actor in (case["admin_user"], case["super_admin_user"]):
            headers = auth_headers(actor.username)
            for suffix in ("", "/parts/source", "/parts/snapshot"):
                response = await async_client.get(BASE + "/batches/" + made["batch_id"] + suffix, headers=headers)
                assert response.status_code == 403, response.text
    finally:
        event.remove(db.bind, "before_cursor_execute", record)
    assert not any(column in sql for sql in statements for column in PRIVATE)


def test_wire_budget_counts_the_complete_envelope_and_rejects_whole_overflow():
    from app.routers.ai_research_variables_sources import reply

    overhead = len(reply("").body)
    assert len(reply("a" * (MAX_BYTES - overhead)).body) == MAX_BYTES
    with pytest.raises(HTTPException) as error:
        reply("a" * (MAX_BYTES - overhead + 1))
    assert error.value.status_code == 413
