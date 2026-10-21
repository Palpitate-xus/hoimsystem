"""Actual75 purpose, whole selected text and controlled Source governance SQL."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import deidentification_collection as collection
from app.ai import deidentification_sources as sources
from app.ai.deidentification_models import AIDeidentificationCase
from app.ai.deidentification_spans import digest
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_registry import create_registry_original, review_registry_original
from tests.test_ai_research_cohort_collection import clinical_case
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import acl_request, anchors, permitted, publish
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


@pytest.fixture
def deid_case(db_session, research_case):
    case = research_case
    case["scope_request"]["permitted_uses"] = ["deidentification_review"]
    scope, acl, authorization = permitted(db_session, case)
    reg, notes = clinical_case(db_session, case)
    notes[0].symptom = "\ufeff张三\r\n😀é原文2026-10-21T12:00:00.123456Z，电话13800138000"
    db_session.commit()
    return case, scope, acl, authorization, reg, notes


def selection(db, values):
    case, scope, *_ = values
    request = {**anchors(scope), "patient_id": case["patient"].patient_id}
    choices = sources.choices(db, case["admin_user"], request)
    row = next(x for x in choices["items"] if x["record_id"] == values[-1][0].medical_record_id and x["field"] == "symptom")
    return {**request, "documents": [dict(family=row["family"], record_id=row["record_id"], field=row["field"], expected_original_hash=row["original_hash"])]}


def made_case(db, values):
    case = values[0]
    request = selection(db, values)
    preview = sources.preview_input(db, case["admin_user"], request)
    return sources.create_case(db, case["admin_user"], dict(request=request, expected_collection_digest=preview["expected_collection_digest"], basis_note=BASIS))


def grant_super(db, values):
    case, scope, *_ = values
    body = {**acl_request(case, scope), "user_id": case["super_admin_user"].user_id}
    return publish(db, case, "acl", create_registry_original(db, case["super_admin_user"], "acl", body))


def test_actual_source_capture_selects_whole_unchanged_field_and_public_has_no_private_identity(db_session, deid_case):
    db, (case, _, _, _, _, notes) = db_session, deid_case
    request = selection(db, deid_case)
    preview = sources.preview_input(db, case["admin_user"], request)
    captured = preview["capture"]
    assert collection.verify_capture(captured) == captured
    value = made_case(db, deid_case)
    assert value["status"] == "draft" and not value["eligible"]
    assert value["snapshot"]["capture"]["selected_documents"][0]["document"]["text"] == notes[0].symptom
    public = value["public_source"]
    assert public["documents"][0]["text"] == notes[0].symptom
    assert public["anonymity_guaranteed"] is False
    assert not any(k in str(public.keys()) for k in ("patient_id", "scope_id", "actor_id", "basis_note"))
    assert "scope_original" not in public and "authority_actors" not in public
    fresh = sources.preview_input(db, case["admin_user"], request)
    assert fresh["capture"]["captured_at"] != captured["captured_at"]
    assert fresh["expected_collection_digest"] == preview["expected_collection_digest"]
    assert len(captured["member_manifest"]) > len(captured["selected_originals"])


@pytest.mark.parametrize("actor", ["admin_user", "super_admin_user"])
def test_current_scope_or_patient_denial_happens_before_clinical_text_queries(db_session, deid_case, actor):
    db, (case, _, _, authorization, *_) = db_session, deid_case
    request = selection(db, deid_case)
    review_registry_original(db, case["super_admin_user"], "authorization", authorization["source_record_id"], dict(expected_revision=2, basis_note=BASIS), revoke=True)
    sql = []

    def observe(conn, cursor, statement, parameters, context, many):
        sql.append(statement)

    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        with pytest.raises(HTTPException) as error:
            sources.preview_input(db, case[actor], request)
        assert error.value.status_code == 403
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    assert not any("hoimsystem_medical_record.symptom" in statement for statement in sql)


def test_super_without_project_permission_gets_only_opaque_source_metadata_and_can_stop_without_raw_text(db_session, deid_case):
    db, case = db_session, deid_case[0]
    value = made_case(db, deid_case)
    sql = []

    def observe(conn, cursor, statement, parameters, context, many):
        sql.append(statement)

    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        audited = sources.source_current(db, case["super_admin_user"], value["case_id"], audit_only=True)
        assert audited["snapshot"] is None and audited["public_source"] is None and audited["proof_scope"] == "safe_metadata_and_opaque_hashes_only"
        stopped = sources.review_case(db, case["super_admin_user"], value["case_id"], dict(expected_revision=1, expected_content_hash=value["content_hash"], basis_note=BASIS), revoke=True)
        assert stopped["status"] == "revoked" and stopped["snapshot"] is None
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    assert not any("SELECT hoimsystem_ai_deidentification_case.snapshot_json" in statement or "hoimsystem_medical_record.symptom" in statement for statement in sql)
    assert any("deid_sha256_utf8(hoimsystem_ai_deidentification_case.snapshot_json)" in statement for statement in sql)


def test_only_true_current_super_with_project_patient_permission_can_technically_publish(db_session, deid_case):
    db, case = db_session, deid_case[0]
    grant_super(db, deid_case)
    value = made_case(db, deid_case)
    body = dict(expected_revision=1, expected_content_hash=value["content_hash"], decision="publish", basis_note=BASIS)
    with pytest.raises(HTTPException) as error:
        sources.review_case(db, case["admin_user"], value["case_id"], body)
    assert error.value.status_code == 403
    accepted = sources.review_case(db, case["super_admin_user"], value["case_id"], body)
    assert accepted["status"] == "published" and accepted["audit_only"]
    normal = sources.source_current(db, case["admin_user"], value["case_id"], execution=True)
    assert normal["eligible"] and normal["public_source"]["source_governance_hash"] == accepted["governance_hash"]
    with pytest.raises(HTTPException) as error:
        sources.review_case(db, case["super_admin_user"], value["case_id"], body)
    assert error.value.status_code == 409


@pytest.mark.parametrize("change", ["selected_text", "unselected_text", "new_member", "delete_member", "parent_rebound"])
def test_same_explicit_request_whole_candidate_changes_invalidate_prior_capture_and_case(db_session, deid_case, change):
    from app.models import MedicalRecord

    db, (case, _, _, _, _, notes) = db_session, deid_case
    value = made_case(db, deid_case)
    request = value["snapshot"]["capture"]["request"]
    old = value["snapshot"]["capture"]["collection_digest"]
    if change == "selected_text":
        notes[0].symptom += "改变"
    elif change == "unselected_text":
        notes[1].symptom += "改变"
    elif change == "new_member":
        db.add(MedicalRecord(patient_id=case["patient"].patient_id, doctor_id=case["doctor"].doctor_id, consultation_time=None, symptom="新增的未知日期原件", result=None, status=0))
    elif change == "delete_member":
        db.delete(notes[1])
    else:
        notes[0].registration_uuid = None
    db.commit()
    if change in {"selected_text", "parent_rebound"}:
        with pytest.raises(HTTPException):
            sources.preview_input(db, case["admin_user"], request)
    else:
        assert sources.preview_input(db, case["admin_user"], request)["expected_collection_digest"] != old
    current = sources.source_current(db, case["admin_user"], value["case_id"])
    assert not current["current"] and current["snapshot"] is None and current["public_source"] is None


@pytest.mark.parametrize("mutation", ["selected_quote", "manifest_drop", "authority_missing", "authority_hash", "actor_drop", "invented_field", "null_to_empty"])
def test_pure_capture_proof_rejects_self_rehashed_missing_or_modified_selected_anchors(db_session, deid_case, mutation):
    value = sources.preview_input(db_session, deid_case[0]["admin_user"], selection(db_session, deid_case))["capture"]
    forged = copy.deepcopy(value)
    if mutation == "selected_quote":
        forged["selected_documents"][0]["document"]["text"] += "x"
    elif mutation == "manifest_drop":
        forged["member_manifest"].pop()
        forged["manifest_hash"] = digest(forged["member_manifest"])
    elif mutation == "authority_missing":
        del forged["authorization_manifest"][0]["metadata"]["payload_json_hash"]
    elif mutation == "authority_hash":
        forged["authorization_manifest"][0]["metadata"]["payload_json_hash"] = "f" * 64
    elif mutation == "actor_drop":
        forged["authority_actors"].pop()
    elif mutation == "invented_field":
        forged["selected_originals"][0]["original"]["foreign"] = "not declared"
    else:
        forged["selected_documents"][0]["document"]["absent_reason"] = "not_recorded"
    forged["collection_digest"] = digest({k: v for k, v in forged.items() if k not in {"captured_at", "collection_digest"}})
    with pytest.raises(HTTPException) as error:
        collection.verify_capture(forged)
    assert error.value.status_code == 409


@pytest.mark.parametrize("fault", ["audit", "body", "actor"])
def test_actual_after_specific_audit_fault_rolls_back_entire_source_transaction(db_session, deid_case, fault):
    db, case = db_session, deid_case[0]
    request = selection(db, deid_case)
    expected = sources.preview_input(db, case["admin_user"], request)["expected_collection_digest"]
    before = (db.query(AIDeidentificationCase).count(), db.query(AIAuditEvent).count())
    changes = {
        "audit": "DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id;",
        "body": "UPDATE hoimsystem_ai_deidentification_case SET snapshot_json='{}';",
        "actor": "UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=" + str(case["admin_user"].user_id) + ";",
    }
    db.execute(text("CREATE TRIGGER synthetic_deid_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='deidentification.case.create' BEGIN " + changes[fault] + " END"))
    db.commit()
    try:
        with pytest.raises(HTTPException):
            sources.create_case(db, case["admin_user"], dict(request=request, expected_collection_digest=expected, basis_note=BASIS))
        assert (db.query(AIDeidentificationCase).count(), db.query(AIAuditEvent).count()) == before
        assert case["admin_user"].user_role == "admin"
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER synthetic_deid_fault"))
        db.commit()


def test_current_model_outbound_permission_unknown_is_denied_before_any_case_text(db_session, deid_case):
    db, case = db_session, deid_case[0]
    value = made_case(db, deid_case)
    statements = []

    def observe(conn, cursor, sql, params, context, many):
        statements.append(sql)

    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        with pytest.raises(HTTPException) as failure:
            sources.source_current(db, case["admin_user"], value["case_id"], external_model=True)
        assert failure.value.status_code == 403
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    assert not any("SELECT hoimsystem_ai_deidentification_case.snapshot_json" in sql or "hoimsystem_medical_record.symptom" in sql for sql in statements)


def test_74_only_purpose_never_grants_75_clinical_field_read(db_session, research_case):
    case = research_case
    scope, _, _ = permitted(db_session, case)
    sql = []

    def observe(conn, cursor, statement, params, context, many):
        sql.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", observe)
    try:
        with pytest.raises(HTTPException) as failure:
            sources.choices(db_session, case["admin_user"], {**anchors(scope), "patient_id": case["patient"].patient_id})
        assert failure.value.status_code == 403
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observe)
    assert not any("hoimsystem_medical_record.symptom" in s for s in sql)


def test_care_access_basis_cannot_read_care_rows_before_canonical_patient_lock(db_session, research_case):
    from app.models import Patient

    db, case = db_session, research_case
    case["scope_request"]["permitted_uses"] = ["deidentification_review"]
    scope, _, _ = permitted(db, case, basis="current_care_or_grant")
    # Admin's declared care basis has no automatic admin bypass. Add a real
    # expiring category grant only after the project/patient documents exist.
    import datetime as dt

    from app.ai.models import AIPatientGrant
    from app.ai.research_cohort_sources import utcnow

    db.add(
        AIPatientGrant(
            user_id=case["admin_user"].user_id,
            patient_id=case["patient"].patient_id,
            category="knowledge",
            reason=BASIS,
            expires_at=utcnow() + dt.timedelta(days=1),
            revoked=0,
            created_by=case["super_admin_user"].user_id,
        )
    )
    db.commit()
    reads = []

    def observe(conn, cursor, statement, params, context, many):
        if statement.lstrip().startswith("SELECT"):
            reads.append(statement)

    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        sources.choices(db, case["admin_user"], {**anchors(scope), "patient_id": case["patient"].patient_id})
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    lock_position = next(i for i, sql in enumerate(reads) if sql.startswith("SELECT hoimsystem_patient.patient_id AS") and " IN (" not in sql and "hoimsystem_patient.patient_id =" in sql)
    grant_position = next(i for i, sql in enumerate(reads) if "hoimsystem_ai_patient_grant" in sql)
    assert lock_position < grant_position
    assert Patient.__table__.c.patient_id is not None


def test_body_reload_reapplies_patient_boundary_if_locator_is_rebound_between_reads(db_session, deid_case):
    db, case, target = db_session, deid_case[0], deid_case[-1][0]
    request = selection(db, deid_case)
    changed, body_sql = [], []

    def observe(conn, cursor, sql, params, context, many):
        if "hoimsystem_medical_record.symptom" in sql:
            body_sql.append(sql)
        if not changed and sql.startswith("SELECT hoimsystem_medical_record.medical_record_id AS") and "symptom" not in sql:
            changed.append(True)
            conn.exec_driver_sql("UPDATE hoimsystem_medical_record SET patient_id=? WHERE medical_record_id=?", (case["patient2"].patient_id, target.medical_record_id))

    event.listen(db.bind, "after_cursor_execute", observe)
    try:
        with pytest.raises(HTTPException) as failure:
            sources.preview_input(db, case["admin_user"], request)
        assert failure.value.status_code == 409 and changed
        assert body_sql and all("hoimsystem_medical_record.patient_id =" in sql for sql in body_sql)
    finally:
        event.remove(db.bind, "after_cursor_execute", observe)
        db.rollback()
