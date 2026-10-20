"""Actual SQL surgery scenario governance and authority after real audit writes."""

import datetime
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError

from app.ai import surgery_facts as facts
from app.ai import surgery_scenarios as scenarios
from app.ai.models import AIAuditEvent
from app.ai.surgery_context import binding_for
from app.ai.surgery_contract import hash_content
from app.ai.surgery_scenario_models import AISurgeryScenario
from app.models import Doctor, User
from tests.test_ai_surgery_facts import NOTE, NOW, create
from tests.test_ai_surgery_facts import surgery_case as surgery_case
from tests.test_ai_surgery_snapshot import snapshot_case as snapshot_case


def draft_scenario(db, actual_case, actor=None):
    _snapshot, _captured, declaration, case = actual_case
    row = scenarios.create_scenario(db, actor or case["director"], declaration)
    db.commit()
    return row


def review_values(row, decision="publish"):
    return {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": decision, "basis_note": NOTE}


def revoke_values(row):
    return {"expected_revision": row.revision, "expected_content_hash": row.content_hash, "basis_note": NOTE}


def published_scenario(db, actual_case):
    row = draft_scenario(db, actual_case)
    scenarios.review_scenario(db, actual_case[3]["super"], row.scenario_id, review_values(row))
    db.commit()
    return row


def audit_count(db, scenario_id, action):
    return db.query(AIAuditEvent).filter_by(target=scenario_id, action="surgery.scenario." + action).count()


def test_actual_draft_publish_bind_and_revoke_keep_frozen_bytes_and_original_publication(db_session, snapshot_case):
    case = snapshot_case[3]
    row = draft_scenario(db_session, snapshot_case)
    original = row.snapshot_json, row.content_hash, row.collection_digest
    draft = scenarios.scenario_current(db_session, case["director"], row.scenario_id)
    assert draft["snapshot"] is not None and draft["public_source"] is None and draft["source_current"]
    assert not draft["eligible"] and draft["exclusion_reasons"] == ["scenario_draft"]
    assert not draft["can_review"] and draft["can_revoke"] and draft["candidate_only"] and not draft["automatic_booking"]
    with pytest.raises(HTTPException) as error:
        scenarios.authorize_scenario(db_session, case["director"], row.scenario_id)
    assert error.value.status_code == 409
    scenarios.review_scenario(db_session, case["super"], row.scenario_id, review_values(row))
    db_session.commit()
    current = scenarios.scenario_current(db_session, case["director"], row.scenario_id)
    assert current["eligible"] and current["source_current"] and current["public_source"] is not None
    assert current["public_source"]["content_hash"] == original[1] and current["projection_hash"] == hash_content(current["public_source"])
    assert current["public_source"]["governance_hash"] == current["governance_hash"]
    bound = binding_for(current["public_source"], pool_id=row.pool_id, department_id=row.department_id)
    assert scenarios.authorize_scenario(db_session, case["director"], row.scenario_id, binding=bound)[0].scenario_id == row.scenario_id
    projection_bytes, projection_hash = row.projection_json, row.projection_hash
    publication_hash = current["public_source"]["governance_hash"]
    scenarios.revoke_scenario(db_session, case["director"], row.scenario_id, revoke_values(row))
    db_session.commit()
    assert row.status == "revoked" and row.revision == 3
    assert (row.snapshot_json, row.content_hash, row.collection_digest) == original and (row.projection_json, row.projection_hash) == (projection_bytes, projection_hash)
    ordinary = scenarios.scenario_current(db_session, case["director"], row.scenario_id)
    audit = scenarios.scenario_current(db_session, case["super"], row.scenario_id, audit_only=True)
    assert ordinary["snapshot"] is None and ordinary["public_source"] is None and ordinary["review_basis_note"] is None and ordinary["revoke_reason"] is None
    assert audit["snapshot"] is not None and audit["public_source"]["governance_hash"] == publication_hash
    assert audit["governance_hash"] != publication_hash and not audit["eligible"]
    assert all(audit_count(db_session, row.scenario_id, action) == 1 for action in ("create", "publish", "revoke"))


@pytest.mark.parametrize("decision", ["reject", "draft_revoke"])
def test_rejected_and_revoked_drafts_are_terminal_without_fabricated_projection(db_session, snapshot_case, decision):
    case = snapshot_case[3]
    row = draft_scenario(db_session, snapshot_case)
    if decision == "reject":
        scenarios.review_scenario(db_session, case["super"], row.scenario_id, review_values(row, "reject"))
    else:
        scenarios.revoke_scenario(db_session, case["director"], row.scenario_id, revoke_values(row))
    db_session.commit()
    assert row.revision == 2 and row.projection_json is None and row.projection_hash is None
    assert scenarios.scenario_current(db_session, case["super"], row.scenario_id, audit_only=True)["snapshot"] is not None
    with pytest.raises(HTTPException) as error:
        scenarios.review_scenario(db_session, case["super"], row.scenario_id, review_values(row))
    assert error.value.status_code == 409
    db_session.rollback()
    with pytest.raises(HTTPException) as error:
        scenarios.revoke_scenario(db_session, case["super"], row.scenario_id, {"expected_revision": 2, "expected_content_hash": row.content_hash, "basis_note": NOTE})
    assert error.value.status_code == 409
    db_session.rollback()


@pytest.mark.parametrize("mutation", ["revision", "content_hash", "binding"])
def test_exact_cas_and_run_binding_reject_substitution_without_second_audit(db_session, snapshot_case, mutation):
    case = snapshot_case[3]
    row = draft_scenario(db_session, snapshot_case)
    request = review_values(row)
    if mutation == "revision":
        request["expected_revision"] = 1
        scenarios.review_scenario(db_session, case["super"], row.scenario_id, request)
        db_session.commit()
    elif mutation == "content_hash":
        request["expected_content_hash"] = "0" * 64
    else:
        scenarios.review_scenario(db_session, case["super"], row.scenario_id, request)
        db_session.commit()
        _, _, source = scenarios.authorize_scenario(db_session, case["director"], row.scenario_id)
        binding = binding_for(source, pool_id=row.pool_id, department_id=row.department_id)
        binding["collection_digest"] = "0" * 64
        with pytest.raises(HTTPException) as error:
            scenarios.authorize_scenario(db_session, case["director"], row.scenario_id, binding=binding)
        assert error.value.status_code == 409
        return
    with pytest.raises(HTTPException) as error:
        scenarios.review_scenario(db_session, case["super"], row.scenario_id, request)
    assert error.value.status_code == 409
    db_session.rollback()
    assert audit_count(db_session, row.scenario_id, "publish") == (1 if mutation == "revision" else 0)


@pytest.mark.parametrize("actor", ["doctor_user", "foreign_user", "admin"])
def test_care_and_operational_permissions_remain_separate_from_registry_or_signer(db_session, snapshot_case, actor):
    case = snapshot_case[3]
    current = case[actor] if actor != "admin" else case["seed"]["admin_user"]
    with pytest.raises(HTTPException) as error:
        scenarios.create_scenario(db_session, current, snapshot_case[2])
    assert error.value.status_code == 403
    db_session.rollback()
    row = draft_scenario(db_session, snapshot_case)
    with pytest.raises(HTTPException) as error:
        scenarios.review_scenario(db_session, case["director"], row.scenario_id, review_values(row))
    assert error.value.status_code == 403
    db_session.rollback()
    with pytest.raises(HTTPException) as error:
        scenarios.scenario_current(db_session, case["director"], row.scenario_id, audit_only=True)
    assert error.value.status_code == 403


@pytest.mark.parametrize("change", ["new_source", "revoke_source", "clinical_parent", "account_role"])
def test_source_membership_and_parent_change_redact_ordinary_but_super_keeps_own_hash(db_session, snapshot_case, change):
    case = snapshot_case[3]
    row = published_scenario(db_session, snapshot_case)
    before = row.snapshot_json, row.projection_json
    if change == "new_source":
        create(db_session, case)
    elif change == "revoke_source":
        source = db_session.query(facts.AISurgerySource).filter_by(pool_id=row.pool_id, source_kind="operating_room_identity_capability").one()
        facts.review_source(
            db_session, case["super"], source.source_kind, source.source_record_id, {"expected_revision": 2, "expected_content_hash": source.content_hash, "basis_note": NOTE}, revoke=True
        )
        db_session.commit()
    elif change == "clinical_parent":
        case["application"].preop_diagnosis = "真实合成病例父内容改变"
        db_session.commit()
    else:
        case["doctor_user"].user_role = "admin"
        db_session.commit()
    ordinary = scenarios.scenario_current(db_session, case["director"], row.scenario_id)
    audit = scenarios.scenario_current(db_session, case["super"], row.scenario_id, audit_only=True)
    assert ordinary["snapshot"] is None and ordinary["public_source"] is None and not ordinary["source_current"] and not ordinary["eligible"]
    assert audit["snapshot"] is not None and audit["public_source"] is not None and not audit["source_current"] and not audit["eligible"]
    assert (row.snapshot_json, row.projection_json) == before
    with pytest.raises(HTTPException) as error:
        scenarios.authorize_scenario(db_session, case["director"], row.scenario_id)
    assert error.value.status_code == 409
    db_session.rollback()
    # Super may still revoke the complete frozen original, without pretending it is current.
    scenarios.revoke_scenario(db_session, case["super"], row.scenario_id, revoke_values(row))
    db_session.commit()
    assert row.status == "revoked"


def test_past_start_is_readable_original_history_but_cannot_execute_new_tasks(db_session, snapshot_case, monkeypatch):
    case = snapshot_case[3]
    row = published_scenario(db_session, snapshot_case)
    monkeypatch.setattr(facts, "utcnow", lambda: NOW + datetime.timedelta(days=2))
    detail = scenarios.scenario_current(db_session, case["director"], row.scenario_id)
    assert detail["snapshot"] is not None and detail["public_source"] is not None and detail["source_current"]
    assert not detail["eligible"] and detail["exclusion_reasons"] == ["scenario_period_or_algorithm_changed"]
    assert scenarios.authorize_scenario(db_session, case["director"], row.scenario_id, execution=False)[0].scenario_id == row.scenario_id
    with pytest.raises(HTTPException) as error:
        scenarios.authorize_scenario(db_session, case["director"], row.scenario_id)
    assert error.value.status_code == 409


@pytest.mark.parametrize("tamper", ["private_bytes", "private_hash", "public_bytes", "public_rehashed", "row_scope"])
def test_super_audit_never_bypasses_bad_original_or_rehashed_false_projection(db_session, snapshot_case, tamper):
    case = snapshot_case[3]
    row = published_scenario(db_session, snapshot_case)
    if tamper == "private_bytes":
        row.snapshot_json += " "
    elif tamper == "private_hash":
        row.content_hash = "0" * 64
    elif tamper in {"public_bytes", "public_rehashed"}:
        value = json.loads(row.projection_json)
        value["problem_coverage"]["finite_domains_status"] = "unknown"
        row.projection_json = scenarios.bounded_json(value)
        if tamper == "public_rehashed":
            row.projection_hash = hash_content(value)
    else:
        row.department_id = case["foreign"].department_id
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        scenarios.scenario_current(db_session, case["super"], row.scenario_id, audit_only=True)
    assert error.value.status_code == 409
    db_session.rollback()
    with pytest.raises(HTTPException) as error:
        scenarios.revoke_scenario(db_session, case["super"], row.scenario_id, revoke_values(row))
    assert error.value.status_code == 409
    db_session.rollback()


@pytest.mark.parametrize("operation", ["create", "publish", "revoke"])
def test_actual_sql_audit_failure_rolls_back_whole_governance_and_frozen_projection(db_session, snapshot_case, operation):
    case = snapshot_case[3]
    row = None if operation == "create" else draft_scenario(db_session, snapshot_case)
    if operation == "revoke":
        scenarios.review_scenario(db_session, case["super"], row.scenario_id, review_values(row))
        db_session.commit()
    previous = None if row is None else (row.status, row.revision, row.snapshot_json, row.projection_json, row.projection_hash)
    before_count = db_session.query(AISurgeryScenario).filter_by(pool_id=case["pool"].pool_id).count()
    # A real SQLite trigger rejects the SQL audit INSERT. No current-authority,
    # collection, projection or persistence function is replaced by a fake.
    trigger = "test_reject_surgery_scenario_audit"
    action = "surgery.scenario." + operation
    db_session.execute(text(f"CREATE TEMP TRIGGER {trigger} BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='{action}' BEGIN SELECT RAISE(ABORT, 'isolated synthetic audit rejected'); END"))
    try:
        with pytest.raises(IntegrityError):
            if operation == "create":
                scenarios.create_scenario(db_session, case["director"], snapshot_case[2])
            elif operation == "publish":
                scenarios.review_scenario(db_session, case["super"], row.scenario_id, review_values(row))
            else:
                scenarios.revoke_scenario(db_session, case["super"], row.scenario_id, revoke_values(row))
    finally:
        db_session.rollback()
        db_session.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
        db_session.commit()
    assert db_session.query(AISurgeryScenario).filter_by(pool_id=case["pool"].pool_id).count() == before_count
    if row is not None:
        db_session.refresh(row)
        assert (row.status, row.revision, row.snapshot_json, row.projection_json, row.projection_hash) == previous
        assert audit_count(db_session, row.scenario_id, operation) == 0


@pytest.mark.parametrize("mutation", ["super_role", "case", "source", "membership"])
def test_post_audit_real_sql_mutation_is_rechecked_before_publish_acceptance(db_session, snapshot_case, mutation):
    case = snapshot_case[3]
    row = draft_scenario(db_session, snapshot_case)
    row_id, super_id = row.scenario_id, case["super"].user_id
    source = db_session.query(facts.AISurgerySource).filter_by(pool_id=row.pool_id, source_kind="operating_room_identity_capability").one()
    member = db_session.query(facts.AISurgeryPoolMembership).filter_by(pool_id=row.pool_id, resource_id=case["resources"]["room"].resource_id, status="published").one()
    source_id, member_id = source.source_record_id, member.membership_id
    application_id = case["application"].application_id
    values = review_values(row)
    state = {"fired": False}

    def mutate(connection, _cursor, statement, parameters, _context, _many):
        if state["fired"] or "INSERT INTO hoimsystem_ai_audit_event" not in statement or "surgery.scenario.publish" not in str(parameters):
            return
        state["fired"] = True
        if mutation == "super_role":
            connection.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": super_id})
        elif mutation == "case":
            connection.execute(text("UPDATE hoimsystem_surgery_application SET preop_diagnosis='actual synthetic mutation' WHERE application_id=:id"), {"id": application_id})
        elif mutation == "source":
            connection.execute(
                text("UPDATE hoimsystem_ai_surgery_source SET status='revoked',revision=3,revoked_by=:actor,revoked_at=:at,revoke_reason=:basis WHERE source_record_id=:id"),
                {"actor": super_id, "at": NOW.isoformat(sep=" ", timespec="microseconds"), "basis": NOTE, "id": source_id},
            )
        else:
            connection.execute(
                text("UPDATE hoimsystem_ai_surgery_pool_membership SET status='revoked',revision=3,active_pair_key=NULL,revoked_by=:actor,revoked_at=:at,revoke_reason=:basis WHERE membership_id=:id"),
                {"actor": super_id, "at": NOW.isoformat(sep=" ", timespec="microseconds"), "basis": NOTE, "id": member_id},
            )

    event.listen(db_session.get_bind(), "after_cursor_execute", mutate)
    try:
        with pytest.raises(HTTPException) as error:
            scenarios.review_scenario(db_session, case["super"], row_id, values)
        assert error.value.status_code in {403, 409}
    finally:
        event.remove(db_session.get_bind(), "after_cursor_execute", mutate)
        db_session.rollback()
    assert state["fired"]
    db_session.refresh(row)
    assert row.status == "draft" and row.revision == 1 and row.projection_json is None and row.projection_hash is None
    assert audit_count(db_session, row_id, "publish") == 0
    assert db_session.query(User).filter_by(user_id=super_id).one().user_role == "super_admin"
    assert db_session.query(facts.AISurgerySource).filter_by(source_record_id=source_id).one().status == "published"


def test_current_reads_are_locked_after_first_gate_and_sqlite_does_not_fake_row_locks(db_session, snapshot_case, monkeypatch):
    row = published_scenario(db_session, snapshot_case)
    case = snapshot_case[3]
    scenario_id = row.scenario_id
    actor = case["director"]
    queries, executed = [], []
    original = facts.current_query

    def current(query, *, locking=False):
        query = original(query, locking=locking)
        queries.append(str(query.statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})))
        return query

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        executed.append(statement)

    monkeypatch.setattr(facts, "current_query", current)
    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        scenarios.authorize_scenario(db_session, actor, scenario_id, locking=True)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)
    assert "INSERT" in executed[0].upper() and "hoimsystem_ai_surgery_write_gate" in executed[0]
    assert queries and all("FOR UPDATE" in statement for statement in queries)
    assert any("FROM hoimsystem_ai_surgery_scenario" in statement for statement in queries)
    assert not any("FOR UPDATE" in statement for statement in executed)


