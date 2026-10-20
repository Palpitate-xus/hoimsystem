"""Real ORM respiratory originals, actual governed LIS parents and explicit bedside pairing."""

import datetime
import json
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app import inpatient_laboratory as labs
from app import inpatient_respiratory_sources as respiratory
from app import inpatient_support_common as common
from app.ai import lab_mappings
from app.inpatient_observations import canonical_json, utc_text
from app.inpatient_respiratory_models import InpatientArterialPairSource, InpatientMapSource, InpatientRespiratorySource
from app.models import Doctor, LabObservation, LabOrder, LabResult
from app.routers import ai_lab_mappings as mapping_routes
from app.routers import inpatient_laboratory as lab_routes
from tests.test_ai_observation_windows import observation_case as observation_case
from tests.test_ai_observation_windows import point
from tests.test_inpatient_laboratory import body as lab_body
from tests.test_inpatient_laboratory import published_mapping
from tests.test_inpatient_respiratory_contract import NOTE, map_payload, support_payload


def create(db, case, kind, payload, *, actor=None, admission_id=None):
    row = common.create_source(db, actor or case["doctor"], kind, {"patient_id": case["patient_id"], "admission_id": admission_id or case["admission"].admission_id, "payload": payload})
    db.commit()
    return row


def body(case, **changes):
    return {
        "pao2": {"lab_source_id": case["lab"].lab_source_id, "expected_content_hash": case["lab"].content_hash},
        "fio2": {"observation_id": case["fio2"].observation_id, "expected_content_hash": case["fio2"].content_hash},
        "support": {"support_source_id": case["support"].support_source_id, "expected_content_hash": case["support"].content_hash},
        "arterial_sample_confirmed": True,
        "same_sampling_state_confirmed": True,
        "fio2_applicability_confirmed": True,
        "review_note": NOTE,
        "note": "明确当前回顾核实；实际原量并不自动构成SOFA评分或脓毒症诊断",
        **changes,
    }


@pytest.fixture
def source_case(db_session, observation_case, monkeypatch):
    case = observation_case
    monkeypatch.setattr(common, "definitions", lambda: {item.kind: item for item in respiratory.DEFINITIONS})
    monkeypatch.setattr(common, "utcnow", lambda: case["now"])
    for module in (labs, lab_routes, lab_mappings, mapping_routes):
        monkeypatch.setattr(module, "utcnow", lambda: case["now"] - datetime.timedelta(minutes=5))
    for model in (InpatientArterialPairSource, InpatientRespiratorySource, InpatientMapSource):
        db_session.query(model).delete()
    suffix = uuid.uuid4().hex[:12]
    order = LabOrder(lab_order_id="pair-order-" + suffix, patient_id=case["patient_id"], doctor_id=case["seed"]["doctor"].doctor_id, check_items="旧血气项目", status=2, sample_status=1)
    report = LabResult(lab_result_id="pair-report-" + suffix, lab_order_id=order.lab_order_id, result="完整原始血气报告", audit_status=1, auditor_id=case["seed"]["admin_user"].user_id)
    observation = LabObservation(
        observation_id="pair-lab-" + suffix,
        lab_result_id=report.lab_result_id,
        code_system="original-local-lis",
        code="BG-PAO2",
        display="仅显示名不能用于猜测映射",
        value_num=Decimal("80.12000000"),
        unit="mm[Hg]",
        method="original blood gas method",
        specimen_type="original arterial specimen",
        collected_at=datetime.datetime(2099, 1, 1),
    )
    db_session.add_all([order, report, observation])
    db_session.commit()
    mapping = published_mapping(db_session, case["seed"]["super_admin_user"], observation, analyte_key="arterial_oxygen_partial_pressure")
    lab_case = {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id, "observation": observation, "mapping": mapping}
    lab = labs.create_source(db_session, case["doctor"], lab_body(db_session, lab_case, collected_at_utc=utc_text(case["start"] + datetime.timedelta(hours=1))))
    db_session.commit()
    fio2 = point(
        db_session,
        case,
        observed=case["start"] + datetime.timedelta(minutes=17, microseconds=123),
        payload={"measurements": {"fio2": {"value": "21.00000000", "unit": "%", "absent_reason": None}}, "supplemental_oxygen": "unknown"},
    )
    db_session.commit()
    support = create(
        db_session,
        case,
        "respiratory_support",
        support_payload(start_at=utc_text(case["start"]), verified_until_at=utc_text(case["end"]), delivery_mode="invasive_mechanical", continuity_confirmed=True, continuity_basis_note=NOTE),
    )
    return {**case, "lab": lab, "lab_observation": observation, "lab_report": report, "mapping": mapping, "fio2": fio2, "support": support}


