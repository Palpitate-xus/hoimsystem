"""Actual durable RCA identity in shared routing; SQL authority is still separate."""

import json

import pytest
from app.ai import native_task_access, native_task_routing, runtime
from app.ai import rca_evidence_dispatch as dispatch
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_receipts as receipts
from app.ai.models import AIRun
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact
from app.database import Base
from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.dialects import mysql
from tests.test_ai_rca_evidence_configuration import configured
from tests.test_ai_rca_evidence_execution import provider_service, setup
from tests.test_ai_rca_evidence_execution import synthetic_host as synthetic_host
from tests.test_ai_rca_evidence_grants import cas
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_storage import no_task_text


def test_registered_models_and_actual_shared_claim_use_original_concrete_audit(grant_case):
    case, db = grant_case, grant_case["db"]
    stored, _, _ = configured(case)
    identifier = inspect(stored.run).identity[0]
    identity = native_task_routing.locate_native_task(db, identifier)
    assert (identity.domain, identity.source_id) == ("rca", stored.binding.case_id)
    assert AIRcaEvidenceRunArtifact.__tablename__ in Base.metadata.tables
    claim = runtime.claim_next_run(db)
    assert claim[0] == identifier and receipts.technical_header(db, identifier).claim.lease_token == claim[1]
    assert runtime.claim_next_run(db) is None


@pytest.mark.parametrize("loss", ["grant", "role", "epoch"])
def test_shared_guard_requires_current_original_purpose_and_epoch_before_task_text(grant_case, loss):
    case, db = grant_case, grant_case["db"]
    stored, value, _ = configured(case)
    identifier = inspect(stored.run).identity[0]
    if loss == "grant":
        record = grants.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
        grants.revoke_grant(db, case["actor"], record.identity.grant_id, cas(record))
    else:
        name, value = ("user_role", "admin") if loss == "role" else ("token_invalid_before", "2026-10-21 12:00:00.123456")
        db.execute(text(f"UPDATE hoimsystem_users SET {name}=:v WHERE user_id=:id"), {"v": value, "id": inspect(case["actor"]).identity[0]})
    db.commit()

    def denied():
        with pytest.raises(HTTPException) as failure:
            native_task_access.guard_private_task_read(db, case["actor"], identifier)
        assert failure.value.status_code == 403

    _, columns = no_task_text(db, denied)
    assert not columns


def set_path(data, path, value):
    for key in path[:-1]:
        data = data.setdefault(key, {})
    data[path[-1]] = value


@pytest.mark.parametrize("path", [tuple(path[2:].split(".")) for path in dispatch.INPUT_PATHS])
@pytest.mark.parametrize("value", [None, "opaque-marker-only"])
def test_erased_artifact_and_feature_with_each_null_or_present_marker_never_become_generic(grant_case, path, value):
    case, db = grant_case, grant_case["db"]
    stored, _, _ = configured(case)
    identifier = inspect(stored.run).identity[0]
    package = {}
    set_path(package, path, value)
    db.execute(text("DELETE FROM hoimsystem_ai_rca_evidence_run_artifact WHERE run_id=:id"), {"id": identifier})
    db.execute(text("UPDATE hoimsystem_ai_run SET feature_key='patient_summary',input_json=:body,evidence_json='[]' WHERE run_id=:id"), {"id": identifier, "body": json.dumps(package)})
    db.commit()
    with pytest.raises(HTTPException) as failure:
        dispatch.is_rca_task(db, identifier)
    assert failure.value.status_code == 409


def test_actual_artifact_even_erased_feature_routes_rca_but_full_header_rejects_before_body(grant_case):
    case, db = grant_case, grant_case["db"]
    stored, _, _ = configured(case)
    identifier = inspect(stored.run).identity[0]
    db.execute(text("UPDATE hoimsystem_ai_run SET feature_key='patient_summary',input_json='{}',evidence_json='[]',context_metadata_json='{}' WHERE run_id=:id"), {"id": identifier})
    db.commit()
    assert dispatch.is_rca_task(db, identifier)

    def denied():
        with pytest.raises(HTTPException) as failure:
            native_task_access.guard_private_task_read(db, case["actor"], identifier)
        assert failure.value.status_code == 409

    no_task_text(db, denied)


def test_true_generic_non_uuid_and_invalid_json_are_not_forced_into_rca(grant_case):
    db = grant_case["db"]
    stored, _, _ = configured(grant_case)
    identifier = inspect(stored.run).identity[0]
    db.execute(text("DELETE FROM hoimsystem_ai_rca_evidence_run_artifact WHERE run_id=:id"), {"id": identifier})
    db.execute(text("UPDATE hoimsystem_ai_run SET run_id='legacy-nonuuid',feature_key='patient_summary',input_json='invalid json',evidence_json='[]' WHERE run_id=:id"), {"id": identifier})
    db.commit()
    assert dispatch.is_rca_task(db, "legacy-nonuuid") is False
    from types import SimpleNamespace

    mysql_db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=mysql.dialect()))
    statement = str(dispatch.marker_statement(mysql_db, "legacy-nonuuid").compile(dialect=mysql.dialect()))
    assert "json_valid" in statement.lower() and "case" in statement.lower() and "json_type(json_extract" in statement.lower()


