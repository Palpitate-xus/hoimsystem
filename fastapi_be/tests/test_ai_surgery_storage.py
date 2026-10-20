"""Actual SQL storage primitives and native recomputation, not an auth pipeline.

These synthetic SQL fixtures deliberately do not stand in for a fully authorized
scenario. Current scenario/care/config authorization is exercised by the separate
integration owner once that source layer is complete; no auth function is mocked.
"""

import copy
import datetime
import hashlib
import json
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.ai.gateway import AIExecutionError
from app.ai.governance import digest
from app.ai.models import AIAuditEvent, AIProvider, AIRun
from app.ai.runtime import provider_snapshot
from app.ai.surgery_config import runtime_descriptor, runtime_from_descriptor
from app.ai.surgery_context import MISSING_DATA, SCOPE_NOTE, binding_for, surgery_evidence
from app.ai.surgery_contract import SurgerySource, canonical_json, hash_content
from app.ai.surgery_model import compute_surgery, generation_result_for_analysis
from app.ai.surgery_models import AISurgeryPool
from app.ai.surgery_scenario_models import AISurgeryRunResult, AISurgeryScenario
from app.ai.surgery_storage import RESULT_BYTES, SurgeryResultReference, _read_blob, _stage_blob, _verify_result, bounded_result, is_surgery_snapshot, load_snapshot, run_binding
from app.models import Department
from tests.test_ai_surgery_contract import source_dict

NOW = datetime.datetime(2026, 10, 20, 12, 0, 0, 123456)
CLOCK = "2026-10-20T12:00:00.123456Z"


def fresh_id():
    return str(uuid.uuid4())


@pytest.fixture
def native_runtime():
    return runtime_from_descriptor(runtime_descriptor())


@pytest.fixture
def storage_case(db_session, seed_data, native_runtime):
    """SQL-valid anchors plus an actual typed core Source, not a fake auth grant."""
    db = db_session
    actor = seed_data["super_admin_user"]
    department = Department(name="synthetic-storage-" + fresh_id())
    db.add(department)
    db.flush()
    pool = AISurgeryPool(
        pool_id=fresh_id(),
        department_id=department.department_id,
        schema_version="surgery_pool_v1",
        payload_json="{}",
        parent_binding_json="{}",
        content_hash=hash_content({}),
        recorded_at=NOW,
        created_by=actor.user_id,
    )
    db.add(pool)
    db.flush()
    source = source_dict()
    private = {"scope": "synthetic SQL storage only", "frozen_unicode_original": "合成院内原量" * 10000}
    source["scenario_id"] = fresh_id()
    source["content_hash"] = hash_content(private)
    source["source_id"] = f"surgery_scenario:{source['scenario_id']}:{source['content_hash'][:12]}"
    source = SurgerySource.model_validate(source).model_dump(mode="json")
    binding = binding_for(source, pool_id=pool.pool_id, department_id=department.department_id)
    scenario = AISurgeryScenario(
        scenario_id=source["scenario_id"],
        department_id=department.department_id,
        pool_id=pool.pool_id,
        schema_version="surgery_scenario_private_v1",
        as_of=NOW,
        created_at=NOW,
        created_by=actor.user_id,
        snapshot_json=canonical_json(private),
        content_hash=source["content_hash"],
        collection_digest=source["collection"]["collection_digest"],
        projection_json=canonical_json(source),
        projection_hash=hash_content(source),
        status="published",
        revision=2,
        reviewed_by=actor.user_id,
        reviewed_at=NOW,
        review_basis_note="合成SQL生命周期核对，不构成实际运营或当前来源授权验证",
    )
    provider = AIProvider(
        name="synthetic-surgery-storage-" + fresh_id(),
        kind="specialist",
        api_base="http://127.0.0.1:8821",
        model=native_runtime["model_version"],
        enabled=1,
        allows_patient_data=0,
        created_by=actor.user_id,
    )
    db.add_all([scenario, provider])
    db.flush()
    context = {
        "scope": "department",
        "source_domain": "surgery_declared_stage_resources",
        "department_ids": [department.department_id],
        "pool_ids": [pool.pool_id],
        "selected_sources": {"surgery_scenario_id": source["scenario_id"]},
        "surgery_binding": binding,
        "scope_note": SCOPE_NOTE,
        "missing_data": list(MISSING_DATA),
        "truncated_sources": [],
        "snapshot_time": CLOCK,
    }
    evidence = [surgery_evidence(binding)]
    snapshot = {
        "catalog_version": "synthetic-storage",
        "system_prompt": "SYNTH_SYSTEM_仅按明确审核原件核对",
        "task_prompt": "SYNTH_TASK_不得自动预订",
        "payload": {"input": {"surgery_scenario_id": source["scenario_id"], "question": "SYNTH_PRIVATE_QUESTION"}, "context": context, "tools": {}, "evidence": evidence},
        "provider_snapshot": provider_snapshot(provider),
        "feature_validation": {"status": "validated", "note": "合成工程验证", "validated_by": actor.user_id, "validated_at": CLOCK, "feature_revision": 1},
    }
    metadata = {
        "context_digest": digest(context),
        "clinical_context_fingerprint": digest({key: value for key, value in context.items() if key != "snapshot_time"}),
        "tool_fingerprint": digest({}),
        "source_count": 1,
        "department_ids": [department.department_id],
        "missing_data": list(MISSING_DATA),
        "snapshot_time": CLOCK,
        "feature_revision": 1,
        "validation_status": "validated",
    }
    run = AIRun(
        run_id=fresh_id(),
        feature_key="surgery_scheduling",
        provider_id=provider.provider_id,
        provider_revision=provider.revision,
        prompt_hash=digest([snapshot["system_prompt"], snapshot["task_prompt"]]),
        context_digest=digest(context),
        patient_id=None,
        encounter_ref=None,
        requested_by=actor.user_id,
        status="running",
        preview=1,
        lease_token=fresh_id(),
        input_json=canonical_json(snapshot),
        context_metadata_json=canonical_json(metadata),
        evidence_json=canonical_json(evidence),
    )
    db.add(run)
    db.commit()
    analysis = compute_surgery(source, hashlib.sha256((snapshot["system_prompt"] + "\n\n" + snapshot["task_prompt"]).encode()).hexdigest(), native_runtime)
    result = {**generation_result_for_analysis(analysis), "surgery_analysis": analysis.model_dump(mode="json")}
    return {"run": run, "source": source, "binding": binding, "snapshot": snapshot, "metadata": metadata, "evidence": evidence, "result": result, "scenario": scenario}


