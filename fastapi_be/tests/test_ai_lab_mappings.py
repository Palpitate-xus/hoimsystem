"""Real synthetic API/ORM publication, identity, revocation and audit contracts."""

import copy
import datetime
import importlib.util
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.ai.lab_mappings import create_mapping, mapping_current, mapping_detail, mapping_matches, matching_mappings
from app.ai.models import AIAuditEvent, AIFeatureConfig, AILabMapping


def draft_body(**changes):
    return {
        "source_namespace": "synthetic-lis-A/catalog-2026",
        "signature": {"code_system": "local", "code": "SYN-CREA", "unit": "mg/dL", "method": "synthetic-method-A", "specimen_type": "synthetic-serum", "value_kind": "numeric"},
        "analyte_key": "creatinine",
        "evidence_reference": "synthetic catalogue document v2026 page 1",
        "rationale": "Synthetic identity review only; no actual clinical terminology or risk-model validation.",
        **changes,
    }


def publish_body(**changes):
    return {
        "expected_revision": 1,
        "semantic_confirmed": True,
        "source_signature_confirmed": True,
        "review_note": "Synthetic reviewer compared code, namespace, unit, method and specimen; no clinical validation.",
        **changes,
    }


@pytest.fixture
def case(db_session, seed_data, auth_headers):
    db_session.query(AILabMapping).delete()
    db_session.commit()
    return {"seed": seed_data, "super": seed_data["super_admin_user"], "headers": auth_headers(seed_data["super_admin_user"].username)}


async def post_draft(client, case, body=None):
    response = await client.post("/api/ai/admin/lab-mappings", headers=case["headers"], json=body or draft_body())
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def publish(client, case, item, **changes):
    return await client.post(f"/api/ai/admin/lab-mappings/{item['mapping_id']}/publish", headers=case["headers"], json=publish_body(**changes))


