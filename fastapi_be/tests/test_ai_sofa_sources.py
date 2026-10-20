"""Actual ORM manifest completeness, reliable cutoff clocks and unchanged old originals."""

import datetime
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import inpatient_gcs
from app import inpatient_support_common as common
from app.ai import sofa_sources as sofa
from app.inpatient_laboratory import hash_content
from app.inpatient_observations import canonical_json, utc_text
from app.inpatient_respiratory_models import InpatientArterialPairSource
from tests.test_ai_observation_windows import observation_case as observation_case
from tests.test_ai_observation_windows import urine
from tests.test_inpatient_respiratory_contract import NOTE, map_payload
from tests.test_inpatient_respiratory_sources import body as pair_body
from tests.test_inpatient_respiratory_sources import create
from tests.test_inpatient_respiratory_sources import source_case as source_case


@pytest.fixture
def sofa_case(db_session, source_case, monkeypatch):
    case = source_case
    monkeypatch.setattr(sofa, "utcnow", lambda: case["now"])
    monkeypatch.setattr(inpatient_gcs, "utcnow", lambda: case["now"])
    case["map"] = create(db_session, case, "map", map_payload(observed_at=utc_text(case["start"])))
    case["pair"] = create(db_session, case, "arterial_pair", pair_body(case))
    case["gcs"] = inpatient_gcs.create_source(
        db_session,
        case["doctor"],
        {
            "patient_id": case["patient_id"],
            "admission_id": case["admission"].admission_id,
            "observed_at": utc_text(case["start"] + datetime.timedelta(minutes=11)),
            "payload": {
                "components": {"eye": {"score": 4, "absent_reason": None}, "verbal": {"score": None, "absent_reason": "not_testable"}, "motor": {"score": 6, "absent_reason": None}},
                "anchor_point": None,
                "same_exam_confirmed": False,
                "same_exam_basis_note": None,
                "note": "合成不可测言语原GCS，不得补正常15或NT1",
            },
        },
    )
    db_session.commit()
    return {**case, "period_start": case["end"] - datetime.timedelta(days=1), "period_end": case["end"], "cutoff": case["now"]}


def period(case, **changes):
    return {
        "patient_id": case["patient_id"],
        "admission_id": case["admission"].admission_id,
        "period_start": utc_text(case["period_start"]),
        "period_end": utc_text(case["period_end"]),
        "as_of": utc_text(case["cutoff"]),
        **changes,
    }


def manifest(db, case, **changes):
    values = period(case, **changes)
    return sofa.period_manifest(db, case["doctor"], values["patient_id"], values["admission_id"], values["period_start"], values["period_end"], values["as_of"])


def review(member, *, status="unknown"):
    value = {
        "kind": member["kind"],
        "member_key": member["member_key"],
        "expected_content_hash": member["content_hash"],
        "status": status,
        "basis_note": NOTE,
        "exclusion_reason": "not_applicable" if status == "excluded" else None,
    }
    if member["kind"] == "gcs":
        value.update(interpretable="unknown", sedation_confounding_status="unknown", other_confounding_status="unknown", confounding_basis_note=NOTE)
    if member["kind"] == "arterial_pair":
        value.update(qualifying_respiratory_support="unknown", support_qualification_basis_note=NOTE)
    if member["kind"] == "vasoactive":
        value.update(continuous_iv="unknown", rate_scope="unknown", weight_use_confirmed=False, weight_basis_note=NOTE, mass_basis_compatible_confirmed=False, mass_basis_note=NOTE)
    return value


def request(case, original):
    coverage = {axis: {"source_inventory": "unknown", "clinical_protocol": "unknown", "basis_note": NOTE} for axis in sofa.AXES}
    coverage["cardiovascular"].update(drug_exposure="unknown", no_other_unrepresented_exposure_confirmed=False)
    return {
        **period(case),
        "rule_profile_id": "12345678-1234-4234-8234-13123456789a",
        "expected_rule_profile_hash": "a" * 64,
        "expected_manifest_hash": original["content_hash"],
        "age_at_period_years": None,
        "age_basis_note": NOTE,
        "care_setting": "unknown",
        "care_setting_basis_note": NOTE,
        "applicability_confirmed": False,
        "member_reviews": [review(member) for member in original["members"]],
        "coverage": coverage,
        "conflict_reviews": [],
        "vasoactive_group_reviews": [],
        "note": "",
    }


