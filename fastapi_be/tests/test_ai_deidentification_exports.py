"""Single finite output: independent authority review, quota and exact audits."""

import datetime as dt
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import deidentification_exports as exports
from app.ai import deidentification_reviews as reviews
from app.ai.deidentification_models import AIDeidentificationExportRelease
from app.ai.deidentification_spans import digest, utf8
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_cohort_sources import utc_text
from tests.test_ai_deidentification_reviews import accepted_review, residual
from tests.test_ai_deidentification_sources import deid_case as deid_case  # noqa: F401
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


def release_request(review):
    now = exports.utcnow()
    return dict(
        review_id=review["review_id"],
        expected_content_hash=review["content_hash"],
        expected_governance_hash=review["governance_hash"],
        authority_status="recorded_permitted",
        authority_reference="隔离合成明确逐件导出依据编号，不是真实伦理许可",
        original_authority_text="\ufeff合成原记录\r\n仅同意此收件范围及本次完整选定输出🧪",
        recipient_scope="internal_named_recipient",
        recipient_reference="合成项目明确受控接收人甲",
        declared_purpose=BASIS,
        valid_from=utc_text(now - dt.timedelta(days=1)),
        valid_until=utc_text(now + dt.timedelta(days=1)),
        maximum_downloads=1,
        residual_risk_acknowledged=True,
        basis_note=BASIS,
    )


def authority_review(value, decision="reviewed_residual_risk_remains"):
    return {**residual(value, decision), "review_scope": "recorded_authority_recipient_period_and_selected_output_not_legal_certification"}


def accepted_release(db, values):
    case = values[0]
    review = accepted_review(db, values)
    value = exports.create_release(db, case["admin_user"], release_request(review))
    exports.review_release(db, case["super_admin_user"], value["release_id"], authority_review(value), manual=True)
    return exports.review_release(db, case["super_admin_user"], value["release_id"], dict(expected_revision=1, expected_content_hash=value["content_hash"], decision="publish", basis_note=BASIS))


def test_actual_single_output_requires_independent_authority_review_then_technical_publication(db_session, deid_case):
    db, case = db_session, deid_case[0]
    review = accepted_review(db, deid_case)
    value = exports.create_release(db, case["admin_user"], release_request(review))
    assert value["manual_status"] == "unknown" and not value["eligible"]
    with pytest.raises(HTTPException):
        exports.download_release(db, case["admin_user"], value["release_id"])
    with pytest.raises(HTTPException):
        exports.review_release(db, case["super_admin_user"], value["release_id"], dict(expected_revision=1, expected_content_hash=value["content_hash"], decision="publish", basis_note=BASIS))
    with pytest.raises(HTTPException):
        exports.review_release(db, case["admin_user"], value["release_id"], authority_review(value), manual=True)
    exports.review_release(db, case["super_admin_user"], value["release_id"], authority_review(value), manual=True)
    ready = exports.review_release(db, case["super_admin_user"], value["release_id"], dict(expected_revision=1, expected_content_hash=value["content_hash"], decision="publish", basis_note=BASIS))
    assert ready["eligible"] and ready["manual_status"] == "reviewed_residual_risk_remains"
    assert ready["manual_review"]["request"]["review_scope"].startswith("recorded_authority_recipient_period")


def test_actual_download_is_whole_reviewed_utf8_without_original_quotes_or_authority_notes(db_session, deid_case):
    db, case = db_session, deid_case[0]
    value = accepted_release(db, deid_case)
    result = exports.download_release(db, case["admin_user"], value["release_id"])
    body = json.loads(result["body"])
    assert result["cache_control"] == "no-store" and result["filename"] == "deidentification-" + value["release_id"] + ".json"
    assert body == value["artifact"] and digest(body) == result["sha256"] and body["anonymity_guaranteed"] is False
    assert body["documents"][0]["text"].startswith("\ufeff[已遮蔽]\r\n😀é")
    assert "13800138000" in body["documents"][0]["text"]  # honest residual risk
    assert not {"patient_id", "scope_id", "actor", "basis_note", "original_authority_text", "edits", "quote"} & body.keys()
    assert "合成原记录" not in result["body"].decode("utf-8") and "张三" not in result["body"].decode("utf-8")
    row = db.get(AIDeidentificationExportRelease, value["release_id"])
    assert row.download_count == 1 and row.last_download_event_id == result["audit_event_id"]
    audit = db.get(AIAuditEvent, result["audit_event_id"])
    assert audit.action == "deidentification.release.download" and audit.target == row.release_id
    assert json.loads(audit.detail_json)["artifact_hash"] == row.artifact_hash
    with pytest.raises(HTTPException):
        exports.download_release(db, case["admin_user"], value["release_id"])
    assert db.get(AIDeidentificationExportRelease, value["release_id"]).download_count == 1


