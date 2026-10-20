"""Six real clinical axes through the production public projection and independent pure model."""

import datetime
import json
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app import inpatient_gcs
from app import inpatient_laboratory as labs
from app import inpatient_vasoactive as vaso
from app.ai import sofa_sources as sofa
from app.ai.sofa_model import sofa_values
from app.inpatient_observations import canonical_json, utc_text
from app.models import LabObservation, Pharmaceutical
from tests.test_ai_observation_windows import urine
from tests.test_ai_sofa_sources import assessment_case as assessment_case
from tests.test_ai_sofa_sources import manifest, register, request, review
from tests.test_ai_sofa_sources import observation_case as observation_case
from tests.test_ai_sofa_sources import sofa_case as sofa_case
from tests.test_ai_sofa_sources import source_case as source_case
from tests.test_ai_vasoactive_mappings import published_mapping as drug_mapping
from tests.test_inpatient_laboratory import body as lab_body
from tests.test_inpatient_laboratory import published_mapping
from tests.test_inpatient_respiratory_contract import NOTE
from tests.test_inpatient_respiratory_sources import body as pair_body
from tests.test_inpatient_respiratory_sources import create
from tests.test_inpatient_vasoactive import dose
from tests.test_inpatient_vasoactive import payload as vaso_payload


def lab_original(db, case, analyte, value, unit, *, text=None):
    original = LabObservation(
        observation_id="sofa-lab-" + uuid.uuid4().hex[:20],
        lab_result_id=case["lab_report"].lab_result_id,
        code_system="synthetic-sofa",
        code="SYN-" + uuid.uuid4().hex[:10],
        display="private original display is never clinical identity",
        value_num=Decimal(value) if value is not None else None,
        value_text=text,
        unit=unit,
        method="synthetic",
        specimen_type="synthetic",
        flag="unknown",
        collected_at=datetime.datetime(2000, 1, 1, 12, 0),
    )
    db.add(original)
    db.commit()
    mapping = published_mapping(db, case["seed"]["super_admin_user"], original, analyte_key=analyte)
    source = labs.create_source(
        db,
        case["doctor"],
        lab_body(
            db,
            {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id, "observation": original, "mapping": mapping},
            collected_at_utc=utc_text(case["start"] + datetime.timedelta(minutes=7)),
        ),
    )
    db.commit()
    return source, original


def clinical_request(case, original):
    values = request(case, original)
    values.update(rule_profile_id=case["profile"].rule_profile_id, expected_rule_profile_hash=case["profile"].content_hash, age_at_period_years=60, care_setting="icu", applicability_confirmed=True)
    for axis in sofa.AXES:
        values["coverage"][axis].update(source_inventory="complete", clinical_protocol="adequate")
    values["coverage"]["cardiovascular"].update(drug_exposure="none", no_other_unrepresented_exposure_confirmed=True)
    values["member_reviews"] = [review(member, status="confirmed") for member in original["members"]]
    for item in values["member_reviews"]:
        if item["kind"] == "arterial_pair":
            item.update(qualifying_respiratory_support="yes")
        if item["kind"] == "gcs":
            item.update(interpretable="confirmed", sedation_confounding_status="excluded", other_confounding_status="excluded")
    return values


@pytest.fixture
def complete_case(db_session, assessment_case):
    case = assessment_case
    for analyte, value, unit in (("platelet_count", "160.00000000", "10^9/L"), ("total_bilirubin", "1.00000000", "mg/dL"), ("creatinine", "1.00000000", "mg/dL")):
        lab_original(db_session, case, analyte, value, unit)
    complete_gcs = inpatient_gcs.create_source(
        db_session,
        case["doctor"],
        {
            "patient_id": case["patient_id"],
            "admission_id": case["admission"].admission_id,
            "observed_at": utc_text(case["start"] + datetime.timedelta(minutes=16)),
            "payload": {
                "components": {"eye": {"score": 4, "absent_reason": None}, "verbal": {"score": 5, "absent_reason": None}, "motor": {"score": 6, "absent_reason": None}},
                "anchor_point": None,
                "same_exam_confirmed": False,
                "same_exam_basis_note": None,
                "note": "独立实际完整EVM检查，未替换旧NT原件",
            },
        },
    )
    full_urine = urine(
        db_session,
        case,
        start=case["period_start"],
        end=case["period_end"],
        recorded=case["cutoff"],
        payload={
            "volume_ml": "1000.00000000",
            "absent_reason": None,
            "collection_completeness": "complete",
            "patient_total": True,
            "collection_method": "synthetic complete measured 24h",
            "note": "实际收集整日，不外推",
        },
    )
    db_session.commit()
    original = manifest(db_session, case)
    values = clinical_request(case, original)
    for item in values["member_reviews"]:
        if item["member_key"] in ("gcs:" + case["gcs"].gcs_observation_id, "urine:" + case["urine"].interval_id):
            item.update(status="excluded", exclusion_reason="not_applicable")
    values["conflict_reviews"] = [
        {
            "group_id": group["group_id"],
            "expected_group_digest": group["group_digest"],
            "status": "resolved",
            "accepted_source_ids": [next(member["source_id"] for member in original["members"] if member["identifier"] == full_urine.interval_id)],
            "excluded_source_ids": [next(member["source_id"] for member in original["members"] if member["identifier"] == case["urine"].interval_id)],
            "basis_note": NOTE,
        }
        for group in original["conflict_groups"]
    ]
    return {**case, "complete_gcs": complete_gcs, "full_urine": full_urine, "request": values}


