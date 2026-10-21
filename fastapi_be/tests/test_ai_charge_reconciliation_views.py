"""Actual SQL ordinary/current and Super/frozen task views and FK history."""

import copy
import hashlib
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.ai import charge_reconciliation_sources as sources
from app.ai.charge_reconciliation_history import filter_history
from app.ai.charge_reconciliation_runtime import create_charge_run
from app.ai.charge_reconciliation_storage import load_snapshot
from app.ai.charge_reconciliation_view_contract import ChargeArtifactRecord
from app.ai.charge_reconciliation_views import describe_charge_run
from app.ai.models import AIRun
from app.models import InpatientCharge
from tests.test_ai_charge_reconciliation_runtime import configured
from tests.test_ai_charge_reconciliation_sources import NOTE, cas
from tests.test_ai_charge_reconciliation_sources import charge_case as _charge_case

charge_case = _charge_case


def test_pending_full_view_anchors_exact_retained_raw_json_and_complete_projection(charge_case):
    case, db = charge_case, charge_case["db"]
    actor, req, value, _, _ = configured(case)
    run = create_charge_run(db, actor, req)
    data = describe_charge_run(db, actor, run)
    assert data["usage_receipt_status"] == "pending" and data["result"] is None
    assert data["input_tokens"] is data["output_tokens"] is None
    assert data["charge_case_id"] == value["case_snapshot_id"]
    proof = data["charge_artifact"]
    for raw, anchor in [("input_json", "input_hash"), ("evidence_json", "evidence_hash"), ("context_metadata_json", "metadata_hash")]:
        assert proof[anchor] == hashlib.sha256(getattr(run, raw).encode("utf-8")).hexdigest()
    assert proof["created_at"].endswith(".123456Z") and ChargeArtifactRecord.model_validate(proof).run_id == run.run_id
    assert data["charge_findings"]["charge_source"] == value["public_source"]
    assert data["charge_findings"]["charge_case"]["can_record"] is False
    assert describe_charge_run(db, actor, run, False).keys().isdisjoint({"result", "charge_artifact", "charge_findings"})


def test_ordinary_original_actor_reads_current_but_super_alone_can_audit_revoked_source(charge_case):
    case, db = charge_case, charge_case["db"]
    actor, req, value, _, _ = configured(case, actor=case["admin_user"], preview=False)
    run = create_charge_run(db, actor, req)
    assert describe_charge_run(db, actor, run)["charge_findings"]["charge_source"] == value["public_source"]
    sources.revoke_case(db, case["super_admin_user"], value["case_snapshot_id"], {**cas(value), "basis_note": NOTE})
    db.commit()
    with pytest.raises(HTTPException) as caught:
        describe_charge_run(db, actor, run)
    assert caught.value.status_code == 409
    db.rollback()
    data = describe_charge_run(db, case["super_admin_user"], run)
    assert data["charge_findings"]["charge_case"]["status"] == "revoked"
    assert data["charge_findings"]["charge_source"] == value["public_source"]


def test_other_ordinary_actor_cannot_read_private_task_even_when_patient_authorized(charge_case):
    case, db = charge_case, charge_case["db"]
    actor, req, _, _, _ = configured(case)
    run = create_charge_run(db, actor, req)
    with pytest.raises(HTTPException) as caught:
        describe_charge_run(db, case["admin_user"], run)
    assert caught.value.status_code == 403


def test_changed_nonwinner_record_invalidates_ordinary_view_while_super_keeps_frozen_proof(charge_case):
    case, db = charge_case, charge_case["db"]
    actor, req, value, _, _ = configured(case, actor=case["admin_user"], preview=False)
    run = create_charge_run(db, actor, req)
    charge_id = case["charges"][-1].charge_id
    db.execute(update(InpatientCharge).where(InpatientCharge.charge_id == charge_id).values(status=-7))
    db.commit()
    with pytest.raises(HTTPException) as caught:
        describe_charge_run(db, actor, run)
    assert caught.value.status_code == 409
    db.rollback()
    assert describe_charge_run(db, case["super_admin_user"], run)["charge_findings"]["charge_source"] == value["public_source"]


def test_history_requires_exact_patient_admission_and_uses_actual_artifact_case_fk(charge_case):
    case, db = charge_case, charge_case["db"]
    actor, req, value, _, _ = configured(case, actor=case["admin_user"], preview=False)
    first = create_charge_run(db, actor, req)
    other_actor, other_req, other, _, _ = configured(case, actor=actor, preview=False)
    second = create_charge_run(db, other_actor, other_req)
    # Both cases have the same actual patient/Admission; their immutable case FKs differ.
    assert other["case_snapshot_id"] != value["case_snapshot_id"]
    query = filter_history(db, actor, db.query(AIRun), charge_case_id=value["case_snapshot_id"], patient_id=value["patient_id"], encounter_ref=value["admission_id"])
    assert [row.run_id for row in query] == [first.run_id] and second.run_id != first.run_id
    for patient_id, encounter_ref, expected in [(None, None, 422), (value["patient_id"] + 10000, value["admission_id"], 403), (value["patient_id"], str(uuid.uuid4()), 403)]:
        with pytest.raises(HTTPException) as caught:
            filter_history(db, actor, db.query(AIRun), charge_case_id=value["case_snapshot_id"], patient_id=patient_id, encounter_ref=encounter_ref)
        assert caught.value.status_code == expected
    assert filter_history(db, case["super_admin_user"], db.query(AIRun), charge_case_id=value["case_snapshot_id"], patient_id=None, encounter_ref=None).count() == 1


def test_raw_original_json_reencoding_is_not_a_valid_full_view(charge_case):
    case, db = charge_case, charge_case["db"]
    actor, req, _, _, _ = configured(case)
    run = create_charge_run(db, actor, req)
    run.input_json += " "
    with pytest.raises(HTTPException) as caught:
        describe_charge_run(db, actor, run)
    assert caught.value.status_code == 409
    db.rollback()
    assert load_snapshot(db, run)[0]["payload"]["input"] == req.input


@pytest.mark.parametrize("field,value", [("requested_by", True), ("result_bytes", 0), ("receipt_event_id", True), ("created_at", "2026-10-21T12:30:00Z")])
def test_public_artifact_contract_refuses_coercion_or_loss_of_actual_clock_precision(charge_case, field, value):
    case, db = charge_case, charge_case["db"]
    actor, req, _, _, _ = configured(case)
    run = create_charge_run(db, actor, req)
    proof = copy.deepcopy(describe_charge_run(db, actor, run)["charge_artifact"])
    proof[field] = value
    with pytest.raises(ValueError):
        ChargeArtifactRecord.model_validate(proof)