@pytest.mark.asyncio
async def test_shared_execute_dispatches_actual_rca_outside_routing_sql_session(grant_case, monkeypatch):
    identifier, lease, owner, _value, factory, active, _state, _reads = setup(grant_case)
    from app import database

    monkeypatch.setattr(database, "SessionLocal", factory)
    transport, calls = provider_service("chat", None, active)
    await runtime.execute_claimed(identifier, lease, transport=transport)
    assert len(calls) == 1
    with factory() as db:
        actual = receipts.read_receipt(db, receipts.technical_header(db, identifier))
        assert actual.status == "succeeded" and actual.usage.input_tokens == 11


def test_generic_recheck_cannot_invoke_native_rca(grant_case):
    stored, _, _ = configured(grant_case)
    with pytest.raises(runtime.AIExecutionError) as failure:
        runtime._recheck_task(grant_case["db"], stored.run)
    assert failure.value.code == "TASK_CONTRACT_CHANGED"


def test_known_rca_guard_never_locks_unrelated_global_gates(grant_case, monkeypatch):
    case, db = grant_case, grant_case["db"]
    stored, _, _ = configured(case)
    identifier = inspect(stored.run).identity[0]

    def forbidden(_db):
        raise AssertionError("This RCA authority path has no global Gate")

    monkeypatch.setattr(native_task_access, "lock_directory_gates", forbidden)
    native_task_access.guard_private_task_read(db, case["actor"], identifier)


def test_rca_and_other_real_artifacts_cannot_both_claim_one_run(grant_case, monkeypatch):
    from app.ai.document_extraction_models import AIDocumentExtractionRunAnchor

    case, db = grant_case, grant_case["db"]
    stored, _, _ = configured(case)
    identifier = inspect(stored.run).identity[0]
    from app.ai import document_evidence_contract, document_evidence_sources
    from tests.test_ai_document_evidence_contract import NOW as DOC_NOW
    from tests.test_ai_document_extraction_storage import create_task

    monkeypatch.setattr(document_evidence_sources, "utcnow", lambda: document_evidence_contract.clock(DOC_NOW))
    other = create_task(db)
    anchor = db.get(AIDocumentExtractionRunAnchor, inspect(other.run).identity[0])
    values = {column.name: getattr(anchor, column.name) for column in anchor.__table__.columns}
    db.add(AIDocumentExtractionRunAnchor(**{**values, "run_id": identifier}))
    db.flush()
    with pytest.raises(HTTPException) as failure:
        dispatch.is_rca_task(db, identifier)
    assert failure.value.status_code == 409


def test_orphan_null_marker_is_retained_while_shared_queue_claims_later_ordinary_work(grant_case):
    db = grant_case["db"]
    stored, _, _ = configured(grant_case)
    identifier = inspect(stored.run).identity[0]
    db.execute(text("DELETE FROM hoimsystem_ai_rca_evidence_run_artifact WHERE run_id=:id"), {"id": identifier})
    # Keep the deliberate orphan older than every ordinary synthetic queue.
    # Fair polling must retain it and claim the explicit later ordinary job.
    db.execute(
        text("UPDATE hoimsystem_ai_run SET feature_key='patient_summary',input_json=:body,evidence_json='[]',create_time='1900-01-01 00:00:00' WHERE run_id=:id"),
        {"id": identifier, "body": '{"payload":{"input":{"rca_evidence_case_id":null}}}'},
    )
    import datetime as dt
    import uuid

    later = AIRun(
        run_id=str(uuid.uuid4()),
        feature_key="operations_qa",
        requested_by=inspect(grant_case["actor"]).identity[0],
        prompt_hash="a" * 64,
        context_digest="b" * 64,
        create_time=dt.datetime(1900, 1, 1, 0, 0, 1),
    )
    db.add(later)
    db.commit()
    later_id = later.run_id
    before = tuple(db.query(*AIRun.__table__.columns).filter_by(run_id=identifier).one())
    claim = runtime.claim_next_run(db)
    assert claim is not None and claim[0] == later_id
    assert tuple(db.query(*AIRun.__table__.columns).filter_by(run_id=identifier).one()) == before
    assert db.query(AIRun.status, AIRun.lease_token).filter_by(run_id=identifier).one() == ("queued", None)