def test_manifest_enumerates_actual_roots_without_recounting_pair_dependencies_and_preserves_raws(db_session, sofa_case):
    case = sofa_case
    before = (case["lab"].snapshot_json, case["fio2"].payload_json, case["gcs"].payload_json)
    result = manifest(db_session, case)
    assert [item["kind"] for item in result["members"]] == ["arterial_pair", "gcs", "laboratory", "map", "respiratory_support", "urine"]
    assert result["content_hash"] == hash_content({key: value for key, value in result.items() if key != "content_hash"})
    assert result == manifest(db_session, case)
    pair = next(item["full_source"] for item in result["members"] if item["kind"] == "arterial_pair")
    assert pair["reference_snapshots"]["pao2"]["collected_at_utc"] != pair["reference_snapshots"]["fio2"]["observed_at"]
    gcs = next(item["full_source"] for item in result["members"] if item["kind"] == "gcs")
    assert gcs["payload"]["components"]["verbal"] == {"score": None, "absent_reason": "not_testable"}
    assert gcs["derived_total"] is None
    assert before == (case["lab"].snapshot_json, case["fio2"].payload_json, case["gcs"].payload_json)


@pytest.mark.parametrize("field,value", [("patient_id", True), ("patient_id", "1"), ("patient_id", 1.0), ("period_start", "2026-01-01T00:00:00Z"), ("period_end", "2026-01-01T00:00:00.000000+00:00")])
def test_period_request_rejects_coercion_and_noncanonical_clocks(sofa_case, field, value):
    with pytest.raises(ValidationError):
        sofa.PeriodRequest.model_validate(period(sofa_case, **{field: value}))


@pytest.mark.parametrize("offset", [-1, 1])
def test_only_exact_twenty_four_hours_is_accepted(sofa_case, offset):
    with pytest.raises(ValidationError):
        sofa.PeriodRequest.model_validate(period(sofa_case, period_start=utc_text(sofa_case["period_start"] + datetime.timedelta(microseconds=offset))))


def test_future_cutoff_is_rejected_before_any_candidate_is_read(db_session, sofa_case):
    with pytest.raises(HTTPException) as error:
        manifest(db_session, sofa_case, as_of=utc_text(sofa_case["now"] + datetime.timedelta(microseconds=1)))
    assert error.value.status_code == 422


def test_late_roots_are_invisible_before_counts_and_member_ids(db_session, sofa_case, monkeypatch):
    before = manifest(db_session, sofa_case)
    monkeypatch.setattr(common, "utcnow", lambda: sofa_case["now"] + datetime.timedelta(microseconds=1))
    late = create(db_session, sofa_case, "map", map_payload(observed_at=utc_text(sofa_case["start"])))
    after = manifest(db_session, sofa_case)
    assert before == after
    assert late.support_source_id not in canonical_json(after)


def test_new_cutoff_visible_member_changes_the_entire_manifest_even_when_identical_value(db_session, sofa_case):
    before = manifest(db_session, sofa_case)
    create(db_session, sofa_case, "map", map_payload(observed_at=utc_text(sofa_case["start"])))
    after = manifest(db_session, sofa_case)
    assert before["content_hash"] != after["content_hash"] and len(after["members"]) == len(before["members"]) + 1
    assert after["conflict_groups"] == []  # Same UTC alone does not prove the same sample.


def test_revoked_original_remains_full_explicitly_excluded_member(db_session, sofa_case):
    case = sofa_case
    before = manifest(db_session, case)
    row = case["map"]
    common.revoke_source(db_session, case["doctor"], "map", row.support_source_id, {"patient_id": case["patient_id"], "admission_id": row.admission_id, "expected_revision": 1, "reason": NOTE})
    db_session.commit()
    after = manifest(db_session, case)
    member = next(item for item in after["members"] if item["identifier"] == row.support_source_id)
    assert member["eligible"] is False and member["exclusion_reasons"] == ["source_revoked"]
    assert member["content_hash"] == row.content_hash and member["full_source"]["payload"]["map"]["value"] == "0.00000000"
    assert before["content_hash"] != after["content_hash"]


