"""Actual doctor episode originals, current evidence and transactional HTTP governance."""

import datetime
import json
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import inpatient_infection_episodes as episodes
from app import inpatient_support_common as common
from app.ai.governance import digest
from app.ai.models import AIAuditEvent
from app.diagnosis_review import source_facts
from app.inpatient_infection_models import InpatientInfectionEpisodeSource
from app.inpatient_observations import canonical_json, utc_text
from app.models import ClinicalDiagnosisReview, Doctor, StructuredMedicalRecord
from tests.test_inpatient_respiratory_sources import observation_case as observation_case
from tests.test_inpatient_respiratory_sources import source_case as source_case

REAL_DEFINITIONS = common.definitions
NOTE = "临床医生现在核实合成患者原住院感染范围与发作时刻，保留原始未知和独立证据，不自动构成脓毒症或感染所致器官变化。"


@pytest.fixture
def episode_case(db_session, source_case, monkeypatch):
    monkeypatch.setattr(common, "definitions", REAL_DEFINITIONS)
    db_session.query(InpatientInfectionEpisodeSource).delete()
    db_session.commit()
    return source_case


def payload(case, **changes):
    return {
        "infection_status": "suspected",
        "clinical_scope_start_at": utc_text(case["start"]),
        "clinical_scope_end_at": None,
        "first_suspected_at": utc_text(case["start"] + datetime.timedelta(minutes=2)),
        "onset_at": None,
        "onset_time_basis": "unknown",
        "onset_basis_note": NOTE,
        "infection_basis_note": NOTE,
        "evidence_refs": [],
        "note": "单条医生原始声明，不代表历史截止时已知或完整SOFA。",
        **changes,
    }


def body(case, **changes):
    return {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id, "payload": payload(case, **changes)}


def create(db, case, **changes):
    row = common.create_source(db, case["doctor"], "infection_episode", body(case, **changes))
    db.commit()
    return row


@pytest.mark.asyncio
async def test_actual_doctor_source_preserves_unknown_onset_original_scope_and_current_recording_clock(async_client, auth_headers, db_session, episode_case):
    case = episode_case
    before = (case["lab"].snapshot_json, case["fio2"].payload_json, case["admission"].status)
    response = await async_client.post("/api/inpatient-support/infection_episode", headers=auth_headers(case["doctor"].username), json=body(case))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["event_at"] is None and data["payload"]["onset_at"] is None
    assert data["recorded_at"] == utc_text(case["now"]) > utc_text(case["as_of"])
    assert data["payload"]["clinical_scope_start_at"] == utc_text(case["start"]) and data["payload"]["clinical_scope_end_at"] is None
    assert data["kind"] == "infection_episode" and data["schema_version"] == "infection_episode_v1"
    assert data["source_id"] == f"infection_episode:{data['support_source_id']}:{data['content_hash'][:12]}"
    assert data["author_qualification"]["clinical_review_signed"] is True and data["eligible"] and data["can_record"] and data["can_revoke"]
    assert data["source_verification"] == "explicit_human_record_not_independently_verified"
    assert data["reference_snapshots"] == {"evidence": []} and "sepsis_confirmed" not in data
    row = db_session.get(InpatientInfectionEpisodeSource, data["support_source_id"])
    assert row.payload_json == canonical_json(data["payload"])
    assert before == (case["lab"].snapshot_json, case["fio2"].payload_json, case["admission"].status)
    assert db_session.query(AIAuditEvent).filter_by(action="support_source.create", target=row.support_source_id).count() == 1
    with pytest.raises(HTTPException) as unavailable:
        common.authorize_source(db_session, case["doctor"], case["patient_id"], row.admission_id, "infection_episode", row.support_source_id, as_of=case["as_of"])
    assert unavailable.value.status_code == 409


