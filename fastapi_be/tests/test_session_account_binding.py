"""JWT sessions belong to one immutable account, including reused identifiers."""

import datetime
import importlib.util
import re
import uuid
from pathlib import Path

import jwt
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app import database
from app.config import settings
from app.dependencies import resolve_access_token
from app.models import User
from app.routers.user import create_access_token


@pytest.fixture
def bound_account(db_session, seed_data):
    account = User(username="bound-" + uuid.uuid4().hex[:12], password=seed_data["patient_user"].password, user_role="patient")
    db_session.add(account)
    db_session.commit()
    return account


def _payload(account):
    return jwt.decode(create_access_token(account.username, user=account), settings.SECRET_KEY, algorithms=["HS256"])


@pytest.mark.asyncio
@pytest.mark.parametrize("reuse_id", [False, True])
async def test_deleted_and_recreated_username_cannot_reuse_old_session(async_client, db_session, bound_account, reuse_id):
    original_id, username, original_subject = bound_account.user_id, bound_account.username, bound_account.auth_subject
    original_token = create_access_token(username, user=bound_account)
    password_hash = bound_account.password
    db_session.delete(bound_account)
    db_session.commit()
    replacement = User(user_id=original_id if reuse_id else original_id + 100, username=username, password=password_hash, user_role="doctor")
    db_session.add(replacement)
    db_session.commit()
    assert replacement.auth_subject != original_subject
    old_session = await async_client.post("/api/userInfo", json={"accesstoken": original_token})
    assert old_session.status_code == 401
    login = await async_client.post("/api/login", json={"username": username, "password": "123456"})
    assert login.status_code == 200
    new_session = await async_client.post("/api/userInfo", json={"accesstoken": login.json()["data"]["accesstoken"]})
    assert new_session.status_code == 200
    assert new_session.json()["data"]["permissions"] == ["doctor"]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["exp", "sub", "iat", "uid", "sid"])
