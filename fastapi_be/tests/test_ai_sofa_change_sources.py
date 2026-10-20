"""Actual current/baseline daily originals and separately governed infection review."""

import datetime
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import inpatient_support_common as common
from app.ai import sofa_change_sources as changes
from app.ai import sofa_sources as daily
from app.ai.sofa_models import AISofaChangeAssessment
from app.inpatient_laboratory import hash_content
from app.inpatient_observations import canonical_json, utc_text
from tests.test_ai_sofa_sources import assessment_case as assessment_case
from tests.test_ai_sofa_sources import manifest, register
from tests.test_ai_sofa_sources import observation_case as observation_case
from tests.test_ai_sofa_sources import request as daily_request
from tests.test_ai_sofa_sources import sofa_case as sofa_case
from tests.test_ai_sofa_sources import source_case as source_case
from tests.test_inpatient_infection_episodes import payload as infection_payload
from tests.test_inpatient_respiratory_contract import NOTE


@pytest.fixture
def change_case(db_session, assessment_case):
    case = assessment_case
    current = register(db_session, case)
    infection = common.create_source(
        db_session, case["doctor"], "infection_episode", {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id, "payload": infection_payload(case)}
    )
    db_session.commit()
    return {**case, "current": current, "infection": infection}


def body(case, **changes_):
    source = common.governance(case["infection"])
    return {
        "patient_id": case["patient_id"],
        "admission_id": case["admission"].admission_id,
        "current_assessment_id": case["current"].assessment_id,
        "expected_current_content_hash": case["current"].content_hash,
        "expected_current_projection_hash": case["current"].projection_hash,
        "baseline": {"mode": "unknown", "basis_note": NOTE},
        "infection_source_id": case["infection"].support_source_id,
        "expected_infection_content_hash": case["infection"].content_hash,
        "expected_infection_governance_hash": source["governance_hash"],
        "infection_review": {"current_presence": "unknown", "current_presence_basis_note": NOTE, "onset_review": "unknown", "onset_review_basis_note": NOTE},
        "review": {
            "acute_change": "unknown",
            "acute_change_basis_note": NOTE,
            "attribution": "uncertain",
            "attribution_basis_note": NOTE,
            "temporal_relation": "unknown",
            "temporal_relation_basis_note": NOTE,
        },
        "note": "合成当前回顾性归因核实，不能冒充历史预测或感染所致器官障碍诊断",
        **changes_,
    }


def create(db, case, **changes_):
    row = changes.create_change_assessment(db, case["doctor"], body(case, **changes_))
    db.commit()
    return row


def observed_baseline(db, case, *, admission=None, actor=None, start=None, end=None):
    earlier = {**case, "admission": admission or case["admission"], "period_end": end or case["period_start"], "period_start": start or case["period_start"] - datetime.timedelta(days=1)}
    original = (
        manifest(db, earlier)
        if actor is None
        else daily.period_manifest(db, actor, earlier["patient_id"], earlier["admission"].admission_id, utc_text(earlier["period_start"]), utc_text(earlier["period_end"]), utc_text(earlier["cutoff"]))
    )
    values = daily_request(earlier, original)
    values.update(rule_profile_id=case["profile"].rule_profile_id, expected_rule_profile_hash=case["profile"].content_hash)
    row = daily.create_assessment(db, actor or case["doctor"], values)
    db.commit()
    return row


def baseline_ref(row):
    return {"mode": "observed", "assessment_id": row.assessment_id, "expected_content_hash": row.content_hash, "expected_projection_hash": row.projection_hash}


def test_current_infection_unknown_baseline_retains_complete_raws_and_minimal_public_fact_hashes(db_session, change_case):
    case = change_case
    row = create(db_session, case)
    current = changes.authorize_change(db_session, case["doctor"], row.patient_id, row.admission_id, row.change_assessment_id)
    public = current["specialist_source"]
    assert row.content_hash == hash_content(current["snapshot"]) and row.projection_hash == hash_content(public)
    assert current["eligible"] is True and public["baseline"]["mode"] == "unknown"
    assert public["current"]["assessment_id"] == case["current"].assessment_id
    assert public["infection"]["onset_at"] is None and public["infection"]["current_presence"] == "unknown"
    assert public["review_mode"] == "current_retrospective_review" and public["historical_prediction"] is False
    for forbidden in ("patient_id", "admission_id", "created_by", "basis_note", NOTE, "evidence_refs", "barcode", "external_stream_id"):
        assert forbidden not in canonical_json(public)


