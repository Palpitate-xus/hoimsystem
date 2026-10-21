"""Real SQL blob/lease primitives; these anchors do not claim source authorization."""

import copy
import hashlib
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.ai.governance import digest
from app.ai.inventory_config import runtime_descriptor, runtime_from_descriptor
from app.ai.inventory_context import _short_context, inventory_evidence
from app.ai.inventory_contract import canonical_json, hash_content
from app.ai.inventory_model import compute_inventory, generation_result_for_analysis
from app.ai.inventory_native_source_models import AIInventoryNativeSource
from app.ai.inventory_protocol import InventoryGenerationResult
from app.ai.inventory_scenario_models import AIInventoryRunResult, AIInventoryScenario
from app.ai.inventory_storage import RESULT_BYTES, InventoryResultReference, _read_blob, _stage_blob, _verify_result, bounded_result, is_inventory_snapshot, load_snapshot
from app.ai.models import AIAuditEvent, AIProvider, AIRun
from app.ai.runtime import provider_snapshot
from app.ai.supply_source_models import AISupplyUnitDefinition
from tests.test_ai_inventory_capacity import maximum_source
from tests.test_ai_inventory_context import bundle
from tests.test_ai_inventory_contract import refresh, uid

NOW = datetime(2026, 10, 20, 12, 0, 0, 123456)
CLOCK = "2026-10-20T12:00:00.123456Z"


@pytest.fixture
def storage_case(db_session, seed_data):
    db, actor = db_session, seed_data["super_admin_user"]
    source = maximum_source(lots=512, days=3)
    source["scenario_id"] = str(uuid4())
    source["source_id"] = f"inventory_scenario:{source['scenario_id']}:{source['content_hash'][:12]}"
    for reference in (source["observation"]["ref"], source["scenario"]["ref"]):
        reference["source_record_id"] = str(uuid4())
        reference["source_id"] = f"inventory_fact:{reference['source_record_id']}:{reference['content_hash'][:12]}"
    refresh(source)
    binding = bundle(source)["context"]["inventory_binding"]
    binding["unit_definition_id"] = str(uuid4())
    private = {"scope": "synthetic SQL primitives only", "frozen_unicode_original": "合成院内原量" * 10000}
    unit = AISupplyUnitDefinition(
        unit_definition_id=binding["unit_definition_id"],
        item_kind="pharmaceutical",
        item_id=binding["item_id"],
        scope="hospital_inventory",
        schema_version="supply_unit_private_v1",
        recorded_at=NOW,
        payload_json="{}",
        parent_binding_json="{}",
        content_hash=hash_content({}),
        created_by=actor.user_id,
    )
    db.add(unit)
    db.flush()
    originals = [
        AIInventoryNativeSource(
            source_record_id=ref["source_record_id"],
            source_kind=ref["kind"],
            item_kind="pharmaceutical",
            item_id=binding["item_id"],
            scope="hospital_inventory",
            unit_definition_id=unit.unit_definition_id,
            date_from=None if ref["kind"] == "inventory_observation" else source["date_from"],
            date_to=None if ref["kind"] == "inventory_observation" else source["date_to"],
            timezone=None if ref["kind"] == "inventory_observation" else source["timezone"],
            schema_version="inventory_native_source_private_v1",
            recorded_at=NOW,
            created_by=actor.user_id,
            payload_json="{}",
            parent_binding_json="{}",
            content_hash=ref["content_hash"],
            status="draft",
            revision=1,
            review_basis_note="",
            revoke_reason="",
        )
        for ref in (source["observation"]["ref"], source["scenario"]["ref"])
    ]
    db.add_all(originals)
    db.flush()
    series = AIInventoryScenario(
        scenario_id=source["scenario_id"],
        item_kind="pharmaceutical",
        item_id=binding["item_id"],
        scope="hospital_inventory",
        unit_definition_id=unit.unit_definition_id,
        observation_source_id=originals[0].source_record_id,
        quantity_scenario_source_id=originals[1].source_record_id,
        schema_version="inventory_scenario_private_v1",
        as_of=NOW,
        created_at=NOW,
        created_by=actor.user_id,
        snapshot_json=canonical_json(private),
        content_hash=source["content_hash"],
        collection_digest=binding["collection_digest"],
        projection_json=canonical_json(source),
        projection_hash=hash_content(source),
        status="published",
        revision=2,
        reviewed_by=actor.user_id,
        reviewed_at=NOW,
        review_basis_note="仅合成SQL生命周期核对，未授予当前来源执行权限",
    )
    runtime = runtime_from_descriptor(runtime_descriptor())
    provider = AIProvider(
        name="synthetic-inventory-storage-" + str(uuid4()),
        kind="specialist",
        api_base="http://127.0.0.1:8823",
        model=runtime["model_version"],
        enabled=1,
        allows_patient_data=0,
        created_by=actor.user_id,
    )
    db.add_all([series, provider])
    db.flush()
    context = _short_context(binding, CLOCK)
    evidence = [inventory_evidence(binding)]
    snapshot = {
        "catalog_version": "synthetic-storage",
        "system_prompt": "SYNTH_SYSTEM",
        "task_prompt": "SYNTH_TASK",
        "payload": {"input": {"inventory_scenario_id": source["scenario_id"], "question": "SYNTH_PRIVATE"}, "context": context, "tools": {}, "evidence": evidence},
        "provider_snapshot": provider_snapshot(provider),
        "feature_validation": {"status": "validated", "note": "synthetic", "validated_by": actor.user_id, "validated_at": CLOCK, "feature_revision": 1},
    }
    metadata = {
        "instructions_digest": hashlib.sha256((snapshot["system_prompt"] + "\n\n" + snapshot["task_prompt"]).encode()).hexdigest(),
        "context_digest": digest(context),
        "clinical_context_fingerprint": digest({key: value for key, value in context.items() if key != "snapshot_time"}),
        "tool_fingerprint": digest({}),
        "source_count": 1,
        "department_ids": [],
        "missing_data": context["missing_data"],
        "snapshot_time": CLOCK,
        "feature_revision": 1,
        "validation_status": "validated",
    }
    run = AIRun(
        run_id=str(uuid4()),
        feature_key="inventory_optimization",
        provider_id=provider.provider_id,
        provider_revision=provider.revision,
        prompt_hash=digest([snapshot["system_prompt"], snapshot["task_prompt"]]),
        context_digest=digest(context),
        requested_by=actor.user_id,
        status="running",
        preview=1,
        lease_token=str(uuid4()),
        input_json=canonical_json(snapshot),
        context_metadata_json=canonical_json(metadata),
        evidence_json=canonical_json(evidence),
    )
    db.add(run)
    db.commit()
    analysis = compute_inventory(source, hashlib.sha256((snapshot["system_prompt"] + "\n\n" + snapshot["task_prompt"]).encode()).hexdigest(), runtime)
    result = InventoryGenerationResult.model_validate({**generation_result_for_analysis(analysis), "inventory_analysis": analysis.model_dump(mode="json")}).model_dump(mode="json")
    return {"run": run, "source": source, "binding": binding, "snapshot": snapshot, "metadata": metadata, "evidence": evidence, "result": result}