def test_all_six_axes_require_real_measurements_and_human_full_day_coverage(db_session, complete_case):
    case = complete_case
    row = register(db_session, case)
    source = sofa.assessment_detail(db_session, row)["specialist_source"]
    result = sofa_values(source)
    assert result["calculation_status"] == "computed" and result["protocol_complete_domain_count"] == result["observed_scored_domain_count"] == 6
    assert result["complete_total_score"] == result["lower_bound"] == result["upper_bound"] == 2
    assert [domain["axis"] for domain in result["domains"]] == list(sofa.AXES)
    assert [domain["observed_max_score"] for domain in result["domains"]] == [1, 0, 0, 1, 0, 0]
    assert len(source["gcs_observations"]) == 2 and len(source["urine_intervals"]) == 2
    assert source["respiratory_observations"][0]["pao2"]["collected_at_utc"] != source["respiratory_observations"][0]["fio2"]["observed_at"]
    assert result["diagnosis_provided"] is result["probability_provided"] is result["treatment_provided"] is False


@pytest.mark.parametrize("change", ["coverage_unknown", "gcs_sedation", "gcs_other_confounder", "gcs_interpretability", "resp_support_unknown", "urine_partial"])
def test_explicit_uncertainty_prevents_complete_total_even_with_other_five_axes_observed(db_session, complete_case, change):
    case = complete_case
    values = json.loads(canonical_json(case["request"]))
    if change == "resp_support_unknown":
        pao2, _ = lab_original(db_session, case, "arterial_oxygen_partial_pressure", "20.00000000", "mm[Hg]")
        pair = create(db_session, case, "arterial_pair", pair_body(case, pao2={"lab_source_id": pao2.lab_source_id, "expected_content_hash": pao2.content_hash}))
        values = clinical_request(case, manifest(db_session, case))
        for original in case["request"]["member_reviews"]:
            if original["status"] == "excluded":
                next(item for item in values["member_reviews"] if item["member_key"] == original["member_key"]).update(status="excluded", exclusion_reason=original["exclusion_reason"])
        values["conflict_reviews"] = case["request"]["conflict_reviews"]
        next(item for item in values["member_reviews"] if item["member_key"] == "arterial_pair:" + pair.support_source_id)["qualifying_respiratory_support"] = "unknown"
    if change == "coverage_unknown":
        values["coverage"]["liver"]["source_inventory"] = "unknown"
    elif change.startswith("gcs_"):
        item = next(item for item in values["member_reviews"] if item["member_key"] == "gcs:" + case["complete_gcs"].gcs_observation_id)
        key, value = {
            "gcs_sedation": ("sedation_confounding_status", "present"),
            "gcs_other_confounder": ("other_confounding_status", "unknown"),
            "gcs_interpretability": ("interpretable", "limited"),
        }[change]
        item[key] = value
    elif change == "resp_support_unknown":
        pass
    else:
        values["coverage"]["renal"]["clinical_protocol"] = "incomplete"
    row = register(db_session, case, values=values)
    result = sofa_values(sofa.assessment_detail(db_session, row)["specialist_source"])
    assert result["calculation_status"] == "partial" and result["complete_total_score"] is None
    assert result["protocol_complete_domain_count"] == 5