@pytest.mark.parametrize("unknown", ["permission", "period", "authority_text", "whitespace_authority", "recipient"])
def test_unknown_or_unusable_export_authority_is_recorded_but_not_filled_by_super(db_session, deid_case, unknown):
    db, case = db_session, deid_case[0]
    request = release_request(accepted_review(db, deid_case))
    if unknown == "permission":
        request["authority_status"] = "unknown"
    elif unknown == "period":
        request.update(valid_from=None, valid_until=None)
    elif unknown == "authority_text":
        request["original_authority_text"] = None
    elif unknown == "whitespace_authority":
        request["original_authority_text"] = "　\r\n"
    else:
        request["recipient_reference"] = "　\t"
    value = exports.create_release(db, case["admin_user"], request)
    assert value["original"]["request"] == request
    exports.review_release(db, case["super_admin_user"], value["release_id"], authority_review(value), manual=True)
    with pytest.raises(HTTPException):
        exports.review_release(db, case["super_admin_user"], value["release_id"], dict(expected_revision=1, expected_content_hash=value["content_hash"], decision="publish", basis_note=BASIS))
    assert not exports.get_release(db, case["admin_user"], value["release_id"])["eligible"]


@pytest.mark.parametrize("fault", ["audit", "artifact", "counter", "source_stop", "actor"])
def test_download_after_actual_audit_fault_is_atomic_and_never_commits_quota_or_bad_receipt(db_session, deid_case, fault):
    db, case = db_session, deid_case[0]
    value = accepted_release(db, deid_case)
    before = db.query(AIAuditEvent).count()
    changes = {
        "audit": "DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id;",
        "artifact": "UPDATE hoimsystem_ai_deidentification_release SET artifact_json='{}',artifact_bytes=2;",
        "counter": "UPDATE hoimsystem_ai_deidentification_release SET maximum_downloads=99;",
        "source_stop": "UPDATE hoimsystem_ai_deidentification_case SET content_hash='" + "f" * 64 + "';",
        "actor": "UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=" + str(case["admin_user"].user_id) + ";",
    }
    db.execute(text("CREATE TRIGGER synthetic_deid_download_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='deidentification.release.download' BEGIN " + changes[fault] + " END"))
    db.commit()
    try:
        with pytest.raises(HTTPException):
            exports.download_release(db, case["admin_user"], value["release_id"])
        row = db.get(AIDeidentificationExportRelease, value["release_id"])
        assert row.download_count == 0 and row.last_download_event_id is None and row.artifact_json == json.dumps(value["artifact"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        assert db.query(AIAuditEvent).count() == before
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER synthetic_deid_download_fault"))
        db.commit()


def test_explicit_export_period_and_review_withdrawal_stop_download_without_restoring_source(db_session, deid_case, monkeypatch):
    db, case = db_session, deid_case[0]
    value = accepted_release(db, deid_case)
    end = db.get(AIDeidentificationExportRelease, value["release_id"]).valid_until
    monkeypatch.setattr(exports, "utcnow", lambda: end)
    with pytest.raises(HTTPException):
        exports.download_release(db, case["admin_user"], value["release_id"])
    monkeypatch.undo()
    review = reviews.get_review(db, case["admin_user"], value["review_id"])
    reviews.review_original(db, case["super_admin_user"], value["review_id"], dict(expected_revision=2, expected_content_hash=review["content_hash"], basis_note=BASIS), revoke=True)
    with pytest.raises(HTTPException):
        exports.download_release(db, case["super_admin_user"], value["release_id"])
    audited = exports.get_release(db, case["super_admin_user"], value["release_id"], audit_only=True)
    assert audited["artifact"] is not None and not audited["eligible"]


def test_super_without_current_project_acl_never_reads_export_text_even_frozen(db_session, deid_case):
    db, case = db_session, deid_case[0]
    value = accepted_release(db, deid_case)
    # Revoke Super's explicit project ACL; technical role cannot replace it.
    from app.ai.research_cohort_models import AIResearchProjectACL

    root = db.query(AIResearchProjectACL).filter_by(scope_id=deid_case[1]["scope_id"], user_id=case["super_admin_user"].user_id).one()
    review_registry_original(db, case["super_admin_user"], "acl", root.acl_id, dict(expected_revision=2, basis_note=BASIS), revoke=True)
    statements = []

    def observe(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        audited = exports.get_release(db, case["super_admin_user"], value["release_id"], audit_only=True)
        assert audited["original"] is None and audited["artifact"] is None and not audited["eligible"]
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    assert not any("SELECT hoimsystem_ai_deidentification_release.release_json" in sql or "SELECT hoimsystem_ai_deidentification_review.review_json" in sql for sql in statements)
    assert not any("hoimsystem_medical_record.symptom" in sql for sql in statements)


def test_release_output_contains_every_reviewed_field_even_empty_or_unmodified(db_session, deid_case):
    db, case = db_session, deid_case[0]
    value = accepted_release(db, deid_case)
    review = reviews.get_review(db, case["admin_user"], value["review_id"])
    assert value["artifact"]["documents"] == review["output"]["documents"]
    assert db.get(AIDeidentificationExportRelease, value["release_id"]).artifact_bytes == len(utf8(json.dumps(value["artifact"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
