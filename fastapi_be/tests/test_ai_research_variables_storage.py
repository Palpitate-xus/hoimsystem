"""Actual Source/config -> short Run/artifact and creation-audit atomicity.

No claim, dispatch, receipt, provider call, successful result or API is claimed
by this first creation layer. Independent SQL model tests own FK enforcement.
"""

import copy
import hashlib
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import Select, event, inspect, text
from sqlalchemy.exc import IntegrityError

from app.ai import research_variables_storage as storage
from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_variables_configuration import current_configuration
from app.ai.research_variables_run_models import ANCHOR_FIELDS, AIResearchVariableRunArtifact, AIResearchVariableRunResult
from app.ai.research_variables_task_context import prepare_context
from app.ai.research_variables_task_contract import canonical, digest
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory


@pytest.fixture(autouse=True)
def cleanup_trigger(db_session):
    yield
    db_session.rollback()
    db_session.execute(text("DROP TRIGGER IF EXISTS variable_task_stage_fault"))
    db_session.commit()


def prepare(db, configured, task_factory):
    case, _, _, permissions, batch, _ = task_factory()
    actor = case["admin_user"]
    prepared = prepare_context(db, actor, {"research_variable_batch_id": batch["batch_id"], "question": "\ufeff保留原单位和未知\r\n🧪e\u0301"})
    actual = current_configuration(db, actor, preview=False)
    return case, permissions, batch, prepared, storage.snapshot_for_context(prepared, actual)


def counts(db):
    return tuple(db.query(model).count() for model in (AIRun, AIResearchVariableRunArtifact, AIResearchVariableRunResult, AIAuditEvent))


def test_actual_source_config_stage_has_short_run_full_source_independent_binding_and_exact_creation_pk_without_claim(db_session, configured, task_factory):
    case, _, batch, prepared, snapshot = prepare(db_session, configured, task_factory)
    before = counts(db_session)
    staged = storage.stage_run(db_session, case["admin_user"], AIRun(run_id=str(uuid.uuid4()), preview=0), prepared, snapshot)
    db_session.commit()
    run, artifact = staged.run, staged.artifact
    assert run.feature_key == "research_extraction" and run.patient_id is None and run.encounter_ref is None and run.status == "queued"
    assert inspect(run).identity[0] == artifact.run_id and artifact.batch_id == batch["batch_id"]
    assert run.result_json == "{}" and not any(getattr(artifact, key) for key in ("claim_event_id", "claim_lease", "claimed_at", "dispatch_event_id", "dispatched_at", "usage_event_id"))
    assert counts(db_session) == (before[0] + 1, before[1] + 1, before[2], before[3] + 1)
    assert artifact.source_json == canonical(prepared.source) and artifact.binding_json == canonical(prepared.binding)
    assert all(len(getattr(run, key).encode()) <= 65535 for key in storage.RUN_TEXT)
    assert "documents" not in storage.canonical_value(run.input_json)["payload"]["context"]
    assert artifact.recorded_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ") == snapshot.payload.context.snapshot_time
    assert run.create_time == artifact.recorded_at.replace(microsecond=0)
    audit = db_session.get(AIAuditEvent, artifact.create_event_id)
    assert audit.action == "research_variable_run.create" and audit.create_time == run.create_time
    assert storage.canonical_value(audit.detail_json) == storage.creation_detail(run, artifact)
    expected = {
        "input_hash": hashlib.sha256(run.input_json.encode()).hexdigest(),
        "evidence_hash": hashlib.sha256(run.evidence_json.encode()).hexdigest(),
        "metadata_hash": hashlib.sha256(run.context_metadata_json.encode()).hexdigest(),
        "prompt_hash": run.prompt_hash,
        "context_digest": run.context_digest,
        "instructions_digest": storage.types.instructions_digest(snapshot),
        "source_hash": hashlib.sha256(artifact.source_json.encode()).hexdigest(),
        "binding_hash": hashlib.sha256(artifact.binding_json.encode()).hexdigest(),
    }
    assert {key: getattr(artifact, key) for key in ANCHOR_FIELDS} == expected
    assert digest(prepared.data) == run.context_digest


@pytest.mark.parametrize("which", ["role", "epoch", "patient_permission", "config"])
def test_original_permission_or_configuration_change_prevents_new_task_and_audit_creation(db_session, configured, task_factory, which):
    case, permissions, _, prepared, snapshot = prepare(db_session, configured, task_factory)
    actor = case["admin_user"]
    if which == "patient_permission":
        review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    elif which == "config":
        configured[1].revision += 1
        db_session.commit()
    else:
        actor.user_role = "director" if which == "role" else actor.user_role
        if which == "epoch":
            import datetime as dt

            actor.token_invalid_before = dt.datetime(2026, 10, 21)
        db_session.commit()
    before = counts(db_session)
    with pytest.raises(HTTPException) as error:
        storage.stage_run(db_session, actor, AIRun(run_id=str(uuid.uuid4()), preview=0), prepared, snapshot)
    assert error.value.status_code in {403, 409} and counts(db_session) == before