@pytest.mark.parametrize("change", ["lab_original", "point_hash", "doctor_identity", "root_hash"])
def test_broken_actual_original_or_doctor_dependency_blocks_whole_manifest_instead_of_silently_dropping_member(db_session, sofa_case, change):
    from app.models import Doctor

    case = sofa_case
    if change == "lab_original":
        case["lab_report"].audit_status = 0
    elif change == "point_hash":
        case["fio2"].content_hash = "0" * 64
    elif change == "doctor_identity":
        signer = json.loads(case["pair"].author_qualification_json)
        db_session.get(Doctor, signer["doctor_id"]).user_id = case["seed"]["nurse_user"].user_id
    else:
        case["map"].content_hash = "0" * 64
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        values = period(case)
        sofa.period_manifest(db_session, case["seed"]["super_admin_user"], values["patient_id"], values["admission_id"], values["period_start"], values["period_end"], values["as_of"])
    assert error.value.status_code == 409


def test_every_original_pair_for_same_actual_sample_is_bound_into_conflict_membership(db_session, sofa_case):
    case = sofa_case
    create(db_session, case, "arterial_pair", pair_body(case, note="合成原同份血气的第二个人工明确配对"))
    result = manifest(db_session, case)
    groups = [group for group in result["conflict_groups"] if group["relation"] == "arterial_original"]
    assert len(groups) == 1 and len(groups[0]["member_source_ids"]) == 2
    pair_rows = db_session.query(InpatientArterialPairSource).filter_by(admission_id=case["admission"].admission_id).all()
    assert sorted(groups[0]["member_keys"]) == sorted(f"arterial_pair:{row.support_source_id}" for row in pair_rows)


def test_positive_urine_overlap_is_explicit_and_touching_endpoints_are_not_overlap(db_session, sofa_case):
    case = sofa_case
    urine(db_session, case, start=case["start"], end=case["start"] + datetime.timedelta(minutes=30), recorded=case["cutoff"])
    urine(db_session, case, start=case["end"], end=case["end"] + datetime.timedelta(minutes=30), recorded=case["cutoff"])
    db_session.commit()
    result = manifest(db_session, case)
    groups = [group for group in result["conflict_groups"] if group["relation"] == "overlapping_urine"]
    assert len(groups) == 1 and len(groups[0]["member_keys"]) == 2
    assert len([item for item in result["members"] if item["kind"] == "urine"]) == 2


@pytest.mark.parametrize("field", ["age_at_period_years", "care_setting", "applicability_confirmed", "coverage", "member_reviews", "vasoactive_group_reviews"])
def test_private_clinical_states_are_required_without_hidden_normal_defaults(db_session, sofa_case, field):
    values = request(sofa_case, manifest(db_session, sofa_case))
    values.pop(field)
    with pytest.raises(ValidationError):
        sofa.AssessmentCreate.model_validate(values)


def test_all_seven_strict_review_types_and_unknowns_survive_roundtrip(db_session, sofa_case):
    values = request(sofa_case, manifest(db_session, sofa_case))
    actual = sofa.AssessmentCreate.model_validate(values).model_dump(mode="json")
    assert json.loads(canonical_json(actual)) == values
    for change in ({"basis_note": " " * 999}, {"status": "confirmed", "exclusion_reason": "duplicate_record"}, {"score": 4}, {"kind": "laboratory", "quantity": "1"}):
        wrong = json.loads(canonical_json(values))
        wrong["member_reviews"][0].update(change)
        with pytest.raises(ValidationError):
            sofa.AssessmentCreate.model_validate(wrong)


def test_stream_identity_is_not_split_by_free_narrative_basis():
    identity = {"source_namespace": "synthetic-pump", "external_stream_id": "actual-stream-1", "identity_basis_note": NOTE}
    first = {"payload": {"stream_identity": identity}}
    second = {"payload": {"stream_identity": {**identity, "identity_basis_note": NOTE + " Another real review."}}}
    assert sofa.stream_key(first) == sofa.stream_key(second) == hash_content({key: identity[key] for key in ("source_namespace", "external_stream_id")})


