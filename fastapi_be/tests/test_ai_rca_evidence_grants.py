"""Actual synthetic purpose SQL/audit atomicity, not MySQL waits or Source API."""

import datetime as dt
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import Select, event, inspect, text

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as g
from app.ai.models import AIAuditEvent
from app.ai.rca_evidence_models import AIRcaPurposeGrant
from app.database import Base
from app.models import AdverseEvent, Patient, User
from tests.rca_sqlite_test_support import preserve_foreign_key_mode

NOW = dt.datetime(2026, 10, 21, 12, 0, 0, 123456)
NOTE = "仅此实际事件与关联患者的本次RCA调查用途；不认证临床因果。"


@pytest.fixture
def grant_case(db_session, seed_data, monkeypatch):
    db = db_session
    with preserve_foreign_key_mode(db):
        Base.metadata.create_all(db.get_bind())
        patient = Patient(name="合成用途主体", identity="rca-synthetic-" + __import__("uuid").uuid4().hex, permission="allow")
        db.add(patient)
        db.flush()
        original = AdverseEvent(
            patient_id=patient.patient_id, reporter_id=seed_data["doctor_user"].user_id, description="尚未授权时不可读取的合成事件正文", handle_result="不能自动认定原因", severity=0, status=0
        )
        db.add(original)
        db.commit()
        monkeypatch.setattr(g, "utcnow", lambda: NOW)
        yield {"db": db, "actor": seed_data["super_admin_user"], "users": seed_data, "event_id": inspect(original).identity[0], "patient_id": inspect(patient).identity[0]}


def body(case, kind, **values):
    return {
        "event_id": case["event_id"],
        "expected_event_patient_id": case["patient_id"],
        "grantee_id": inspect(case["actor"]).identity[0],
        "permission_kind": kind,
        "purpose": "incident_rca",
        "valid_until": (NOW + dt.timedelta(days=1)).isoformat(timespec="microseconds") + "Z",
        "basis_note": NOTE,
        "explicit_scope_review": True,
        **values,
    }


def issue(case, kind="event_investigation", **values):
    result = g.create_grant(case["db"], case["actor"], body(case, kind, **values))
    case["db"].commit()
    return result


def both(case):
    return issue(case), issue(case, "associated_patient_processing")


def cas(record):
    return {"expected_revision": record.governance.revision, "expected_content_hash": record.content_hash, "expected_governance_hash": record.governance_hash, "basis_note": NOTE}


def no_source_text(db, callback):
    fields = []

    def observe(state):
        if state.is_select and isinstance(state.statement, Select):
            fields.extend(column.key for column in state.statement.selected_columns)

    event.listen(db, "do_orm_execute", observe)
    try:
        value = callback()
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert not {"description", "event_type", "handle_result", "root_cause", "timeline", "original_json", "case_json"}.intersection(fields)
    return value, fields


def deny(case, status=403):
    with pytest.raises(HTTPException) as error:
        g.authorize_event(case["db"], case["actor"], case["event_id"])
    assert error.value.status_code == status


def audit_count(db):
    return db.query(AIAuditEvent).filter(AIAuditEvent.action.like("rca_grant.%")).count()


def test_current_super_without_event_purpose_does_not_read_source_text(grant_case):
    _, fields = no_source_text(grant_case["db"], lambda: deny(grant_case))
    assert "grant_json" not in fields


def test_each_patient_linked_event_needs_two_independent_actual_purpose_rows(grant_case):
    case, db = grant_case, grant_case["db"]
    first = issue(case)
    no_source_text(db, lambda: deny(case))
    second = issue(case, "associated_patient_processing")
    authorization, fields = no_source_text(db, lambda: g.authorize_event(db, case["actor"], case["event_id"]))
    assert authorization.event_grant.identity.grant_id == first.identity.grant_id
    assert authorization.patient_grant.identity.grant_id == second.identity.grant_id
    assert first.identity.grant_id != second.identity.grant_id
    assert first.governance.created_audit_event_id != second.governance.created_audit_event_id
    assert first.identity.issued_at == "2026-10-21T12:00:00.123456Z"
    audit = db.get(AIAuditEvent, first.governance.created_audit_event_id)
    assert audit.create_time == NOW.replace(microsecond=0)
    assert json.loads(audit.detail_json)["recorded_at_utc6"] == first.identity.issued_at
    assert "grant_json" in fields


