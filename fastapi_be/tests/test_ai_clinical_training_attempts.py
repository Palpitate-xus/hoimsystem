"""Actual unique claim/dispatch Audit PK and current-authority SQL stages."""

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import clinical_training_attempts as a
from app.ai import clinical_training_reviews as reviews
from app.ai import clinical_training_storage as s
from app.ai.models import AIAuditEvent
from tests.test_ai_clinical_training_configuration import configured as configured
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_registry import observe_bodies
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case
from tests.test_ai_clinical_training_storage import assert_zero_bodies, counts
from tests.test_ai_clinical_training_storage import stored as stored


def test_actual_claim_and_dispatch_specific_pk_full_utc6_lease_and_no_duplicate_stage(stored):
    case, key = stored
    db = case["db"]
    before = counts(db)
    claim = a.stage_claim(db, case["actor"], key)
    assert claim.schema_version == "clinical_training_claim_v1" and claim.submission_id == case["submission"]["submission_id"]
    header, run = a.phase_header(db, key), s.run_header(db, key)
    assert header["claimed_at"] == a.clock(claim.claimed_at) and header["lease_token"] == claim.lease_token == run["lease_token"]
    assert run["start_time"] == header["claimed_at"].replace(microsecond=0) and run["status"] == "running"
    assert a.claim_from_headers(db, header, run) == claim
    assert db.get(AIAuditEvent, claim.claim_event_id).action == a.CLAIM_ACTION
    assert a.stage_claim(db, case["actor"], key) is None
    dispatched = a.stage_dispatch(db, case["actor"], claim)
    assert dispatched.schema_version == "clinical_training_dispatch_v1" and dispatched.claim_event_id == claim.claim_event_id
    assert a.clock(dispatched.dispatched_at) >= header["claimed_at"]
    assert len({claim.created_audit_event_id, claim.claim_event_id, dispatched.dispatch_event_id}) == 3
    assert db.get(AIAuditEvent, dispatched.dispatch_event_id).action == a.DISPATCH_ACTION
    assert a.stage_dispatch(db, case["actor"], claim) is None
    actual = a.technical_attempt(db, claim)
    assert actual.claim == claim and actual.dispatch == dispatched
    assert counts(db)[AIAuditEvent.__tablename__] == before[AIAuditEvent.__tablename__] + 2


def test_actual_unclaimed_technical_header_never_manufactures_attempt_or_reads_source_body(stored):
    case, key = stored
    db = case["db"]
    columns, observer = observe_bodies(db)
    try:
        actual = a.technical_header(db, key)
        assert actual.claim is actual.dispatch is None and actual.header["status"] == "queued"
        assert actual.artifact["claim_event_id"] is actual.artifact["lease_token"] is actual.artifact["claimed_at"] is None
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)


@pytest.mark.parametrize("phase", ["claim", "dispatch"])
@pytest.mark.parametrize("fault", ["source_revoked", "owner_epoch", "disabled", "provider_revision"])
def test_current_source_epoch_config_loss_denies_claim_dispatch_before_bodies_without_stage_audit(stored, phase, fault):
    case, key = stored
    db = case["db"]
    claim = a.stage_claim(db, case["actor"], key) if phase == "dispatch" else None
    if fault == "source_revoked":
        reviews.revoke_review(db, case["author"], case["review"]["review_id"], dict(revision=1, reason="明确本次模型处理撤回"))
    elif fault == "owner_epoch":
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:key"), dict(key=case["actor"].user_id, clock=dt.datetime.now(dt.UTC).replace(tzinfo=None)))
    elif fault == "disabled":
        case["config"].enabled = 0
    else:
        case["provider"].revision += 1
    db.flush()
    before = counts(db)
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            a.stage_dispatch(db, case["actor"], claim) if claim else a.stage_claim(db, case["actor"], key)
        assert error.value.status_code in {403, 409}
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
    assert counts(db) == before


@pytest.mark.parametrize("field", ["lease_token", "claim_event_id", "source_projection_hash", "source_binding_hash", "instructions_digest", "claimed_at"])
def test_closed_forged_claim_is_not_dispatch_authority_and_refuses_before_all_bodies(stored, field):
    case, key = stored
    db = case["db"]
    claim = a.stage_claim(db, case["actor"], key)
    value = claim.model_dump(mode="json")
    if field == "lease_token":
        value[field] = str(uuid.uuid4())
    elif field == "claim_event_id":
        event_row = AIAuditEvent(actor_id=case["actor"].user_id, action="synthetic.actual.unrelated.claim", target=key, detail_json="{}")
        db.add(event_row)
        db.flush()
        value[field] = event_row.event_id
    elif field == "claimed_at":
        value[field] = s.references.utc_text(a.clock(value[field]) + dt.timedelta(microseconds=1))
    else:
        value[field] = "0" * 64
    columns, observer = observe_bodies(db)
    before = counts(db)
    try:
        with pytest.raises(HTTPException) as error:
            a.stage_dispatch(db, case["actor"], value)
        assert error.value.status_code == 409
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
    assert counts(db) == before


@pytest.mark.parametrize("phase", ["claim", "dispatch"])
def test_actual_post_phase_update_reference_mutation_rolls_back_caller_transaction(stored, phase):
    case, key = stored
    db = case["db"]
    claim = a.stage_claim(db, case["actor"], key) if phase == "dispatch" else None
    db.commit()
    before = counts(db)
    trigger = "training_after_" + phase + "_update"
    field = "claim_event_id" if phase == "claim" else "dispatch_event_id"
    document_id = case["documents"][0].document_id
    db.execute(text("CREATE TEMP TRIGGER " + trigger + " AFTER UPDATE OF " + field + " ON hoimsystem_ai_training_run_artifact WHEN NEW." + field + " IS NOT NULL AND OLD." + field + " IS NULL BEGIN UPDATE hoimsystem_ai_knowledge_document SET status='retired' WHERE document_id='" + document_id + "'; END"))
    db.commit()
    try:
        with pytest.raises(HTTPException) as error:
            a.stage_dispatch(db, case["actor"], claim) if claim else a.stage_claim(db, case["actor"], key)
        assert error.value.status_code in {403, 409}
        db.rollback()
        assert counts(db) == before
        assert db.execute(text("SELECT status FROM hoimsystem_ai_knowledge_document WHERE document_id=:key"), dict(key=document_id)).scalar_one() == "published"
        actual = a.technical_header(db, key)
        assert actual.dispatch is None and (actual.claim == claim if claim else actual.claim is None)
    finally:
        db.execute(text("DROP TRIGGER IF EXISTS " + trigger))
        db.commit()