def test_actual_pair_freezes_complete_current_originals_and_retains_distinct_physiology_and_review_clocks(db_session, source_case):
    case = source_case
    before = (case["fio2"].payload_json, case["fio2"].content_hash, case["lab"].snapshot_json, case["lab"].content_hash, case["lab_observation"].value_num, case["lab_report"].audit_status)
    row = create(db_session, case, "arterial_pair", body(case))
    source = common.source_current(db_session, row, "arterial_pair")
    refs = source["reference_snapshots"]
    assert set(refs) == {"pao2", "fio2", "support"}
    assert refs["pao2"] == labs.source_current(db_session, case["lab"])
    assert refs["support"] == common.source_current(db_session, case["support"], "respiratory_support")
    assert source["event_at"] == refs["pao2"]["collected_at_utc"] != refs["fio2"]["observed_at"]
    assert source["recorded_at"] == utc_text(case["now"]) != source["event_at"]
    assert refs["pao2"]["snapshot"]["original"]["observation"]["collected_at"] == "2099-01-01T00:00:00.000000"
    assert refs["pao2"]["snapshot"]["original"]["observation"]["time_basis"] == "unknown"
    assert refs["pao2"]["snapshot"]["original"]["observation"]["value_num"] == "80.12000000"
    assert refs["fio2"]["payload"]["measurements"]["fio2"] == {"value": "21.00000000", "unit": "%", "absent_reason": None}
    assert source["author_qualification"]["clinical_review_signed"] is True
    assert source["source_id"] == f"arterial_pair:{row.support_source_id}:{row.content_hash[:12]}"
    assert source["eligible"] is True and source["exclusion_reasons"] == []
    assert row.reference_snapshot_json == canonical_json(refs)
    assert before == (case["fio2"].payload_json, case["fio2"].content_hash, case["lab"].snapshot_json, case["lab"].content_hash, case["lab_observation"].value_num, case["lab_report"].audit_status)


@pytest.mark.parametrize("value,reason", [("0", None), (None, "unknown"), (None, "not_performed"), (None, "measurement_error")])
def test_unknown_or_zero_fio2_is_retained_with_unresolved_review_without_division_or_score(db_session, source_case, value, reason):
    case = source_case
    fio2 = point(db_session, case, payload={"measurements": {"fio2": {"value": value, "unit": "%", "absent_reason": reason}}, "supplemental_oxygen": "unknown"})
    db_session.commit()
    data = body(
        case,
        fio2={"observation_id": fio2.observation_id, "expected_content_hash": fio2.content_hash},
        arterial_sample_confirmed=False,
        same_sampling_state_confirmed=False,
        fio2_applicability_confirmed=False,
    )
    row = create(db_session, case, "arterial_pair", data)
    source = common.source_current(db_session, row, "arterial_pair")
    assert source["payload"] == data
    assert source["reference_snapshots"]["fio2"]["payload"]["measurements"]["fio2"] == {"value": value, "unit": "%", "absent_reason": reason}
    assert not ({"score", "pao2_fio2_ratio", "sofa", "scoring_ready"} & source.keys())


@pytest.mark.parametrize("ended,offset_microseconds,accepted", [(True, -1, True), (True, 0, False), (True, 1, False), (False, -1, True), (False, 0, True), (False, 1, False)])
def test_stopped_interval_half_open_and_ongoing_verified_endpoint_inclusive(db_session, source_case, ended, offset_microseconds, accepted):
    case = source_case
    sample = case["lab"].collected_at_utc
    endpoint = sample - datetime.timedelta(microseconds=offset_microseconds)
    support = create(
        db_session,
        case,
        "respiratory_support",
        support_payload(start_at=utc_text(case["start"]), verified_until_at=utc_text(endpoint), ended_at=utc_text(endpoint) if ended else None),
    )
    data = body(case, support={"support_source_id": support.support_source_id, "expected_content_hash": support.content_hash})
    if accepted:
        assert create(db_session, case, "arterial_pair", data).event_at == sample
    else:
        with pytest.raises(HTTPException) as error:
            create(db_session, case, "arterial_pair", data)
        assert error.value.status_code == 409


@pytest.mark.parametrize("dependency", ["pao2", "fio2", "support"])
def test_exact_full_parent_hash_is_required_before_any_pair_write(db_session, source_case, dependency):
    case = source_case
    data = body(case)
    data[dependency]["expected_content_hash"] = "0" * 64
    before = db_session.query(InpatientArterialPairSource).count()
    with pytest.raises(HTTPException) as error:
        create(db_session, case, "arterial_pair", data)
    assert error.value.status_code == 409
    assert db_session.query(InpatientArterialPairSource).count() == before


