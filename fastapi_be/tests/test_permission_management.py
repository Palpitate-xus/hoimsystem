"""Exercise persisted fine-grained policies through the actual authenticated API."""

import json

import pytest

from app.access_control import base_permissions
from app.access_models import AccessPolicy, AccessPolicyAudit
from app.models import MedicalRecord


@pytest.fixture(autouse=True)
def clean_policies(db_session):
    db_session.query(AccessPolicyAudit).delete()
    db_session.query(AccessPolicy).delete()
    db_session.commit()
    yield
    db_session.rollback()
    db_session.query(AccessPolicyAudit).delete()
    db_session.query(AccessPolicy).delete()
    db_session.commit()


async def write(client, headers, kind, key, permissions, version=0, **extra):
    return await client.put(f"/api/access/policies/{kind}/{key}", headers=headers, json={"expected_version": version, "allowed_permissions": permissions, **extra})


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/access/catalog", "/api/access/policies/role/doctor", "/api/access/audit"])
async def test_non_admin_cannot_read_configuration(async_client, seed_data, auth_headers, path):
    response = await async_client.get(path, headers=auth_headers(seed_data["doctor_user"].username))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_catalog_has_exact_methods_templates_fields_ai_and_11_roles(async_client, seed_data, auth_headers):
    response = await async_client.get("/api/access/catalog", headers=auth_headers(seed_data["super_admin_user"].username))
    assert response.status_code == 200
    data = response.json()["data"]
    items = {p["code"]: p for p in data["permissions"]}
    assert len(data["roles"]) == 11
    assert "PUT /api/access/policies/{kind}/{key}" in items
    assert "FIELD patient_list.identity" in items
    assert sum(p["method"] == "AI" for p in data["permissions"]) == 80
    assert not next(r for r in data["roles"] if r["key"] == "super_admin")["manageable"]


@pytest.mark.asyncio
async def test_role_read_allowed_write_denied_without_losing_session(async_client, seed_data, auth_headers, db_session):
    admin = auth_headers(seed_data["super_admin_user"].username)
    doctor = auth_headers(seed_data["doctor_user"].username)
    count = db_session.query(MedicalRecord).count()
    saved = await write(async_client, admin, "role", "doctor", ["GET /api/medicalRecord/getList"])
    assert saved.status_code == 200, saved.text
    assert (await async_client.get("/api/medicalRecord/getList", headers=doctor)).status_code == 200
    denied = await async_client.post("/api/medicalRecord/create", headers=doctor, json={})
    assert denied.status_code == 403
    assert db_session.query(MedicalRecord).count() == count
    info = await async_client.post("/api/userInfo", json={"accesstoken": doctor["accesstoken"]})
    assert info.status_code == 200
    assert info.json()["data"]["authorization"]["permission_codes"] == ["GET /api/medicalRecord/getList"]
    assert (await async_client.get("/api/access/me", headers=doctor)).status_code == 200


