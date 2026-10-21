"""Actual synthetic SQL Case and current authorization, no model transport."""

import copy
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.ai import charge_reconciliation_context as context
from app.ai import charge_reconciliation_sources as sources
from app.ai.charge_reconciliation_models import AIChargeCaseSnapshot
from app.models import InpatientCharge, User
from tests.test_ai_charge_reconciliation_sources import NOTE, cas, published
from tests.test_ai_charge_reconciliation_sources import charge_case as _charge_case

charge_case = _charge_case


def selected(case, value):
    return {"charge_case_id": value["case_snapshot_id"], "question": "请核实原记录🙂\r\n保留问题。"}


def bundle(case, value, **overrides):
    return context.charge_context(
        case["db"], case["super_admin_user"], overrides.get("patient_id", case["patient"].patient_id), overrides.get("encounter_ref", case["admission"].admission_id), selected(case, value)
    )


def payload(expanded, values):
    return {"context": expanded, "input": values, "tools": {}, "evidence": [context.charge_evidence(expanded["charge_binding"])]}


def test_actual_case_short_binding_and_sole_public_outbound_projection(charge_case):
    case = charge_case
    value = published(case)
    original = copy.deepcopy(value)
    bound = bundle(case, value)
    assert bound.data["selected_sources"] == {"charge_case_id": value["case_snapshot_id"]}
    assert bound.department_ids == {case["department"].department_id}
    assert "snapshot" not in bound.data and "charge_source" not in bound.data
    expanded = context.expand_context(case["db"], bound.data, user=case["super_admin_user"], current=True)
    request = context.public_payload(payload(expanded, selected(case, value)))
    assert request == {"charge_source": value["public_source"], "source_projection_hash": value["projection_hash"], "question": selected(case, value)["question"]}
    encoded = json.dumps(request, ensure_ascii=False)
    for private in (
        case["patient"].name,
        case["patient"].identity,
        case["patient"].phone,
        case["admission"].admission_id,
        value["snapshot"]["identity_secret"],
        NOTE,
        "private-only-patient",
        "private-only-drug",
    ):
        assert private not in encoded
    assert len(request["charge_source"]["charges"]) == 65
    assert expanded["charge_case"]["can_review"] is False
    assert expanded["charge_case"]["can_revoke"] is False
    assert value == original


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"charge_case_id": None},
        {"charge_case_id": True},
        {"charge_case_id": "A" * 36},
        {"charge_case_id": "00000000-0000-0000-0000-000000000000", "coding_case_id": "foreign"},
        {"charge_case_id": "00000000-0000-0000-0000-000000000000", "patient_id": 1},
    ],
)
def test_selection_rejects_missing_noncanonical_and_mixed_business_inputs(values):
    with pytest.raises(HTTPException) as caught:
        context.selection(values)
    assert caught.value.status_code == 422


@pytest.mark.parametrize("question", [True, 1, [], {}, "x" * 2001, "\ud800"])
def test_question_is_exact_bounded_utf8_only(question):
    with pytest.raises(HTTPException) as caught:
        context.selection({"charge_case_id": "00000000-0000-0000-0000-000000000000", "question": question})
    assert caught.value.status_code == 422


@pytest.mark.parametrize("scope", [{"patient_id": True}, {"patient_id": 2147483647}, {"encounter_ref": None}, {"encounter_ref": "00000000-0000-0000-0000-000000000000"}])
def test_exact_patient_and_actual_admission_scope_required(charge_case, scope):
    value = published(charge_case)
    with pytest.raises(HTTPException) as caught:
        bundle(charge_case, value, **scope)
    assert caught.value.status_code == 403


@pytest.mark.parametrize("key", ["identity", "coding_binding", "patient", "other_original"])
def test_mixed_private_context_rejected_before_outbound(charge_case, key):
    case = charge_case
    value = published(case)
    bound = bundle(case, value)
    expanded = context.expand_context(case["db"], bound.data, user=case["super_admin_user"], current=True)
    expanded[key] = "synthetic private injected value"
    with pytest.raises(ValueError):
        context.public_payload(payload(expanded, selected(case, value)))
    with pytest.raises(HTTPException) as caught:
        context.expand_context(case["db"], {**bound.data, key: "foreign"}, user=case["super_admin_user"], current=True)
    assert caught.value.status_code == 409