@pytest.mark.parametrize("fault", ["header", "auth_header", "phase", "audit", "audit_abort", "source", "actor"])
def test_actual_postflush_sql_mutations_roll_back_run_artifact_creation_audit_and_source_side_effect(db_session, configured, task_factory, fault):
    case, _, batch, prepared, snapshot = prepare(db_session, configured, task_factory)
    before = counts(db_session)
    if fault == "audit_abort":
        trigger = "CREATE TRIGGER variable_task_stage_fault BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='research_variable_run.create' BEGIN SELECT RAISE(ABORT,'controlled actual creation audit abort'); END"
    elif fault == "audit":
        trigger = "CREATE TRIGGER variable_task_stage_fault AFTER UPDATE OF detail_json ON hoimsystem_ai_audit_event WHEN NEW.action='research_variable_run.create' BEGIN UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id; END"
    else:
        mutations = {
            "header": "UPDATE hoimsystem_ai_run SET status='succeeded' WHERE run_id=NEW.run_id;",
            "auth_header": "UPDATE hoimsystem_ai_research_variable_run_artifact SET request_authorization_hash='" + "f" * 64 + "' WHERE run_id=NEW.run_id;",
            "phase": "UPDATE hoimsystem_ai_research_variable_run_artifact SET claim_event_id=(SELECT MIN(event_id) FROM hoimsystem_ai_audit_event),claim_lease='00000000-0000-0000-0000-000000000001',claimed_at=NEW.recorded_at WHERE run_id=NEW.run_id;",
            "source": "UPDATE hoimsystem_ai_research_variable_batch SET snapshot_json='{}' WHERE batch_id=NEW.batch_id;",
            "actor": "UPDATE hoimsystem_users SET user_role='nurse' WHERE user_id=NEW.requested_by;",
        }
        trigger = "CREATE TRIGGER variable_task_stage_fault AFTER INSERT ON hoimsystem_ai_research_variable_run_artifact BEGIN " + mutations[fault] + " END"
    db_session.execute(text(trigger))
    statements = []
    mutations = []

    def seen(state):
        if state.is_select and isinstance(state.statement, Select):
            statements.extend(column.key for column in state.statement.selected_columns)

    def emitted(conn, cursor, statement, parameters, ctx, many):
        if statement.lstrip().startswith("INSERT INTO hoimsystem_ai_"):
            mutations.append(statement)

    event.listen(db_session, "do_orm_execute", seen)
    event.listen(db_session.bind, "before_cursor_execute", emitted)
    try:
        with pytest.raises((HTTPException, IntegrityError)) as error:
            storage.stage_run(db_session, case["admin_user"], AIRun(run_id=str(uuid.uuid4()), preview=0), prepared, snapshot)
    finally:
        event.remove(db_session, "do_orm_execute", seen)
        event.remove(db_session.bind, "before_cursor_execute", emitted)
    assert any(statement.startswith("INSERT INTO hoimsystem_ai_run ") for statement in mutations)
    if fault == "audit_abort":
        assert isinstance(error.value, IntegrityError) and "controlled actual creation audit abort" in str(error.value)
    else:
        assert any(statement.startswith("INSERT INTO hoimsystem_ai_research_variable_run_artifact ") for statement in mutations)
        assert isinstance(error.value, HTTPException) and error.value.status_code == (403 if fault == "actor" else 409)
    assert counts(db_session) == before
    assert case["admin_user"].user_role == "admin"
    original = db_session.execute(text("SELECT snapshot_json FROM hoimsystem_ai_research_variable_batch WHERE batch_id=:id"), {"id": batch["batch_id"]}).scalar_one()
    assert storage.canonical_value(original, 8388608) == batch["original"]["snapshot"]
    if fault in {"header", "auth_header", "phase", "audit"}:
        assert not set(storage.RUN_TEXT + storage.ART_TEXT).intersection(statements)


def test_full_source_and_evidence_cannot_be_rebound_in_both_mutable_copies(db_session, configured, task_factory):
    case, _, _, prepared, snapshot = prepare(db_session, configured, task_factory)
    changed = copy.deepcopy(snapshot.model_dump(mode="json"))
    changed["payload"]["evidence"][0]["documents_hash"] = "f" * 64
    before = counts(db_session)
    with pytest.raises(ValueError):
        storage.stage_run(db_session, case["admin_user"], AIRun(run_id=str(uuid.uuid4()), preview=0), prepared, changed)
    assert counts(db_session) == before
