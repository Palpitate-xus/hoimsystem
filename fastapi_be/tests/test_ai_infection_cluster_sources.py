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


def test_transfer_permission_is_independent_before_clinical_body(infection_case):
    db, author, _, _, _ = infection_case
    request, _, _, _ = ready(infection_case)
    meta = s.create_snapshot(db, author, request)
    db.commit()
    statements = []

    def capture(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        with pytest.raises(HTTPException) as denied:
            s.snapshot_part(db, author, meta["snapshot_id"], "public", external_model=True)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert denied.value.status_code == 403
    assert not any("hoimsystem_ai_infection_snapshot.private_json" in sql or "hoimsystem_infection_case.description" in sql for sql in statements)


def test_independent_review_author_role_change_and_audit_deleted_are_not_publication(infection_case):
    db, author, reviewer, _, _ = infection_case
    request, grants, _, _ = ready(infection_case)
    db.query(User).filter_by(user_id=reviewer.user_id).update({"user_role": "doctor"}, synchronize_session=False)
    db.commit()
    with pytest.raises(HTTPException):
        s.preview_roots(db, author, request)
    db.query(User).filter_by(user_id=reviewer.user_id).update({"user_role": "super_admin"}, synchronize_session=False)
    db.commit()
    db.execute(text("DELETE FROM hoimsystem_ai_audit_event WHERE event_id=:key"), {"key": grants[0].governance.review_event_id})
    db.commit()
    with pytest.raises(HTTPException):
        s.preview_roots(db, author, request)


def test_exact_root_cannot_get_a_second_or_missing_published_review(infection_case):
    db, author, reviewer, _, _ = infection_case
    request, _, _, review = ready(infection_case)
    proposal = review.payload.model_dump(mode="json")
    for key in ("review_id", "created_by", "recorded_at"):
        proposal.pop(key)
    with pytest.raises(HTTPException):
        r.create_case_review(db, author, proposal)
    r.revoke_record(db, reviewer, "review", review.record_id, cas(review))
    db.commit()
    with pytest.raises(HTTPException):
        s.create_snapshot(db, author, request)


def test_own_staged_root_is_flushed_and_cannot_escape_review(infection_case):
    db, author, _, _, row = infection_case
    request, _, _, _ = ready(infection_case)
    values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    values["case_id"] = str(uuid.uuid4())
    staged = InfectionCase(**values)
    db.add(staged)
    with pytest.raises(HTTPException):
        s.create_snapshot(db, author, request)
    assert db.query(InfectionCase).count() == 1
    assert db.query(AIInfectionSnapshot).count() == 0


def test_snapshot_after_audit_new_root_trigger_rolls_back_whole_acceptance(infection_case):
    db, author, _, _, row = infection_case
    request, _, _, _ = ready(infection_case)
    rid = str(uuid.uuid4())
    db.execute(
        text(
            f"CREATE TRIGGER infection_new_root AFTER INSERT ON hoimsystem_ai_infection_snapshot BEGIN INSERT INTO hoimsystem_infection_case SELECT '{rid}', patient_id, department_id, infection_type, pathogen, onset_date, severity, status, description, reporter_id, create_time, update_time FROM hoimsystem_infection_case LIMIT 1; END"
        )
    )
    db.commit()
    before = db.query(AIAuditEvent).count()
    try:
        with pytest.raises(HTTPException):
            s.create_snapshot(db, author, request)
        assert db.query(AIInfectionSnapshot).count() == 0
        assert db.query(InfectionCase).count() == 1
        assert db.query(AIAuditEvent).count() == before
    finally:
        db.execute(text("DROP TRIGGER infection_new_root"))
        db.commit()


@pytest.mark.parametrize("roles", ["[{}]", '["super_admin","super_admin"]', "null", '["doctor"]'])
def test_execution_role_config_is_strict_and_sup_has_no_role_bypass(infection_case, roles):
    from app.ai.models import AIFeatureConfig

    db, author, _, _, _ = infection_case
    request, _, _, _ = ready(infection_case)
    config = db.get(AIFeatureConfig, "infection_cluster")
    if config is None:
        config = AIFeatureConfig(feature_key="infection_cluster", allowed_roles_json=roles, updated_by=author.user_id)
        db.add(config)
    else:
        config.allowed_roles_json = roles
    db.commit()
    with pytest.raises(HTTPException) as denied:
        r.authorize_patients(db, author, request["patient_ids"], require_config=True)
    assert denied.value.status_code == (403 if roles == '["doctor"]' else 409)
    db.rollback()


def test_actual_4097_sql_roots_are_rejected_without_clipping(infection_case):
    db, author, _, _, row = infection_case
    request, _, _, _ = ready(infection_case)
    values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    values["description"] = "synthetic bounded SQL root"
    db.bulk_insert_mappings(InfectionCase, [{**values, "case_id": str(uuid.uuid4())} for _ in range(4096)])
    db.commit()
    with pytest.raises(HTTPException) as overflow:
        s.preview_roots(db, author, request)
    assert overflow.value.status_code == 413
    assert db.query(InfectionCase).count() == 4097
    assert db.query(AIInfectionSnapshot).count() == 0


def grant_second_patient(db, author, reviewer, patient_id):
    full = r.create_grant(
        db,
        author,
        {
            "patient_id": patient_id,
            "user_id": author.user_id,
            "purpose": "infection_surveillance_processing",
            "valid_from": "2026-10-01T00:00:00.000000Z",
            "valid_to": "2026-11-01T00:00:00.000000Z",
            "basis_note": NOTE,
        },
    )
    db.commit()
    return publish(db, reviewer, full)


def test_changed_snapshot_scope_locator_rejected_before_private_text(infection_case, seed_data):
    db, author, reviewer, _, _ = infection_case
    request, _, _, _ = ready(infection_case)
    grant_second_patient(db, author, reviewer, seed_data["patient2"].patient_id)
    meta = s.create_snapshot(db, author, request)
    db.commit()
    forged = {**request, "patient_ids": [seed_data["patient2"].patient_id]}
    db.execute(text("UPDATE hoimsystem_ai_infection_snapshot SET scope_json=:scope WHERE snapshot_id=:id"), {"scope": c.canonical(forged), "id": meta["snapshot_id"]})
    db.commit()
    statements = []

    def record(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        with pytest.raises(HTTPException) as denied:
            s.snapshot_part(db, author, meta["snapshot_id"], "private")
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    assert denied.value.status_code == 409
    assert not any("hoimsystem_ai_infection_snapshot.private_json" in sql or "hoimsystem_infection_case.description" in sql for sql in statements)


def test_changed_review_patient_header_rejected_before_payload_text(infection_case, seed_data):
    db, author, reviewer, _, _ = infection_case
    _, _, _, full = ready(infection_case)
    grant_second_patient(db, author, reviewer, seed_data["patient2"].patient_id)
    db.execute(text("UPDATE hoimsystem_ai_infection_case_review SET patient_id=:pid WHERE review_id=:id"), {"pid": seed_data["patient2"].patient_id, "id": full.record_id})
    db.commit()
    statements = []

    def record(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        with pytest.raises(HTTPException) as denied:
            r.detail(db, author, "review", full.record_id)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    assert denied.value.status_code == 409
    assert not any("hoimsystem_ai_infection_case_review.payload_json" in sql or "hoimsystem_infection_case.description" in sql for sql in statements)
