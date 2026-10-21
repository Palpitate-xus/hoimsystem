"""Actual SQL task anchors bind the whole original request, never reconstructed JSON."""

import copy
import hashlib
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.ai import charge_reconciliation_context as context
from app.ai import charge_reconciliation_contract as c
from app.ai import charge_reconciliation_storage as storage
from app.ai.charge_reconciliation_prompt import CHARGE_RECONCILIATION_SYSTEM_PROMPT
from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.context import context_metadata
from app.ai.governance import digest
from app.ai.models import AIProvider, AIRun
from app.ai.runtime import provider_snapshot
from tests.test_ai_charge_reconciliation_sources import charge_case as _charge_case
from tests.test_ai_charge_reconciliation_sources import published

charge_case = _charge_case


def original_run(case):
    db = case["db"]
    value = published(case)
    values = {"charge_case_id": value["case_snapshot_id"], "question": "请人工核对原记录🙂\r\n保留完整问题。"}
    bundle = context.charge_context(db, case["super_admin_user"], value["patient_id"], value["admission_id"], values)
    provider = AIProvider(
        name="synthetic-charge-" + uuid.uuid4().hex, kind="chat", api_base="https://synthetic.invalid", model="synthetic-text", allows_patient_data=1, created_by=case["super_admin_user"].user_id
    )
    db.add(provider)
    db.flush()
    task = "合成独立任务Prompt：仅提出待核实问题，保留逐字来源🙂。"
    validation = {"status": "unreviewed", "note": "", "validated_by": None, "validated_at": None, "feature_revision": 1}
    snapshot = {
        "catalog_version": "synthetic-charge-task-v1",
        "system_prompt": CHARGE_RECONCILIATION_SYSTEM_PROMPT,
        "task_prompt": task,
        "payload": {"input": values, "context": bundle.data, "tools": {}, "evidence": bundle.evidence},
        "provider_snapshot": provider_snapshot(provider),
        "feature_validation": validation,
    }
    metadata = {
        **context_metadata(bundle),
        "feature_revision": 1,
        "validation_status": "unreviewed",
        "tool_fingerprint": digest({}),
        "instructions_digest": hashlib.sha256(c.utf8(CHARGE_RECONCILIATION_SYSTEM_PROMPT + "\n\n" + task)).hexdigest(),
        "model_version": provider.model,
    }
    run = AIRun(
        run_id=str(uuid.uuid4()),
        feature_key=storage.FEATURE_KEY,
        requested_by=case["super_admin_user"].user_id,
        provider_id=provider.provider_id,
        provider_revision=provider.revision,
        prompt_version=0,
        patient_id=value["patient_id"],
        encounter_ref=value["admission_id"],
        preview=1,
        status="queued",
        input_json=c.canonical_json(snapshot),
        evidence_json=c.canonical_json(bundle.evidence),
        context_metadata_json=c.canonical_json(metadata),
        context_digest=digest(bundle.data),
        prompt_hash=digest([CHARGE_RECONCILIATION_SYSTEM_PROMPT, task]),
        result_json="{}",
    )
    db.add(run)
    db.flush()
    storage.stage_anchor(db, run)
    db.commit()
    return run, snapshot, metadata, value


def test_complete_original_task_sql_anchor_and_exact_bytes_round_trip(charge_case):
    case, db = charge_case, charge_case["db"]
    run, snapshot, metadata, value = original_run(case)
    saved, binding, meta, evidence = storage.load_snapshot(db, run)
    assert saved == snapshot and meta == metadata and evidence == snapshot["payload"]["evidence"]
    assert binding == snapshot["payload"]["context"]["charge_binding"]
    row = db.get(AIChargeRunArtifact, run.run_id)
    assert row.case_snapshot_id == value["case_snapshot_id"] and row.requested_by == run.requested_by
    assert row.result_json is row.result_hash is row.result_bytes is row.receipt_event_id is row.accepted_lease is None
    assert storage.is_charge_run(db, run)


