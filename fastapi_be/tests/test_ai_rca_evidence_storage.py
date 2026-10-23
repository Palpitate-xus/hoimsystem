"""Actual Source/Run/Artifact SQL, short storage and pre-Task authority.

No configured feature execution, shared dispatch, model call or receipt stage
is claimed by these initial storage tests. Later runtime tests own that scope.
"""

import datetime as dt
import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import Select, event, inspect, text

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_storage as storage
from app.ai.models import AIAuditEvent, AIProvider, AIRun
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact, AIRcaEvidenceRunResult
from app.ai.runtime import provider_snapshot
from app.database import Base
from app.models import AdverseEvent, AdverseEventRca, User
from tests.test_ai_rca_evidence_context import prepared
from tests.test_ai_rca_evidence_grants import NOW, cas, issue
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_sources import seed_rca
from tests.test_ai_rca_evidence_storage_contract import snapshot


@pytest.fixture(autouse=True)
def cleanup_task_trigger(db_session):
    yield
    db_session.rollback()
    db_session.execute(text("DROP TRIGGER IF EXISTS rca_task_fault"))
    db_session.commit()


def stage(case, *, commit=True):
    db = case["db"]
    Base.metadata.create_all(db.get_bind())
    db.execute(text("PRAGMA foreign_keys=ON"))
    assert db.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    value, _ = prepared(case)
    provider = AIProvider(
        name="synthetic-rca-storage-" + uuid.uuid4().hex[:8],
        kind="chat",
        api_base="https://synthetic.invalid/v1",
        model="synthetic-no-model-call",
        allows_patient_data=1,
        api_key_env="",
        max_output_tokens=4096,
        temperature=0.2,
        timeout_seconds=3,
        revision=1,
        created_by=case["actor"].user_id,
    )
    db.add(provider)
    db.commit()
    raw = snapshot(value)
    raw["provider_snapshot"] = provider_snapshot(provider)
    epoch = case["actor"].token_invalid_before
    raw["actor_epoch"]["token_invalid_before"] = None if epoch is None else epoch.isoformat(timespec="microseconds") + "Z"
    run = AIRun(run_id=str(uuid.uuid4()), prompt_version=0, preview=1)
    result = storage.stage_run(db, case["actor"], run, value, raw)
    if commit:
        db.commit()
    return result, value


def task_counts(db):
    return tuple(db.query(model).count() for model in (AIRun, AIRcaEvidenceRunArtifact, AIRcaEvidenceRunResult, AIAuditEvent, AdverseEventRca))


def no_task_text(db, callback):
    seen = []

    def observe(state):
        if state.is_select and isinstance(state.statement, Select):
            seen.extend(column.key for column in state.statement.selected_columns if column.key in {*storage.RUN_TEXT, *storage.ART_TEXT, "result_json"})

    event.listen(db, "do_orm_execute", observe)
    try:
        return callback(), seen
    finally:
        event.remove(db, "do_orm_execute", observe)


def denied(db, callback, code):
    def attempt():
        with pytest.raises(HTTPException) as failure:
            callback()
        assert failure.value.status_code == code

    _, seen = no_task_text(db, attempt)
    assert not seen


def test_actual_stage_whole_source_and_short_run_input_have_exact_independent_sql_anchor(grant_case):
    case, db = grant_case, grant_case["db"]
    stored, prepared_value = stage(case)
    identifier = inspect(stored.run).identity[0]
    row = db.get(AIRcaEvidenceRunArtifact, identifier)
    assert row.event_grant_id != row.patient_grant_id and row.create_event_id is not None
    assert row.claim_event_id is row.dispatch_event_id is row.usage_event_id is None
    assert row.recorded_at == NOW and stored.run.create_time == NOW.replace(microsecond=0)
    assert row.source_hash == c.digest(prepared_value.source) and row.binding_hash == c.digest(prepared_value.binding)
    assert row.source_bytes == len(row.source_json.encode()) and row.binding_bytes == len(row.binding_json.encode())
    assert len(stored.run.input_json.encode()) <= 65535 and '"rca_evidence_source"' not in stored.run.input_json
    assert '"description"' not in stored.run.input_json and '"identity_secret"' not in row.source_json
    audit = db.get(AIAuditEvent, row.create_event_id)
    assert audit.action == "rca_run.create" and audit.target == identifier
    assert json.loads(audit.detail_json)["artifact"]["source_hash"] == row.source_hash
    assert db.get(AdverseEvent, case["event_id"]).status == 0
    again = storage.load_task(db, case["actor"], identifier)
    assert again.source == prepared_value.source and again.frozen_case == prepared_value.frozen_case
    assert storage.source_piece(db, case["actor"], identifier)["data"] == prepared_value.source.model_dump(mode="json")
    assert storage.case_piece(db, case["actor"], identifier)["data"]["execution_current"] is False