def test_patient_purpose_without_independent_event_purpose_is_not_enough(grant_case):
    issue(grant_case, "associated_patient_processing")
    no_source_text(grant_case["db"], lambda: deny(grant_case))


def test_another_super_does_not_inherit_the_issued_users_purpose(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    other = User(username="rca_other_" + __import__("uuid").uuid4().hex[:7], password="synthetic-unused", user_role="super_admin")
    db.add(other)
    db.commit()
    case = {**case, "actor": other}
    no_source_text(db, lambda: deny(case))


@pytest.mark.parametrize("current", [None, 2, "new"])
def test_event_patient_replacement_or_null_invalidates_old_purposes_before_source_body(grant_case, current):
    case, db = grant_case, grant_case["db"]
    if current == "new":
        db.execute(text("UPDATE hoimsystem_adverse_event SET patient_id=NULL WHERE event_id=:id"), {"id": case["event_id"]})
        db.commit()
        case["patient_id"] = None
        record = issue(case)
        current = grant_case["db"].query(Patient.patient_id).filter(Patient.patient_id.is_not(None)).order_by(Patient.patient_id.desc()).first()[0]
    else:
        record, _ = both(case)
        if current == 2:
            patient = Patient(name="不同合成主体", identity="rca-new-" + __import__("uuid").uuid4().hex, permission="allow")
            db.add(patient)
            db.flush()
            current = patient.patient_id
    db.execute(text("UPDATE hoimsystem_adverse_event SET patient_id=:patient WHERE event_id=:id"), {"patient": current, "id": case["event_id"]})
    db.commit()
    no_source_text(db, lambda: deny(case))
    view = g.grant_detail(db, case["actor"], record.identity.grant_id)
    assert not view.current_scope and "event_patient_changed" in view.scope_reasons


def test_patientless_event_does_not_invent_a_patient_purpose_or_encounter(grant_case):
    case, db = grant_case, grant_case["db"]
    db.execute(text("UPDATE hoimsystem_adverse_event SET patient_id=NULL WHERE event_id=:id"), {"id": case["event_id"]})
    db.commit()
    case["patient_id"] = None
    issue(case)
    current = g.authorize_event(db, case["actor"], case["event_id"])
    assert current.identity.patient_id is None and current.patient_grant is None
    with pytest.raises(HTTPException) as error:
        issue(case, "associated_patient_processing")
    assert error.value.status_code == 422


@pytest.mark.parametrize("permission", [None, "deny", "unknown"])
def test_explicit_patient_processing_grant_does_not_override_actual_patient_permission(grant_case, permission):
    case, db = grant_case, grant_case["db"]
    both(case)
    db.execute(text("UPDATE hoimsystem_patient SET permission=:permission WHERE patient_id=:id"), {"permission": permission, "id": case["patient_id"]})
    db.commit()
    no_source_text(db, lambda: deny(case))


def test_exact_expiry_boundary_denies_before_any_grant_or_source_body(grant_case, monkeypatch):
    record, _ = both(grant_case)
    monkeypatch.setattr(g, "utcnow", lambda: NOW + dt.timedelta(days=1))
    _, fields = no_source_text(grant_case["db"], lambda: deny(grant_case))
    assert "grant_json" not in fields
    assert "grant_expired" in g.grant_detail(grant_case["db"], grant_case["actor"], record.identity.grant_id).scope_reasons


def test_revoke_is_cas_bound_and_cannot_be_repeated_or_used_as_current_permission(grant_case):
    case, db = grant_case, grant_case["db"]
    record, _ = both(case)
    revoked = g.revoke_grant(db, case["actor"], record.identity.grant_id, cas(record))
    db.commit()
    assert revoked.governance.revision == 2 and revoked.scope_reasons == ["grant_revoked"]
    assert revoked.identity == record.identity
    count = audit_count(db)
    no_source_text(db, lambda: deny(case))
    with pytest.raises(HTTPException) as error:
        g.revoke_grant(db, case["actor"], record.identity.grant_id, cas(record))
    assert error.value.status_code == 409 and audit_count(db) == count


@pytest.mark.parametrize("change", ["role", "token"])
def test_current_actor_epoch_loss_precedes_private_source_text(grant_case, change):
    case, db = grant_case, grant_case["db"]
    both(case)
    actor = case["actor"]
    assert actor.user_role == "super_admin" and actor.token_invalid_before is None
    sql = "user_role='admin'" if change == "role" else "token_invalid_before='2030-01-01 00:00:00.123456'"
    db.execute(text("UPDATE hoimsystem_users SET " + sql + " WHERE user_id=:id"), {"id": actor.user_id})
    no_source_text(db, lambda: deny(case))
    db.rollback()


def test_self_rehashed_grant_body_cannot_replace_its_independent_audit(grant_case):
    case, db = grant_case, grant_case["db"]
    record, _ = both(case)
    row = db.get(AIRcaPurposeGrant, record.identity.grant_id)
    identity = json.loads(row.grant_json)
    identity["basis_note"] += "未经原签署的替换"
    row.grant_json, row.content_hash = c.canonical(identity), c.digest(identity)
    db.commit()
    no_source_text(db, lambda: deny(case, 409))


@pytest.mark.parametrize("fault", ["audit", "event", "actor"])
def test_real_sql_trigger_after_new_grant_rolls_back_grant_audit_and_side_effect(grant_case, fault):
    case, db = grant_case, grant_case["db"]
    grant_before, audit_before = db.query(AIRcaPurposeGrant).count(), audit_count(db)
    actor_id = inspect(case["actor"]).identity[0]
    if fault == "audit":
        sql = "CREATE TRIGGER rca_grant_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_grant.create' BEGIN UPDATE hoimsystem_ai_audit_event SET target='forged-target' WHERE event_id=NEW.event_id; END"
    elif fault == "event":
        sql = f"CREATE TRIGGER rca_grant_fault AFTER INSERT ON hoimsystem_ai_rca_purpose_grant BEGIN UPDATE hoimsystem_adverse_event SET patient_id=NULL WHERE event_id={case['event_id']}; END"
    else:
        sql = f"CREATE TRIGGER rca_grant_fault AFTER INSERT ON hoimsystem_ai_rca_purpose_grant BEGIN UPDATE hoimsystem_users SET user_role='admin' WHERE user_id={actor_id}; END"
    db.execute(text(sql))
    db.commit()
    try:
        with pytest.raises(HTTPException) as error:
            issue(case)
        assert error.value.status_code in {403, 409}
        assert db.query(AIRcaPurposeGrant).count() == grant_before and audit_count(db) == audit_before
        assert db.get(AdverseEvent, case["event_id"]).patient_id == case["patient_id"]
        assert db.get(User, actor_id).user_role == "super_admin"
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER rca_grant_fault"))
        db.commit()


def test_real_sql_revoke_mutation_rolls_back_both_revocation_and_specific_audit(grant_case):
    case, db = grant_case, grant_case["db"]
    record = issue(case)
    before = audit_count(db)
    db.execute(
        text(
            "CREATE TRIGGER rca_revoke_fault AFTER UPDATE ON hoimsystem_ai_rca_purpose_grant WHEN NEW.status='revoked' BEGIN UPDATE hoimsystem_ai_rca_purpose_grant SET grant_json='{}' WHERE grant_id=NEW.grant_id; END"
        )
    )
    db.commit()
    try:
        with pytest.raises(HTTPException) as error:
            g.revoke_grant(db, case["actor"], record.identity.grant_id, cas(record))
        assert error.value.status_code == 409 and audit_count(db) == before
        assert g.grant_detail(db, case["actor"], record.identity.grant_id).governance.status == "active"
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER rca_revoke_fault"))
        db.commit()
