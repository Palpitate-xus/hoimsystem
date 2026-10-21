"""Actual purpose-authorized explicit edits, independent review and rollback."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.ai import deidentification_reviews as reviews
from app.ai import deidentification_sources as sources
from app.ai.deidentification_models import AIDeidentificationReview
from app.ai.deidentification_spans import canonical, digest, utf8
from app.ai.models import AIAuditEvent
from tests.test_ai_deidentification_sources import deid_case as deid_case  # noqa: F401
from tests.test_ai_deidentification_sources import grant_super, made_case
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


def published_source(db, values):
    case = values[0]
    grant_super(db, values)
    source = made_case(db, values)
    sources.review_case(db, case["super_admin_user"], source["case_id"], dict(expected_revision=1, expected_content_hash=source["content_hash"], decision="publish", basis_note=BASIS))
    return sources.source_current(db, case["admin_user"], source["case_id"], execution=True)


def review_request(source, *, edits=True):
    doc = source["public_source"]["documents"][0]
    body = dict(
        case_id=source["case_id"],
        expected_content_hash=source["content_hash"],
        expected_governance_hash=source["governance_hash"],
        selection_confirmed=True,
        unselected_fields_not_covered=True,
        basis_note=BASIS,
    )
    start = doc["text"].index("张三")
    body["edits"] = [dict(document_source_id=doc["source_id"], text_hash=doc["text_hash"], start=start, end=start + 2, quote="张三", action="mask")] if edits else []
    return body


def residual(value, decision="reviewed_residual_risk_remains"):
    return dict(
        expected_revision=1,
        expected_content_hash=value["content_hash"],
        decision=decision,
        review_scope="complete_selected_output_only_not_anonymity_certification",
        residual_risks=["组合标识及未选字段不在本次核查覆盖范围内"],
        basis_note=BASIS,
    )


def accepted_review(db, values):
    case = values[0]
    source = published_source(db, values)
    value = reviews.create_review(db, case["admin_user"], review_request(source))
    reviews.review_original(db, case["super_admin_user"], value["review_id"], residual(value), manual=True)
    return reviews.review_original(db, case["super_admin_user"], value["review_id"], dict(expected_revision=1, expected_content_hash=value["content_hash"], decision="publish", basis_note=BASIS))


def test_actual_literal_edits_and_unselected_codepoints_preserved_before_independent_review(db_session, deid_case):
    db, case = db_session, deid_case[0]
    source = published_source(db, deid_case)
    value = reviews.create_review(db, case["admin_user"], review_request(source))
    original = source["public_source"]["documents"][0]["text"]
    assert value["output"]["documents"][0]["text"] == original.replace("张三", "[已遮蔽]", 1)
    assert "\r\n😀é" in value["output"]["documents"][0]["text"]
    assert "13800138000" in value["output"]["documents"][0]["text"]  # no automatic detector
    assert value["manual_status"] == "unknown" and value["manual_review"] is None and not value["eligible"]
    assert value["anonymity_guaranteed"] is False and value["original"]["request"]["edits"][0]["quote"] == "张三"
    row = db.get(AIDeidentificationReview, value["review_id"])
    assert row.output_bytes == len(utf8(row.output_json)) and row.output_hash == digest(value["output"])


def test_no_edits_is_explicit_unchanged_output_and_never_anonymity(db_session, deid_case):
    source = published_source(db_session, deid_case)
    value = reviews.create_review(db_session, deid_case[0]["admin_user"], review_request(source, edits=False))
    assert value["output"]["documents"] == source["public_source"]["documents"]
    assert not value["eligible"] and value["output"]["anonymity_guaranteed"] is False


def test_technical_super_cannot_publish_unknown_or_replace_independent_self_review(db_session, deid_case):
    db, case = db_session, deid_case[0]
    source = published_source(db, deid_case)
    value = reviews.create_review(db, case["super_admin_user"], review_request(source))
    with pytest.raises(HTTPException) as error:
        reviews.review_original(db, case["super_admin_user"], value["review_id"], residual(value), manual=True)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        reviews.review_original(db, case["super_admin_user"], value["review_id"], dict(expected_revision=1, expected_content_hash=value["content_hash"], decision="publish", basis_note=BASIS))
    assert error.value.status_code == 409
    assert reviews.get_review(db, case["super_admin_user"], value["review_id"])["manual_status"] == "unknown"


def test_independent_manual_signature_cas_then_technical_publication_is_current_not_certification(db_session, deid_case):
    db, case = db_session, deid_case[0]
    value = accepted_review(db, deid_case)
    assert value["eligible"] and value["status"] == "published" and value["manual_status"] == "reviewed_residual_risk_remains"
    assert not value["anonymity_guaranteed"]
    assert value["manual_review"]["actor"]["user_id"] == case["super_admin_user"].user_id
    with pytest.raises(HTTPException):
        reviews.review_original(db, case["super_admin_user"], value["review_id"], residual(value), manual=True)


def test_negative_manual_review_is_preserved_but_never_published_as_ready(db_session, deid_case):
    db, case = db_session, deid_case[0]
    source = published_source(db, deid_case)
    value = reviews.create_review(db, case["admin_user"], review_request(source))
    negative = reviews.review_original(db, case["super_admin_user"], value["review_id"], residual(value, "not_confirmed"), manual=True)
    assert negative["manual_status"] == "not_confirmed" and not negative["eligible"]
    with pytest.raises(HTTPException):
        reviews.review_original(db, case["super_admin_user"], value["review_id"], dict(expected_revision=1, expected_content_hash=value["content_hash"], decision="publish", basis_note=BASIS))


@pytest.mark.parametrize("fault", ["audit", "output", "actor"])
def test_actual_review_after_audit_fault_rolls_back_original_output_and_event(db_session, deid_case, fault):
    db, case = db_session, deid_case[0]
    source = published_source(db, deid_case)
    before = (db.query(AIDeidentificationReview).count(), db.query(AIAuditEvent).count())
    changes = {
        "audit": "DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id;",
        "output": "UPDATE hoimsystem_ai_deidentification_review SET output_json='{}',output_bytes=2;",
        "actor": "UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=" + str(case["admin_user"].user_id) + ";",
    }
    db.execute(text("CREATE TRIGGER synthetic_deid_review_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='deidentification.review.create' BEGIN " + changes[fault] + " END"))
    db.commit()
    try:
        with pytest.raises(HTTPException):
            reviews.create_review(db, case["admin_user"], review_request(source))
        assert (db.query(AIDeidentificationReview).count(), db.query(AIAuditEvent).count()) == before
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER synthetic_deid_review_fault"))
        db.commit()


@pytest.mark.parametrize("change", ["source_stop", "body", "signer_epoch"])
def test_withdrawal_or_current_authority_change_stops_ordinary_review_but_no_frozen_bypass(db_session, deid_case, change):
    db, case = db_session, deid_case[0]
    value = accepted_review(db, deid_case)
    if change == "source_stop":
        source = sources.source_current(db, case["admin_user"], value["case_id"])
        sources.review_case(db, case["super_admin_user"], value["case_id"], dict(expected_revision=2, expected_content_hash=source["content_hash"], basis_note=BASIS), revoke=True)
    elif change == "body":
        deid_case[-1][0].symptom += "新文字"
        db.commit()
    else:
        import datetime as dt

        case["super_admin_user"].token_invalid_before = dt.datetime(2026, 10, 21, 12)
        db.commit()
    current = reviews.get_review(db, case["admin_user"], value["review_id"])
    assert not current["eligible"]
    if change != "signer_epoch":
        assert current["original"] is None and current["output"] is None
        audited = reviews.get_review(db, case["super_admin_user"], value["review_id"], audit_only=True)
        assert audited["output"] is not None and not audited["eligible"]


@pytest.mark.parametrize("mutation", ["quote", "extra", "output"])
def test_rehashed_review_cannot_change_original_literal_positions_or_output(db_session, deid_case, mutation):
    db, case = db_session, deid_case[0]
    value = accepted_review(db, deid_case)
    row = db.get(AIDeidentificationReview, value["review_id"])
    forged = copy.deepcopy(value["original"])
    if mutation == "quote":
        forged["request"]["edits"][0]["quote"] = "伪文"
    elif mutation == "extra":
        forged["patient_name"] = "额外字段"
    else:
        row.output_json = row.output_json.replace("13800138000", "00000000000")
        row.output_hash = digest(__import__("json").loads(row.output_json))
        row.output_bytes = len(utf8(row.output_json))
        forged["output_hash"] = row.output_hash
    row.review_json = canonical(forged)
    row.content_hash = digest(forged)
    db.commit()
    with pytest.raises(HTTPException):
        reviews.get_review(db, case["admin_user"], value["review_id"])