def stage_success(db, case, value=None):
    run = case["run"]
    run.result_json = _stage_blob(db, run, run.lease_token, case["binding"], case["result"] if value is None else value)
    run.status = "succeeded"
    db.commit()
    return run


def test_short_snapshot_reconstructs_exact_frozen_anchors_without_private_originals(storage_case):
    case = storage_case
    snapshot, metadata, evidence, binding = load_snapshot(case["run"])
    assert (snapshot, metadata, evidence, binding) == (case["snapshot"], case["metadata"], case["evidence"], case["binding"])
    assert all(len(raw.encode()) < 65535 for raw in (case["run"].input_json, case["run"].evidence_json, case["run"].context_metadata_json))
    assert "frozen_unicode_original" not in case["run"].input_json
    assert "surgery_source" not in snapshot["payload"]["context"]
    assert is_surgery_snapshot(snapshot) is True
    assert is_surgery_snapshot({"payload": {"context": {}, "input": {}}, "provider_snapshot": {"model": "legacy-external"}}) is False


@pytest.mark.parametrize("value", [None, [], {"payload": []}, {"provider_snapshot": []}, {"payload": {"context": []}}, {"payload": {"input": []}}])
def test_invalid_detection_shapes_reject_instead_of_falling_into_legacy_mode(value):
    with pytest.raises(HTTPException) as error:
        is_surgery_snapshot(value)
    assert error.value.status_code == 409


@pytest.mark.parametrize("field", ["input_json", "evidence_json", "context_metadata_json"])
@pytest.mark.parametrize("change", ["duplicate", "whitespace", "nonfinite"])
def test_noncanonical_short_json_is_not_restored_even_if_semantically_equivalent(storage_case, field, change):
    run = storage_case["run"]
    raw = getattr(run, field)
    if change == "duplicate":
        first_object = json.loads(raw)
        if isinstance(first_object, list):
            first_object = first_object[0]
        key = next(iter(first_object))
        duplicate = canonical_json({key: first_object[key]})[1:-1]
        opening = raw.index("{") + 1
        raw = raw[:opening] + duplicate + "," + raw[opening:]
    elif change == "whitespace":
        raw = " " + raw
    else:
        raw = '{"nonfinite":NaN}'
    setattr(run, field, raw)
    with pytest.raises(HTTPException) as error:
        run_binding(run)
    assert error.value.status_code == 409


