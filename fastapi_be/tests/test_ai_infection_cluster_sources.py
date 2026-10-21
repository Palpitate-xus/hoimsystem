"""Actual synthetic ORM source governance, authority and complete current roots."""

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_registry as r
from app.ai import infection_cluster_sources as s
from app.ai.infection_cluster_models import AIInfectionCaseReview, AIInfectionDefinition, AIInfectionPurposeGrant, AIInfectionSnapshot
from app.ai.models import AIAuditEvent
from app.models import InfectionCase, User

NOW = dt.datetime(2026, 10, 21, 12, 0, 0, 123456)
NOTE = "合成工程用途与完整原件已独立核对；不声称执业或临床定义有效。"


def cas(full):
    return {"expected_revision": full.governance.revision, "expected_content_hash": full.content_hash, "expected_governance_hash": full.governance_hash, "basis_note": NOTE}


def publish(db, actor, full, **extra):
    result = r.review_record(db, actor, full.kind, full.record_id, {**cas(full), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", **extra})
    db.commit()
    return result


@pytest.fixture
def infection_case(db_session, seed_data, monkeypatch):
    db = db_session
    monkeypatch.setattr(r, "utcnow", lambda: NOW)
    for model in (AIInfectionSnapshot, AIInfectionCaseReview, AIInfectionPurposeGrant, AIInfectionDefinition):
        db.query(model).delete(synchronize_session=False)
    db.query(InfectionCase).delete(synchronize_session=False)
    db.query(AIAuditEvent).filter(AIAuditEvent.action.like("infection.%")).delete(synchronize_session=False)
    db.commit()
    author = seed_data["super_admin_user"]
    reviewer = db.query(User).filter_by(username="infection_second_super").one_or_none()
    if reviewer is None:
        reviewer = User(username="infection_second_super", password="synthetic-not-auth", user_role="super_admin")
        db.add(reviewer)
    reviewer.user_role = "super_admin"
    reviewer.token_invalid_before = None
    db.commit()
    patient = seed_data["patient"]
    row = InfectionCase(
        case_id=str(uuid.uuid4()),
        patient_id=patient.patient_id,
        department_id=None,
        infection_type="原文\ufeff标签",
        pathogen="",
        onset_date=dt.date(2026, 10, 10),
        severity=4,
        status=2,
        description="\ufeff原说明\r\n😀é:2026-10-21T12:00:00.123456Z",
        reporter_id=author.user_id,
        create_time=dt.datetime(2026, 10, 10, 9, 1, 2, 123456),
        update_time=dt.datetime(2026, 10, 11, 9, 1, 2, 654321),
    )
    db.add(row)
    db.commit()
    return db, author, reviewer, patient, row


def ready(infection_case):
    db, author, reviewer, patient, row = infection_case
    grants = []
    for recipient in (author, reviewer):
        grant = r.create_grant(
            db,
            author,
            {
                "patient_id": patient.patient_id,
                "user_id": recipient.user_id,
                "purpose": "infection_surveillance_processing",
                "valid_from": "2026-10-01T00:00:00.000000Z",
                "valid_to": "2026-11-01T00:00:00.000000Z",
                "basis_note": NOTE,
            },
        )
        db.commit()
        grants.append(publish(db, reviewer, grant))
    definition = r.create_definition(
        db, author, {"version_label": "独立合成定义v1", "definition_text": "仅作合成工程核验，不是任何临床或CDC定义。", "infection_type_codes": ["LOCAL_X"], "pathogen_codes": []}
    )
    db.commit()
    definition = publish(db, reviewer, definition)
    request = {
        "patient_ids": [patient.patient_id],
        "window": {"date_from": "2026-10-01", "date_to": "2026-10-21", "coordinate_basis": "recorded_onset_date_inclusive_no_event_timezone"},
        "definition_id": definition.record_id,
    }
    preview = s.preview_roots(db, author, request)
    pure = preview["definition"]
    raw = preview["originals"][0]
    proposal = {
        "case_id": row.case_id,
        "original_content_hash": raw["content_hash"],
        "definition_id": definition.record_id,
        "definition_content_hash": pure["content_hash"],
        "definition_governance_hash": pure["governance_hash"],
        "assessment": "undetermined",
        "basis_note": NOTE,
    }
    for field in ("infection_type", "pathogen"):
        value = raw["original"][field]
        proposal[field] = {"original_state": c.value_state(value), "original_value_hash": c.digest(value), "assessment": "not_mapped", "reviewed_code": None, "basis_note": NOTE}
    review = r.create_case_review(db, author, proposal)
    db.commit()
    review = publish(db, reviewer, review)
    return request, grants, definition, review


def test_real_chain_preserves_whole_original_and_sql_only_key(infection_case):
    db, author, _, _, row = infection_case
    request, _, _, _ = ready(infection_case)
    meta = s.create_snapshot(db, author, request)
    db.commit()
    private = s.snapshot_part(db, author, meta["snapshot_id"], "private")
    public = s.snapshot_part(db, author, meta["snapshot_id"], "public")
    original = private["value"]["originals"][0]["original"]
    assert original["description"] == row.description
    assert original["pathogen"] == "" and original["department_id"] is None
    assert original["update_time"]["text"].endswith(".654321")
    assert public["value"]["denominator"]["status"] == "not_provided"
    assert public["value"]["counts"]["distinct_records"] == 1
    assert public["value"]["reports"][0]["human_assessment"] == "undetermined"
    assert str(row.patient_id) not in [str(value) for value in public["value"]["scope"]["patient_tokens"]]
    assert row.case_id not in c.canonical(public) and row.description not in c.canonical(public)
    stored = db.get(AIInfectionSnapshot, meta["snapshot_id"])
    assert len(stored.mapping_key) == 32 and "mapping_key" not in c.canonical(private)
    assert s.snapshot_directory(db, author)["items"][0] == meta


def test_grant_and_definition_self_publication_forbidden_and_cas(infection_case):
    db, author, reviewer, patient, _ = infection_case
    full = r.create_grant(
        db,
        author,
        {
            "patient_id": patient.patient_id,
            "user_id": author.user_id,
            "purpose": "infection_surveillance_processing",
            "valid_from": "2026-10-01T00:00:00.000000Z",
            "valid_to": "2026-11-01T00:00:00.000000Z",
            "basis_note": NOTE,
        },
    )
    db.commit()
    count = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException):
        publish(db, author, full)
    assert db.query(AIAuditEvent).count() == count
    with pytest.raises(HTTPException):
        publish(db, reviewer, full, expected_content_hash="a" * 64)
    assert publish(db, reviewer, full).eligible


def test_sup_without_patient_purpose_reads_no_infection_body(infection_case):
    db, author, reviewer, _, _ = infection_case
    definition = r.create_definition(db, author, {"version_label": "v1", "definition_text": "合成定义", "infection_type_codes": [], "pathogen_codes": []})
    db.commit()
    definition = publish(db, reviewer, definition)
    request = {
        "patient_ids": [infection_case[3].patient_id],
        "window": {"date_from": "2026-10-01", "date_to": "2026-10-21", "coordinate_basis": "recorded_onset_date_inclusive_no_event_timezone"},
        "definition_id": definition.record_id,
    }
    statements = []

    def capture(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        with pytest.raises(HTTPException) as denied:
            s.preview_roots(db, author, request)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert denied.value.status_code == 403
    assert not any("hoimsystem_infection_case.description" in sql for sql in statements)


def test_withdrawal_denies_sup_before_snapshot_body_and_directory_stays_bodyless(infection_case):
    db, author, reviewer, _, _ = infection_case
    request, grants, _, _ = ready(infection_case)
    meta = s.create_snapshot(db, author, request)
    db.commit()
    r.revoke_record(db, reviewer, "grant", grants[0].record_id, cas(grants[0]))
    db.commit()
    statements = []

    def capture(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        directory = s.snapshot_directory(db, author)
        with pytest.raises(HTTPException) as denied:
            s.snapshot_part(db, author, meta["snapshot_id"], "private")
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert denied.value.status_code == 403 and directory["total"] == 1
    assert not any("hoimsystem_ai_infection_snapshot.private_json" in sql or "hoimsystem_infection_case.description" in sql for sql in statements)


@pytest.mark.parametrize("mutation", ["description", "status", "pathogen", "new", "delete", "date_out"])
def test_full_member_change_invalidates_even_same_count_or_null_empty(infection_case, mutation):
    db, author, _, _, row = infection_case
    request, _, _, _ = ready(infection_case)
    meta = s.create_snapshot(db, author, request)
    db.commit()
    if mutation == "new":
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        values["case_id"] = str(uuid.uuid4())
        db.add(InfectionCase(**values))
    elif mutation == "delete":
        db.execute(text("DELETE FROM hoimsystem_infection_case WHERE case_id=:key"), {"key": row.case_id})
    elif mutation == "date_out":
        row.onset_date = dt.date(2025, 1, 1)
    else:
        setattr(row, mutation, {"description": row.description + "changed", "status": 99, "pathogen": None}[mutation])
    db.commit()
    with pytest.raises(HTTPException):
        s.snapshot_part(db, author, meta["snapshot_id"], "public")


def test_audit_trigger_payload_change_rolls_back_registry_write(infection_case):
    db, author, _, _, _ = infection_case
    count = db.query(AIAuditEvent).count()
    db.execute(
        text(
            "CREATE TRIGGER infection_bad_definition AFTER INSERT ON hoimsystem_ai_infection_definition BEGIN UPDATE hoimsystem_ai_infection_definition SET payload_json='{}' WHERE definition_id=NEW.definition_id; END"
        )
    )
    db.commit()
    try:
        with pytest.raises(HTTPException):
            r.create_definition(db, author, {"version_label": "v1", "definition_text": "synthetic", "infection_type_codes": [], "pathogen_codes": []})
        assert db.query(AIInfectionDefinition).count() == 0
        assert db.query(AIAuditEvent).count() == count
    finally:
        db.execute(text("DROP TRIGGER infection_bad_definition"))
        db.commit()