def test_actual_uncommitted_artifact_locator_and_load_use_real_same_session_sql_then_rollback(grant_case):
    case, db = grant_case, grant_case["db"]
    before = task_counts(db)
    stored, value = stage(case, commit=False)
    identifier = inspect(stored.run).identity[0]
    assert storage.locate_artifact(db, identifier) == (identifier, value.binding.case_id, value.binding.requested_by)
    assert storage.load_task(db, case["actor"], identifier).source == value.source
    db.rollback()
    assert storage.locate_artifact(db, identifier) is None
    # stage's helper committed its synthetic Source/provider setup beforehand.
    assert db.query(AIRun).count() == before[0] and db.query(AIRcaEvidenceRunArtifact).count() == before[1]


@pytest.mark.parametrize("axis", ["role", "token_fresh_request", "patient_association", "grant_revoke_then_replace", "new_rca"])
def test_current_source_original_purpose_and_epoch_loss_are_before_any_task_text(grant_case, axis):
    case, db = grant_case, grant_case["db"]
    stored, value = stage(case)
    identifier = inspect(stored.run).identity[0]
    actor_id = inspect(case["actor"]).identity[0]
    if axis == "role":
        db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": actor_id})
        db.commit()
        db.refresh(case["actor"])
    elif axis == "token_fresh_request":
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before='2026-10-21 12:00:01.123456' WHERE user_id=:id"), {"id": actor_id})
        db.commit()
        db.refresh(case["actor"])  # Current JWT-era actor, not a stale old ORM epoch.
    elif axis == "patient_association":
        db.execute(text("UPDATE hoimsystem_adverse_event SET patient_id=NULL WHERE event_id=:id"), {"id": case["event_id"]})
        db.commit()
    elif axis == "grant_revoke_then_replace":
        original = grants.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
        grants.revoke_grant(db, case["actor"], original.identity.grant_id, cas(original))
        db.commit()
        issue(case)
    else:
        seed_rca(case)
    denied(db, lambda: storage.load_task(db, case["actor"], identifier), 409 if axis == "new_rca" else 403)


@pytest.mark.parametrize("axis", ["wrong_create_audit_pk", "self_rehashed_source", "rewrite_epoch", "rewrite_feature"])
def test_exact_creation_audit_and_current_header_prevent_metadata_rewrite_before_task_text(grant_case, axis):
    case, db = grant_case, grant_case["db"]
    stored, value = stage(case)
    identifier = inspect(stored.run).identity[0]
    if axis == "wrong_create_audit_pk":
        wrong_id = value.binding.event_grant.grant_id
        actual = grants.grant_detail(db, case["actor"], wrong_id).governance.created_audit_event_id
        db.execute(text("UPDATE hoimsystem_ai_rca_evidence_run_artifact SET create_event_id=:audit WHERE run_id=:run"), {"audit": actual, "run": identifier})
    elif axis == "self_rehashed_source":
        db.execute(text("UPDATE hoimsystem_ai_rca_evidence_run_artifact SET source_hash=:sha WHERE run_id=:run"), {"sha": "e" * 64, "run": identifier})
    elif axis == "rewrite_feature":
        db.execute(text("UPDATE hoimsystem_ai_run SET feature_key='patient_summary' WHERE run_id=:run"), {"run": identifier})
    else:
        changed = NOW - dt.timedelta(microseconds=1)
        db.execute(
            text("UPDATE hoimsystem_ai_rca_evidence_run_artifact SET actor_token_invalid_before=:epoch WHERE run_id=:run"),
            {"epoch": changed.isoformat(sep=" ", timespec="microseconds"), "run": identifier},
        )
        db.execute(
            text("UPDATE hoimsystem_users SET token_invalid_before=:epoch WHERE user_id=:id"), {"epoch": changed.isoformat(sep=" ", timespec="microseconds"), "id": inspect(case["actor"]).identity[0]}
        )
    db.commit()
    if axis == "rewrite_epoch":
        db.refresh(case["actor"])
    denied(db, lambda: storage.load_task(db, case["actor"], identifier), 409)


