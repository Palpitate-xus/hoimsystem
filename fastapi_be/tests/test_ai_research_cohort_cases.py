"""Actual research Case SQL lifecycle, explicit rights and deterministic proof."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.ai.models import AIAuditEvent
from app.ai.research_cohort_cases import authorize_case, binding_for, case_current, case_proof, create_case, frozen_case_proof, preview_input, review_case
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_models import AIResearchCohortCase
from app.ai.research_cohort_registry import create_registry_original, review_registry_original
from app.ai.research_cohort_snapshot import project_snapshot, verify_snapshot
from app.ai.research_cohort_sources import hash_content
from tests.test_ai_research_cohort_collection import clinical_case
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import acl_request, anchors, permitted, publish
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


def case_request(scope):
    return {
        **anchors(scope),
        "criteria": {
            "schema_version": "research_recorded_criteria_v1",
            "root": {"op": "recorded_text_contains", "family": "medical_records", "field": "symptom", "literal": "否认胸痛", "quantifier": "any_record"},
        },
    }


def prepared(db, case, *, external_model_use="unknown"):
    case["scope_request"]["data_families"] = ["medical_records", "patient_demographics", "registrations"]
    case["scope_request"]["external_model_use"] = external_model_use
    scope, acl, authorization = permitted(db, case)
    clinical_case(db, case)
    preview = preview_input(db, case["admin_user"], case_request(scope))
    made = create_case(db, case["admin_user"], {"request": preview["request"], "expected_collection_digest": preview["expected_collection_digest"], "basis_note": BASIS})
    return scope, acl, authorization, preview, made


def published(db, case, **kwargs):
    scope, acl, authorization, preview, made = prepared(db, case, **kwargs)
    review_case(db, case["super_admin_user"], made["case_id"], {"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    actual = case_current(db, case["admin_user"], made["case_id"])
    return scope, acl, authorization, preview, actual


def test_actual_capture_create_publish_full_current_and_hmac_evidence_are_closed_without_model_permission(db_session, research_case):
    db, case = db_session, research_case
    scope, _, _, preview, made = published(db, case)
    row, snapshot, source = authorize_case(db, case["admin_user"], made["case_id"])
    assert row["eligible"] and source == made["public_source"]
    assert source["counts"] == {"declared_patients": 1, "recorded_true": 1, "recorded_false": 0, "unknown": 0}
    assert project_snapshot(snapshot, source["governance_hash"]) == source
    assert source["member_manifest_hash"] == hash_content(source["member_manifest"])
    assert binding_for(row, source)["projection_hash"] == hash_content(source)
    assert snapshot["capture"]["collection_digest"] == preview["expected_collection_digest"]
    assert snapshot["creation_basis_note"] == BASIS
    encoded = canonical_json(source)
    assert "patient_id" not in encoded and "registration_uuid" not in encoded and "identity_secret" not in encoded and "scope_id" not in encoded
    assert scope["scope_id"] not in encoded and case["patient"].name not in encoded
    evidence = source["outcomes"][0]["leaves"][0]["evidence"]
    assert any(e["quote"] == "否认胸痛" for e in evidence)
    # Local capture/read and external model handling are separate permissions.
    with pytest.raises(HTTPException) as error:
        authorize_case(db, case["admin_user"], made["case_id"], external_model=True, execution=True)
    assert error.value.status_code == 403


def test_explicit_model_permission_still_requires_actual_requester_acl_not_super_technical_identity(db_session, research_case):
    db, case = db_session, research_case
    scope, _, _, _, made = published(db, case, external_model_use="recorded_permitted")
    assert authorize_case(db, case["admin_user"], made["case_id"], external_model=True, execution=True)[0]["eligible"]
    with pytest.raises(HTTPException):
        authorize_case(db, case["super_admin_user"], made["case_id"], external_model=True, execution=True)
    own_acl = {**acl_request(case, scope), "user_id": case["super_admin_user"].user_id}
    publish(db, case, "acl", create_registry_original(db, case["super_admin_user"], "acl", own_acl))
    # Adding any root invalidates the old Case rather than quietly rebinding.
    after = case_current(db, case["super_admin_user"], made["case_id"])
    assert not after["eligible"] and after["snapshot"] is None


@pytest.mark.parametrize("which", ["authorization", "acl"])
def test_withdrawn_access_hides_clinical_bodies_even_super_technical_frozen_audit(db_session, research_case, which):
    db, case = db_session, research_case
    _, acl, authorization, _, made = published(db, case)
    value = authorization if which == "authorization" else acl
    review_registry_original(db, case["super_admin_user"], which, value["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    for actor, audit in ((case["admin_user"], False), (case["super_admin_user"], True)):
        after = case_current(db, actor, made["case_id"], audit_only=audit)
        assert not after["eligible"] and after["snapshot"] is None and after["public_source"] is None and after["local_resolution"] is None
        assert "否认胸痛" not in canonical_json(after) and "symptom" not in canonical_json(after)
        if audit:
            assert after["protected_original_integrity_verified"] and after["safe_manifest"]
            assert after["can_revoke"]
            assert frozen_case_proof(db, actor, made["case_id"]) == after
        with pytest.raises(HTTPException):
            authorize_case(db, actor, made["case_id"], execution=True)


def test_new_same_patient_record_or_same_count_text_change_invalidates_case_without_exposing_stale_raw(db_session, research_case):
    db, case = db_session, research_case
    _, _, _, _, made = published(db, case)
    db.execute(text("UPDATE hoimsystem_medical_record SET symptom='变化后的完整原量' WHERE patient_id=:id"), {"id": case["patient"].patient_id})
    db.commit()
    after = case_current(db, case["admin_user"], made["case_id"])
    assert not after["eligible"] and not after["parent_current"] and after["snapshot"] is None


def test_stale_expected_digest_rolls_back_before_case_or_audit_and_never_adopts_new_source(db_session, research_case):
    db, case = db_session, research_case
    case["scope_request"]["data_families"] = ["medical_records", "patient_demographics"]
    scope, _, _ = permitted(db, case)
    preview = preview_input(db, case["admin_user"], case_request(scope))
    clinical_case(db, case)
    before = db.query(AIAuditEvent).count()
    before_cases = db.query(AIResearchCohortCase).count()
    with pytest.raises(HTTPException) as error:
        create_case(db, case["admin_user"], {"request": preview["request"], "expected_collection_digest": preview["expected_collection_digest"], "basis_note": BASIS})
    assert error.value.status_code == 409 and db.query(AIResearchCohortCase).count() == before_cases and db.query(AIAuditEvent).count() == before


def test_case_cas_revoke_reconstructs_original_publication_and_ordinary_redaction(db_session, research_case):
    db, case = db_session, research_case
    _, _, _, _, made = published(db, case)
    original = made["public_source"]
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException):
        review_case(db, case["super_admin_user"], made["case_id"], {"expected_revision": 1, "basis_note": BASIS}, revoke=True)
    assert db.query(AIAuditEvent).count() == before
    review_case(db, case["super_admin_user"], made["case_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    redacted = case_current(db, case["admin_user"], made["case_id"])
    assert redacted["snapshot"] is None and redacted["public_source"] is None
    # Even the technical Super cannot read clinical original without own ACL.
    audit = case_current(db, case["super_admin_user"], made["case_id"], audit_only=True)
    assert audit["snapshot"] is None and audit["protected_original_integrity_verified"]
    assert case_proof(db.get(AIResearchCohortCase, made["case_id"]))[1] == original


@pytest.mark.parametrize("fault", ["audit", "body", "actor"])
def test_real_postwrite_sql_faults_rollback_complete_case_and_specific_audit(db_session, research_case, fault):
    db, case = db_session, research_case
    case["scope_request"]["data_families"] = ["medical_records", "patient_demographics"]
    scope, _, _ = permitted(db, case)
    preview = preview_input(db, case["admin_user"], case_request(scope))
    before = db.query(AIAuditEvent).count()
    before_cases = db.query(AIResearchCohortCase).count()
    actor_id = case["admin_user"].user_id
    if fault == "audit":
        body = "UPDATE hoimsystem_ai_audit_event SET target='changed-specific-receipt' WHERE event_id=NEW.event_id;"
        table, condition = "hoimsystem_ai_audit_event", "NEW.action='research.case.create'"
    elif fault == "body":
        body = "UPDATE hoimsystem_ai_research_cohort_case SET snapshot_json='{}' WHERE case_id=NEW.case_id;"
        table, condition = "hoimsystem_ai_research_cohort_case", "1=1"
    else:
        body = f"UPDATE hoimsystem_users SET user_role='patient' WHERE user_id={actor_id};"
        table, condition = "hoimsystem_ai_research_cohort_case", "1=1"
    db.execute(text(f"CREATE TRIGGER research_case_fault AFTER INSERT ON {table} WHEN {condition} BEGIN {body} END"))
    db.commit()
    try:
        with pytest.raises(HTTPException):
            create_case(db, case["admin_user"], {"request": preview["request"], "expected_collection_digest": preview["expected_collection_digest"], "basis_note": BASIS})
        assert db.query(AIResearchCohortCase).count() == before_cases and db.query(AIAuditEvent).count() == before
        assert db.get(type(case["admin_user"]), actor_id).user_role == "admin"
    finally:
        db.execute(text("DROP TRIGGER research_case_fault"))
        db.commit()


@pytest.mark.parametrize("part", ["evaluation", "request", "authorization", "secret"])
def test_false_rehashed_snapshot_does_not_pass_current_recipe_evidence_closure(db_session, research_case, part):
    db, case = db_session, research_case
    _, _, _, _, made = published(db, case)
    value = copy.deepcopy(made["snapshot"])
    if part == "evaluation":
        value["evaluation"]["outcomes"][0]["truth"] = "false"
    elif part == "request":
        value["request"]["criteria"]["root"]["literal"] = "替换条件"
    elif part == "authorization":
        value["capture"]["patient_authorizations"][0]["payload"]["authorization_kind"] = "denied"
    else:
        value["identity_secret"] = "z" * 64
    with pytest.raises(HTTPException) as error:
        verify_snapshot(value)
    assert error.value.status_code == 409


def test_corrupt_own_case_blocks_super_audit_not_silently_opaque_success(db_session, research_case):
    db, case = db_session, research_case
    _, _, _, _, made = published(db, case)
    db.execute(text("UPDATE hoimsystem_ai_research_cohort_case SET snapshot_json='{}' WHERE case_id=:id"), {"id": made["case_id"]})
    db.commit()
    with pytest.raises(HTTPException) as error:
        case_current(db, case["super_admin_user"], made["case_id"], audit_only=True)
    assert error.value.status_code == 409


def test_super_can_technically_review_current_draft_without_being_given_patient_clinical_body(db_session, research_case):
    db, case = db_session, research_case
    _, _, _, _, made = prepared(db, case)
    technical = case_current(db, case["super_admin_user"], made["case_id"], audit_only=True)
    assert technical["can_review"] and technical["parent_current"] and not technical["eligible"]
    assert technical["snapshot"] is None and technical["public_source"] is None and technical["local_resolution"] is None
    assert "否认胸痛" not in canonical_json(technical)
