"""Real SQL native identities and pre-BODY guards, without Main Task exposure."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text, update

from app.ai import native_task_access as access
from app.ai import native_task_routing as routing
from app.ai import operations_support_registry as registry
from app.ai import operations_support_shared as shared
from app.ai import operations_support_storage as storage
from app.ai.models import AIAuditEvent, AIRun
from app.ai.operations_support_models import AIOperationsWriteGate
from app.ai.operations_support_run_models import AIOperationsRunArtifact
from app.models import User
from tests.test_ai_operations_support_configuration import actors as actors
from tests.test_ai_operations_support_configuration import configured as configured
from tests.test_ai_operations_support_configuration import source as source
from tests.test_ai_operations_support_receipts import capture_without_body
from tests.test_ai_operations_support_storage import no_body, stage


@pytest.mark.parametrize("erased", [False, True])
def test_actual_expired_native_identity_without_hint_never_returns_task_body(configured, erased):
    db = configured[0][0]
    identifier = stage(configured)
    artifact = db.get(AIOperationsRunArtifact, identifier)
    if erased:
        db.execute(update(AIRun).where(AIRun.run_id == identifier).values(feature_key="patient_summary", input_json="{}", context_metadata_json="{}"), execution_options={"synchronize_session": False})
    db.expunge(artifact)
    db.info.pop("native_task_routing_staged_identities", None)
    run = db.get(AIRun, identifier)
    db.expire(run)
    actual = capture_without_body(db, lambda: routing.locate_native_task(db, run))
    assert actual.domain == "operations_support" and actual.run_id == identifier and actual.source_id == configured[3]["case_id"]
    assert capture_without_body(db, lambda: shared.is_operations_task(db, run)) is True
    assert inspect(run).expired_attributes


@pytest.mark.parametrize("fault", ["source", "owner_epoch", "erased_header"])
@pytest.mark.parametrize("who", ["owner", "super"])
def test_mixed_private_guard_rechecks_current_source_and_epoch_before_expired_task_body(configured, fault, who):
    db, registrar, creator, reviewer, admin = configured[0]
    identifier = stage(configured)
    if fault == "source":
        registry.revoke_original(db, registrar, configured[1]["original_id"], {"revision": 1, "reason": "混合目录不能恢复资料"})
    elif fault == "owner_epoch":
        db.execute(update(User).where(User.user_id == admin.user_id).values(token_invalid_before=registry.utcnow()), execution_options={"synchronize_session": False})
    else:
        db.execute(update(AIRun).where(AIRun.run_id == identifier).values(feature_key="patient_summary"), execution_options={"synchronize_session": False})
    run = db.get(AIRun, identifier)
    db.expire(run)
    no_body(db, lambda: access.guard_private_task_read(db, admin if who == "owner" else registrar, routing.opaque_run_id(run)), 409 if fault == "erased_header" else 403)


def orphan(db, owner, **changes):
    row = AIRun(feature_key="operations_support", requested_by=owner, input_json="{}", context_metadata_json="{}", evidence_json="[]", result_json="{}", prompt_hash="0" * 64, context_digest="0" * 64, **changes)
    db.add(row)
    db.flush()
    return row.run_id


@pytest.mark.parametrize("marker", ["feature", "input_schema", "metadata_schema", "null_reserved_key"])
def test_marker_only_orphan_is_never_generic_or_body_readable(configured, marker):
    db, registrar, creator, reviewer, admin = configured[0]
    identifier = orphan(db, admin.user_id)
    if marker != "feature":
        values = {"feature_key": "patient_summary"}
        if marker == "input_schema":
            values["input_json"] = '{"schema_version":"operations_support_task_ref_v1"}'
        elif marker == "metadata_schema":
            values["context_metadata_json"] = '{"schema_version":"operations_support_task_metadata_v1"}'
        else:
            values["input_json"] = '{"operations_case_id":null}'
        db.execute(update(AIRun).where(AIRun.run_id == identifier).values(**values), execution_options={"synchronize_session": False})
    assert capture_without_body(db, lambda: shared.is_operations_task(db, identifier)) is True
    assert capture_without_body(db, lambda: routing.locate_native_task(db, identifier)) is None
    no_body(db, lambda: access.guard_private_task_read(db, registrar, identifier), 409)
    before = db.query(AIAuditEvent).count()
    assert capture_without_body(db, lambda: shared.quarantine_orphan(db, identifier)) is True
    assert db.query(AIAuditEvent).count() == before + 1 and storage.run_header(db, identifier)["error_code"] == "NATIVE_ARTIFACT_REQUIRED"
    assert capture_without_body(db, lambda: shared.quarantine_orphan(db, identifier)) is False
    # No usage receipt, no statement that this orphan did/didn't incur a call.
    assert db.query(AIAuditEvent).filter_by(target=identifier, action="operations.task.usage").count() == 0


def test_rolled_back_real_staged_hint_does_not_invent_an_artifact(configured):
    db = configured[0][0]
    with db.begin_nested() as nested:
        identifier = stage(configured)
        assert routing.locate_native_task(db, identifier).domain == "operations_support"
        nested.rollback()
    assert capture_without_body(db, lambda: routing.locate_native_task(db, identifier)) is None


def test_mixed_directory_never_lazily_creates_missing_operations_gate(configured):
    db = configured[0][0]
    identifier = stage(configured)
    db.execute(text("DELETE FROM hoimsystem_ai_operations_write_gate WHERE gate_id=1"))
    capture_without_body(db, lambda: access.lock_directory_gates(db))
    assert db.query(AIOperationsWriteGate).filter_by(gate_id=1).one_or_none() is None
    no_body(db, lambda: shared.guard_operations_task(db, configured[0][-1], identifier), 409)


def test_128_corrupt_artifacts_and_128_unknown_role_orphans_do_not_hide_later_valid_sql_candidate(configured):
    from app.ai.research_cohort_dispatch import queue_candidate_condition as research_condition

    db, registrar, creator, reviewer, admin = configured[0]
    base_id = stage(configured)
    artifact = db.get(AIOperationsRunArtifact, base_id)
    fields = {column.name: getattr(artifact, column.name) for column in AIOperationsRunArtifact.__table__.columns}
    unknown = User(username="unknownops" + uuid.uuid4().hex[:8], password=admin.password, user_role="unknown_native_role")
    db.add(unknown)
    db.flush()
    for _ in range(128):
        identifier = orphan(db, admin.user_id)
        audit = AIAuditEvent(actor_id=admin.user_id, action="synthetic.corrupt.clone", target=identifier, detail_json="{}")
        db.add(audit)
        db.flush()
        db.add(AIOperationsRunArtifact(**{**fields, "run_id": identifier, "created_audit_event_id": audit.event_id}))
        db.flush()
        db.execute(update(AIRun).where(AIRun.run_id == identifier).values(feature_key="patient_summary"), execution_options={"synchronize_session": False})
        orphan(db, unknown.user_id)
    db.execute(update(AIRun).where(AIRun.run_id == base_id).values(status="failed"), execution_options={"synchronize_session": False})
    legal = stage(configured)
    db.commit()
    actual = capture_without_body(
        db,
        lambda: db.query(AIRun.run_id).filter(AIRun.status == "queued", shared.queue_candidate_condition(db), research_condition(db)).order_by(AIRun.create_time, AIRun.run_id).first(),
    )
    assert actual.run_id == legal


def test_real_quarantine_audit_trigger_header_mutation_rolls_back_status_and_audit(configured):
    db, registrar, creator, reviewer, admin = configured[0]
    identifier = orphan(db, admin.user_id)
    db.commit()
    before = db.query(AIAuditEvent).count()
    db.execute(text("CREATE TRIGGER ops_quarantine_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='operations.task.quarantine' BEGIN UPDATE hoimsystem_ai_run SET prompt_hash='" + "1" * 64 + "' WHERE run_id='" + identifier + "'; END"))
    db.commit()
    try:
        with pytest.raises(HTTPException) as exc:
            shared.quarantine_orphan(db, identifier)
        assert exc.value.status_code == 409 and storage.run_header(db, identifier)["status"] == "queued" and db.query(AIAuditEvent).count() == before
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS ops_quarantine_fault"))
        db.commit()