@pytest.fixture
def assessment_case(db_session, sofa_case, monkeypatch):
    from app.ai import risk_rule_profiles
    from app.ai.models import AIRiskRuleProfile
    from app.ai.sofa_contract import recipe_digest
    from app.routers import ai_risk_rules

    case = sofa_case
    for module in (risk_rule_profiles, ai_risk_rules):
        monkeypatch.setattr(module, "utcnow", lambda: case["now"] - datetime.timedelta(microseconds=1))
    profile = db_session.query(AIRiskRuleProfile).filter_by(rule_id=sofa.RULE_ID, status="published").first()
    if profile is None:
        profile = risk_rule_profiles.create_profile(
            db_session,
            case["seed"]["super_admin_user"],
            {
                "name": "Synthetic complete SOFA original-source implementation",
                "rule_id": sofa.RULE_ID,
                "expected_recipe_digest": recipe_digest(),
                "evidence_reference": "Synthetic original implementation review, no clinical validation",
                "rationale": NOTE,
            },
        )
        db_session.commit()
        ai_risk_rules.publish_profile(
            profile.rule_profile_id,
            ai_risk_rules.ProfilePublish(
                expected_revision=1,
                expected_recipe_digest=recipe_digest(),
                implementation_terms_confirmed=True,
                review_note=NOTE,
                review_evidence_reference="Synthetic independent implementation source review",
            ),
            db_session,
            case["seed"]["super_admin_user"],
        )
    original = manifest(db_session, case)
    values = request(case, original)
    values.update(rule_profile_id=profile.rule_profile_id, expected_rule_profile_hash=profile.content_hash)
    return {**case, "request": values, "profile": profile}


def register(db, case, *, actor=None, values=None):
    row = sofa.create_assessment(db, actor or case["doctor"], values or case["request"])
    db.commit()
    return row


def test_complete_daily_original_has_immutable_private_public_hashes_and_no_outbound_identity_or_notes(db_session, assessment_case):
    case = assessment_case
    row = register(db_session, case)
    current = sofa.authorize_assessment(db_session, case["doctor"], case["patient_id"], row.admission_id, row.assessment_id)
    public = current["specialist_source"]
    assert current["eligible"] is True and current["snapshot"]["manifest"]["content_hash"] == row.manifest_digest
    assert row.content_hash == hash_content(current["snapshot"])
    assert row.projection_hash == hash_content(public) and public["content_hash"] == row.content_hash
    assert public["assessment_governance_hash"] == current["governance_hash"]
    assert public["gcs_observations"][0]["components"]["verbal"]["score"] is None
    assert public["population"]["adult"] == "unknown" and public["population"]["applicability_confirmed"] is False
    assert len(public["respiratory_observations"]) == len(public["respiratory_support_observations"]) == 1
    encoded = canonical_json(public)
    for forbidden in ("patient_id", "admission_id", "created_by", "basis_note", "value_text", "barcode", "external_stream_id", "identity_basis_note", NOTE):
        assert forbidden not in encoded
    assert "current_retrospective_review" == current["snapshot"]["review_mode"]
    assert current["snapshot"]["historical_prediction"] is False


@pytest.mark.parametrize("role", ["nurse_user", "admin_user", "super_admin_user"])
def test_manager_or_grant_does_not_create_actual_doctor_identity(db_session, assessment_case, role):
    from app.ai.sofa_models import AISofaAssessment

    case = assessment_case
    before = db_session.query(AISofaAssessment).count()
    with pytest.raises(HTTPException) as error:
        register(db_session, case, actor=case["seed"][role])
    assert error.value.status_code == 403
    assert db_session.query(AISofaAssessment).count() == before


@pytest.mark.parametrize("change", ["omit_review", "wrong_hash", "wrong_manifest", "extra_review", "profile_hash"])
def test_all_member_and_profile_bindings_are_atomic_preconditions(db_session, assessment_case, change):
    from app.ai.sofa_models import AISofaAssessment

    case = assessment_case
    values = json.loads(canonical_json(case["request"]))
    if change == "omit_review":
        values["member_reviews"].pop()
    elif change == "wrong_hash":
        values["member_reviews"][0]["expected_content_hash"] = "0" * 64
    elif change == "wrong_manifest":
        values["expected_manifest_hash"] = "0" * 64
    elif change == "extra_review":
        values["member_reviews"].append({**values["member_reviews"][0], "member_key": "arterial_pair:missing"})
    else:
        values["expected_rule_profile_hash"] = "0" * 64
    before = db_session.query(AISofaAssessment).count()
    with pytest.raises(HTTPException) as error:
        register(db_session, case, values=values)
    assert error.value.status_code == 409
    assert db_session.query(AISofaAssessment).count() == before


