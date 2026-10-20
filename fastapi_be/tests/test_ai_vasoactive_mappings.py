"""Actual synthetic catalog identities, Super-only drafts and atomic governance."""

import json
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app import inpatient_support_common as common
from app import inpatient_vasoactive as vaso
from app.ai.models import AIAuditEvent
from app.database import get_db
from app.inpatient_vasoactive_models import AIVasoactiveDrugMapping, InpatientVasoactiveSource
from app.models import Pharmaceutical
from app.routers import ai_vasoactive_mappings as routes
from tests.test_ai_observation_windows import observation_case as observation_case

NOTE = "合成审核明确核对实际原药品身份、活性成分及原量单位语义；仅为工程测试，不证明临床映射或模型有效性。"


@pytest.fixture
def vaso_case(db_session, observation_case, monkeypatch):
    case = observation_case
    db_session.query(InpatientVasoactiveSource).delete()
    db_session.query(AIVasoactiveDrugMapping).delete()
    drug = Pharmaceutical(name="合成原药" + uuid.uuid4().hex[:8], barcode="synthetic-vaso-" + uuid.uuid4().hex, stock=0, price=0, status=0)
    db_session.add(drug)
    db_session.commit()
    case["drug"] = drug
    for module in (vaso, routes, common):
        monkeypatch.setattr(module, "utcnow", lambda: case["now"])
    return case


def mapping_body(db, case, **changes):
    identity = vaso.original_drug_identity(db, case["drug"].pharmaceutical_id)
    return {
        "name": "合成血管活性原药物映射",
        "source_namespace": "synthetic-original-drug-catalog",
        "pharmaceutical_id": case["drug"].pharmaceutical_id,
        "expected_original_drug_identity_hash": vaso.hash_content(identity),
        "drug_key": "norepinephrine",
        "active_moiety_basis": "unknown",
        "allowed_rate_units": ["ug/kg/min", "ug/min", "mg/h", "mL/h"],
        "evidence_reference": "Synthetic actual catalog identity and unit review",
        "rationale": NOTE,
        **changes,
    }


def publish_body(revision=1):
    return {"expected_revision": revision, "original_identity_confirmed": True, "drug_semantics_confirmed": True, "rate_units_confirmed": True, "review_note": NOTE}


def published_mapping(db, case, **changes):
    row = vaso.create_mapping(db, case["seed"]["super_admin_user"], mapping_body(db, case, **changes))
    db.commit()
    routes.publish_mapping(row.mapping_id, routes.MappingPublish(**publish_body()), db, case["seed"]["super_admin_user"])
    return db.get(AIVasoactiveDrugMapping, row.mapping_id)


@pytest_asyncio.fixture
async def mapping_client(db_session):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic-vaso-mapping") as client:
        yield client