def test_super_creator_demotion_after_audit_does_not_skip_ordinary_current_care(db_session, snapshot_case):
    case = snapshot_case[3]
    super_id = case["super"].user_id
    # This actual alias grants Pool scope after demotion, but no original care:
    # it neither owns the admission nor participates in an original schedule.
    alias = Doctor(name="合成仅资源池范围医师", department_id=case["department"].department_id, user_id=super_id, permission="doctor")
    db_session.add(alias)
    db_session.commit()
    row = draft_scenario(db_session, snapshot_case, actor=case["super"])
    row_id, values = row.scenario_id, revoke_values(row)
    state = {"fired": False}

    def demote(connection, _cursor, statement, parameters, _context, _many):
        if state["fired"] or "INSERT INTO hoimsystem_ai_audit_event" not in statement or "surgery.scenario.revoke" not in str(parameters):
            return
        state["fired"] = True
        connection.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": super_id})

    event.listen(db_session.get_bind(), "after_cursor_execute", demote)
    try:
        with pytest.raises(HTTPException) as error:
            scenarios.revoke_scenario(db_session, case["super"], row_id, values)
        assert error.value.status_code in {403, 409}
    finally:
        event.remove(db_session.get_bind(), "after_cursor_execute", demote)
        db_session.rollback()
    assert state["fired"]
    db_session.refresh(row)
    assert row.status == "draft" and row.revision == 1 and audit_count(db_session, row_id, "revoke") == 0


