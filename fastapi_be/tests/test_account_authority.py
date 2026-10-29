"""Account administration must preserve administrator and session boundaries."""

import datetime
import uuid
from base64 import b64decode, b64encode

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import HTTPException
from sqlalchemy import event, update
from sqlalchemy.orm import Session

from app.access_models import AccessPolicy
from app.account_authority import lock_account_management
from app.config import settings
from app.models import Doctor, User
from app.routers.user import create_access_token
from app.security import hash_password, verify_password


@pytest.fixture
def spare_account(db_session):
    def create(role="patient"):
        user = User(username=f"account-{uuid.uuid4().hex[:10]}", password=hash_password("before123"), user_role=role)
        db_session.add(user)
        db_session.commit()
        return user

    return create


@pytest.mark.asyncio
@pytest.mark.parametrize("target_role", ["admin", "super_admin"])
@pytest.mark.parametrize("operation", ["resetPassword", "delete", "updateRole"])
async def test_admin_cannot_manage_other_administrator(
    async_client, seed_data, auth_headers, db_session, spare_account, target_role, operation
):
    target = spare_account(target_role)
    payload = {"user_id": target.user_id, "new_password": "changed123", "user_role": "doctor"}
    response = await async_client.post(
        f"/api/user/{operation}", headers=auth_headers(seed_data["admin_user"].username), json=payload
    )
    assert response.status_code == 403
    db_session.expire_all()
    unchanged = db_session.get(User, target.user_id)
    assert unchanged is not None
    assert unchanged.user_role == target_role
    assert verify_password("before123", unchanged.password)


@pytest.mark.asyncio
@pytest.mark.parametrize("new_role", ["admin", "super_admin"])
async def test_admin_cannot_create_another_administrator(async_client, seed_data, auth_headers, spare_account, new_role):
    target = spare_account()
    response = await async_client.post(
        "/api/user/updateRole",
        headers=auth_headers(seed_data["admin_user"].username),
        json={"user_id": target.user_id, "user_role": new_role},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "super_admin"])
