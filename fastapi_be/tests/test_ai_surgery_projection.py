"""Actual governed private SQL originals projected without raw technical keys."""

import copy
import json
import re

import pytest

from app.ai import surgery_facts as facts
from app.ai.surgery_contract import hash_content
from app.ai.surgery_projection import PublicIdentity, new_identity_secret, project_case, public_fact, verified_original
from app.ai.surgery_scenario_input import CaseDomain, MemberDeclaration
from tests.test_ai_surgery_facts import NOTE, amount, publish, request
from tests.test_ai_surgery_facts import surgery_case as surgery_case


def reference(value):
    return {"source_record_id": value["source_record_id"], "expected_content_hash": value["content_hash"], "expected_governance_hash": value["governance_hash"]}


@pytest.fixture
def originals(db_session, surgery_case):
    case = surgery_case
    values = {}
    for kind in ("case_requirements", "case_duration_estimate"):
        body = request(case, kind)
        if kind == "case_requirements":
            payload = body["payload"]
            payload.update(required=True, required_absent_reason=None, procedure_group_key="patient_private_group", procedure_group_absent_reason=None)
            payload["patient_segment_ids"] = ["patient_wang_ming"]
            payload["room"]["slot_id"] = "patient_zhang_san"
            payload["room"]["occupation"]["segment_ids"] = ["patient_wang_ming"]
        else:
            body["payload"]["segments"][0]["segment_id"] = "patient_wang_ming"
        row = facts.create_source(db_session, case["doctor_user"], kind, body)
        db_session.commit()
        publish(db_session, case, row)
        values[kind] = facts.source_current(db_session, case["super"], kind, row.source_record_id, audit_only=True)
    domain = CaseDomain(
        application_id=case["application"].application_id,
        requirements=reference(values["case_requirements"]),
        duration_estimate=reference(values["case_duration_estimate"]),
        start_domain_status="attested_complete",
        starts=[{"start_at": "2026-10-21T08:00:00.000001Z", "penalty": amount("0")}],
        room={
            "slot_id": "patient_zhang_san",
            "domain_status": "attested_complete",
            "choices": [{"resource_id": case["resources"]["room"].resource_id, "penalty": amount("0"), "duty_source": None, "duty_binding_status": None, "duty_basis_note": None}],
            "basis_note": NOTE,
        },
        roles=[],
        equipment=[],
        penalty_if_scheduled=amount("0"),
        penalty_if_deferred=None,
        basis_note=NOTE,
    )
    return values, domain, case


def test_private_random_secret_keeps_same_patient_and_asset_linked_without_public_sql_id_namespace():
    secret = new_identity_secret()
    other = new_identity_secret()
    assert re.fullmatch(r"[a-f0-9]{64}", secret) and secret != other
    public = PublicIdentity(secret)
    assert public.uuid("patient", 1) == public.uuid("patient", 1)
    assert public.uuid("patient", 1) != public.uuid("resource", 1)
    assert public.uuid("patient", 1) != public.uuid("patient", "1")
    assert public.uuid("patient", 1) != PublicIdentity(other).uuid("patient", 1)
    assert public.hashed_key("capability", "patient_private") == public.prehashed_key("capability", hash_content("patient_private"))
    assert public.hashed_key("capability", "patient_private") != public.hashed_key("transition_class", "patient_private")


@pytest.mark.parametrize("secret", [None, 0, True, "a" * 63, "A" * 64, "g" * 64])
def test_identity_secret_cannot_be_defaulted_or_coerced(secret):
    with pytest.raises(ValueError):
        PublicIdentity(secret)


def test_actual_whole_case_originals_mask_free_ascii_stage_slot_group_and_all_private_bodies(originals):
    values, domain, case = originals
    identities = PublicIdentity("1" * 64)
    result = project_case(domain, values["case_requirements"], values["case_duration_estimate"], {}, identities)
    assert result["issues"] == []
    body = result["case"].model_dump(mode="json")
    serialized = json.dumps(body, ensure_ascii=False)
    for forbidden in ("patient_wang_ming", "patient_zhang_san", "patient_private_group", NOTE, case["application"].application_id, case["resources"]["room"].resource_id, "1" * 64):
        assert forbidden not in serialized
    assert body["timing"]["segments"][0]["segment_id"] == body["room"]["occupation"]["segment_ids"][0] == body["patient_presence"]["segment_ids"][0]
    assert body["patient_presence"]["occupation_mode"] == "envelope"
    assert body["room"]["occupation"]["occupation_mode"] == "segments"
    assert body["starts"][0]["start_at"].endswith("000001Z")
    assert body["penalty_if_scheduled"]["value"] == "0"
    assert body["timing"]["segments"][0]["end_offset_us"] == {"value": None, "absent_reason": "unknown"}
    assert body["room"]["occupation"]["accounting"]["counted_as_work"] is None
    assert body["patient_conflict_token"] == identities.uuid("patient", case["patient"].patient_id)
    assert verified_original(values["case_requirements"]).content_hash == values["case_requirements"]["content_hash"]


