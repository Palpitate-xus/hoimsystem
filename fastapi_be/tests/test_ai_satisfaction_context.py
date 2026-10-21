"""Actual current Source authority around short satisfaction-only task bindings."""

import copy
import datetime as dt

import pytest
from fastapi import HTTPException

from app.ai.review_curation import create_excerpt, load_review_source
from app.ai.satisfaction_context import binding_for_value, expand_context, public_payload, satisfaction_context, satisfaction_evidence, selection, short_context
from app.ai.satisfaction_draft import source_hash
from app.ai.satisfaction_sources import frozen_case_proof, revoke_case
from app.ai.schemas import ReviewExcerptWrite
from app.models import Review
from tests.test_ai_satisfaction_sources import BASIS, published
from tests.test_ai_satisfaction_sources import satisfaction_case as satisfaction_case  # noqa: F401


def ready(db, case):
    made = published(db, case)
    values = {"satisfaction_case_id": made["case_id"], "question": "请核对这份明确人工摘录提出的候诊顺序问题。"}
    bundle = satisfaction_context(db, case["admin_user"], values)
    return made, values, bundle


def test_actual_complete_source_short_context_expansion_and_only_safe_model_payload(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    made, values, bundle = ready(db, case)
    assert not bundle.department_ids and bundle.data["department_ids"] == []
    assert set(bundle.data["selected_sources"]) == {"satisfaction_case_id"}
    assert len(bundle.evidence) == 1 and len(str(bundle.data)) < 5000
    assert "satisfaction_source" not in bundle.data and "safe_snapshot" not in str(bundle.data)
    expanded = expand_context(db, bundle.data, user=case["admin_user"], current=True)
    assert expanded["satisfaction_case"]["snapshot"] is None
    assert expanded["satisfaction_case"]["review_basis_note"] is expanded["satisfaction_case"]["revoke_reason"] is None
    assert expanded["satisfaction_case"]["frozen_task_view"] is True
    output = public_payload({"input": values, "context": expanded, "tools": {}, "evidence": bundle.evidence})
    assert output == {"satisfaction_source": made["public_source"], "question": values["question"]}
    assert source_hash(output["satisfaction_source"]) == bundle.data["satisfaction_binding"]["projection_hash"]
    assert case["review"].comment not in str(output)
    assert "patient_id" not in str(output) and "visit_id" not in str(output) and "identity_secret" not in str(output)
    assert binding_for_value(frozen_case_proof(db, made["case_id"])) == bundle.data["satisfaction_binding"]
    assert bundle.data == short_context(bundle.data["satisfaction_binding"], bundle.data["snapshot_time"])
    assert bundle.evidence == [satisfaction_evidence(bundle.data["satisfaction_binding"])]


@pytest.mark.parametrize("value", [{}, {"satisfaction_case_id": "../outside"}, {"satisfaction_case_id": True}, {"satisfaction_case_id": "1" * 36}, {"coding_case_id": "a" * 36}])
def test_task_selection_requires_the_exact_one_canonical_source_reference(value):
    with pytest.raises(HTTPException) as error:
        selection(value)
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "field,value", [("patient_id", 1), ("encounter_ref", "synthetic"), ("home_id", "synthetic"), ("review_id", 1), ("department_id", 1), ("doctor_ids", [1]), ("surgery_scenario_id", "synthetic")]
)
def test_foreign_patient_clinical_and_other_feature_references_are_never_operational_scope(field, value):
    with pytest.raises(HTTPException) as error:
        selection({"satisfaction_case_id": "11111111-1111-1111-1111-111111111111", field: value})
    assert error.value.status_code == 422


@pytest.mark.parametrize("question", [False, [], "x" * 2001, "🧪" * 2001, "surrogate\ud800"])
def test_question_is_exact_bounded_unicode_and_never_coerced(question):
    with pytest.raises(HTTPException) as error:
        selection({"satisfaction_case_id": "11111111-1111-1111-1111-111111111111", "question": question})
    assert error.value.status_code == 422