@pytest.mark.asyncio
async def test_actual_mapping_options_draft_publish_and_revoke_preserve_identity_without_stock_or_default_classification(mapping_client, db_session, vaso_case, auth_headers):
    case = vaso_case
    headers = auth_headers(case["seed"]["super_admin_user"].username)
    response = await mapping_client.get("/api/ai/admin/vasoactive-drug-mappings/options", headers=headers, params={"keyword": case["drug"].name})
    assert response.status_code == 200, response.text
    options = response.json()["data"]
    assert options["clinical_mapping_seeded"] is False
    original = options["pharmaceuticals"]["items"][0]
    assert original == {
        **vaso.original_drug_identity(db_session, case["drug"].pharmaceutical_id),
        "original_drug_identity_hash": mapping_body(db_session, case)["expected_original_drug_identity_hash"],
    }
    assert db_session.query(AIVasoactiveDrugMapping).count() == 0
    created = await mapping_client.post("/api/ai/admin/vasoactive-drug-mappings", headers=headers, json=mapping_body(db_session, case))
    assert created.status_code == 200, created.text
    draft = created.json()["data"]
    assert draft["status"] == "draft" and draft["revision"] == 1 and not draft["eligible"]
    assert draft["original_identity_current"] and draft["original_drug_identity"] == vaso.original_drug_identity(db_session, case["drug"].pharmaceutical_id)
    assert draft["active_moiety_basis"] == "unknown" and draft["allowed_rate_units"] == ["ug/kg/min", "ug/min", "mg/h", "mL/h"]
    assert not {"stock", "price"} & draft["original_drug_identity"].keys()
    identifier = draft["mapping_id"]
    published = await mapping_client.post(f"/api/ai/admin/vasoactive-drug-mappings/{identifier}/publish", headers=headers, json=publish_body())
    assert published.status_code == 200, published.text
    current = published.json()["data"]
    assert current["eligible"] and current["revision"] == 2 and current["content_hash"] == draft["content_hash"]
    assert current["governance_hash"] != draft["governance_hash"]
    detail = await mapping_client.get(f"/api/ai/admin/vasoactive-drug-mappings/{identifier}", headers=headers)
    assert detail.json()["data"] == current
    denied = await mapping_client.post(f"/api/ai/admin/vasoactive-drug-mappings/{identifier}/revoke", headers=headers, json={"expected_revision": 1, "reason": NOTE})
    assert denied.status_code == 409
    revoked = await mapping_client.post(f"/api/ai/admin/vasoactive-drug-mappings/{identifier}/revoke", headers=headers, json={"expected_revision": 2, "reason": NOTE})
    assert revoked.status_code == 200 and revoked.json()["data"]["revision"] == 3
    assert revoked.json()["data"]["content_hash"] == draft["content_hash"] and not revoked.json()["data"]["eligible"]
    assert db_session.query(AIAuditEvent).filter(AIAuditEvent.target == identifier, AIAuditEvent.action.like("vasoactive_drug_mapping.%")).count() == 3
    again = await mapping_client.post(f"/api/ai/admin/vasoactive-drug-mappings/{identifier}/publish", headers=headers, json=publish_body(3))
    assert again.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["doctor_user", "nurse_user", "admin_user", "director_user", "patient_user"])
async def test_actual_admin_endpoints_are_super_only(mapping_client, vaso_case, auth_headers, role):
    headers = auth_headers(vaso_case["seed"][role].username)
    for path in ("/ai/admin/vasoactive-drug-mappings", "/ai/admin/vasoactive-drug-mappings/options"):
        assert (await mapping_client.get("/api" + path, headers=headers)).status_code == 403


@pytest.mark.parametrize(
    "field,value",
    [
        ("pharmaceutical_id", True),
        ("pharmaceutical_id", "1"),
        ("pharmaceutical_id", 1.0),
        ("drug_key", "noradrenaline-guessed"),
        ("active_moiety_basis", "assumed-base"),
        ("allowed_rate_units", []),
        ("allowed_rate_units", ["mg/kg/min"]),
        ("allowed_rate_units", ["ug/min", "ug/min"]),
        ("source_namespace", " namespace"),
        ("rationale", " " * 30),
        ("expected_original_drug_identity_hash", "0"),
    ],
)
def test_mapping_input_is_strict_exact_and_has_no_inferred_semantics(db_session, vaso_case, field, value):
    with pytest.raises(ValidationError):
        vaso.MappingCreate.model_validate(mapping_body(db_session, vaso_case, **{field: value}))


@pytest.mark.parametrize(
    "field,value", [("original_identity_confirmed", 1), ("rate_units_confirmed", "true"), ("drug_semantics_confirmed", False), ("expected_revision", True), ("review_note", " " * 30)]
)
def test_publication_requires_each_actual_confirmation(field, value):
    with pytest.raises(ValidationError):
        routes.MappingPublish.model_validate({**publish_body(), field: value})