@pytest.mark.asyncio
async def test_explicit_draft_publication_and_irreversible_revoke_do_not_enable_ai(async_client, db_session, case):
    before = [(item.feature_key, item.enabled, item.validation_status) for item in db_session.query(AIFeatureConfig)]
    item = await post_draft(async_client, case)
    assert item["status"] == "draft" and item["revision"] == 1 and item["published_at"] is None
    with pytest.raises(HTTPException):
        mapping_current(db_session, item["mapping_id"])
    original = db_session.get(AILabMapping, item["mapping_id"]).payload_json
    response = await publish(async_client, case, item)
    assert response.status_code == 200, response.text
    reviewed = response.json()["data"]
    assert reviewed["status"] == "published" and reviewed["revision"] == 2
    assert reviewed["content_hash"] == item["content_hash"]
    assert datetime.datetime.fromisoformat(reviewed["published_at"].replace("Z", "+00:00")) >= datetime.datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
    assert mapping_current(db_session, item["mapping_id"])["signature"] == item["signature"]
    assert (await publish(async_client, case, item)).status_code == 409
    assert (
        await async_client.post(f"/api/ai/admin/lab-mappings/{item['mapping_id']}/revoke", headers=case["headers"], json={"expected_revision": 1, "reason": "synthetic withdraw"})
    ).status_code == 409
    withdrawn = await async_client.post(
        f"/api/ai/admin/lab-mappings/{item['mapping_id']}/revoke", headers=case["headers"], json={"expected_revision": 2, "reason": "synthetic withdrawal after explicit review"}
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["data"]["revision"] == 3
    assert withdrawn.json()["data"]["content_hash"] == item["content_hash"]
    assert withdrawn.json()["data"]["governance_hash"] != reviewed["governance_hash"]
    assert db_session.get(AILabMapping, item["mapping_id"]).payload_json == original
    with pytest.raises(HTTPException):
        mapping_current(db_session, item["mapping_id"])
    assert mapping_current(db_session, item["mapping_id"], allow_revoked=True)["status"] == "revoked"
    assert (await publish(async_client, case, item, expected_revision=3)).status_code == 409
    assert [(item.feature_key, item.enabled, item.validation_status) for item in db_session.query(AIFeatureConfig)] == before
    actions = [row.action for row in db_session.query(AIAuditEvent).filter_by(target=item["mapping_id"])]
    assert actions == ["lab_mapping.create", "lab_mapping.publish", "lab_mapping.revoke"]
    for method in ("PUT", "PATCH", "DELETE"):
        assert (await async_client.request(method, f"/api/ai/admin/lab-mappings/{item['mapping_id']}", headers=case["headers"])).status_code == 405


@pytest.mark.asyncio
async def test_duplicate_published_identity_conflicts_then_new_explicit_version_can_publish(async_client, db_session, case):
    first, second = await post_draft(async_client, case), await post_draft(async_client, case)
    assert (await publish(async_client, case, first)).status_code == 200
    assert (await publish(async_client, case, second)).status_code == 409
    assert mapping_detail(db_session, second["mapping_id"])["status"] == "draft"
    await async_client.post(
        f"/api/ai/admin/lab-mappings/{first['mapping_id']}/revoke", headers=case["headers"], json={"expected_revision": 2, "reason": "synthetic replace by separately reviewed definition"}
    )
    assert (await publish(async_client, case, second)).status_code == 200
    assert mapping_current(db_session, first["mapping_id"], allow_revoked=True)["content_hash"] == first["content_hash"]


@pytest.mark.asyncio
async def test_unpublished_draft_can_withdraw_but_cannot_enter_source_history(async_client, db_session, case):
    item = await post_draft(async_client, case)
    result = await async_client.post(f"/api/ai/admin/lab-mappings/{item['mapping_id']}/revoke", headers=case["headers"], json={"expected_revision": 1, "reason": "synthetic draft not suitable"})
    assert result.status_code == 200 and result.json()["data"]["revision"] == 2
    assert result.json()["data"]["published_at"] is None
    with pytest.raises(HTTPException):
        mapping_current(db_session, item["mapping_id"], allow_revoked=True)


@pytest.mark.parametrize("role_key", ["admin_user", "director_user", "doctor_user", "nurse_user", "cashier_user", "pharmacist_user", "guide_user", "lab_tech_user", "registrar_user", "patient_user"])
@pytest.mark.asyncio
async def test_only_super_can_list_read_create_publish_or_revoke(role_key, async_client, db_session, case, auth_headers):
    item = await post_draft(async_client, case)
    headers = auth_headers(case["seed"][role_key].username)
    for method, path, body in [
        ("GET", "/options", None),
        ("GET", "", None),
        ("GET", "/" + item["mapping_id"], None),
        ("POST", "", draft_body()),
        ("POST", "/" + item["mapping_id"] + "/publish", publish_body()),
        ("POST", "/" + item["mapping_id"] + "/revoke", {"expected_revision": 1, "reason": "synthetic unauthorized"}),
    ]:
        response = await async_client.request(method, "/api/ai/admin/lab-mappings" + path, headers=headers, **({"json": body} if body is not None else {}))
        assert response.status_code == 403
    assert mapping_detail(db_session, item["mapping_id"])["status"] == "draft"


@pytest.mark.parametrize("field,value", [("code_system", ""), ("code", " "), ("unit", None), ("unit", " mg/dL"), ("method", ""), ("specimen_type", ""), ("value_kind", "unknown")])
@pytest.mark.asyncio
async def test_mapping_requires_exact_nonempty_source_signature(field, value, async_client, case):
    body = draft_body()
    body["signature"][field] = value
    response = await async_client.post("/api/ai/admin/lab-mappings", headers=case["headers"], json=body)
    assert response.status_code == 422


@pytest.mark.parametrize("field,value", [("semantic_confirmed", False), ("semantic_confirmed", 1), ("source_signature_confirmed", "true"), ("expected_revision", True), ("review_note", " " * 30)])
@pytest.mark.asyncio
async def test_publication_requires_two_literal_confirmations_and_meaningful_note(field, value, async_client, case):
    item = await post_draft(async_client, case)
    assert (await publish(async_client, case, item, **{field: value})).status_code == 422


@pytest.mark.asyncio
async def test_source_identity_keeps_namespace_case_method_specimen_unit_and_qualitative_distinct(async_client, db_session, case):
    body = draft_body()
    item = await post_draft(async_client, case, body)
    assert (await publish(async_client, case, item)).status_code == 200
    observation = SimpleNamespace(**{key: value for key, value in body["signature"].items() if key != "value_kind"}, value_num=Decimal("0.00000000"), value_text=None)
    assert [x["mapping_id"] for x in matching_mappings(db_session, observation, body["source_namespace"])] == [item["mapping_id"]]
    assert matching_mappings(db_session, observation, body["source_namespace"].lower()) == []
    for key, value in [("code", "syn-crea"), ("code_system", "LOCAL"), ("unit", "mg/dl"), ("method", "different method"), ("specimen_type", "different specimen")]:
        different = copy.copy(observation)
        setattr(different, key, value)
        assert not mapping_matches(mapping_current(db_session, item["mapping_id"]), different)
        assert matching_mappings(db_session, different) == []
    second = await post_draft(async_client, case, draft_body(source_namespace="synthetic-lis-B/another-catalogue"))
    assert (await publish(async_client, case, second)).status_code == 200
    assert len(matching_mappings(db_session, observation)) == 2  # Explicit namespace choice remains necessary.
    qualitative = draft_body(analyte_key="culture_result")
    qualitative["signature"].update(value_kind="qualitative", unit=None)
    third = await post_draft(async_client, case, qualitative)
    assert (await publish(async_client, case, third)).status_code == 200
    observation.value_num, observation.value_text, observation.unit = None, "<0.1 is original text, not a numeric zero", None
    assert [x["mapping_id"] for x in matching_mappings(db_session, observation)] == [third["mapping_id"]]


@pytest.mark.parametrize(
    "field,value", [("code", "changed-original-code"), ("payload_json", "{}"), ("content_hash", "0" * 64), ("identity_hash", "0" * 64), ("created_at", datetime.datetime(9999, 1, 1))]
)
def test_mutated_original_mapping_is_rejected_even_when_status_looks_valid(field, value, db_session, case):
    row = create_mapping(db_session, case["super"], draft_body())
    db_session.commit()
    setattr(row, field, value)
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        mapping_detail(db_session, row.mapping_id)
    assert caught.value.status_code == 409


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_publication_and_preserves_other_drafts(async_client, db_session, case, monkeypatch):
    from app.routers import ai_lab_mappings

    item = await post_draft(async_client, case)
    other = await post_draft(async_client, case)
    monkeypatch.setattr(ai_lab_mappings, "audit", lambda db, actor, *args: db.add(AIAuditEvent(actor_id=actor, action=None, target="synthetic-invalid-audit", detail_json="{}")))
    assert (await publish(async_client, case, item)).status_code == 409
    assert mapping_detail(db_session, item["mapping_id"])["status"] == "draft"
    assert mapping_detail(db_session, other["mapping_id"])["status"] == "draft"
    assert db_session.get(AILabMapping, item["mapping_id"]).published_key is None


def test_stale_super_object_cannot_create_mapping_after_role_loss(db_session, case):
    from app.models import User

    stale = SimpleNamespace(user_id=case["super"].user_id, user_role="super_admin")
    db_session.query(User).filter_by(user_id=stale.user_id).update({"user_role": "admin"})
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        create_mapping(db_session, stale, draft_body())
    assert caught.value.status_code == 403


def test_actual_mapping_migration_roundtrip_only_adds_mapping_table(tmp_path):
    spec = importlib.util.spec_from_file_location("synthetic_mapping_revision", Path(__file__).parents[1] / "alembic/versions/20261020_ai_lab_mappings.py")
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    engine = create_engine("sqlite:///" + str(tmp_path / "mapping-only.sqlite"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE hoimsystem_users(user_id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE synthetic_legacy_lab(id INTEGER PRIMARY KEY, raw_value TEXT, raw_clock TEXT)"))
        connection.execute(text("INSERT INTO synthetic_legacy_lab VALUES(1,'0.00000000','2001-02-03 04:05:06')"))
        before = connection.execute(text("SELECT * FROM synthetic_legacy_lab")).all()
        revision.op = Operations(MigrationContext.configure(connection))
        revision.upgrade()
        actual = inspect(connection)
        assert set(c["name"] for c in actual.get_columns(AILabMapping.__tablename__)) == set(AILabMapping.__table__.columns.keys())
        assert {i["name"] for i in actual.get_indexes(AILabMapping.__tablename__)} == {i.name for i in AILabMapping.__table__.indexes}
        assert {c["name"] for c in actual.get_check_constraints(AILabMapping.__tablename__)} == {c.name for c in AILabMapping.__table__.constraints if c.__class__.__name__ == "CheckConstraint"}
        revision.downgrade()
        assert actual.get_table_names() != []
        assert connection.execute(text("SELECT * FROM synthetic_legacy_lab")).all() == before
        assert AILabMapping.__tablename__ not in inspect(connection).get_table_names()
        revision.upgrade()
        assert connection.execute(text("SELECT * FROM synthetic_legacy_lab")).all() == before
    ddl = str(CreateTable(AILabMapping.__table__).compile(dialect=mysql.dialect()))
    for field in ("created_at", "published_at", "revoked_at"):
        assert f"{field} DATETIME(6)" in ddl
    assert "UNIQUE (published_key)" in ddl
    engine.dispose()