@pytest.mark.parametrize("parent", ["source", "pool"])
def test_super_valid_scenario_own_audit_survives_damaged_live_dependency_without_new_eligibility(db_session, snapshot_case, parent):
    case = snapshot_case[3]
    row = published_scenario(db_session, snapshot_case)
    before = row.snapshot_json, row.projection_json
    if parent == "pool":
        case["pool"].content_hash = "0" * 64
    else:
        original = db_session.query(facts.AISurgerySource).filter_by(pool_id=row.pool_id, source_kind="case_requirements").one()
        original.content_hash = "0" * 64
    db_session.commit()
    result = scenarios.scenario_current(db_session, case["super"], row.scenario_id, audit_only=True)
    assert result["snapshot"] is not None and result["public_source"] is not None and not result["source_current"] and not result["eligible"]
    assert (row.snapshot_json, row.projection_json) == before
    with pytest.raises(HTTPException) as error:
        scenarios.authorize_scenario(db_session, case["super"], row.scenario_id)
    assert error.value.status_code == 409
    db_session.rollback()
    scenarios.revoke_scenario(db_session, case["super"], row.scenario_id, revoke_values(row))
    db_session.commit()
    assert row.status == "revoked" and row.revision == 3
    assert (row.snapshot_json, row.projection_json) == before