@pytest.mark.parametrize("field", ["input_json", "evidence_json", "context_metadata_json"])
def test_reencoded_or_whitespace_changed_raw_original_json_is_rejected(charge_case, field):
    run, _, _, _ = original_run(charge_case)
    setattr(run, field, getattr(run, field) + " ")
    with pytest.raises(HTTPException) as caught:
        storage.load_snapshot(charge_case["db"], run)
    assert caught.value.status_code == 409


@pytest.mark.parametrize("field", storage.ANCHOR_FIELDS)
def test_current_sql_anchor_hash_change_is_not_accepted_from_identity_cache(charge_case, field):
    case, db = charge_case, charge_case["db"]
    run, _, _, _ = original_run(case)
    db.get(AIChargeRunArtifact, run.run_id)
    db.execute(update(AIChargeRunArtifact).where(AIChargeRunArtifact.run_id == run.run_id).values({field: "f" * 64}))
    db.commit()
    with pytest.raises(HTTPException) as caught:
        storage.load_snapshot(db, run)
    assert caught.value.status_code == 409


@pytest.mark.parametrize(
    "mutation", ["mixed_context", "wrong_feature", "wrong_patient", "wrong_encounter", "wrong_author", "provider_extra", "provider_bool", "validation_extra", "tool", "evidence", "unknown_metadata"]
)
def test_closed_task_fields_scope_and_original_provider_are_required(charge_case, mutation):
    run, snapshot, metadata, _ = original_run(charge_case)
    if mutation == "mixed_context":
        snapshot["payload"]["context"]["patient_body"] = "private synthetic text"
    elif mutation == "wrong_feature":
        run.feature_key = "record_draft"
    elif mutation == "wrong_patient":
        run.patient_id = True
    elif mutation == "wrong_encounter":
        run.encounter_ref = "another-admission"
    elif mutation == "wrong_author":
        run.requested_by = charge_case["admin_user"].user_id
    elif mutation == "provider_extra":
        snapshot["provider_snapshot"]["api_key"] = "synthetic-not-a-secret"
    elif mutation == "provider_bool":
        snapshot["provider_snapshot"]["revision"] = True
    elif mutation == "validation_extra":
        snapshot["feature_validation"]["pretend_validated"] = True
    elif mutation == "tool":
        snapshot["payload"]["tools"] = {"execute_charge": True}
    elif mutation == "evidence":
        snapshot["payload"]["evidence"] = []
    else:
        metadata["pretend_financial_validation"] = True
    run.input_json = c.canonical_json(snapshot)
    run.context_metadata_json = c.canonical_json(metadata)
    with pytest.raises(HTTPException) as caught:
        storage.load_snapshot(charge_case["db"], run)
    assert caught.value.status_code == 409


def test_removing_optional_json_markers_cannot_downgrade_a_durable_charge_run(charge_case):
    case, db = charge_case, charge_case["db"]
    run, _, _, _ = original_run(case)
    run.feature_key = "record_draft"
    run.input_json = "{}"
    run.result_json = "{}"
    db.flush()
    assert storage.is_charge_run(db, run)
    with pytest.raises(HTTPException) as caught:
        storage.load_snapshot(db, run)
    assert caught.value.status_code == 409


def test_missing_durable_anchor_rejects_source_proof_even_with_consistent_json(charge_case):
    case, db = charge_case, charge_case["db"]
    run, _, _, _ = original_run(case)
    db.delete(db.get(AIChargeRunArtifact, run.run_id))
    db.commit()
    with pytest.raises(HTTPException) as caught:
        storage.load_snapshot(db, run)
    assert caught.value.status_code == 409


def test_original_text_capacity_uses_utf8_and_never_truncates_or_accepts_duplicate_json(charge_case):
    run, snapshot, _, _ = original_run(charge_case)
    before = copy.deepcopy(snapshot)
    snapshot["task_prompt"] = "界" * 22000
    run.input_json = c.canonical_json(snapshot)
    with pytest.raises(HTTPException) as caught:
        storage.load_snapshot(charge_case["db"], run)
    assert caught.value.status_code == 409 and len(c.utf8(run.input_json)) > 65535
    assert before["task_prompt"] != snapshot["task_prompt"]
    for raw in ('{"a":1,"a":1}', '{"a":NaN}', "{} ", '"\ud800"'):
        with pytest.raises((ValueError, UnicodeError)):
            storage._json(raw)
