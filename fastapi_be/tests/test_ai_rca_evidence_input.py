"""Pure purpose scope/hash checks; no SQL authority or actual grants claimed."""

import copy

import pytest
from pydantic import ValidationError

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_input as i

NOW = "2026-10-21T12:00:00.123456Z"
FUTURE = "2026-10-22T12:00:00.123456Z"
NOTE = "仅此实际事件与指定患者的RCA调查用途，未证明临床因果。"


def create(**changes):
    return {
        "event_id": 1,
        "expected_event_patient_id": 2,
        "grantee_id": 3,
        "permission_kind": "event_investigation",
        "purpose": "incident_rca",
        "valid_until": FUTURE,
        "basis_note": NOTE,
        "explicit_scope_review": True,
        **changes,
    }


def record(**changes):
    identity = i.GrantIdentity(
        schema_version="rca_purpose_grant_v1",
        grant_id="00000000-0000-0000-0000-000000000001",
        event_id=1,
        patient_id_at_grant=2,
        grantee_id=3,
        permission_kind="event_investigation",
        purpose="incident_rca",
        valid_until=FUTURE,
        basis_note=NOTE,
        explicit_scope_review=True,
        issued_by=4,
        issued_at=NOW,
    )
    gov = i.GrantGovernance(status="active", revision=1, revoked_by=None, revoked_at=None, revoke_reason="", created_audit_event_id=1, revoked_audit_event_id=None)
    content = c.digest(identity)
    return {
        "identity": identity.model_dump(mode="json"),
        "content_hash": content,
        "governance": gov.model_dump(mode="json"),
        "governance_hash": c.digest({"grant_id": identity.grant_id, "content_hash": content, "governance": gov}),
        "evaluated_at": NOW,
        "event_patient_id_now": 2,
        "grantee_current_super": True,
        "current_scope": True,
        "scope_reasons": [],
        **changes,
    }


@pytest.mark.parametrize("permission", ["event_investigation", "associated_patient_processing"])
def test_explicit_independent_purposes_preserve_exact_text_and_utc6(permission):
    body = create(permission_kind=permission, basis_note="\ufeff原样\r\n😀 " + NOTE)
    assert i.GrantCreate.model_validate(body).model_dump(mode="json") == body


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_id", True),
        ("grantee_id", 0),
        ("explicit_scope_review", 1),
        ("explicit_scope_review", False),
        ("purpose", "research"),
        ("permission_kind", "all_patient_data"),
        ("valid_until", "2026-02-30T00:00:00.000000Z"),
        ("valid_until", "2026-10-22T12:00:00Z"),
        ("basis_note", " \u0085\u001c"),
        ("basis_note", "\ud800"),
    ],
)
def test_invalid_scope_and_ambiguous_review_are_rejected(field, value):
    with pytest.raises(ValidationError):
        i.GrantCreate.model_validate(create(**{field: value}))


def test_patientless_event_has_only_real_event_purpose_without_fictional_patient():
    assert i.GrantCreate.model_validate(create(expected_event_patient_id=None)).expected_event_patient_id is None
    with pytest.raises(ValidationError):
        i.GrantCreate.model_validate(create(expected_event_patient_id=None, permission_kind="associated_patient_processing"))


@pytest.mark.parametrize("mutation", ["body", "revocation", "audit_pk", "boolean_scope", "association", "expiry", "role"])
def test_whole_grant_and_independent_governance_anchors_cannot_self_misrepresent_current_permission(mutation):
    value = record()
    assert i.GrantRecord.model_validate(value).current_scope
    value = copy.deepcopy(value)
    if mutation == "body":
        value["identity"]["grantee_id"] += 1
    elif mutation == "revocation":
        value["governance"]["revoke_reason"] = NOTE
    elif mutation == "audit_pk":
        value["governance"]["created_audit_event_id"] += 1
    elif mutation == "boolean_scope":
        value["current_scope"] = 1
    elif mutation == "association":
        value["event_patient_id_now"] = None
    elif mutation == "expiry":
        value["evaluated_at"] = FUTURE
    else:
        value["grantee_current_super"] = False
    with pytest.raises(ValidationError):
        i.GrantRecord.model_validate(value)


@pytest.mark.parametrize("old_patient,patient", [(2, None), (2, 4), (None, 2)])
def test_any_current_patient_association_change_including_null_is_an_explicit_invalid_scope(old_patient, patient):
    value = record(event_patient_id_now=patient, current_scope=False, scope_reasons=["event_patient_changed"])
    value["identity"]["patient_id_at_grant"] = old_patient
    value["content_hash"] = c.digest(value["identity"])
    value["governance_hash"] = c.digest({"grant_id": value["identity"]["grant_id"], "content_hash": value["content_hash"], "governance": value["governance"]})
    parsed = i.GrantRecord.model_validate(value)
    assert not parsed.current_scope and parsed.identity.patient_id_at_grant == old_patient


def test_all_current_grant_failures_are_retained_with_exact_reasons():
    value = record(evaluated_at=FUTURE, event_patient_id_now=None, grantee_current_super=False, current_scope=False)
    value["governance"].update(status="revoked", revision=2, revoked_by=4, revoked_at=NOW, revoke_reason=NOTE, revoked_audit_event_id=2)
    value["governance_hash"] = c.digest({"grant_id": value["identity"]["grant_id"], "content_hash": value["content_hash"], "governance": value["governance"]})
    value["scope_reasons"] = ["grant_expired", "grant_revoked", "event_patient_changed", "grantee_not_current_super"]
    parsed = i.GrantRecord.model_validate(value)
    assert parsed.scope_reasons == value["scope_reasons"] and not parsed.current_scope


@pytest.mark.parametrize("field", ["privacy_review", "faithfulness_review", "provenance_review"])
def test_each_publication_signature_is_explicit_and_cannot_be_replaced_by_workflow_status(field):
    value = {
        "expected_revision": 1,
        "expected_content_hash": "a" * 64,
        "expected_governance_hash": "b" * 64,
        "decision": "publish",
        "privacy_review": "confirmed",
        "faithfulness_review": "confirmed",
        "provenance_review": "confirmed",
        "basis_note": NOTE,
    }
    assert i.SourceReview.model_validate(value).decision == "publish"
    value[field] = "unknown"
    with pytest.raises(ValidationError):
        i.SourceReview.model_validate(value)
    value["decision"] = "reject"
    assert i.SourceReview.model_validate(value).decision == "reject"