def test_short_sql_snapshot_has_exact_local_anchors_and_complete_native_recomputation(storage_case):
    case = storage_case
    assert load_snapshot(case["run"]) == (case["snapshot"], case["metadata"], case["evidence"], case["binding"])
    assert "frozen_unicode_original" not in case["run"].input_json
    assert "inventory_source" not in case["snapshot"]["payload"]["context"]
    assert _verify_result(case["result"], case["snapshot"], case["evidence"], case["source"]) == case["result"]


@pytest.mark.parametrize("marker", ["binding", "source", "scenario", "reference", "provider"])
def test_every_native_marker_detects_tampered_feature_independently(marker):
    snapshot = {"payload": {"context": {}, "input": {}}, "provider_snapshot": {"model": "external"}}
    if marker in {"binding", "source", "scenario"}:
        snapshot["payload"]["context"]["inventory_" + marker] = {}
    elif marker == "reference":
        snapshot["payload"]["input"]["inventory_scenario_id"] = uid("series")
    else:
        snapshot["provider_snapshot"]["model"] = "inventory:" + "a" * 64
    assert is_inventory_snapshot(snapshot)


@pytest.mark.parametrize("change", ["feature", "patient", "prompt", "scenario_selection", "tools", "evidence", "context_extra", "provider_revision", "metadata_count", "coerced_item"])
def test_short_binding_corruption_cannot_be_restored_by_normal_loading(storage_case, change):
    case = storage_case
    run, snapshot = case["run"], copy.deepcopy(case["snapshot"])
    if change == "feature":
        run.feature_key = "operations_qa"
    elif change == "patient":
        run.patient_id = 1
    elif change == "prompt":
        snapshot["task_prompt"] += "altered"
    elif change == "scenario_selection":
        snapshot["payload"]["input"]["inventory_scenario_id"] = uid("different scenario")
    elif change == "tools":
        snapshot["payload"]["tools"] = {"unreviewed": True}
    elif change == "evidence":
        snapshot["payload"]["evidence"] = []
    elif change == "context_extra":
        snapshot["payload"]["context"]["inventory_source"] = case["source"]
    elif change == "provider_revision":
        snapshot["provider_snapshot"]["revision"] += 1
    elif change == "metadata_count":
        metadata = copy.deepcopy(case["metadata"])
        metadata["source_count"] = True
        run.context_metadata_json = canonical_json(metadata)
    else:
        snapshot["payload"]["context"]["inventory_binding"]["item_id"] = str(case["binding"]["item_id"])
    run.input_json = canonical_json(snapshot)
    with pytest.raises(HTTPException) as error:
        load_snapshot(run)
    assert error.value.status_code == 409