@pytest.mark.parametrize("operation", ["delete", "updateRole"])
async def test_administrator_cannot_delete_self_or_change_own_role(async_client, seed_data, auth_headers, role, operation):
    actor = seed_data[f"{role}_user"]
    response = await async_client.post(
        f"/api/user/{operation}",
        headers=auth_headers(actor.username),
        json={"user_id": actor.user_id, "user_role": "patient"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("target_role", ["admin", "super_admin"])
async def test_super_admin_can_restore_administrator_password_and_revoke_old_token(
    async_client, seed_data, auth_headers, db_session, spare_account, target_role
):
    target = spare_account(target_role)
    old_token = create_access_token(target.username)
    response = await async_client.post(
        "/api/user/resetPassword",
        headers=auth_headers(seed_data["super_admin_user"].username),
        json={"user_id": target.user_id, "new_password": "restored123"},
    )
    assert response.status_code == 200
    assert "restored123" not in response.text
    db_session.refresh(target)
    assert target.token_invalid_before is not None
    assert verify_password("restored123", target.password)
    old_session = await async_client.post("/api/userInfo", json={"accesstoken": old_token})
    assert old_session.status_code == 401
    login = await async_client.post("/api/login", json={"username": target.username, "password": "restored123"})
    assert login.status_code == 200
    fresh_session = await async_client.post("/api/userInfo", json={"accesstoken": login.json()["data"]["accesstoken"]})
    assert fresh_session.status_code == 200


@pytest.mark.asyncio
async def test_super_admin_role_change_revokes_old_session(async_client, seed_data, auth_headers, spare_account):
    target = spare_account()
    old_token = create_access_token(target.username)
    response = await async_client.post(
        "/api/user/updateRole",
        headers=auth_headers(seed_data["super_admin_user"].username),
        json={"user_id": target.user_id, "user_role": "admin"},
    )
    assert response.status_code == 200
    old_session = await async_client.post("/api/userInfo", json={"accesstoken": old_token})
    assert old_session.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("target_role", ["admin", "super_admin"])
async def test_doctor_delete_cannot_bypass_protected_account_guard(
    async_client, seed_data, auth_headers, db_session, spare_account, target_role
):
    target = spare_account(target_role)
    doctor = Doctor(name="关联管理员", user_id=target.user_id, permission="doctor")
    db_session.add(doctor)
    db_session.commit()
    doctor_id, target_id = doctor.doctor_id, target.user_id
    response = await async_client.post(
        "/api/doctorManagement/delete",
        headers=auth_headers(seed_data["admin_user"].username),
        json={"doctor_id": doctor_id},
    )
    assert response.status_code == 403
    db_session.expire_all()
    assert db_session.get(Doctor, doctor_id) is not None
    assert db_session.get(User, target_id) is not None


@pytest.mark.asyncio
async def test_super_admin_can_delete_unreferenced_account(async_client, seed_data, auth_headers, db_session, spare_account):
    target = spare_account("admin")
    target_id = target.user_id
    response = await async_client.post(
        "/api/user/delete",
        headers=auth_headers(seed_data["super_admin_user"].username),
        json={"user_id": target_id},
    )
    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.get(User, target_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("token_kind", ["missing_exp", "missing_sub", "expired"])
async def test_body_token_entry_requires_standard_claims(async_client, seed_data, token_kind):
    payload = {"sub": seed_data["patient_user"].username}
    if token_kind == "missing_sub":
        payload = {"exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)}
    elif token_kind == "expired":
        payload["exp"] = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    response = await async_client.post("/api/userInfo", json={"accesstoken": token})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_body_token_entry_returns_effective_authorization_snapshot(async_client, seed_data):
    response = await async_client.post(
        "/api/userInfo", json={"accesstoken": create_access_token(seed_data["patient_user"].username)}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["permissions"] == ["patient"]
    assert data["username"] == seed_data["patient_user"].username
    assert data["avatar"] == ""
    assert "authorization" in data


@pytest.mark.asyncio
async def test_encrypted_login_upgrades_legacy_password_using_decrypted_value(async_client, db_session, spare_account):
    target = spare_account()
    target.password = "legacy123"
    db_session.commit()
    key_response = await async_client.get("/api/publicKey")
    key = serialization.load_der_public_key(b64decode(key_response.json()["data"]["publicKey"]))
    encrypted = "RSA1:" + b64encode(key.encrypt(b"legacy123", padding.PKCS1v15())).decode()
    first = await async_client.post("/api/login", json={"username": target.username, "password": encrypted})
    assert first.status_code == 200
    db_session.refresh(target)
    assert verify_password("legacy123", target.password)
    assert not verify_password(encrypted, target.password)
    again = await async_client.post("/api/login", json={"username": target.username, "password": "legacy123"})
    assert again.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["role", "user"])
async def test_disabled_policy_rejects_login_and_body_token(async_client, db_session, spare_account, kind):
    target = spare_account()
    old_token = create_access_token(target.username)
    policy = AccessPolicy(kind=kind, subject_key=target.user_role if kind == "role" else str(target.user_id), disabled=True)
    db_session.add(policy)
    db_session.commit()
    try:
        login = await async_client.post("/api/login", json={"username": target.username, "password": "before123"})
        assert login.status_code == 403
        assert "accesstoken" not in login.text
        user_info = await async_client.post("/api/userInfo", json={"accesstoken": old_token})
        assert user_info.status_code == 403
    finally:
        db_session.delete(policy)
        db_session.commit()


@pytest.mark.parametrize("current_role", ["doctor", "super_admin"])
def test_guard_rejects_stale_actor_role_before_identity_map_refresh(db_session, seed_data, spare_account, current_role):
    actor = seed_data["admin_user"]
    target = spare_account()
    authenticated_role = actor.user_role
    with Session(bind=db_session.bind) as other:
        other.execute(update(User).where(User.user_id == actor.user_id).values(user_role=current_role))
        other.commit()
    assert authenticated_role == "admin"
    with pytest.raises(HTTPException) as denied:
        lock_account_management(db_session, actor, target.user_id, operation="role", new_role="admin")
    assert denied.value.status_code == 403
    db_session.rollback()


def test_guard_rechecks_target_role_after_identity_map_was_loaded(db_session, seed_data, spare_account):
    target = spare_account()
    assert target.user_role == "patient"
    with Session(bind=db_session.bind) as other:
        other.execute(update(User).where(User.user_id == target.user_id).values(user_role="super_admin"))
        other.commit()
    with pytest.raises(HTTPException) as denied:
        lock_account_management(db_session, seed_data["admin_user"], target.user_id, operation="reset_password")
    assert denied.value.status_code == 403
    db_session.rollback()


def test_guard_uses_ordered_locking_current_read(db_session, seed_data, spare_account):
    target = spare_account()
    observed = []

    def inspect_query(execution):
        statement = execution.statement
        if execution.is_select and statement._for_update_arg is not None:
            observed.append(str(statement.compile()))

    event.listen(db_session, "do_orm_execute", inspect_query)
    try:
        actor, account = lock_account_management(db_session, seed_data["admin_user"], target.user_id, operation="reset_password")
        assert actor.user_role == "admin"
        assert account.user_id == target.user_id
    finally:
        event.remove(db_session, "do_orm_execute", inspect_query)
        db_session.rollback()
    assert len(observed) == 1
    assert "ORDER BY hoimsystem_users.user_id FOR UPDATE" in observed[0]