def rewrite(case, *, sync_hashes=False):
    run, snapshot, metadata = case["run"], case["snapshot"], case["metadata"]
    context = snapshot["payload"]["context"]
    if sync_hashes:
        run.context_digest = metadata["context_digest"] = digest(context)
        metadata["clinical_context_fingerprint"] = digest({key: value for key, value in context.items() if key != "snapshot_time"})
        metadata["tool_fingerprint"] = digest(snapshot["payload"]["tools"])
    run.input_json, run.context_metadata_json, run.evidence_json = canonical_json(snapshot), canonical_json(metadata), canonical_json(case["evidence"])


@pytest.mark.parametrize(
    "change",
    [
        "prompt",
        "context_digest",
        "fingerprint",
        "missing",
        "scope",
        "scope_note",
        "extra_body",
        "selected",
        "input_override",
        "pool",
        "department_type",
        "binding_revision_float",
        "tools",
        "evidence",
        "source_count_bool",
        "feature_revision_float",
        "snapshot_time",
        "provider_id_bool",
        "provider_revision_float",
        "provider_model",
        "provider_kind",
        "validation_revision",
        "patient",
        "encounter",
        "feature",
    ],
)
def test_changed_frozen_anchors_or_double_rehashed_scope_fail_closed(storage_case, change):
    case, run = storage_case, storage_case["run"]
    context, snapshot, metadata = case["snapshot"]["payload"]["context"], case["snapshot"], case["metadata"]
    rehash = change in {"missing", "scope", "scope_note", "extra_body", "selected", "pool", "department_type", "binding_revision_float", "tools"}
    if change == "prompt":
        snapshot["task_prompt"] += " tampered"
    elif change == "context_digest":
        metadata["context_digest"] = "a" * 64
    elif change == "fingerprint":
        metadata["clinical_context_fingerprint"] = "a" * 64
    elif change == "missing":
        context["missing_data"] = metadata["missing_data"] = []
    elif change == "scope":
        context["source_domain"] = "patient"
    elif change == "scope_note":
        context["scope_note"] = "unverified arbitrary scope"
    elif change == "extra_body":
        context["surgery_scenario"] = {"private": "must remain SQL blob"}
    elif change == "selected":
        context["selected_sources"]["surgery_scenario_id"] = fresh_id()
    elif change == "input_override":
        snapshot["payload"]["input"]["objective_mode"] = "override"
    elif change == "pool":
        context["pool_ids"] = [fresh_id()]
    elif change == "department_type":
        context["department_ids"] = metadata["department_ids"] = [float(case["binding"]["department_id"])]
    elif change == "binding_revision_float":
        context["surgery_binding"]["revision"] = 2.0
    elif change == "tools":
        snapshot["payload"]["tools"] = {"free_constraints": "not a source"}
    elif change == "evidence":
        case["evidence"][0]["content"] = "rewritten both evidence copies"
        snapshot["payload"]["evidence"] = copy.deepcopy(case["evidence"])
    elif change == "source_count_bool":
        metadata["source_count"] = True
    elif change == "feature_revision_float":
        metadata["feature_revision"] = 1.0
    elif change == "snapshot_time":
        metadata["snapshot_time"] = "2026-02-30T12:00:00.123456Z"
    elif change == "provider_id_bool":
        snapshot["provider_snapshot"]["provider_id"] = True
    elif change == "provider_revision_float":
        snapshot["provider_snapshot"]["revision"] = 1.0
    elif change == "provider_model":
        snapshot["provider_snapshot"]["model"] = "surgery:unregistered"
    elif change == "provider_kind":
        snapshot["provider_snapshot"]["kind"] = "chat"
    elif change == "validation_revision":
        snapshot["feature_validation"]["feature_revision"] = 2
    elif change == "patient":
        run.patient_id = 1
    elif change == "encounter":
        run.encounter_ref = "original-patient-case"
    elif change == "feature":
        run.feature_key = "bed_forecast"
    else:
        raise AssertionError(change)
    rewrite(case, sync_hashes=rehash)
    with pytest.raises(HTTPException) as error:
        run_binding(run)
    assert error.value.status_code == 409


def test_actual_sql_complete_unicode_blob_and_tiny_pointer_commit_with_exact_audit(db_session, storage_case):
    case, db = storage_case, db_session
    # Storage accepts complete UTF-8 objects without truncation; semantic native
    # checks below are independent, so this bulk payload is not a model result.
    value = {"whole_unicode_proof": "合成未截断完整证明" * 12000, "zero": 0, "false": False, "unknown": None}
    run = stage_success(db, case, value)
    row = db.get(AISurgeryRunResult, run.run_id)
    pointer = SurgeryResultReference.model_validate(json.loads(run.result_json))
    assert len(run.result_json.encode()) < 65535 < row.result_bytes == len(row.result_json.encode())
    assert _read_blob(db, run) == value
    assert pointer.content_hash == row.content_hash == hash_content(value)
    assert pointer.source_binding_hash == row.source_binding_hash == hash_content(case["binding"])
    audit = db.query(AIAuditEvent).filter_by(target=run.run_id, action="run.surgery_result.accept").one()
    assert json.loads(audit.detail_json) == {key: getattr(pointer, key) for key in ("content_hash", "result_bytes", "source_binding_hash")}