def test_same_patient_other_admission_point_is_not_implicitly_joined(db_session, source_case):
    case = source_case
    foreign = point(db_session, case, admission=case["other"].admission_id, payload={"measurements": {"fio2": {"value": "21", "unit": "%", "absent_reason": None}}, "supplemental_oxygen": "unknown"})
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        create(db_session, case, "arterial_pair", body(case, fio2={"observation_id": foreign.observation_id, "expected_content_hash": foreign.content_hash}))
    assert error.value.status_code == 409


def test_oxygen_flow_point_without_original_fio2_cannot_supply_default_room_air(db_session, source_case):
    case = source_case
    with pytest.raises(HTTPException) as error:
        create(db_session, case, "arterial_pair", body(case, fio2={"observation_id": case["point"].observation_id, "expected_content_hash": case["point"].content_hash}))
    assert error.value.status_code == 409


@pytest.mark.parametrize("change", ["lab_value", "report_audit", "point_hash", "support_revoke", "mapping_revoke", "doctor_identity"])
def test_live_original_dependency_changes_block_current_use_but_valid_frozen_original_remains_auditable(db_session, source_case, change):
    case = source_case
    row = create(db_session, case, "arterial_pair", body(case))
    original = common.source_current(db_session, row, "arterial_pair")
    if change == "lab_value":
        case["lab_observation"].value_num = Decimal("80.13000000")
    elif change == "report_audit":
        case["lab_report"].audit_status = 0
    elif change == "point_hash":
        case["fio2"].content_hash = "0" * 64
    elif change == "support_revoke":
        common.revoke_source(
            db_session,
            case["doctor"],
            "respiratory_support",
            case["support"].support_source_id,
            {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id, "expected_revision": 1, "reason": NOTE},
        )
    elif change == "mapping_revoke":
        mapping = db_session.get(lab_mappings.AILabMapping, case["mapping"]["mapping_id"])
        mapping.status, mapping.revision, mapping.published_key = "revoked", 3, None
        mapping.revoked_at, mapping.revoked_by, mapping.revoke_reason = case["now"] - datetime.timedelta(minutes=4), case["seed"]["super_admin_user"].user_id, NOTE
    else:
        db_session.get(Doctor, original["author_qualification"]["doctor_id"]).user_id = case["seed"]["nurse_user"].user_id
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        common.source_current(db_session, row, "arterial_pair")
    assert error.value.status_code == 409
    audit = common.source_current(db_session, row, "arterial_pair", audit_only=True)
    assert audit["content_hash"] == original["content_hash"]
    assert audit["reference_snapshots"] == original["reference_snapshots"]
    assert audit["eligible"] is False and audit["exclusion_reasons"]


def test_signed_doctor_historical_role_change_preserves_captured_identity_without_current_user_authority(db_session, source_case):
    case = source_case
    row = create(db_session, case, "arterial_pair", body(case))
    case["doctor"].user_role = "admin"
    db_session.commit()
    assert common.source_current(db_session, row, "arterial_pair")["eligible"] is True
    with pytest.raises(HTTPException) as error:
        create(db_session, case, "arterial_pair", body(case))
    assert error.value.status_code == 403


def test_corrupted_pair_body_is_never_presented_as_intact_frozen_source_even_audit_only(db_session, source_case):
    row = create(db_session, source_case, "arterial_pair", body(source_case))
    tampered = json.loads(row.reference_snapshot_json)
    tampered["fio2"]["payload"]["measurements"]["fio2"]["value"] = "100"
    row.reference_snapshot_json = canonical_json(tampered)
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        common.source_current(db_session, row, "arterial_pair", audit_only=True)
    assert error.value.status_code == 409


@pytest.mark.parametrize("kind", ["map", "respiratory_support"])
def test_nurse_can_record_original_bedside_sources_but_never_doctor_required_pair(db_session, source_case, kind):
    case = source_case
    from app.models import NursingRecord

    db_session.add(NursingRecord(admission_id=case["admission"].admission_id, patient_id=case["patient_id"], nurse_id=case["seed"]["nurse_user"].user_id, note="合成当前照护记录"))
    db_session.commit()
    data = map_payload(observed_at=utc_text(case["start"])) if kind == "map" else support_payload(start_at=utc_text(case["start"]), verified_until_at=utc_text(case["end"]))
    row = create(db_session, case, kind, data, actor=case["seed"]["nurse_user"])
    assert common.source_current(db_session, row, kind)["author_qualification"]["role_at_creation"] == "nurse"
    with pytest.raises(HTTPException) as error:
        create(db_session, case, "arterial_pair", body(case), actor=case["seed"]["nurse_user"])
    assert error.value.status_code == 403