def test_real_observed_baseline_is_a_second_independently_authorized_whole_day(db_session, change_case):
    case = change_case
    prior = observed_baseline(db_session, case)
    row = create(db_session, case, baseline=baseline_ref(prior))
    source = changes.change_detail(db_session, row)["specialist_source"]
    assert source["baseline"]["mode"] == "observed" and source["baseline"]["source"]["assessment_id"] == prior.assessment_id
    assert source["baseline"]["source"]["end_at"] == source["current"]["start_at"]
    assert row.baseline_assessment_id == prior.assessment_id


@pytest.mark.parametrize("no_known,confirmed", [(False, False), (False, True), (True, False), (True, True)])
def test_conditional_zero_is_explicit_doctor_assumption_with_both_unmet_conditions_retained(db_session, change_case, no_known, confirmed):
    baseline = {"mode": "conditional_zero", "no_known_preexisting_organ_dysfunction": no_known, "preinfection_baseline_assumption_confirmed": confirmed, "basis_note": NOTE}
    row = create(db_session, change_case, baseline=baseline)
    public = changes.change_detail(db_session, row)["specialist_source"]
    assert public["baseline"] == {key: value for key, value in baseline.items() if key != "basis_note"} | {"basis_hash": hash_content(NOTE)}
    assert row.baseline_assessment_id is None


@pytest.mark.parametrize("field", ["baseline", "infection_review", "review", "expected_current_projection_hash", "expected_infection_governance_hash"])
def test_no_implicit_baseline_or_infection_attribution_default(change_case, field):
    values = body(change_case)
    values.pop(field)
    with pytest.raises(ValidationError):
        changes.ChangeCreate.model_validate(values)


@pytest.mark.parametrize("field", ["expected_current_content_hash", "expected_current_projection_hash", "expected_infection_content_hash", "expected_infection_governance_hash"])
def test_full_daily_and_infection_governance_hashes_are_atomic_preconditions(db_session, change_case, field):
    before = db_session.query(AISofaChangeAssessment).count()
    with pytest.raises(HTTPException) as error:
        create(db_session, change_case, **{field: "0" * 64})
    assert error.value.status_code == 409
    assert db_session.query(AISofaChangeAssessment).count() == before


def test_current_day_cannot_be_reused_as_its_own_baseline(db_session, change_case):
    with pytest.raises(HTTPException) as error:
        create(db_session, change_case, baseline=baseline_ref(change_case["current"]))
    assert error.value.status_code == 409


def test_unknown_original_onset_cannot_be_made_known_by_later_clinician_review(db_session, change_case):
    values = body(change_case)
    values["infection_review"]["onset_review"] = "known"
    with pytest.raises(HTTPException) as error:
        changes.create_change_assessment(db_session, change_case["doctor"], values)
    assert error.value.status_code == 409


def test_infection_recorded_after_daily_cutoff_is_transparently_current_retrospective_evidence(db_session, change_case, monkeypatch):
    case = change_case
    later = case["now"] + datetime.timedelta(minutes=1)
    monkeypatch.setattr(common, "utcnow", lambda: later)
    monkeypatch.setattr(daily, "utcnow", lambda: later)
    infection = common.create_source(
        db_session, case["doctor"], "infection_episode", {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id, "payload": infection_payload(case)}
    )
    db_session.commit()
    row = create(db_session, {**case, "infection": infection})
    source = changes.change_detail(db_session, row)["specialist_source"]
    assert source["infection"]["late_original_available_after_current_as_of"] is True
    assert source["infection"]["recorded_at"] > source["current"]["as_of"]
    assert source["historical_prediction"] is False


