"""Actual mounted main/JWT source governance, full literal bytes and boundaries."""

import pytest
from sqlalchemy import event

from app.ai import document_evidence_contract as d
from app.ai import drug_label_contract as c
from app.ai import drug_label_sources as s
from app.ai.drug_label_models import AIDrugLabelSource
from app.models import User
from tests.test_ai_drug_label_sources import NOTE, NOW, cas, create
from tests.test_ai_drug_label_sources import label_case as _label_case

label_case = _label_case
ROOT = "/api/ai/drug-label-sources"


def create_body(case):
    _, _, sku, original = case
    return dict(
        pharmaceutical_id=sku.pharmaceutical_id,
        expected_identity_hash=d.digest(s.identity(sku)),
        original=dict(original_id=original.snapshot.original_id, content_hash=original.content_hash, governance_hash=original.governance_hash),
        basis_note=NOTE,
    )


@pytest.mark.asyncio
async def test_actual_main_complete_release_self_signature_publication_revoke_and_audit(async_client, auth_headers, label_case):
    db, users, sku, original = label_case
    super_headers = auth_headers(users["super_admin_user"].username)
    pharm_headers = auth_headers(users["pharmacist_user"].username)
    response = await async_client.post(ROOT, json=create_body(label_case), headers=super_headers)
    assert response.status_code == 200, response.text
    value = c.SourceRecord.model_validate(response.json()["data"])
    binding = value.snapshot.source_binding_id
    assert value.snapshot.recorded_at == NOW
    assert value.snapshot.original.snapshot.text == original.snapshot.text
    assert "2026-10-21T12:00:00.123456Z" in value.snapshot.original.snapshot.text
    ordinary = await async_client.get(f"{ROOT}/{binding}", headers=pharm_headers)
    assert ordinary.status_code == 200
    assert ordinary.json()["data"]["snapshot"]["original"]["snapshot"]["text"] == original.snapshot.text
    assert (await async_client.get(f"/api/ai/admin/document-evidence/originals/{original.snapshot.original_id}", headers=pharm_headers)).status_code == 403
    response = await async_client.post(
        f"{ROOT}/{binding}/professional-review", headers=pharm_headers, json={**cas(value), "catalog_match_review": "confirmed", "provided_text_version_review": "confirmed", "basis_note": NOTE}
    )
    assert response.status_code == 200, response.text
    value = c.SourceRecord.model_validate(response.json()["data"])
    assert not value.eligible and value.professional_review.snapshot.signed_at == NOW
    prof = value.professional_review
    response = await async_client.post(
        f"{ROOT}/{binding}/review",
        headers=super_headers,
        json={
            **cas(value),
            "decision": "approve",
            "professional": {"professional_review_id": prof.snapshot.professional_review_id, "content_hash": prof.content_hash, "governance_hash": prof.governance_hash},
            "basis_note": NOTE,
        },
    )
    assert response.status_code == 200, response.text
    value = c.SourceRecord.model_validate(response.json()["data"])
    assert value.eligible and value.governance.reviewed_at == NOW
    statements = []

    def sql(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", sql)
    try:
        listing = await async_client.get(ROOT, params={"pharmaceutical_id": sku.pharmaceutical_id}, headers=pharm_headers)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", sql)
    assert listing.status_code == 200, listing.text
    row = next(row for row in listing.json()["data"]["items"] if row["source_binding_id"] == binding)
    assert row["detail_required"] and row["recorded_at"] == NOW
    assert not any("snapshot_json" in statement or "original_text" in statement for statement in statements)
    response = await async_client.post(f"{ROOT}/{binding}/professional-review/revoke", headers=pharm_headers, json={**cas(prof), "basis_note": "😀" * 1000})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["professional_review"]["governance"]["revoke_reason"] == "😀" * 1000
    assert (await async_client.get(f"{ROOT}/{binding}", headers=pharm_headers)).status_code == 409
    audit = await async_client.get(f"{ROOT}/{binding}", params={"audit_only": "true"}, headers=super_headers)
    assert audit.status_code == 200, audit.text
    value = c.SourceRecord.model_validate(audit.json()["data"])
    assert value.snapshot.original.snapshot.text == original.snapshot.text
    assert value.audit_only and not value.eligible and not value.can_revoke
    assert value.professional_review.governance.revoked_at == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin_user", "doctor_user", "director_user", "nurse_user", "patient_user"])
async def test_legacy_roles_cannot_access_source_catalog_or_release(async_client, auth_headers, label_case, role):
    _, users, _, _ = label_case
    if role not in users:
        actor = User(username="73" + role, user_role=role.removesuffix("_user"))
        label_case[0].add(actor)
        label_case[0].commit()
    else:
        actor = users[role]
    headers = auth_headers(actor.username)
    assert (await async_client.get(ROOT + "/options", headers=headers)).status_code == 403
    assert (await async_client.get(ROOT + "/catalog", headers=headers)).status_code == 403
    assert (await async_client.post(ROOT, headers=headers, json=create_body(label_case))).status_code == 403


@pytest.mark.asyncio
async def test_super_cannot_sign_and_pharmacist_cannot_technical_publish_or_release(async_client, auth_headers, label_case):
    _, users, _, _ = label_case
    value = create(label_case)
    sup = auth_headers(users["super_admin_user"].username)
    pharm = auth_headers(users["pharmacist_user"].username)
    assert (await async_client.post(ROOT, headers=pharm, json=create_body(label_case))).status_code == 403
    signature = {**cas(value), "catalog_match_review": "confirmed", "provided_text_version_review": "confirmed", "basis_note": NOTE}
    assert (await async_client.post(f"{ROOT}/{value.snapshot.source_binding_id}/professional-review", headers=sup, json=signature)).status_code == 403
    assert (
        await async_client.post(f"{ROOT}/{value.snapshot.source_binding_id}/review", headers=pharm, json={**cas(value), "decision": "reject", "professional": None, "basis_note": NOTE})
    ).status_code == 403


@pytest.mark.asyncio
async def test_actual_catalog_preserves_null_and_keyset_complete_flag(async_client, auth_headers, label_case):
    _, users, sku, _ = label_case
    headers = auth_headers(users["pharmacist_user"].username)
    response = await async_client.get(ROOT + "/catalog", params={"after_id": sku.pharmaceutical_id - 1, "page_size": 1}, headers=headers)
    assert response.status_code == 200, response.text
    first = response.json()["data"]["items"][0]
    assert first["identity"]["pharmaceutical_id"] == sku.pharmaceutical_id and first["identity"]["barcode"] is None
    assert first["identity_hash"] == d.digest(s.identity(sku))
    assert set(first["identity"]) == set(c.COMPARISON_FIELDS)
    assert (await async_client.get(ROOT, headers=headers)).status_code == 403
    options = (await async_client.get(ROOT + "/options", headers=headers)).json()["data"]
    assert options["professional_signer_user_id"] == users["pharmacist_user"].user_id
    assert options["can_professional_sign"] and options["licensure_verification"] == "not_provided"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":"\\ud800"}'])
async def test_bad_complete_json_rejected_without_echo_or_source_write(async_client, auth_headers, label_case, body):
    db, users, _, _ = label_case
    before = db.query(AIDrugLabelSource).count()
    response = await async_client.post(ROOT, headers={**auth_headers(users["super_admin_user"].username), "content-type": "application/json"}, content=body)
    assert response.status_code == 422 and "snapshot" not in response.text
    assert db.query(AIDrugLabelSource).count() == before


@pytest.mark.asyncio
async def test_no_auth_and_foreign_signer_payload_are_rejected(async_client, auth_headers, label_case):
    assert (await async_client.get(ROOT + "/options")).status_code == 401
    _, users, _, _ = label_case
    value = create(label_case)
    response = await async_client.post(
        f"{ROOT}/{value.snapshot.source_binding_id}/professional-review",
        headers=auth_headers(users["pharmacist_user"].username),
        json={**cas(value), "catalog_match_review": "confirmed", "provided_text_version_review": "confirmed", "basis_note": NOTE, "signer_user_id": users["super_admin_user"].user_id},
    )
    assert response.status_code == 422