def test_actual_native_result_is_recomputed_with_frozen_prompt_and_registered_runtime(storage_case, db_session):
    case = storage_case
    checked = _verify_result(case["result"], case["snapshot"], case["evidence"], case["source"])
    assert checked == case["result"]
    run = stage_success(db_session, case, checked)
    assert _verify_result(_read_blob(db_session, run), *[case[key] for key in ("snapshot", "evidence", "source")]) == checked


@pytest.mark.parametrize("change", ["score", "assignment", "proof", "explanation", "prompt", "model", "source", "mixed"])
def test_whole_native_recompute_rejects_plausible_but_unbound_results(storage_case, change):
    case = storage_case
    result, snapshot, source = copy.deepcopy(case["result"]), copy.deepcopy(case["snapshot"]), copy.deepcopy(case["source"])
    if change == "score":
        result["surgery_analysis"]["solution"]["scheduled_count"] += 1
    elif change == "assignment":
        result["surgery_analysis"]["solution"]["assignments"][0]["start_at"] = "2026-10-21T08:00:00.000002Z"
    elif change == "proof":
        result["surgery_analysis"]["optimistic_search"]["primitive_operations"] += 1
    elif change == "explanation":
        result["summary"] += " invented certainty"
    elif change == "prompt":
        snapshot["task_prompt"] += " different original prompt"
    elif change == "model":
        snapshot["provider_snapshot"]["model"] = "surgery:" + "a" * 64
    elif change == "source":
        source["cases"][0]["starts"][0]["penalty"]["value"] = "1"
    elif change == "mixed":
        result["bed_analysis"] = {}
    else:
        raise AssertionError(change)
    with pytest.raises(AIExecutionError):
        _verify_result(result, snapshot, case["evidence"], source)


@pytest.mark.parametrize("change", ["wrong_lease", "cancelled", "reclaimed", "database_scope"])
def test_sql_current_lease_recheck_catches_stale_orm_state(db_session, storage_case, change):
    db, case = db_session, storage_case
    run, lease = case["run"], case["run"].lease_token
    if change == "wrong_lease":
        lease = fresh_id()
    elif change == "cancelled":
        db.execute(text("UPDATE hoimsystem_ai_run SET status='cancelled' WHERE run_id=:id"), {"id": run.run_id})
    elif change == "reclaimed":
        db.execute(text("UPDATE hoimsystem_ai_run SET lease_token=:lease WHERE run_id=:id"), {"id": run.run_id, "lease": fresh_id()})
    elif change == "database_scope":
        db.execute(text("UPDATE hoimsystem_ai_run SET context_digest=:digest WHERE run_id=:id"), {"id": run.run_id, "digest": "a" * 64})
    with pytest.raises(HTTPException) as error:
        _stage_blob(db, run, lease, case["binding"], case["result"])
    assert error.value.status_code == 409
    assert db.query(AISurgeryRunResult).filter_by(run_id=run.run_id).count() == 0
    db.rollback()


def test_staging_preserves_pending_usage_and_finish_fields_until_atomic_commit(db_session, storage_case):
    run = storage_case["run"]
    run.input_tokens, run.output_tokens, run.latency_ms, run.finish_time = 0, 0, 123, NOW
    run.result_json = _stage_blob(db_session, run, run.lease_token, storage_case["binding"], storage_case["result"])
    assert run.latency_ms == 123 and run.finish_time == NOW and run.status == "running"
    assert db_session.in_transaction()
    db_session.rollback()