def test_raw_task_change_without_rehash_is_rejected_after_current_scope_not_shown_as_new_result(grant_case):
    case, db = grant_case, grant_case["db"]
    stored, _ = stage(case)
    identifier = inspect(stored.run).identity[0]
    raw = json.loads(stored.run.input_json)
    raw["task_prompt"] += "未经原版本保存的替换"
    db.execute(text("UPDATE hoimsystem_ai_run SET input_json=:raw WHERE run_id=:run"), {"raw": c.canonical(raw), "run": identifier})
    db.commit()
    with pytest.raises(HTTPException) as failure:
        storage.load_task(db, case["actor"], identifier)
    assert failure.value.status_code == 409


@pytest.mark.parametrize("fault", ["audit", "source_hash", "actor", "new_member", "run_owner", "run_mutable"])
def test_real_sql_trigger_postflush_rejects_whole_run_artifact_audit_and_side_effect_atomically(grant_case, fault):
    case, db = grant_case, grant_case["db"]
    Base.metadata.create_all(db.get_bind())
    value, _ = prepared(case)
    provider = AIProvider(name="rca-fault-" + uuid.uuid4().hex, kind="chat", api_base="https://synthetic.invalid/v1", model="synthetic", allows_patient_data=1, created_by=case["actor"].user_id)
    db.add(provider)
    db.commit()
    raw = snapshot(value)
    raw["provider_snapshot"] = provider_snapshot(provider)
    actor_id = inspect(case["actor"]).identity[0]
    if fault == "audit":
        sql = "CREATE TRIGGER rca_task_fault BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_run.create' BEGIN SELECT RAISE(ABORT,'synthetic audit reject'); END"
    elif fault == "source_hash":
        sql = (
            "CREATE TRIGGER rca_task_fault AFTER INSERT ON hoimsystem_ai_rca_evidence_run_artifact BEGIN UPDATE hoimsystem_ai_rca_evidence_run_artifact SET source_hash='"
            + "f" * 64
            + "' WHERE run_id=NEW.run_id; END"
        )
    elif fault == "actor":
        sql = f"CREATE TRIGGER rca_task_fault AFTER INSERT ON hoimsystem_ai_rca_evidence_run_artifact BEGIN UPDATE hoimsystem_users SET user_role='admin' WHERE user_id={actor_id}; END"
    elif fault == "new_member":
        sql = f"CREATE TRIGGER rca_task_fault AFTER INSERT ON hoimsystem_ai_rca_evidence_run_artifact BEGIN INSERT INTO hoimsystem_adverse_event_rca(event_id,event_summary,root_cause,corrective_actions,pdca_cycle,create_time) VALUES ({case['event_id']},'actual trigger new member','not verified','no effect proof','P','2026-10-21 12:00:00.123456'); END"
    elif fault == "run_owner":
        other = inspect(case["users"]["doctor_user"]).identity[0]
        sql = f"CREATE TRIGGER rca_task_fault AFTER INSERT ON hoimsystem_ai_rca_evidence_run_artifact BEGIN UPDATE hoimsystem_ai_run SET requested_by={other} WHERE run_id=NEW.run_id; END"
    else:
        sql = "CREATE TRIGGER rca_task_fault AFTER INSERT ON hoimsystem_ai_rca_evidence_run_artifact BEGIN UPDATE hoimsystem_ai_run SET input_tokens=999 WHERE run_id=NEW.run_id; END"
    before = task_counts(db)
    db.execute(text(sql))
    db.commit()
    try:
        with pytest.raises(HTTPException) as failure:
            storage.stage_run(db, case["actor"], AIRun(run_id=str(uuid.uuid4()), prompt_version=0, preview=1), value, raw)
        assert failure.value.status_code in {403, 409}
        if fault == "new_member":
            assert "仅当前全集仍匹配" in failure.value.detail
        assert task_counts(db) == before
        assert db.get(User, actor_id).user_role == "super_admin"
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER rca_task_fault"))
        db.commit()