@pytest.mark.asyncio
async def test_user_restrictions_intersect_role_and_cannot_restore_a_denied_role_operation(async_client, seed_data, auth_headers):
    actor = auth_headers(seed_data["super_admin_user"].username)
    uid = seed_data["doctor_user"].user_id
    assert (await write(async_client, actor, "role", "doctor", ["GET /api/medicalRecord/getList"])).status_code == 200
    response = await write(async_client, actor, "user", str(uid), ["POST /api/medicalRecord/create"])
    assert response.status_code == 422
    response = await write(async_client, actor, "user", str(uid), [])
    assert response.status_code == 200
    headers = auth_headers(seed_data["doctor_user"].username)
    assert (await async_client.get("/api/medicalRecord/getList", headers=headers)).status_code == 403
    response = await write(async_client, actor, "user", str(uid), None, version=1)
    assert response.status_code == 200
    assert (await async_client.get("/api/medicalRecord/getList", headers=headers)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,key", [("role", "admin"), ("role", "super_admin")])
async def test_ordinary_admin_cannot_change_administrator_policies(async_client, seed_data, auth_headers, kind, key):
    response = await write(async_client, auth_headers(seed_data["admin_user"].username), kind, key, [])
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_configure_staff_but_not_admin_accounts(async_client, seed_data, auth_headers):
    actor = auth_headers(seed_data["admin_user"].username)
    assert (await write(async_client, actor, "role", "nurse", [])).status_code == 200
    for role in ("admin_user", "super_admin_user"):
        response = await write(async_client, actor, "user", str(seed_data[role].user_id), [], disabled=True)
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_grant_outside_business_qualification_or_unknown_code_is_rejected(async_client, seed_data, auth_headers, db_session):
    actor = auth_headers(seed_data["super_admin_user"].username)
    for grant in ["POST /api/user/delete", "GET /api/not-real"]:
        response = await write(async_client, actor, "role", "patient", [grant])
        assert response.status_code == 422
    assert db_session.query(AccessPolicy).count() == 0
    assert db_session.query(AccessPolicyAudit).count() == 0


@pytest.mark.asyncio
async def test_optimistic_version_conflict_never_overwrites_or_adds_audit(async_client, seed_data, auth_headers, db_session):
    actor = auth_headers(seed_data["super_admin_user"].username)
    first = await write(async_client, actor, "role", "doctor", [])
    assert first.status_code == 200
    conflict = await write(async_client, actor, "role", "doctor", None)
    assert conflict.status_code == 409
    conflict = await write(async_client, actor, "role", "doctor", None, version=9)
    assert conflict.status_code == 409
    policy = db_session.get(AccessPolicy, ("role", "doctor"))
    db_session.refresh(policy)
    assert policy.version == 1 and json.loads(policy.allowed_json) == []
    assert db_session.query(AccessPolicyAudit).count() == 1
    assert (await write(async_client, actor, "role", "doctor", None, version=1)).status_code == 200


@pytest.mark.asyncio
async def test_live_request_reads_updated_policy_even_with_old_token(async_client, seed_data, auth_headers):
    actor = auth_headers(seed_data["super_admin_user"].username)
    target = auth_headers(seed_data["doctor_user"].username)
    assert (await async_client.get("/api/medicalRecord/getList", headers=target)).status_code == 200
    assert (await write(async_client, actor, "role", "doctor", [])).status_code == 200
    assert (await async_client.get("/api/medicalRecord/getList", headers=target)).status_code == 403
    assert (await write(async_client, actor, "role", "doctor", None, version=1)).status_code == 200
    assert (await async_client.get("/api/medicalRecord/getList", headers=target)).status_code == 200


@pytest.mark.asyncio
async def test_patient_field_permissions_mask_and_withhold_selected_fields(async_client, seed_data, auth_headers):
    actor = auth_headers(seed_data["super_admin_user"].username)
    permissions = sorted(base_permissions("doctor") - {"FIELD patient_list.identity", "FIELD patient_list.address", "FIELD patient_list.allergy"})
    assert (await write(async_client, actor, "role", "doctor", permissions)).status_code == 200
    response = await async_client.get("/api/patientManagement/getList", headers=auth_headers(seed_data["doctor_user"].username))
    assert response.status_code == 200
    for patient in response.json()["data"]:
        assert "*" in patient["identity"]
        assert patient["address"] == "" and patient["allergy_history"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["01", "0", "-1", "999999999999999999999999"])
async def test_noncanonical_user_keys_cannot_write_unenforced_policies(async_client, seed_data, auth_headers, key):
    response = await write(async_client, auth_headers(seed_data["super_admin_user"].username), "user", key, [])
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_corrupt_persisted_policy_fails_closed(async_client, seed_data, auth_headers, db_session):
    db_session.add(AccessPolicy(kind="role", subject_key="doctor", version=1, allowed_json='{"allow":"everything"}', data_scope="existing", disabled=False))
    db_session.commit()
    response = await async_client.get("/api/medicalRecord/getList", headers=auth_headers(seed_data["doctor_user"].username))
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_policy_audit_is_paginated_and_records_changed_subject(async_client, seed_data, auth_headers):
    actor = auth_headers(seed_data["super_admin_user"].username)
    assert (await write(async_client, actor, "role", "doctor", [])).status_code == 200
    response = await async_client.get("/api/access/audit?page=1&page_size=1", headers=actor)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1 and data["list"][0]["subject"] == "role:doctor"
    detail = json.loads(data["list"][0]["detail"])
    assert detail["before"]["allowed_permissions"] is None and detail["after"]["allowed_permissions"] == []