def test_actual_sql_audit_failure_rolls_back_blob_pointer_success_and_usage_together(db_session, storage_case):
    db, case = db_session, storage_case
    run, original_id, lease = case["run"], case["run"].run_id, case["run"].lease_token
    run.result_json = _stage_blob(db, run, lease, case["binding"], case["result"])
    run.status, run.output_tokens, run.finish_time = "succeeded", 7, NOW
    # A genuine SQL NOT NULL failure, with the valid acceptance audit still in
    # the same transaction. No mocked commit/rollback or mocked SQL result.
    db.add(AIAuditEvent(actor_id=run.requested_by, action=None, target=run.run_id, detail_json="{}"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.expire_all()
    restored = db.get(AIRun, original_id)
    assert (restored.status, restored.lease_token, restored.result_json, restored.output_tokens, restored.finish_time) == ("running", lease, "{}", 0, None)
    assert db.get(AISurgeryRunResult, original_id) is None
    assert db.query(AIAuditEvent).filter_by(target=original_id).count() == 0


def test_pending_duplicate_blob_cannot_be_staged_twice_without_a_flush(db_session, storage_case):
    case, run = storage_case, storage_case["run"]
    _stage_blob(db_session, run, run.lease_token, case["binding"], case["result"])
    with pytest.raises(HTTPException):
        _stage_blob(db_session, run, run.lease_token, case["binding"], case["result"])
    db_session.rollback()


@pytest.mark.parametrize(
    "change",
    [
        "whitespace",
        "duplicate",
        "wrong_id",
        "wrong_scenario",
        "wrong_lease",
        "binding",
        "boolean_size",
        "cancelled",
        "blob_sha",
        "blob_size",
        "blob_binding",
        "blob_lease",
        "blob_scenario",
        "blob_schema",
        "blob_noncanonical",
        "blob_missing",
    ],
)
def test_pointer_and_actual_sql_blob_integrity_fail_closed(db_session, storage_case, change):
    db, case = db_session, storage_case
    run = stage_success(db, case)
    reference = json.loads(run.result_json)
    row = db.get(AISurgeryRunResult, run.run_id)
    if change == "whitespace":
        run.result_json = " " + run.result_json
    elif change == "duplicate":
        run.result_json = run.result_json[:-1] + ',"run_id":' + json.dumps(run.run_id) + "}"
    elif change == "wrong_id":
        reference["run_id"] = fresh_id()
    elif change == "wrong_scenario":
        reference["scenario_id"] = fresh_id()
    elif change == "wrong_lease":
        reference["lease_token"] = fresh_id()
    elif change == "binding":
        reference["source_binding_hash"] = "a" * 64
    elif change == "boolean_size":
        reference["result_bytes"] = True
    elif change == "cancelled":
        run.status = "cancelled"
    elif change == "blob_sha":
        row.content_hash = "a" * 64
    elif change == "blob_size":
        row.result_bytes += 1
    elif change == "blob_binding":
        row.source_binding_hash = "a" * 64
    elif change == "blob_lease":
        row.lease_token = fresh_id()
    elif change == "blob_scenario":
        row.scenario_id = fresh_id()
    elif change == "blob_schema":
        row.schema_version = "other_result_v1"
    elif change == "blob_noncanonical":
        row.result_json = " " + row.result_json
    elif change == "blob_missing":
        db.delete(row)
    else:
        raise AssertionError(change)
    if change not in {"whitespace", "duplicate"}:
        run.result_json = canonical_json(reference)
    db.flush()
    with pytest.raises((HTTPException, ValueError, ValidationError)):
        _read_blob(db, run)
    db.rollback()


def test_rehashed_corrupt_sql_blob_still_fails_whole_native_recomputation(db_session, storage_case):
    db, case = db_session, storage_case
    run = stage_success(db, case)
    row = db.get(AISurgeryRunResult, run.run_id)
    value = json.loads(row.result_json)
    value["surgery_analysis"]["solution"]["scheduled_count"] += 1
    row.result_json, row.content_hash, row.result_bytes = bounded_result(value)
    reference = json.loads(run.result_json)
    reference.update(content_hash=row.content_hash, result_bytes=row.result_bytes)
    run.result_json = canonical_json(reference)
    db.commit()
    read = _read_blob(db, run)
    assert read == value  # Its new hashes agree, so only actual recomputation rejects it.
    with pytest.raises(AIExecutionError):
        _verify_result(read, case["snapshot"], case["evidence"], case["source"])


def test_exact_full_utf8_limit_counts_bytes_without_truncation_or_ascii_escaping():
    size = RESULT_BYTES - len(canonical_json({"v": ""}).encode())
    text_value = "中" * (size // 3) + "x" * (size % 3)
    serialized, digest_value, actual = bounded_result({"v": text_value})
    assert actual == RESULT_BYTES and "中" in serialized and json.loads(serialized)["v"] == text_value
    assert hashlib.sha256(serialized.encode()).hexdigest() == digest_value
    with pytest.raises(HTTPException) as error:
        bounded_result({"v": text_value + "x"})
    assert error.value.status_code == 422


@pytest.mark.parametrize("value", [{"x": float("nan")}, {"x": float("inf")}, {"x": "\ud800"}, {"x": object()}])
def test_nonfinite_invalid_unicode_or_non_json_is_not_a_storable_result(value):
    with pytest.raises(HTTPException) as error:
        bounded_result(value)
    assert error.value.status_code == 422
