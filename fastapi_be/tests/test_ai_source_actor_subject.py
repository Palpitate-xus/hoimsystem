"""Current source actor subject is checked before any domain/data authority."""

import importlib

import pytest
from fastapi import HTTPException

from tests.test_ai_admin_write_authority import change_subject, restore_subject, subject

GUARDS = [
    ("charge", "charge_reconciliation_write_guard", "current_charge_actor", {"allowed_roles": {"super_admin", "admin"}}),
    ("satisfaction", "satisfaction_write_guard", "current_actor", {"allowed_roles": {"super_admin", "admin"}}),
    ("document_and_change", "document_evidence_sources", "current_super", {}),
    ("drug_label", "drug_label_sources", "current_actor", {"allowed_roles": {"super_admin", "admin"}}),
    ("cohort_deidentification_variables", "research_cohort_write_guard", "current_actor", {"allowed_roles": {"super_admin", "admin"}}),
    ("operations", "operations_support_write_guard", "current_actor", {"allowed_roles": {"super_admin", "admin"}}),
    ("training", "clinical_training_write_guard", "current_actor", {"allowed_roles": {"super_admin", "admin"}}),
    ("rca", "rca_evidence_write_guard", "current_actor", {"allowed_roles": {"super_admin", "admin"}}),
    ("infection", "infection_cluster_write_guard", "lock_infection_write", {"allowed_roles": {"super_admin", "admin"}}),
]


@pytest.mark.parametrize("guard", GUARDS, ids=lambda g: g[0])
@pytest.mark.parametrize("axis", ["role", "epoch", "username"])
def test_current_original_subject(db_session, seed_data, guard, axis):
    actor = seed_data["super_admin_user"]
    original = subject(actor)
    change_subject(db_session, original, axis)
    call = getattr(importlib.import_module("app.ai." + guard[1]), guard[2])
    try:
        with pytest.raises(HTTPException) as caught:
            call(db_session, actor, **guard[3])
        assert caught.value.status_code == 403
    finally:
        db_session.rollback()
        restore_subject(db_session, original)


@pytest.mark.parametrize("guard", GUARDS, ids=lambda g: g[0])
@pytest.mark.parametrize("expired", [False, True], ids=["loaded", "expired-internal-identity"])
def test_current_subject_keeps_each_original_source_role_contract(db_session, seed_data, guard, expired):
    actor = seed_data["super_admin_user"]
    identifier = actor.user_id
    if expired:
        db_session.expire(actor)
    call = getattr(importlib.import_module("app.ai." + guard[1]), guard[2])
    result = call(db_session, actor, **guard[3])
    assert result.user_id == identifier and result.user_role == "super_admin"