@pytest.mark.parametrize(
    "change",
    [
        "status_bool",
        "future_scope",
        "future_suspicion",
        "future_onset",
        "end_not_after_start",
        "naive",
        "submicrosecond",
        "missing_onset_basis",
        "unknown_but_has_onset",
        "duplicate_evidence",
        "sepsis_override",
        "probability",
    ],
)
def test_episode_cannot_forge_clocks_unknowns_or_diagnostic_fields(change, db_session, episode_case):
    case = episode_case
    data = body(case)
    future = utc_text(case["now"] + datetime.timedelta(microseconds=1))
    if change == "status_bool":
        data["payload"]["infection_status"] = True
    elif change == "future_scope":
        data["payload"]["clinical_scope_start_at"] = future
    elif change == "future_suspicion":
        data["payload"]["first_suspected_at"] = future
    elif change == "future_onset":
        data["payload"].update(onset_at=future, onset_time_basis="explicit_clinician_verified_utc")
    elif change == "end_not_after_start":
        data["payload"]["clinical_scope_end_at"] = data["payload"]["clinical_scope_start_at"]
    elif change == "naive":
        data["payload"]["clinical_scope_start_at"] = case["start"].isoformat()
    elif change == "submicrosecond":
        data["payload"]["clinical_scope_start_at"] = "2026-10-20T10:00:00.1234567Z"
    elif change == "missing_onset_basis":
        data["payload"]["onset_time_basis"] = "explicit_clinician_verified_utc"
    elif change == "unknown_but_has_onset":
        data["payload"]["onset_at"] = utc_text(case["start"])
    elif change == "duplicate_evidence":
        ref = {"kind": "lab_source", "source_id": case["lab"].lab_source_id, "expected_content_hash": case["lab"].content_hash}
        data["payload"]["evidence_refs"] = [ref, ref]
    else:
        data["payload"]["sepsis_confirmed" if change == "sepsis_override" else "probability"] = True
    before = db_session.query(InpatientInfectionEpisodeSource).count()
    with pytest.raises((HTTPException, ValidationError)):
        common.create_source(db_session, case["doctor"], "infection_episode", data)
    assert db_session.query(InpatientInfectionEpisodeSource).count() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["nurse_user", "admin_user", "super_admin_user", "cashier_user", "pharmacist_user", "guide_user", "lab_tech_user", "registrar_user", "patient_user"])
async def test_every_infection_status_still_requires_actual_doctor_signature(role, async_client, auth_headers, db_session, episode_case):
    case = episode_case
    before = db_session.query(InpatientInfectionEpisodeSource).count()
    response = await async_client.post("/api/inpatient-support/infection_episode", headers=auth_headers(case["seed"][role].username), json=body(case, infection_status="unknown"))
    assert response.status_code == 403, response.text
    assert db_session.query(InpatientInfectionEpisodeSource).count() == before


@pytest.mark.parametrize("known", [False, True])
def test_exact_known_onset_uses_own_utc_without_substituting_review_or_suspicion(known, db_session, episode_case):
    case = episode_case
    instant = case["start"] - datetime.timedelta(minutes=5, microseconds=123456)
    row = create(db_session, case, **({"onset_at": utc_text(instant), "onset_time_basis": "explicit_clinician_verified_utc"} if known else {}))
    assert row.event_at == (instant if known else None)
    assert row.recorded_at == case["now"]


def test_real_lab_evidence_candidates_and_full_parent_hash_are_preserved_and_rechecked(db_session, episode_case):
    case = episode_case
    candidates = episodes.evidence_candidates(db_session, case["patient_id"], case["admission"].admission_id, "lab_source")
    candidate = next(item for item in candidates["items"] if item["source_id"] == case["lab"].lab_source_id)
    assert candidate["eligible"] and candidate["source_snapshot"]["content_hash"] == candidate["expected_content_hash"]
    ref = {key: candidate[key] for key in ("kind", "source_id", "expected_content_hash")}
    row = create(db_session, case, evidence_refs=[ref])
    frozen = common.source_current(db_session, row, "infection_episode")
    assert frozen["reference_snapshots"]["evidence"] == [candidate["source_snapshot"]]
    case["lab_report"].result += " changed omitted original parent text"
    db_session.commit()
    with pytest.raises(HTTPException) as changed:
        common.source_current(db_session, row, "infection_episode")
    assert changed.value.status_code == 409
    audit = common.source_current(db_session, row, "infection_episode", audit_only=True)
    assert audit["reference_snapshots"] == frozen["reference_snapshots"] and not audit["eligible"]


