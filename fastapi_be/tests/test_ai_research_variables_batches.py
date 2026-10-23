"""Actual isolated SQLite Batch creation/governance/currentness/atomic faults."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app.ai.models import AIAuditEvent
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_variables_batches import batch_current, create_batch, review_batch
from app.ai.research_variables_models import AIResearchVariableBatch
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401
from tests.test_ai_research_variables_collection import variable_capture_case as variable_capture_case  # noqa: F401
from tests.test_ai_research_variables_dictionary import technical_review
from tests.test_ai_research_variables_dictionary import variable_dictionary_case as variable_dictionary_case  # noqa: F401


def make(db, fixture):
    case, _, request, _, _ = fixture
    return create_batch(db, case["admin_user"], {**request, "basis_note": BASIS})


def test_actual_batch_creation_publication_revocation_bind_immutable_snapshot_independent_private_key_and_three_exact_audit_pks(db_session, variable_capture_case):
    case, _, _, _, _ = variable_capture_case
    made = make(db_session, variable_capture_case)
    assert made["status"] == "draft" and not made["eligible"]
    published = review_batch(db_session, case["super_admin_user"], made["batch_id"], technical_review())
    assert published["eligible"] and published["status"] == "published"
    revoked = review_batch(db_session, case["super_admin_user"], made["batch_id"], dict(expected_revision=2, basis_note=BASIS), revoke=True)
    assert revoked["status"] == "revoked" and revoked["revision"] == 3 and not revoked["eligible"]
    packets = (made, published, revoked)
    assert len({p["content_hash"] for p in packets}) == 1
    assert len({p["governance_hash"] for p in packets}) == 3
    assert len({p["projection_hash"] for p in packets}) == 3
    assert all(p["original"]["snapshot"] == made["original"]["snapshot"] for p in packets)
    ids = [p["original"]["last_event_id"] for p in packets]
    assert len(set(ids)) == 3 and db_session.query(AIAuditEvent).filter(AIAuditEvent.event_id.in_(ids)).count() == 3
    row = db_session.query(AIResearchVariableBatch).filter_by(batch_id=made["batch_id"]).one()
    assert len(row.identity_key) == 32 and row.created_event_id == ids[0]
    assert batch_current(db_session, case["admin_user"], row.batch_id) == revoked


def test_separate_explicit_creations_use_different_batch_keys_and_unlinkable_model_member_tokens(db_session, variable_capture_case):
    first, second = make(db_session, variable_capture_case), make(db_session, variable_capture_case)
    assert first["batch_id"] != second["batch_id"] and first["content_hash"] != second["content_hash"]
    assert set(first["original"]["source"]["member_tokens"]).isdisjoint(second["original"]["source"]["member_tokens"])


@pytest.mark.parametrize("actor_name", ["admin_user", "super_admin_user"])
def test_withdrawal_denies_first_batch_private_text_even_super_but_explicit_technical_metadata_remains_bodyless(db_session, variable_capture_case, actor_name):
    case, permission, _, _, _ = variable_capture_case
    made = make(db_session, variable_capture_case)
    review_registry_original(db_session, case["super_admin_user"], "authorization", permission["source_record_id"], dict(expected_revision=2, basis_note=BASIS), revoke=True)
    statements = []

    def record(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", record)
    try:
        with pytest.raises(HTTPException) as error:
            batch_current(db_session, case[actor_name], made["batch_id"])
        assert error.value.status_code == 403
        safe = batch_current(db_session, case["super_admin_user"], made["batch_id"], audit_only=True)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)
    assert safe["original"] is None and safe["eligible"] is False
    assert not any("hoimsystem_ai_research_variable_batch.snapshot_json" in sql or "hoimsystem_ai_research_variable_batch.projection_json" in sql for sql in statements)


def test_same_count_current_clinical_literal_change_disables_old_batch_without_automatic_replacement_or_window_winner(db_session, variable_capture_case):
    case, _, _, _, early = variable_capture_case
    made = make(db_session, variable_capture_case)
    db_session.execute(text("UPDATE hoimsystem_medical_record SET symptom=:body WHERE medical_record_id=:id"), dict(body="同一条原记录的新字面值，不自动归一化。", id=early.medical_record_id))
    db_session.commit()
    current = batch_current(db_session, case["admin_user"], made["batch_id"])
    assert current["original"] == made["original"] and not current["eligible"]
    assert "original_capture_or_creator_project_authority_no_longer_current" in current["exclusion_reasons"]
    with pytest.raises(HTTPException) as error:
        review_batch(db_session, case["super_admin_user"], made["batch_id"], technical_review())
    assert error.value.status_code == 409
    assert db_session.query(AIResearchVariableBatch.status).filter_by(batch_id=made["batch_id"]).scalar() == "draft"


def test_ordinary_admin_cannot_technically_publish_and_stale_revision_cannot_repeat_governance(db_session, variable_capture_case):
    case, _, _, _, _ = variable_capture_case
    made = make(db_session, variable_capture_case)
    with pytest.raises(HTTPException) as error:
        review_batch(db_session, case["admin_user"], made["batch_id"], technical_review())
    assert error.value.status_code == 403
    published = review_batch(db_session, case["super_admin_user"], made["batch_id"], technical_review())
    with pytest.raises(HTTPException) as error:
        review_batch(db_session, case["super_admin_user"], made["batch_id"], technical_review())
    assert error.value.status_code == 409
    assert batch_current(db_session, case["super_admin_user"], made["batch_id"]) == published


@pytest.mark.parametrize("fault", ["insert", "snapshot", "projection", "audit", "actor_role", "actor_token"])
def test_real_sql_creation_faults_roll_back_batch_audit_and_actor_changes_atomically(db_session, variable_capture_case, fault):
    case, _, _, _, _ = variable_capture_case
    actor_id = case["admin_user"].user_id
    original_role, original_token = case["admin_user"].user_role, case["admin_user"].token_invalid_before
    batch_count, audit_count = db_session.query(AIResearchVariableBatch).count(), db_session.query(AIAuditEvent).count()
    if fault == "insert":
        sql = "CREATE TRIGGER variable_batch_insert BEFORE INSERT ON hoimsystem_ai_research_variable_batch BEGIN SELECT RAISE(ABORT,'injected actual Batch insert failure'); END"
    elif fault in {"snapshot", "projection"}:
        column, path, value = ("snapshot_json", "$.created_by", "2147483647") if fault == "snapshot" else ("projection_json", "$.privacy_basis", "'anonymous'")
        sql = f"CREATE TRIGGER variable_batch_{fault} AFTER INSERT ON hoimsystem_ai_research_variable_batch BEGIN UPDATE hoimsystem_ai_research_variable_batch SET {column}=json_set({column},'{path}',{value}) WHERE batch_id=NEW.batch_id; END"
    elif fault == "audit":
        sql = "CREATE TRIGGER variable_batch_audit AFTER UPDATE OF detail_json ON hoimsystem_ai_audit_event WHEN NEW.action='research.variable_batch.create' BEGIN UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id; END"
    else:
        assignment = "user_role='director'" if fault == "actor_role" else "token_invalid_before='2099-01-01 00:00:00.000000'"
        sql = f"CREATE TRIGGER variable_batch_{fault} AFTER INSERT ON hoimsystem_ai_research_variable_batch BEGIN UPDATE hoimsystem_users SET {assignment} WHERE user_id={actor_id}; END"
    db_session.execute(text(sql))
    db_session.commit()
    try:
        with pytest.raises(IntegrityError if fault == "insert" else HTTPException) as error:
            make(db_session, variable_capture_case)
        if fault == "insert":
            assert "injected actual Batch insert failure" in str(error.value)
        else:
            assert error.value.status_code == (403 if fault in {"actor_role", "actor_token"} else 409)
        assert db_session.query(AIResearchVariableBatch).count() == batch_count
        assert db_session.query(AIAuditEvent).count() == audit_count
        from app.models import User

        actual = db_session.query(User).filter_by(user_id=actor_id).one()
        assert (actual.user_role, actual.token_invalid_before) == (original_role, original_token)
    finally:
        db_session.rollback()
        db_session.execute(text(f"DROP TRIGGER IF EXISTS variable_batch_{fault}"))
        db_session.commit()


@pytest.mark.parametrize("fault", ["snapshot", "projection", "create_audit", "create_clock", "private_key"])
def test_current_batch_read_rejects_actual_persisted_body_receipt_clock_or_key_tampering(db_session, variable_capture_case, fault):
    case, _, _, _, _ = variable_capture_case
    made = make(db_session, variable_capture_case)
    row = db_session.query(AIResearchVariableBatch).filter_by(batch_id=made["batch_id"]).one()
    if fault == "snapshot":
        value = copy.deepcopy(made["original"]["snapshot"])
        value["capture"]["records"].pop()
        import json

        row.snapshot_json = json.dumps(value, ensure_ascii=False)
    elif fault == "projection":
        row.projection_json = "{}"
    elif fault == "create_audit":
        db_session.query(AIAuditEvent).filter_by(event_id=row.created_event_id).update(dict(detail_json="{}"))
    elif fault == "create_clock":
        import datetime as dt

        db_session.query(AIAuditEvent).filter_by(event_id=row.created_event_id).update(dict(create_time=dt.datetime(2020, 1, 1)))
    else:
        row.identity_key = b"z" * 32
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        batch_current(db_session, case["super_admin_user"], made["batch_id"])
    assert error.value.status_code == 409
