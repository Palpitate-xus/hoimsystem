"""Native configuration paths consult current platform feature policies."""

import importlib
import json

import pytest
from fastapi import HTTPException

from app.access_control import effective_permissions
from app.access_models import AccessPolicy
from app.ai.catalog import FEATURE_BY_KEY
from app.models import User


@pytest.fixture(autouse=True)
def restore_actor_authority(db_session, seed_data):
    original_roles = db_session.query(User.user_id, User.user_role).all()
    yield
    db_session.rollback()
    db_session.query(AccessPolicy).delete(synchronize_session=False)
    for user_id, role in original_roles:
        db_session.query(User).filter(User.user_id == user_id).update({User.user_role: role}, synchronize_session=False)
    db_session.commit()


def revoke(db, user_id, change, feature=None):
    if change == "role":
        db.query(User).filter(User.user_id == user_id).update({User.user_role: "patient"}, synchronize_session=False)
    else:
        policy = db.get(AccessPolicy, ("user", str(user_id)))
        if policy is None:
            policy = AccessPolicy(kind="user", subject_key=str(user_id))
            db.add(policy)
        if change == "feature_revoked":
            allowed = effective_permissions(db, db.get(User, user_id), fresh=True)
            if feature is not None:
                allowed.discard("AI " + feature)
            else:
                allowed.clear()
            policy.allowed_json = json.dumps(sorted(allowed))
        else:
            policy.allowed_json = None
        policy.disabled = change == "disabled"
        policy.version = (policy.version or 0) + 1
    db.commit()


GUARDS = [
    ("runtime", "check_configuration", "clinical_training"),
    ("clinical_training_configuration", "configuration", "clinical_training"),
    ("operations_support_configuration", "configuration", "operations_support"),
    ("research_cohort_storage", "_configuration", "research_cohort"),
    ("research_variables_configuration", "current_configuration", "research_extraction"),
    ("deidentification_task_access", "role_configuration", "deidentification"),
    ("infection_cluster_profiles", "execution_configuration", "infection_cluster"),
    ("infection_cluster_management", "authorize_feature", "infection_cluster"),
]


@pytest.mark.parametrize("module,function,feature", GUARDS)
@pytest.mark.parametrize("change", ["feature_revoked", "disabled"])
def test_native_guard_rechecks_feature_policy_before_configuration_payload(db_session, seed_data, module, function, feature, change):
    user = seed_data["super_admin_user"]
    allowed = effective_permissions(db_session, user)
    assert "AI " + feature in allowed
    key = ("user", str(user.user_id))
    policy = db_session.get(AccessPolicy, key)
    if policy is None:
        policy = AccessPolicy(kind=key[0], subject_key=key[1])
        db_session.add(policy)
    policy.allowed_json = "[]" if change == "feature_revoked" else None
    policy.disabled = change == "disabled"
    policy.version = (policy.version or 0) + 1
    db_session.commit()
    guard = getattr(importlib.import_module("app.ai." + module), function)
    try:
        with pytest.raises(HTTPException) as denied:
            if function == "check_configuration":
                guard(db_session, user, FEATURE_BY_KEY[feature], None, False)
            elif function in {"role_configuration", "authorize_feature"}:
                guard(db_session, user)
            else:
                guard(db_session, user, preview=False)
        assert denied.value.status_code == 403
        assert ("停用" if change == "disabled" else "权限") in denied.value.detail
    finally:
        db_session.rollback()
        db_session.query(AccessPolicy).filter_by(kind=key[0], subject_key=key[1]).delete()
        db_session.commit()