def test_identity_changes_block_publication_and_current_use_but_stock_price_do_not(db_session, vaso_case):
    case = vaso_case
    row = published_mapping(db_session, case)
    before = vaso.mapping_current(db_session, row.mapping_id)
    case["drug"].stock, case["drug"].price = 999, 88
    db_session.commit()
    assert vaso.mapping_current(db_session, row.mapping_id) == before
    case["drug"].barcode += "-changed"
    db_session.commit()
    audit = vaso.mapping_detail(db_session, row.mapping_id)
    assert not audit["eligible"] and not audit["original_identity_current"] and audit["content_hash"] == before["content_hash"]
    with pytest.raises(HTTPException) as error:
        vaso.mapping_current(db_session, row.mapping_id)
    assert error.value.status_code == 409
    routes.revoke_mapping(row.mapping_id, routes.MappingRevoke(expected_revision=2, reason=NOTE), db_session, case["seed"]["super_admin_user"])
    assert vaso.mapping_detail(db_session, row.mapping_id)["status"] == "revoked"


def test_one_published_mapping_per_actual_namespace_identity_and_draft_revocation(db_session, vaso_case):
    case = vaso_case
    first = published_mapping(db_session, case)
    duplicate = vaso.create_mapping(db_session, case["seed"]["super_admin_user"], mapping_body(db_session, case, drug_key="other"))
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        routes.publish_mapping(duplicate.mapping_id, routes.MappingPublish(**publish_body()), db_session, case["seed"]["super_admin_user"])
    assert error.value.status_code == 409
    assert vaso.mapping_detail(db_session, duplicate.mapping_id)["status"] == "draft"
    routes.revoke_mapping(duplicate.mapping_id, routes.MappingRevoke(expected_revision=1, reason=NOTE), db_session, case["seed"]["super_admin_user"])
    assert vaso.mapping_detail(db_session, duplicate.mapping_id)["revision"] == 2
    assert vaso.mapping_current(db_session, first.mapping_id)["drug_key"] == "norepinephrine"


@pytest.mark.parametrize("kind", ["body", "index", "governance"])
def test_changed_mapping_body_index_or_governance_cannot_be_read_as_authentic(db_session, vaso_case, kind):
    row = published_mapping(db_session, vaso_case)
    if kind == "body":
        payload = json.loads(row.payload_json)
        payload["rationale"] += " changed"
        row.payload_json = vaso.canonical_json(payload)
    elif kind == "index":
        row.drug_key = "other"
    else:
        row.revision = 77
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        vaso.mapping_detail(db_session, row.mapping_id)
    assert error.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "publish", "revoke"])
async def test_actual_audit_failure_rolls_back_mapping_mutation(mapping_client, db_session, vaso_case, auth_headers, monkeypatch, action):
    case = vaso_case
    headers = auth_headers(case["seed"]["super_admin_user"].username)
    row = None
    if action != "create":
        row = vaso.create_mapping(db_session, case["seed"]["super_admin_user"], mapping_body(db_session, case))
        db_session.commit()
        if action == "revoke":
            routes.publish_mapping(row.mapping_id, routes.MappingPublish(**publish_body()), db_session, case["seed"]["super_admin_user"])
    before = vaso.mapping_detail(db_session, row.mapping_id) if row else None

    def fail(*_):
        raise RuntimeError("synthetic actual audit insert failure")

    monkeypatch.setattr(routes, "audit", fail)
    path = "/api/ai/admin/vasoactive-drug-mappings" + (f"/{row.mapping_id}/{action}" if row else "")
    payload = mapping_body(db_session, case) if action == "create" else publish_body() if action == "publish" else {"expected_revision": 2, "reason": NOTE}
    with pytest.raises(RuntimeError, match="actual audit"):
        await mapping_client.post(path, headers=headers, json=payload)
    assert (vaso.mapping_detail(db_session, row.mapping_id) if row else None) == before
    assert db_session.query(AIVasoactiveDrugMapping).count() == (1 if row else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("key,value", [("page", "true"), ("page", "1.0"), ("page_size", "1.0"), ("page_size", "101")])
async def test_query_pagination_does_not_coerce_boolean_or_float(mapping_client, vaso_case, auth_headers, key, value):
    response = await mapping_client.get("/api/ai/admin/vasoactive-drug-mappings/options", headers=auth_headers(vaso_case["seed"]["super_admin_user"].username), params={key: value})
    assert response.status_code == 422