def test_question_inclusive_codepoint_and_utf8_limit_preserves_zero_null_and_empty():
    identifier = "11111111-1111-1111-1111-111111111111"
    for value in (None, "", "🧪" * 2000):
        assert selection({"satisfaction_case_id": identifier, "question": value}) == identifier


@pytest.mark.parametrize("change", ["review", "draft_version", "patient", "doctor", "reviewer"])
def test_ordinary_history_execution_false_still_rechecks_every_current_member_and_parent(db_session, satisfaction_case, change):
    db, case = db_session, satisfaction_case
    _, _, bundle = ready(db, case)
    if change == "review":
        db.add(Review(doctor_id=case["doctor"].doctor_id, score=1, review_time=dt.datetime(2026, 10, 20)))
    elif change == "draft_version":
        original = load_review_source(db, case["review"].review_id)
        create_excerpt(
            db,
            case["super_admin_user"],
            ReviewExcerptWrite(
                review_id=case["review"].review_id, expected_source_hash=original.fingerprint, redacted_text="新增未选择的实际合成摘录版本", change_note="新增非赢家同样使原完整集合失效。"
            ),
        )
    elif change == "patient":
        case["patient"].phone = "13911223344"
    elif change == "doctor":
        case["doctor"].department_id = None
    else:
        case["super_admin_user"].user_role = "admin"
    db.commit()
    with pytest.raises(HTTPException) as error:
        expand_context(db, bundle.data, user=case["admin_user"], current=False)
    assert error.value.status_code == 409


def test_internal_frozen_audit_survives_revoke_but_user_path_and_model_dispatch_do_not(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    made, values, bundle = ready(db, case)
    revoke_case(db, case["super_admin_user"], made["case_id"], {"expected_revision": 2, "basis_note": BASIS})
    for actor in (case["admin_user"], case["super_admin_user"]):
        with pytest.raises(HTTPException) as error:
            expand_context(db, bundle.data, user=actor, current=False)
        assert error.value.status_code == 409
    frozen = expand_context(db, bundle.data)
    assert frozen["satisfaction_case"]["status"] == "revoked" and frozen["satisfaction_case"]["snapshot"] is None
    assert frozen["satisfaction_source"] == made["public_source"]
    with pytest.raises(ValueError):
        public_payload({"input": values, "context": frozen, "tools": {}, "evidence": bundle.evidence})
    with pytest.raises(HTTPException):
        expand_context(db, bundle.data, current=True)


def test_actual_role_loss_is_403_not_rewritten_as_a_source_integrity_error(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    _, _, bundle = ready(db, case)
    case["admin_user"].user_role = "patient"
    db.commit()
    with pytest.raises(HTTPException) as error:
        expand_context(db, bundle.data, user=case["admin_user"], current=False)
    assert error.value.status_code == 403


@pytest.mark.parametrize("mutation", ["foreign_context", "private_body", "source_hash", "question_scope", "tools", "evidence", "frozen_flags"])
def test_safe_payload_refuses_mixed_context_private_body_or_self_rehashed_wrong_source(db_session, satisfaction_case, mutation):
    db, case = db_session, satisfaction_case
    made, values, bundle = ready(db, case)
    data = {"input": values, "context": expand_context(db, bundle.data, user=case["admin_user"], current=True), "tools": {}, "evidence": bundle.evidence}
    changed = copy.deepcopy(data)
    if mutation == "foreign_context":
        changed["context"]["coding_binding"] = {}
    elif mutation == "private_body":
        changed["context"]["satisfaction_case"]["snapshot"] = made["snapshot"]
    elif mutation == "source_hash":
        changed["context"]["satisfaction_source"]["safe_snapshot"]["reviews"][0]["recorded_score"] = 5
    elif mutation == "question_scope":
        changed["input"]["patient_id"] = 1
    elif mutation == "tools":
        changed["tools"] = {"write": True}
    elif mutation == "evidence":
        changed["evidence"] = []
    else:
        changed["context"]["satisfaction_case"]["can_revoke"] = True
    with pytest.raises((ValueError, HTTPException)):
        public_payload(changed)
