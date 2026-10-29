"""Permission writes must recheck authenticated subjects after locking reads."""

import datetime

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import delete, event, update
from sqlalchemy.orm import Session

from app.access_models import AccessPolicy, AccessPolicyAudit, AccessPolicyGuard
from app.models import User
from app.routers.permission_management import PolicyUpdate, update_access_policy


@pytest.fixture(autouse=True)
def clean_policy_state(db_session):
    db_session.query(AccessPolicyAudit).delete()
    db_session.query(AccessPolicy).delete()
    db_session.commit()
    yield
    db_session.rollback()
    db_session.query(AccessPolicyAudit).delete()
    db_session.query(AccessPolicy).delete()
    db_session.commit()


def _write(db, actor, kind, key):
    return update_access_policy(kind, key, PolicyUpdate(expected_version=0), BackgroundTasks(), current_user=actor, db=db)


@pytest.mark.parametrize("kind", ["role", "user"])
@pytest.mark.parametrize("change", ["epoch", "username", "demoted", "promoted"])
def test_changed_authenticated_actor_cannot_resume_policy_write(db_session, seed_data, kind, change):
    actor = seed_data["admin_user"]
    actor_id = actor.user_id
    key = "guide" if kind == "role" else str(seed_data["patient2_user"].user_id)
    # Load the authenticated identity before a second transaction changes it.
    original = (actor.username, actor.user_role, actor.token_invalid_before)
    updates = {
        "epoch": {"token_invalid_before": datetime.datetime.now(datetime.UTC).replace(tzinfo=None)},
        "username": {"username": f"moved-admin-{actor_id}"},
        "demoted": {"user_role": "doctor"},
        "promoted": {"user_role": "super_admin"},
    }[change]
    fired = []

    def change_before_lock(state):
        if state.is_select and state.statement._for_update_arg is not None and not fired:
            fired.append(True)
            with Session(bind=db_session.bind) as other:
                other.execute(update(User).where(User.user_id == actor_id).values(**updates))
                other.commit()

    event.listen(db_session, "do_orm_execute", change_before_lock)
    try:
        with pytest.raises(HTTPException) as denied:
            _write(db_session, actor, kind, key)
        assert denied.value.status_code == 403
        assert original == ("admin", "admin", None)
        assert fired == [True]
    finally:
        event.remove(db_session, "do_orm_execute", change_before_lock)
        db_session.rollback()
    assert db_session.get(AccessPolicy, (kind, key)) is None
    assert db_session.query(AccessPolicyAudit).count() == 0


@pytest.mark.parametrize("change", ["admin", "super_admin", "delete"])
def test_target_role_change_or_deletion_cannot_create_a_policy_for_stale_target(db_session, seed_data, change):
    actor = seed_data["admin_user"]
    target_id = seed_data["patient2_user"].user_id
    fired = []

    def change_before_lock(state):
        if state.is_select and state.statement._for_update_arg is not None and not fired:
            fired.append(True)
            with Session(bind=db_session.bind) as other:
                if change == "delete":
                    other.execute(delete(User).where(User.user_id == target_id))
                else:
                    other.execute(update(User).where(User.user_id == target_id).values(user_role=change))
                other.commit()

    event.listen(db_session, "do_orm_execute", change_before_lock)
    try:
        with pytest.raises(HTTPException) as denied:
            _write(db_session, actor, "user", str(target_id))
        assert denied.value.status_code == 409
        assert fired == [True]
    finally:
        event.remove(db_session, "do_orm_execute", change_before_lock)
        db_session.rollback()
    assert db_session.get(AccessPolicy, ("user", str(target_id))) is None
    assert db_session.query(AccessPolicyAudit).count() == 0


def test_role_revocation_before_guard_acquisition_is_rechecked(db_session, seed_data):
    actor = seed_data["admin_user"]
    fired = []

    def revoke():
        fired.append(True)
        with Session(bind=db_session.bind) as other:
            other.add(AccessPolicy(kind="role", subject_key="admin", allowed_json="[]"))
            other.commit()

    def before_lock(state):
        if state.is_select and state.statement._for_update_arg is not None and not fired:
            revoke()

    event.listen(db_session, "do_orm_execute", before_lock)
    try:
        with pytest.raises(HTTPException) as denied:
            _write(db_session, actor, "role", "guide")
        assert denied.value.status_code == 403
        assert fired == [True]
    finally:
        event.remove(db_session, "do_orm_execute", before_lock)
        db_session.rollback()
    assert db_session.get(AccessPolicy, ("role", "guide")) is None
    assert db_session.query(AccessPolicyAudit).count() == 0


def test_policy_guard_is_locked_before_administrator_and_target_accounts(db_session, seed_data):
    statements = []

    def observe(state):
        if state.is_select and state.statement._for_update_arg is not None:
            statements.append(str(state.statement.compile()))

    event.listen(db_session, "do_orm_execute", observe)
    try:
        response = _write(db_session, seed_data["admin_user"], "user", str(seed_data["patient2_user"].user_id))
        assert response["code"] == 200
    finally:
        event.remove(db_session, "do_orm_execute", observe)
    assert len(statements) >= 2
    assert "hoimsystem_access_policy_guard" in statements[0] and statements[0].endswith("FOR UPDATE")
    assert "ORDER BY hoimsystem_users.user_id FOR UPDATE" in statements[1]
    assert db_session.query(AccessPolicyAudit).count() == 1


def test_missing_policy_guard_fails_closed_without_a_configuration_write(db_session, seed_data):
    db_session.query(AccessPolicyGuard).delete()
    db_session.commit()
    try:
        with pytest.raises(HTTPException) as denied:
            _write(db_session, seed_data["admin_user"], "role", "guide")
        assert denied.value.status_code == 503
        db_session.rollback()
        assert db_session.get(AccessPolicy, ("role", "guide")) is None
        assert db_session.query(AccessPolicyAudit).count() == 0
    finally:
        db_session.rollback()
        db_session.add(AccessPolicyGuard(id=1))
        db_session.commit()