async def test_every_bound_identity_claim_is_required(async_client, bound_account, missing):
    payload = _payload(bound_account)
    del payload[missing]
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    response = await async_client.post("/api/userInfo", json={"accesstoken": token})
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("claim,value", [
    ("uid", True), ("uid", False), ("uid", 0), ("uid", -1), ("uid", 2**31), ("uid", "1"), ("uid", 1.0), ("uid", None),
    ("sid", ""), ("sid", None), ("sid", True), ("sid", "F" * 32), ("sid", "f" * 31), ("sid", "f" * 32),
    ("iat", True), ("iat", None), ("iat", "1"), ("iat", -1), ("iat", float("nan")), ("iat", float("inf")), ("iat", float("-inf")),
    ("exp", True), ("exp", "9999999999"), ("exp", float("nan")), ("exp", float("inf")),
])
async def test_invalid_binding_and_clock_claims_are_rejected(async_client, bound_account, claim, value):
    payload = _payload(bound_account)
    payload[claim] = value
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    response = await async_client.post("/api/userInfo", json={"accesstoken": token})
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["other_uid", "other_subject", "other_username", "future_iat", "wrong_key", "unsigned"])
async def test_claims_cannot_be_mixed_between_accounts_or_signatures(async_client, bound_account, seed_data, change):
    payload = _payload(bound_account)
    key, algorithm = settings.SECRET_KEY, "HS256"
    other = seed_data["super_admin_user"]
    if change == "other_uid":
        payload["uid"] = other.user_id
    elif change == "other_subject":
        payload["sid"] = other.auth_subject
    elif change == "other_username":
        payload["sub"] = other.username
    elif change == "future_iat":
        payload["iat"] = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)).timestamp()
    elif change == "wrong_key":
        key = "untrusted-key-that-cannot-sign-this-session"
    else:
        key, algorithm = "", "none"
    token = jwt.encode(payload, key, algorithm=algorithm)
    response = await async_client.post("/api/userInfo", json={"accesstoken": token})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_legacy_username_only_token_requires_new_login(async_client, bound_account):
    token = jwt.encode({"sub": bound_account.username, "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)}, settings.SECRET_KEY, algorithm="HS256")
    response = await async_client.post("/api/userInfo", json={"accesstoken": token})
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["resetPassword", "updateRole"])
async def test_bound_sessions_still_obey_password_and_role_revocation(async_client, bound_account, seed_data, auth_headers, operation):
    old_token = create_access_token(bound_account.username, user=bound_account)
    payload = {"user_id": bound_account.user_id, "new_password": "rebound123", "user_role": "doctor"}
    updated = await async_client.post(f"/api/user/{operation}", headers=auth_headers(seed_data["super_admin_user"].username), json=payload)
    assert updated.status_code == 200
    assert (await async_client.post("/api/userInfo", json={"accesstoken": old_token})).status_code == 401
    password = "rebound123" if operation == "resetPassword" else "123456"
    login = await async_client.post("/api/login", json={"username": bound_account.username, "password": password})
    assert login.status_code == 200
    assert (await async_client.post("/api/userInfo", json={"accesstoken": login.json()["data"]["accesstoken"]})).status_code == 200


@pytest.mark.asyncio
async def test_disabled_account_cannot_resume_old_bound_session_after_reenable(async_client, bound_account, seed_data, auth_headers):
    old_token = create_access_token(bound_account.username, user=bound_account)
    path = f"/api/access/policies/user/{bound_account.user_id}"
    headers = auth_headers(seed_data["super_admin_user"].username)
    assert (await async_client.put(path, headers=headers, json={"expected_version": 0, "disabled": True})).status_code == 200
    assert (await async_client.post("/api/userInfo", json={"accesstoken": old_token})).status_code == 401
    assert (await async_client.post("/api/login", json={"username": bound_account.username, "password": "123456"})).status_code == 403
    assert (await async_client.put(path, headers=headers, json={"expected_version": 1, "disabled": False})).status_code == 200
    assert (await async_client.post("/api/userInfo", json={"accesstoken": old_token})).status_code == 401
    login = await async_client.post("/api/login", json={"username": bound_account.username, "password": "123456"})
    assert login.status_code == 200
    assert (await async_client.post("/api/userInfo", json={"accesstoken": login.json()["data"]["accesstoken"]})).status_code == 200


def test_subject_is_unique_and_immutable_for_persisted_account(db_session, bound_account):
    original = bound_account.auth_subject
    assert re.fullmatch(r"[0-9a-f]{32}", original)
    with pytest.raises(ValueError):
        bound_account.auth_subject = uuid.uuid4().hex
    db_session.rollback()
    assert bound_account.auth_subject == original
    duplicate = User(username="duplicate-" + uuid.uuid4().hex[:9], auth_subject=original)
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_production_issuer_uses_current_user_without_another_session(bound_account, monkeypatch):
    username, identifier, subject = bound_account.username, bound_account.user_id, bound_account.auth_subject

    def forbidden_session():
        raise AssertionError("Current-user issuance must not open another session")

    monkeypatch.setattr(database, "SessionLocal", forbidden_session)
    payload = jwt.decode(create_access_token(username, user=bound_account), settings.SECRET_KEY, algorithms=["HS256"])
    assert payload["uid"] == identifier and payload["sid"] == subject
    assert isinstance(payload["iat"], float)


def test_username_only_test_helper_signs_real_binding_and_unknown_user_remains_invalid(db_session, bound_account):
    valid = create_access_token(bound_account.username)
    assert resolve_access_token(valid, db_session).user_id == bound_account.user_id
    unknown = create_access_token("missing-" + uuid.uuid4().hex[:10])
    with pytest.raises(HTTPException) as denied:
        resolve_access_token(unknown, db_session)
    assert denied.value.status_code == 401


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261029_session_account_binding.py"
    spec = importlib.util.spec_from_file_location("session_binding_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_backfills_unique_subjects_and_preserves_users_on_sqlite():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    users = sa.Table("hoimsystem_users", metadata, sa.Column("user_id", sa.Integer(), primary_key=True), sa.Column("username", sa.String(20)))
    metadata.create_all(engine)
    module = _migration()
    with engine.begin() as connection:
        connection.execute(users.insert(), [{"user_id": index, "username": f"legacy{index}"} for index in range(1, 1003)])
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.upgrade()
        rows = connection.execute(sa.text("SELECT user_id,username,auth_subject FROM hoimsystem_users")).all()
        assert len(rows) == 1002
        assert len({row.auth_subject for row in rows}) == 1002
        assert all(re.fullmatch(r"[0-9a-f]{32}", row.auth_subject) for row in rows)
        inspector = sa.inspect(connection)
        assert not next(column for column in inspector.get_columns("hoimsystem_users") if column["name"] == "auth_subject")["nullable"]
        assert any(index["name"] == "uq_users_auth_subject" and index["unique"] for index in inspector.get_indexes("hoimsystem_users"))
        with Operations.context(MigrationContext.configure(connection)):
            module.downgrade()
        assert "auth_subject" not in {column["name"] for column in sa.inspect(connection).get_columns("hoimsystem_users")}
        assert connection.scalar(sa.select(sa.func.count()).select_from(users)) == 1002
    engine.dispose()