def test_late_new_member_does_not_invalidate_but_cutoff_visible_new_member_does(db_session, assessment_case, monkeypatch):
    case = assessment_case
    row = register(db_session, case)
    frozen = sofa.assessment_detail(db_session, row)
    monkeypatch.setattr(common, "utcnow", lambda: case["cutoff"] + datetime.timedelta(microseconds=1))
    create(db_session, case, "map", map_payload(observed_at=utc_text(case["start"])))
    assert sofa.assessment_detail(db_session, row) == frozen
    monkeypatch.setattr(common, "utcnow", lambda: case["cutoff"])
    create(db_session, case, "map", map_payload(observed_at=utc_text(case["start"])))
    with pytest.raises(HTTPException) as error:
        sofa.assessment_detail(db_session, row)
    assert error.value.status_code == 409
    audited = sofa.assessment_detail(db_session, row, audit_only=True)
    assert audited["eligible"] is False and audited["specialist_source"] == frozen["specialist_source"]
    assert "complete_original_manifest_changed" in audited["exclusion_reasons"]


def test_cas_revoke_retains_original_projection_and_super_can_govern_stale_sources(db_session, assessment_case):
    case = assessment_case
    row = register(db_session, case)
    frozen = sofa.assessment_detail(db_session, row)
    case["lab_report"].audit_status = 0
    db_session.commit()
    sofa.revoke_assessment(db_session, case["seed"]["super_admin_user"], row.assessment_id, 1, NOTE)
    db_session.commit()
    audited = sofa.assessment_detail(db_session, row, audit_only=True)
    assert audited["status"] == "revoked" and audited["revision"] == 2 and audited["eligible"] is False
    assert audited["governance_hash"] != frozen["governance_hash"]
    assert audited["specialist_source"] == frozen["specialist_source"]
    assert audited["specialist_source"]["assessment_governance_hash"] == frozen["governance_hash"]
    with pytest.raises(HTTPException) as stale:
        sofa.revoke_assessment(db_session, case["seed"]["super_admin_user"], row, 1, NOTE)
    assert stale.value.status_code == 409


@pytest.mark.parametrize("location", ["snapshot", "projection", "projection_hash", "private_hash", "metadata"])
def test_corrupted_frozen_original_rejects_even_super_audit_and_cas_revoke(db_session, assessment_case, location):
    case = assessment_case
    row = register(db_session, case)
    if location == "snapshot":
        value = json.loads(row.snapshot_json)
        value["attestation"]["age_at_period_years"] = 90
        row.snapshot_json = canonical_json(value)
    elif location == "projection":
        value = json.loads(row.projection_json)
        value["map_observations"][0]["quantity"]["value"] = "99"
        row.projection_json, row.projection_hash = canonical_json(value), hash_content(value)
    elif location == "projection_hash":
        row.projection_hash = "0" * 64
    elif location == "private_hash":
        row.content_hash = "0" * 64
    else:
        row.manifest_digest = "0" * 64
    db_session.commit()
    for action in (lambda: sofa.assessment_detail(db_session, row, audit_only=True), lambda: sofa.revoke_assessment(db_session, case["seed"]["super_admin_user"], row, 1, NOTE)):
        with pytest.raises(HTTPException) as error:
            action()
        assert error.value.status_code == 409


def test_private_and_public_utf8_caps_reject_before_any_assessment_write(db_session, assessment_case, monkeypatch):
    from app.ai.sofa_models import AISofaAssessment

    case = assessment_case
    row = sofa.create_assessment(db_session, case["doctor"], case["request"])
    private_bytes, public_bytes = len(row.snapshot_json.encode("utf-8")), len(row.projection_json.encode("utf-8"))
    db_session.expunge(row)
    for name, count in (("MAX_PRIVATE_BYTES", private_bytes), ("MAX_PUBLIC_BYTES", public_bytes)):
        before = db_session.query(AISofaAssessment).count()
        with monkeypatch.context() as local:
            local.setattr(sofa, name, count - 1)
            with pytest.raises(HTTPException) as error:
                sofa.create_assessment(db_session, case["doctor"], case["request"])
            assert error.value.status_code == 422
        assert db_session.query(AISofaAssessment).count() == before