def test_any_uncited_source_field_change_cannot_reuse_model_binding(charge_case):
    case = charge_case
    value = published(case)
    bound = bundle(case, value)
    expanded = context.expand_context(case["db"], bound.data, user=case["super_admin_user"], current=True)
    expanded["charge_source"]["charges"][0]["total_amount"] = "999.00"
    with pytest.raises(ValueError):
        context.public_payload(payload(expanded, selected(case, value)))


def test_current_changes_reject_execution_but_retain_complete_frozen_audit(charge_case):
    case, db = charge_case, charge_case["db"]
    value = published(case)
    bound = bundle(case, value)
    db.execute(update(InpatientCharge).where(InpatientCharge.charge_id == case["charges"][0].charge_id).values(quantity=0.25))
    db.commit()
    with pytest.raises(HTTPException) as caught:
        context.expand_context(db, bound.data, user=case["super_admin_user"], current=True)
    assert caught.value.status_code == 409
    frozen = context.expand_context(db, bound.data, user=case["super_admin_user"], current=False)
    assert frozen["charge_case"]["snapshot"] == value["snapshot"]
    assert context.binding_for(frozen["charge_case"]) == bound.data["charge_binding"]
    with pytest.raises(ValueError):
        context.public_payload(payload(frozen, selected(case, value)))


def test_revocation_retains_original_publication_only_for_super_frozen_audit(charge_case):
    case, db = charge_case, charge_case["db"]
    value = published(case)
    bound = bundle(case, value)
    revoked = sources.revoke_case(db, case["super_admin_user"], value["case_snapshot_id"], {**cas(value), "basis_note": NOTE})
    db.commit()
    assert revoked["status"] == "revoked"
    with pytest.raises(HTTPException) as caught:
        context.expand_context(db, bound.data, user=case["super_admin_user"], current=True)
    assert caught.value.status_code == 409
    audit = context.expand_context(db, bound.data, user=case["super_admin_user"], current=False)
    assert audit["charge_source"] == value["public_source"]
    assert audit["charge_case"]["governance_hash"] != bound.data["charge_binding"]["publication_governance_hash"]
    assert context.binding_for(audit["charge_case"]) == bound.data["charge_binding"]
    internal = context.expand_context(db, bound.data)
    assert internal["charge_case"]["snapshot"] == value["snapshot"]
    with pytest.raises(ValueError):
        context.public_payload(payload(internal, selected(case, value)))


def test_missing_case_or_corrupt_frozen_whole_original_cannot_be_audited(charge_case):
    case, db = charge_case, charge_case["db"]
    value = published(case)
    bound = bundle(case, value)
    db.execute(update(AIChargeCaseSnapshot).where(AIChargeCaseSnapshot.case_snapshot_id == value["case_snapshot_id"]).values(content_hash="f" * 64))
    db.commit()
    with pytest.raises(HTTPException) as caught:
        context.expand_context(db, bound.data)
    assert caught.value.status_code == 409


def test_current_role_downgrade_cannot_read_execution_or_super_audit(charge_case):
    case, db = charge_case, charge_case["db"]
    value = published(case)
    bound = bundle(case, value)
    stale = copy.copy(case["super_admin_user"])
    db.execute(update(User).where(User.user_id == stale.user_id).values(user_role="doctor"))
    db.commit()
    for current in (True, False):
        with pytest.raises(HTTPException) as caught:
            context.expand_context(db, bound.data, user=stale, current=current)
        assert caught.value.status_code == 403


def test_current_expansion_requires_explicit_actor(charge_case):
    value = published(charge_case)
    bound = bundle(charge_case, value)
    with pytest.raises(HTTPException) as caught:
        context.expand_context(charge_case["db"], bound.data, current=True)
    assert caught.value.status_code == 409


def test_task_clock_cannot_precede_its_complete_source_capture(charge_case):
    value = published(charge_case)
    bound = bundle(charge_case, value)
    with pytest.raises(ValueError):
        context.short_context(bound.data["charge_binding"], "2026-10-20T00:00:00.000000Z")