def diagnosis(case, db):
    record = StructuredMedicalRecord(
        record_id=str(uuid.uuid4()),
        patient_id=case["patient_id"],
        admission_id=case["admission"].admission_id,
        doctor_id=case["seed"]["doctor"].doctor_id,
        record_type="admission",
        diagnosis="合成疑似原感染病历",
        status=1,
        sign_time=case["now"],
    )
    db.add(record)
    db.flush()
    review = ClinicalDiagnosisReview(
        review_id=str(uuid.uuid4()),
        source_kind="structured",
        source_id=record.record_id,
        patient_id=case["patient_id"],
        encounter_ref=record.admission_id,
        diagnosis_text=record.diagnosis,
        source_hash=digest(source_facts(record)),
        certainty="suspected",
        reason=NOTE,
        revision=1,
        reviewed_by=case["doctor"].user_id,
        reviewed_at=case["now"],
    )
    db.add(review)
    db.commit()
    return record, review


@pytest.mark.parametrize("change", ["parent_body", "unsigned", "newer_review", "wrong_admission", "wrong_hash"])
def test_diagnosis_evidence_binds_latest_actual_review_complete_signed_original_and_original_admission(change, db_session, episode_case):
    case = episode_case
    record, review = diagnosis(case, db_session)
    candidate = episodes.evidence_candidates(db_session, case["patient_id"], record.admission_id, "diagnosis_review")["items"][0]
    assert candidate["eligible"]
    ref = {key: candidate[key] for key in ("kind", "source_id", "expected_content_hash")}
    if change == "wrong_hash":
        ref["expected_content_hash"] = "0" * 64
        with pytest.raises(HTTPException):
            create(db_session, case, evidence_refs=[ref])
        return
    row = create(db_session, case, evidence_refs=[ref])
    frozen = common.source_current(db_session, row, "infection_episode")
    assert frozen["reference_snapshots"]["evidence"][0]["facts"]["original"]["diagnosis"] == record.diagnosis
    if change == "parent_body":
        record.diagnosis += " parent changed"
    elif change == "unsigned":
        record.status = 0
    elif change == "wrong_admission":
        record.admission_id = None
    else:
        newer = ClinicalDiagnosisReview(
            review_id=str(uuid.uuid4()),
            source_kind="structured",
            source_id=record.record_id,
            patient_id=case["patient_id"],
            encounter_ref=record.admission_id,
            diagnosis_text=record.diagnosis,
            source_hash=review.source_hash,
            certainty="excluded",
            reason=NOTE,
            revision=2,
            reviewed_by=case["doctor"].user_id,
            reviewed_at=case["now"],
        )
        db_session.add(newer)
    db_session.commit()
    with pytest.raises(HTTPException):
        common.source_current(db_session, row, "infection_episode")
    audit = common.source_current(db_session, row, "infection_episode", audit_only=True)
    assert not audit["eligible"] and audit["reference_snapshots"] == frozen["reference_snapshots"]


@pytest.mark.asyncio
async def test_doctor_identity_and_care_changes_deny_ordinary_but_preserve_super_cas_audit(async_client, auth_headers, db_session, episode_case):
    case = episode_case
    row = create(db_session, case)
    frozen = common.source_current(db_session, row, "infection_episode")
    signed = json.loads(row.author_qualification_json)
    db_session.get(Doctor, signed["doctor_id"]).user_id = case["seed"]["admin_user"].user_id
    db_session.commit()
    params = {"patient_id": case["patient_id"], "admission_id": row.admission_id}
    source_url = f"/api/inpatient-support/infection_episode/{row.support_source_id}"
    denied = await async_client.get(source_url, params=params, headers=auth_headers(case["doctor"].username))
    assert denied.status_code in {403, 409}
    super_headers = auth_headers(case["seed"]["super_admin_user"].username)
    audit = await async_client.get(f"/api/ai/admin/support-sources/infection_episode/{row.support_source_id}", headers=super_headers)
    assert audit.status_code == 200, audit.text
    assert not audit.json()["data"]["eligible"] and audit.json()["data"]["payload"] == frozen["payload"]
    revoked = await async_client.post(source_url + "/revoke", headers=super_headers, json={**params, "expected_revision": 1, "reason": NOTE})
    assert revoked.status_code == 200 and revoked.json()["data"]["revision"] == 2
    stale = await async_client.post(source_url + "/revoke", headers=super_headers, json={**params, "expected_revision": 1, "reason": NOTE})
    assert stale.status_code == 409