@pytest.mark.parametrize("change", ["missing", "altered", "extra", "changed_prompt_and_task_hash"])
def test_frozen_prompt_summary_is_anchored_to_the_original_complete_prompt(storage_case, change):
    case = storage_case
    run, snapshot, metadata = case["run"], copy.deepcopy(case["snapshot"]), copy.deepcopy(case["metadata"])
    if change == "missing":
        metadata.pop("instructions_digest")
    elif change == "altered":
        metadata["instructions_digest"] = "a" * 64
    elif change == "extra":
        metadata["unbound_inventory_data"] = {"quantity": "999"}
    else:
        snapshot["task_prompt"] += "changed after freeze"
        run.prompt_hash = digest([snapshot["system_prompt"], snapshot["task_prompt"]])
    run.input_json, run.context_metadata_json = canonical_json(snapshot), canonical_json(metadata)
    with pytest.raises(HTTPException) as error:
        load_snapshot(run)
    assert error.value.status_code == 409


def test_blob_pointer_status_and_acceptance_audit_commit_together(db_session, storage_case):
    case, db = storage_case, db_session
    run = case["run"]
    run.result_json = _stage_blob(db, run, run.lease_token, case["binding"], case["result"])
    run.status = "succeeded"
    db.commit()
    reference = InventoryResultReference.model_validate_json(run.result_json)
    blob = db.query(AIInventoryRunResult).filter_by(run_id=run.run_id).one()
    assert reference.source_binding_hash == hash_content(case["binding"])
    assert reference.result_bytes == blob.result_bytes == len(blob.result_json.encode())
    assert len(blob.result_json.encode()) > 65535
    assert _read_blob(db, run) == case["result"]
    assert db.query(AIAuditEvent).filter_by(action="run.inventory_result.accept", target=run.run_id).count() == 1


def test_sql_blob_and_audit_rollback_leave_no_pointer_or_accepted_result(db_session, storage_case):
    db, case = db_session, storage_case
    run = case["run"]
    run.result_json = _stage_blob(db, run, run.lease_token, case["binding"], case["result"])
    run.status = "succeeded"
    db.flush()
    db.rollback()
    db.refresh(run)
    assert run.status == "running" and run.result_json == "{}"
    assert db.query(AIInventoryRunResult).filter_by(run_id=run.run_id).count() == 0
    assert db.query(AIAuditEvent).filter_by(action="run.inventory_result.accept", target=run.run_id).count() == 0


@pytest.mark.parametrize("corruption", ["body", "bytes", "lease", "scenario", "binding", "status"])
def test_accepted_sql_blob_corruption_is_not_read_as_a_valid_comparison(db_session, storage_case, corruption):
    db, case = db_session, storage_case
    run = case["run"]
    run.result_json = _stage_blob(db, run, run.lease_token, case["binding"], case["result"])
    run.status = "succeeded"
    db.commit()
    blob = db.query(AIInventoryRunResult).filter_by(run_id=run.run_id).one()
    if corruption == "body":
        blob.result_json += " "
    elif corruption == "bytes":
        blob.result_bytes += 1
    elif corruption == "lease":
        run.lease_token = uid("other-lease")
    elif corruption == "scenario":
        original = db.query(AIInventoryScenario).filter_by(scenario_id=blob.scenario_id).one()
        clone = {column.name: getattr(original, column.name) for column in AIInventoryScenario.__table__.columns if column.name != "scenario_id"}
        other = AIInventoryScenario(scenario_id=str(uuid4()), **clone)
        db.add(other)
        db.flush()
        blob.scenario_id = other.scenario_id
    elif corruption == "binding":
        blob.source_binding_hash = "f" * 64
    else:
        run.status = "cancelled"
    db.commit()
    with pytest.raises((HTTPException, ValueError)):
        _read_blob(db, run)


def test_utf8_blob_capacity_is_exact_and_never_truncates():
    value = {"text": "药" * 10000}
    raw, content_hash, size = bounded_result(value)
    assert size == len(raw.encode()) and size > len(raw)
    assert content_hash == hashlib.sha256(raw.encode()).hexdigest()
    with pytest.raises(HTTPException) as error:
        bounded_result({"text": "药" * (RESULT_BYTES // 3)})
    assert error.value.status_code == 422