@pytest.mark.parametrize("value,text", [("-1.12345678", None), (None, "private qualitative original finding with no numeric interpretation")])
def test_lis_negative_and_qualitative_originals_remain_visible_and_never_become_normal_zero(db_session, assessment_case, value, text):
    case = assessment_case
    lab, original = lab_original(db_session, case, "total_bilirubin", value, "mg/dL", text=text)
    frozen = manifest(db_session, case)
    values = clinical_request(case, frozen)
    row = register(db_session, case, values=values)
    source = sofa.assessment_detail(db_session, row)["specialist_source"]
    actual = next(item for item in source["lab_observations"] if item["lab_source_id"] == lab.lab_source_id)
    assert actual["quantity"]["value"] == value
    assert actual["quantity"]["value_kind"] == ("qualitative" if text else "numeric")
    assert text is None or text not in canonical_json(source)
    liver = next(domain for domain in sofa_values(source)["domains"] if domain["axis"] == "liver")
    assert liver["observed_max_score"] is None and liver["upper_bound"] == 4
    assert original.value_num == (Decimal(value) if value is not None else None)


def vaso_original(db, case, monkeypatch, *, start=None, end=None, native="0.1", moiety="base", identity_note=NOTE):
    from app.routers import ai_vasoactive_mappings

    monkeypatch.setattr(vaso, "utcnow", lambda: case["now"])
    monkeypatch.setattr(ai_vasoactive_mappings, "utcnow", lambda: case["now"])
    drug = Pharmaceutical(name="SyntheticNE-" + uuid.uuid4().hex[:8], barcode="synthetic-" + uuid.uuid4().hex, stock=0, price=0, status=0)
    db.add(drug)
    db.commit()
    mapping = drug_mapping(db, {**case, "drug": drug}, active_moiety_basis=moiety)
    payload = vaso_payload(
        {**case, "mapping": mapping},
        start_at=utc_text(start or case["start"]),
        verified_until_at=utc_text(end or case["end"]),
        continuity_confirmed=True,
        continuity_basis_note=NOTE,
        dose_input=dose(value=native),
        stream_identity={"source_namespace": "synthetic-sofa-pump", "external_stream_id": "actual-same-stream", "identity_basis_note": identity_note},
    )
    row = create(db, case, "vasoactive", payload)
    return row, drug


def test_old_closed_interval_authenticates_own_body_then_ignores_unrelated_current_mapping_change(db_session, assessment_case, monkeypatch):
    case = assessment_case
    row, drug = vaso_original(db_session, case, monkeypatch, start=case["period_start"] - datetime.timedelta(hours=3), end=case["period_start"] - datetime.timedelta(hours=2))
    before = manifest(db_session, case)
    assert not any(member["identifier"] == row.support_source_id for member in before["members"])
    drug.name = "ChangedOldDrugIdentity"
    db_session.commit()
    assert manifest(db_session, case) == before
    row.content_hash = "0" * 64
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        manifest(db_session, case)
    assert error.value.status_code == 409


def test_actual_prefix_and_direct_normalized_dose_are_retained_without_private_stream_or_drug_names(db_session, complete_case, monkeypatch):
    case = complete_case
    start, end = case["period_start"] - datetime.timedelta(minutes=45), case["period_start"] + datetime.timedelta(minutes=15)
    interval, drug = vaso_original(db_session, case, monkeypatch, start=start, end=end, native="0.10000000")
    frozen = manifest(db_session, case)
    values = clinical_request(case, frozen)
    for original in case["request"]["member_reviews"]:
        if original["status"] == "excluded":
            next(item for item in values["member_reviews"] if item["member_key"] == original["member_key"]).update(status="excluded", exclusion_reason=original["exclusion_reason"])
    values["conflict_reviews"] = case["request"]["conflict_reviews"]
    member_review = next(item for item in values["member_reviews"] if item["kind"] == "vasoactive")
    member_review.update(continuous_iv="confirmed", rate_scope="stream_rate", mass_basis_compatible_confirmed=True)
    values["vasoactive_group_reviews"] = [{"drug_key": "norepinephrine", "relation": "single_stream", "relation_confirmed": True, "dose_basis_consistency_confirmed": True, "basis_note": NOTE}]
    values["coverage"]["cardiovascular"]["drug_exposure"] = "reviewed_intervals"
    row = register(db_session, case, values=values)
    source = sofa.assessment_detail(db_session, row)["specialist_source"]
    actual = source["vasoactive_groups"][0]["intervals"][0]
    assert actual["dose_input"]["rate"]["value"] == "0.10000000" and actual["weight"] is None
    assert actual["start_at"] == utc_text(start) < source["start_at"]
    assert drug.name not in canonical_json(source) and "actual-same-stream" not in canonical_json(source)
    result = sofa_values(source)
    cardiovascular = next(domain for domain in result["domains"] if domain["axis"] == "cardiovascular")
    assert cardiovascular["observed_max_score"] == 3 and result["complete_total_score"] == 4
    assert actual["content_hash"] == interval.content_hash