@pytest.mark.parametrize("change", ["current_revoke", "infection_revoke", "parent_audit", "care_scope"])
def test_current_source_changes_block_ordinary_use_and_preserve_super_frozen_original(db_session, change_case, change):
    case = change_case
    row = create(db_session, case)
    original = changes.change_detail(db_session, row)
    if change == "current_revoke":
        daily.revoke_assessment(db_session, case["seed"]["super_admin_user"], case["current"], 1, NOTE)
    elif change == "infection_revoke":
        common.revoke_source(
            db_session,
            case["doctor"],
            "infection_episode",
            case["infection"].support_source_id,
            {"patient_id": case["patient_id"], "admission_id": row.admission_id, "expected_revision": 1, "reason": NOTE},
        )
    elif change == "parent_audit":
        case["lab_report"].audit_status = 0
    else:
        case["admission"].patient_id = case["seed"]["patient2"].patient_id
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        changes.change_detail(db_session, row)
    assert error.value.status_code == 409
    frozen = changes.change_detail(db_session, row, audit_only=True)
    assert frozen["eligible"] is False and frozen["specialist_source"] == original["specialist_source"]
    changes.revoke_change(db_session, case["seed"]["super_admin_user"], row, 1, NOTE)
    db_session.commit()
    revoked = changes.change_detail(db_session, row, audit_only=True)
    assert revoked["status"] == "revoked" and revoked["revision"] == 2
    assert revoked["specialist_source"] == original["specialist_source"]


def test_revoked_real_baseline_invalidates_whole_change_not_just_optional_branch(db_session, change_case):
    case = change_case
    prior = observed_baseline(db_session, case)
    row = create(db_session, case, baseline=baseline_ref(prior))
    daily.revoke_assessment(db_session, case["seed"]["super_admin_user"], prior, 1, NOTE)
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        changes.authorize_change(db_session, case["doctor"], row.patient_id, row.admission_id, row.change_assessment_id)
    assert error.value.status_code == 409
    assert changes.change_detail(db_session, row, audit_only=True)["eligible"] is False


def test_change_own_projection_corruption_rejects_even_super_audit_and_revoke(db_session, change_case):
    case = change_case
    row = create(db_session, case)
    corrupted = json.loads(row.projection_json)
    corrupted["review"]["acute_change"] = "confirmed"
    row.projection_json, row.projection_hash = canonical_json(corrupted), hash_content(corrupted)
    db_session.commit()
    for action in (lambda: changes.change_detail(db_session, row, audit_only=True), lambda: changes.revoke_change(db_session, case["seed"]["super_admin_user"], row, 1, NOTE)):
        with pytest.raises(HTTPException) as error:
            action()
        assert error.value.status_code == 409


def test_full_change_utf8_caps_reject_before_write_and_never_truncate(db_session, change_case, monkeypatch):
    case = change_case
    sample = changes.create_change_assessment(db_session, case["doctor"], body(case))
    sizes = (("MAX_PRIVATE_BYTES", len(sample.snapshot_json.encode("utf-8"))), ("MAX_PUBLIC_BYTES", len(sample.projection_json.encode("utf-8"))))
    db_session.expunge(sample)
    for name, count in sizes:
        before = db_session.query(AISofaChangeAssessment).count()
        with monkeypatch.context() as local:
            local.setattr(changes, name, count - 1)
            with pytest.raises(HTTPException) as error:
                changes.create_change_assessment(db_session, case["doctor"], body(case))
            assert error.value.status_code == 422
        assert db_session.query(AISofaChangeAssessment).count() == before


def test_change_candidates_use_actual_current_refs_and_do_not_invent_zero_baseline_or_infection(db_session, change_case):
    case = change_case
    values = {key: value for key, value in body(case).items() if key in changes.ChangeCandidatesRequest.model_fields}
    candidates = changes.candidates(db_session, case["doctor"], values)
    assert candidates["current_assessment"]["assessment_id"] == case["current"].assessment_id and candidates["can_sign"] is True
    assert len(candidates["infection_sources"]) == 1
    assert "baseline" not in candidates and "baseline_mode" not in candidates