@pytest.mark.parametrize("change", ["body", "parent", "governance", "identity", "excluded", "audit_draft", "professional", "domain_hash", "domain_demand", "case_parent"])
def test_original_hashes_eligibility_professional_parent_and_finite_demands_fail_closed(originals, change):
    values, domain, case = originals
    values, domain = copy.deepcopy(values), domain.model_dump(mode="json")
    original = values["case_requirements"]
    if change == "body":
        original["payload"]["required"] = False
    elif change == "parent":
        original["parent_binding"]["case"]["patient_id"] += 1
    elif change == "governance":
        original["review_basis_note"] += "变更"
    elif change == "identity":
        original["source_id"] = "surgery_fact:" + original["source_record_id"] + ":" + "0" * 12
    elif change == "excluded":
        original.update(eligible_for_new_use=False, exclusion_reasons=["original_parent_changed"])
    elif change == "audit_draft":
        original.update(status="draft", revision=1, audit_only=True)
    elif change == "professional":
        original["professional_status"] = "unknown"
    elif change == "domain_hash":
        domain["requirements"]["expected_content_hash"] = "0" * 64
    elif change == "domain_demand":
        domain["room"]["slot_id"] = "different"
    else:
        domain["application_id"] = case["admission"].admission_id
    with pytest.raises(ValueError):
        project_case(domain, original, values["case_duration_estimate"], {}, PublicIdentity("2" * 64))


def test_manifest_is_technical_only_and_cannot_restore_audit_or_claim_future_availability(originals, db_session):
    values, _, case = originals
    value = values["case_requirements"]
    declaration = MemberDeclaration(**reference(value), source_kind="case_requirements", selection="confirmed", basis_note=NOTE)
    fact = public_fact(value, declaration, PublicIdentity("3" * 64), "2026-10-20T12:00:01.000000Z")
    assert fact.status == "published" and fact.review == "confirmed"
    assert fact.fact_id != value["source_record_id"]
    assert fact.published_at == value["reviewed_at"]
    serialized = json.dumps(fact.model_dump())
    assert NOTE not in serialized and "patient_id" not in serialized
    with pytest.raises(ValueError, match="original cutoff"):
        public_fact(value, declaration, PublicIdentity("3" * 64), "2026-10-20T00:00:00.000000Z")
    facts.review_source(
        db_session, case["super"], value["source_kind"], value["source_record_id"], {"expected_revision": 2, "expected_content_hash": value["content_hash"], "basis_note": NOTE}, revoke=True
    )
    db_session.commit()
    revoked = facts.source_current(db_session, case["super"], value["source_kind"], value["source_record_id"], audit_only=True)
    with pytest.raises(ValueError):
        public_fact(revoked, declaration, PublicIdentity("3" * 64), "2026-10-20T12:00:01.000000Z")
    declaration.selection = "excluded"
    declaration.expected_governance_hash = revoked["governance_hash"]
    excluded = public_fact(revoked, declaration, PublicIdentity("3" * 64), "2026-10-20T12:00:01.000000Z")
    assert excluded.status == "revoked" and excluded.review == "excluded" and excluded.published_at == value["reviewed_at"]


@pytest.mark.parametrize("missing", ["professional", "required", "group"])
def test_actually_published_unknown_case_fact_never_becomes_a_default_hard_requirement(missing, originals, db_session):
    values, domain, case = originals
    body = request(case, "case_requirements", confirmed=missing != "professional")
    body["payload"] = copy.deepcopy(values["case_requirements"]["payload"])
    if missing == "required":
        body["payload"].update(required=None, required_absent_reason="unknown")
    elif missing == "group":
        body["payload"].update(procedure_group_key=None, procedure_group_absent_reason="unknown")
    row = facts.create_source(db_session, case["doctor_user"], "case_requirements", body)
    db_session.commit()
    publish(db_session, case, row)
    current = facts.source_current(db_session, case["super"], "case_requirements", row.source_record_id, audit_only=True)
    declared = domain.model_dump(mode="json")
    declared["requirements"] = reference(current)
    result = project_case(declared, current, values["case_duration_estimate"], {}, PublicIdentity("4" * 64))
    assert result["case"] is None
    assert result["issues"] == [{"professional": "case_professional_attestation_unknown", "required": "case_required_unknown", "group": "case_procedure_group_key_unknown"}[missing]]
