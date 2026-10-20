"""Real synthetic vasoactive originals, native quantities and exact parent chains."""

import datetime
import json
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app import inpatient_support_common as common
from app import inpatient_vasoactive as vaso
from app.inpatient_observations import utc_text
from app.inpatient_vasoactive_models import AIVasoactiveDrugMapping, InpatientVasoactiveSource
from app.models import InpatientOrder, InpatientOrderItem, MedicationAdministration, NursingRecord, OrderExecution
from app.routers import ai_vasoactive_mappings as mapping_routes
from tests.test_ai_observation_windows import point
from tests.test_ai_vasoactive_mappings import NOTE, published_mapping
from tests.test_ai_vasoactive_mappings import observation_case as observation_case
from tests.test_ai_vasoactive_mappings import vaso_case as vaso_case


@pytest.fixture
def source_case(db_session, vaso_case):
    case = vaso_case
    case["mapping"] = published_mapping(db_session, case)
    case["weight"] = point(
        db_session,
        case,
        observed=case["start"],
        payload={"measurements": {"body_weight": {"value": "70.00000000", "unit": "kg", "absent_reason": None}}, "supplemental_oxygen": "unknown", "note": "合成原体重备注"},
    )
    db_session.commit()
    return case


def dose(mode="weight_normalized", value="0.00000000", *, weight_ref=None, confirmed=False):
    base = {"mode": mode, "weight_ref": weight_ref, "weight_applicability_confirmed": confirmed, "weight_basis_note": NOTE if confirmed else None}

    def quantity(unit):
        return {"value": value, "unit": unit, "absent_reason": "unknown" if value is None else None}

    if mode == "weight_normalized":
        return {**base, "rate": quantity("ug/kg/min")}
    if mode == "absolute":
        return {**base, "rate": quantity("mg/h")}
    return {**base, "concentration": quantity("ug/mL"), "pump_rate": quantity("mL/h")}


def payload(case, **changes):
    return {
        "start_at": utc_text(case["start"] + datetime.timedelta(minutes=10)),
        "verified_until_at": utc_text(case["end"]),
        "ended_at": None,
        "drug_mapping": {"mapping_id": case["mapping"].mapping_id, "expected_content_hash": case["mapping"].content_hash},
        "stream_identity": {"source_namespace": "synthetic-bedside-pump", "external_stream_id": "same-explicit-original-stream", "identity_basis_note": NOTE},
        "origin": None,
        "continuity_confirmed": False,
        "continuity_basis_note": None,
        "dose_input": dose(),
        "note": "合成实际输注原段，未调用模型或自动标准化",
        **changes,
    }


def create(db, case, actor=None, **changes):
    row = common.create_source(db, actor or case["doctor"], "vasoactive", {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id, "payload": payload(case, **changes)})
    db.commit()
    return row


def weight_ref(case):
    return {"observation_id": case["weight"].observation_id, "expected_content_hash": case["weight"].content_hash}


def given_origin(db, case, *, status=2):
    nurse = case["seed"]["nurse_user"]
    old_naive = datetime.datetime(2020, 1, 2, 3, 4, 5, 123456)
    order = InpatientOrder(
        patient_id=case["patient_id"],
        admission_id=case["admission"].admission_id,
        doctor_id=case["seed"]["doctor"].doctor_id,
        category="drug",
        status=2,
        start_time=old_naive,
        create_time=old_naive,
        note="原医嘱全文",
    )
    db.add(order)
    db.flush()
    item = InpatientOrderItem(
        order_id=order.order_id,
        item_name=case["drug"].name,
        item_type="drug",
        item_id_ref=case["drug"].pharmaceutical_id,
        dose="原量文本不得当作连续UTC剂量",
        unit="原单位",
        route="原途径",
        quantity=1,
        unit_price=0,
        total_price=0,
    )
    execution = OrderExecution(order_id=order.order_id, nurse_id=nurse.user_id, status=1, planned_time=old_naive, execution_time=old_naive, note="原执行全文")
    db.add_all([item, execution])
    db.flush()
    administration = MedicationAdministration(
        administration_id=str(uuid.uuid4()),
        execution_id=execution.execution_id,
        order_id=order.order_id,
        patient_id=case["patient_id"],
        nurse_id=nurse.user_id,
        patient_barcode="synthetic-private-wristband",
        medication_barcodes_json=json.dumps([case["drug"].barcode]),
        status=status,
        verified_at=old_naive,
        administration_time=old_naive if status == 2 else None,
        note="原给药全文",
    )
    db.add(administration)
    db.commit()
    return administration, execution, order, item


@pytest.mark.parametrize("mode", ["weight_normalized", "absolute", "pump"])
@pytest.mark.parametrize("value", ["0.00000000", "0.12345678", None])
def test_all_three_actual_dose_modes_preserve_zero_unknown_and_precision_without_normalization(db_session, source_case, mode, value):
    case = source_case
    original = payload(case, dose_input=dose(mode, value))
    row = create(db_session, case, dose_input=original["dose_input"])
    view = common.source_current(db_session, row, "vasoactive")
    assert view["payload"] == original
    assert view["event_at"] == original["start_at"] and view["recorded_at"] == utc_text(case["now"])
    assert view["reference_snapshots"]["drug_mapping"]["original_drug_identity"] == vaso.original_drug_identity(db_session, case["drug"].pharmaceutical_id)
    assert set(view["reference_snapshots"]) == {"drug_mapping", "weight", "origin"}
    assert view["reference_snapshots"]["weight"] is view["reference_snapshots"]["origin"] is None
    assert view["eligible"] and "normalized_rate" not in view and "sofa" not in view
    assert row.payload_json == vaso.canonical_json(original)


@pytest.mark.parametrize("mode", ["weight_normalized", "absolute", "pump"])
def test_explicit_original_weight_is_frozen_once_without_dividing_direct_normalized_dose(db_session, source_case, mode):
    case = source_case
    row = create(db_session, case, dose_input=dose(mode, "0.12345678", weight_ref=weight_ref(case), confirmed=True))
    view = common.source_current(db_session, row, "vasoactive")
    assert view["reference_snapshots"]["weight"]["payload"]["measurements"]["body_weight"]["value"] == "70.00000000"
    assert view["payload"]["dose_input"] == dose(mode, "0.12345678", weight_ref=weight_ref(case), confirmed=True)
    assert "normalized_rate" not in view


def test_same_stream_overlaps_and_conflicting_mapping_originals_are_preserved_without_auto_merge(db_session, source_case):
    case = source_case
    first = create(db_session, case, dose_input=dose(value="0.1"))
    second = create(db_session, case, dose_input=dose(value="0.2"))
    assert first.support_source_id != second.support_source_id
    assert common.source_current(db_session, first, "vasoactive")["payload"]["dose_input"]["rate"]["value"] == "0.1"
    assert common.source_current(db_session, second, "vasoactive")["payload"]["dose_input"]["rate"]["value"] == "0.2"
    assert db_session.query(InpatientVasoactiveSource).count() == 2


@pytest.mark.parametrize("value", [False, 0, 1.1, "NaN", "1e2", "01", "-1", "0.123456789"])
def test_dose_numeric_inputs_are_never_coerced_or_rounded(source_case, value):
    with pytest.raises(ValidationError):
        vaso.VasoactivePayload.model_validate(payload(source_case, dose_input=dose(value=value)))


@pytest.mark.parametrize(
    "change",
    [
        "weight_true_no_ref",
        "weight_false_note",
        "continuity_true_no_note",
        "continuity_false_note",
        "end_differs",
        "future_format",
        "same_start_end",
        "unknown_mode",
        "invented_rate",
        "rate_and_absent",
        "no_absence_reason",
        "bad_native_unit",
        "early_mysql_year",
    ],
)
def test_explicit_interval_weight_continuity_and_tagged_union_validation(source_case, change):
    data = payload(source_case)
    if change == "weight_true_no_ref":
        data["dose_input"].update(weight_applicability_confirmed=True, weight_basis_note=NOTE)
    elif change == "weight_false_note":
        data["dose_input"]["weight_basis_note"] = NOTE
    elif change == "continuity_true_no_note":
        data["continuity_confirmed"] = True
    elif change == "continuity_false_note":
        data["continuity_basis_note"] = NOTE
    elif change == "end_differs":
        data["ended_at"] = data["start_at"]
    elif change == "future_format":
        data["start_at"] = "2026-10-20T10:00:00"
    elif change == "same_start_end":
        data["verified_until_at"] = data["start_at"]
    elif change == "unknown_mode":
        data["dose_input"]["mode"] = "assumed-70kg"
    elif change == "invented_rate":
        data["dose_input"]["normalized_rate"] = "0.1"
    elif change == "rate_and_absent":
        data["dose_input"]["rate"]["absent_reason"] = "unknown"
    elif change == "no_absence_reason":
        data["dose_input"]["rate"]["value"] = None
    elif change == "bad_native_unit":
        data["dose_input"]["rate"]["unit"] = "mcg/kg/min"
    else:
        data["start_at"] = "0999-01-01T01:00:00Z"
    with pytest.raises(ValidationError):
        vaso.VasoactivePayload.model_validate(data)


def test_current_source_checks_verified_until_actual_cutoff_and_native_unit_mapping(db_session, source_case):
    case = source_case
    with pytest.raises(HTTPException):
        create(db_session, case, verified_until_at=utc_text(case["now"] + datetime.timedelta(microseconds=1)))
    restricted = published_mapping(db_session, case, source_namespace="explicit-only-normalized", allowed_rate_units=["ug/kg/min"])
    with pytest.raises(HTTPException):
        create(db_session, case, drug_mapping={"mapping_id": restricted.mapping_id, "expected_content_hash": restricted.content_hash}, dose_input=dose("absolute"))
    assert db_session.query(InpatientVasoactiveSource).count() == 0


@pytest.mark.parametrize("change", ["wrong_scope", "late_observed", "wrong_hash", "raw_note", "mapping_revoke", "drug_identity"])
def test_weight_mapping_and_actual_drug_dependencies_are_full_hash_guarded_with_frozen_audit(db_session, source_case, change):
    case = source_case
    if change in {"wrong_scope", "late_observed", "wrong_hash"}:
        ref = weight_ref(case)
        if change == "wrong_scope":
            row = point(
                db_session,
                case,
                admission=case["other"].admission_id,
                payload={"measurements": {"body_weight": {"value": "70", "unit": "kg", "absent_reason": None}}, "supplemental_oxygen": "unknown"},
            )
            db_session.commit()
            ref = {"observation_id": row.observation_id, "expected_content_hash": row.content_hash}
        elif change == "late_observed":
            row = point(db_session, case, observed=case["end"], payload={"measurements": {"body_weight": {"value": "70", "unit": "kg", "absent_reason": None}}, "supplemental_oxygen": "unknown"})
            db_session.commit()
            ref = {"observation_id": row.observation_id, "expected_content_hash": row.content_hash}
        else:
            ref["expected_content_hash"] = "0" * 64
        with pytest.raises(HTTPException):
            create(db_session, case, dose_input=dose(weight_ref=ref))
        return
    row = create(db_session, case, dose_input=dose(weight_ref=weight_ref(case), confirmed=True))
    frozen = common.source_current(db_session, row, "vasoactive")
    if change == "raw_note":
        raw = json.loads(case["weight"].payload_json)
        raw["note"] += " Changed original note"
        case["weight"].payload_json = vaso.canonical_json(raw)
    elif change == "mapping_revoke":
        mapping_routes.revoke_mapping(case["mapping"].mapping_id, mapping_routes.MappingRevoke(expected_revision=2, reason=NOTE), db_session, case["seed"]["super_admin_user"])
    else:
        case["drug"].name += "改"
    db_session.commit()
    with pytest.raises(HTTPException):
        common.source_current(db_session, row, "vasoactive")
    audit = common.source_current(db_session, row, "vasoactive", audit_only=True)
    assert not audit["eligible"] and audit["reference_snapshots"] == frozen["reference_snapshots"]
    assert audit["content_hash"] == frozen["content_hash"]


def test_actual_given_origin_full_chain_is_hashed_but_old_naive_clocks_never_define_new_utc_interval(db_session, source_case):
    case = source_case
    administration, execution, order, item = given_origin(db_session, case)
    before = (administration.administration_time, execution.execution_time, order.start_time)
    mapping = vaso.mapping_current(db_session, case["mapping"].mapping_id)
    origin = vaso.origin_snapshot(db_session, case["patient_id"], case["admission"].admission_id, administration.administration_id, mapping)
    candidates = vaso.origin_candidates(db_session, case["patient_id"], case["admission"].admission_id, case["mapping"].mapping_id)
    assert candidates["items"] == [{"administration_id": administration.administration_id, "content_hash": origin["content_hash"], "source_id": origin["source_id"], "snapshot": origin}]
    row = create(db_session, case, origin={"administration_id": administration.administration_id, "expected_content_hash": origin["content_hash"]})
    current = common.source_current(db_session, row, "vasoactive")
    saved = current["reference_snapshots"]["origin"]
    assert saved == origin and saved["items"][0]["item_id"] == item.item_id
    assert saved["administration"]["administration_time"] == "2020-01-02T03:04:05.123456" and not saved["administration"]["administration_time"].endswith("Z")
    assert saved["time_basis"] == "legacy_naive_unknown_not_continuous_utc_evidence"
    assert current["event_at"] == payload(case)["start_at"] and not current["event_at"].startswith("2020")
    assert (administration.administration_time, execution.execution_time, order.start_time) == before
    item.note = "Changed original order item"
    db_session.commit()
    with pytest.raises(HTTPException):
        common.source_current(db_session, row, "vasoactive")
    assert not common.source_current(db_session, row, "vasoactive", audit_only=True)["eligible"]


@pytest.mark.parametrize("kind", ["verified_only", "wrong_admission", "wrong_execution", "wrong_drug", "wrong_hash"])
def test_supplied_emar_origin_is_an_actual_matching_given_chain_not_a_client_claim(db_session, source_case, kind):
    case = source_case
    administration, execution, order, item = given_origin(db_session, case, status=1 if kind == "verified_only" else 2)
    mapping = vaso.mapping_current(db_session, case["mapping"].mapping_id)
    if kind == "verified_only":
        with pytest.raises(HTTPException):
            vaso.origin_snapshot(db_session, case["patient_id"], case["admission"].admission_id, administration.administration_id, mapping)
        assert vaso.origin_candidates(db_session, case["patient_id"], case["admission"].admission_id)["items"] == []
        return
    origin = vaso.origin_snapshot(db_session, case["patient_id"], case["admission"].admission_id, administration.administration_id, mapping)
    if kind == "wrong_admission":
        order.admission_id = case["other"].admission_id
    elif kind == "wrong_execution":
        execution.order_id = str(uuid.uuid4())
    elif kind == "wrong_drug":
        item.item_id_ref = case["seed"]["pharmaceutical"].pharmaceutical_id
    db_session.commit()
    with pytest.raises(HTTPException):
        create(db_session, case, origin={"administration_id": administration.administration_id, "expected_content_hash": "0" * 64 if kind == "wrong_hash" else origin["content_hash"]})


def test_no_model_score_probability_or_default_quantity_is_added_and_mysql_types_are_real():
    assert len(vaso.DEFINITIONS) == 1 and vaso.DEFINITIONS[0].doctor_required is False
    source_ddl = str(CreateTable(InpatientVasoactiveSource.__table__).compile(dialect=mysql.dialect()))
    mapping_ddl = str(CreateTable(AIVasoactiveDrugMapping.__table__).compile(dialect=mysql.dialect()))
    assert "MEDIUMTEXT" in source_ddl and source_ddl.count("DATETIME(6)") == 3
    assert mapping_ddl.count("DATETIME(6)") == 3
    assert "sofa" not in InpatientVasoactiveSource.__table__.columns.keys()


def request_body(case, **changes):
    return {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id, "payload": payload(case, **changes)}


def scope(case):
    return {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,value", [("weight_normalized", "0.12345678"), ("absolute", "0.00000000"), ("pump", None)])
async def test_actual_main_http_freezes_selected_mapping_weight_and_given_chain_without_clinical_conversion(async_client, auth_headers, db_session, source_case, mode, value):
    case = source_case
    headers = auth_headers(case["doctor"].username)
    administration, _, _, _ = given_origin(db_session, case)
    options = await async_client.get("/api/inpatient-support/options", params=scope(case), headers=headers)
    assert options.status_code == 200, options.text
    kind = next(item for item in options.json()["data"]["kinds"] if item["kind"] == "vasoactive")
    assert kind["can_record"] is True and kind["schema_version"] == "vasoactive_interval_v1"
    mappings = await async_client.get("/api/inpatient-support/vasoactive/mapping-candidates", params=scope(case), headers=headers)
    assert mappings.status_code == 200, mappings.text
    actual_mapping = mappings.json()["data"]["items"][0]
    assert actual_mapping == vaso.mapping_current(db_session, case["mapping"].mapping_id)
    candidates = await async_client.get("/api/inpatient-support/vasoactive/origin-candidates", params={**scope(case), "mapping_id": actual_mapping["mapping_id"]}, headers=headers)
    assert candidates.status_code == 200, candidates.text
    actual_origin = candidates.json()["data"]["items"][0]
    assert actual_origin["administration_id"] == administration.administration_id
    original = request_body(
        case,
        origin={"administration_id": administration.administration_id, "expected_content_hash": actual_origin["content_hash"]},
        dose_input=dose(mode, value, weight_ref=weight_ref(case), confirmed=True),
    )
    response = await async_client.post("/api/inpatient-support/vasoactive", headers=headers, json=original)
    assert response.status_code == 200, response.text
    source = response.json()["data"]
    assert source["payload"] == original["payload"]
    assert source["eligible"] and source["can_record"] and source["can_revoke"]
    assert source["reference_snapshots"]["drug_mapping"] == actual_mapping
    assert source["reference_snapshots"]["origin"] == actual_origin["snapshot"]
    assert source["reference_snapshots"]["weight"]["payload"]["measurements"]["body_weight"]["value"] == "70.00000000"
    assert source["reference_snapshots"]["origin"]["administration"]["administration_time"] == "2020-01-02T03:04:05.123456"
    assert source["event_at"] == original["payload"]["start_at"]
    assert source["author_qualification"]["actor_id"] == case["doctor"].user_id
    assert not {"sofa", "normalized_rate", "sepsis_probability"} & source.keys()
    identifier = source["support_source_id"]
    detail = await async_client.get(f"/api/inpatient-support/vasoactive/{identifier}", params=scope(case), headers=headers)
    listed = await async_client.get("/api/inpatient-support/vasoactive", params=scope(case), headers=headers)
    assert detail.status_code == listed.status_code == 200
    assert detail.json()["data"] == source == listed.json()["data"]["items"][0]


@pytest.mark.asyncio
async def test_actual_nurse_cannot_bootstrap_vaso_care_but_original_admission_nursing_assignment_can_record(async_client, auth_headers, db_session, source_case):
    case = source_case
    nurse = case["seed"]["nurse_user"]
    headers = auth_headers(nurse.username)
    # New organ-support authorship and other-admission care do not grant this encounter.
    existing = create(db_session, case)
    existing.created_by = nurse.user_id
    db_session.add(NursingRecord(patient_id=case["patient_id"], admission_id=case["other"].admission_id, nurse_id=nurse.user_id, record_time=case["now"], create_time=case["now"]))
    db_session.commit()
    denied = await async_client.post("/api/inpatient-support/vasoactive", json=request_body(case), headers=headers)
    assert denied.status_code == 403, denied.text
    for path in ("mapping-candidates", "origin-candidates"):
        denied = await async_client.get(f"/api/inpatient-support/vasoactive/{path}", params=scope(case), headers=headers)
        assert denied.status_code == 403
    db_session.add(NursingRecord(patient_id=case["patient_id"], admission_id=case["admission"].admission_id, nurse_id=nurse.user_id, record_time=case["now"], create_time=case["now"]))
    db_session.commit()
    created = await async_client.post("/api/inpatient-support/vasoactive", json=request_body(case, dose_input=dose("absolute", "0")), headers=headers)
    assert created.status_code == 200, created.text
    source = created.json()["data"]
    assert source["author_qualification"]["role_at_creation"] == "nurse"
    assert source["payload"]["dose_input"]["rate"]["value"] == "0" and source["can_revoke"]
    identifier = source["support_source_id"]
    revoked = await async_client.post(f"/api/inpatient-support/vasoactive/{identifier}/revoke", json={**scope(case), "expected_revision": 1, "reason": NOTE}, headers=headers)
    assert revoked.status_code == 200 and revoked.json()["data"]["status"] == "revoked"


@pytest.mark.asyncio
async def test_actual_super_mapping_authority_does_not_create_clinical_vaso_originals(async_client, auth_headers, source_case):
    case = source_case
    headers = auth_headers(case["seed"]["super_admin_user"].username)
    options = await async_client.get("/api/inpatient-support/options", params=scope(case), headers=headers)
    assert options.status_code == 200
    assert next(item for item in options.json()["data"]["kinds"] if item["kind"] == "vasoactive")["can_record"] is False
    response = await async_client.post("/api/inpatient-support/vasoactive", headers=headers, json=request_body(case))
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", ["mapping", "origin_item"])
async def test_actual_http_stale_parent_blocks_clinical_reuse_but_super_retains_full_original_and_can_revoke(async_client, auth_headers, db_session, source_case, parent):
    case = source_case
    administration, _, _, item = given_origin(db_session, case)
    original = vaso.origin_snapshot(db_session, case["patient_id"], case["admission"].admission_id, administration.administration_id, vaso.mapping_current(db_session, case["mapping"].mapping_id))
    doctor_headers = auth_headers(case["doctor"].username)
    super_headers = auth_headers(case["seed"]["super_admin_user"].username)
    created = await async_client.post(
        "/api/inpatient-support/vasoactive",
        headers=doctor_headers,
        json=request_body(case, origin={"administration_id": administration.administration_id, "expected_content_hash": original["content_hash"]}),
    )
    assert created.status_code == 200, created.text
    before = created.json()["data"]
    identifier = before["support_source_id"]
    if parent == "mapping":
        mapping_routes.revoke_mapping(case["mapping"].mapping_id, mapping_routes.MappingRevoke(expected_revision=2, reason=NOTE), db_session, case["seed"]["super_admin_user"])
    else:
        item.dose += "完整原链发生变化"
        db_session.commit()
    ordinary = await async_client.get(f"/api/inpatient-support/vasoactive/{identifier}", params=scope(case), headers=doctor_headers)
    assert ordinary.status_code == 409, ordinary.text
    audit = await async_client.get(f"/api/ai/admin/support-sources/vasoactive/{identifier}", headers=super_headers)
    assert audit.status_code == 200, audit.text
    frozen = audit.json()["data"]
    assert not frozen["eligible"] and frozen["exclusion_reasons"]
    assert frozen["reference_snapshots"] == before["reference_snapshots"] and frozen["content_hash"] == before["content_hash"]
    revoke = await async_client.post(f"/api/inpatient-support/vasoactive/{identifier}/revoke", headers=super_headers, json={**scope(case), "expected_revision": 1, "reason": NOTE})
    assert revoke.status_code == 200, revoke.text
    after = revoke.json()["data"]
    assert after["status"] == "revoked" and after["revision"] == 2 and not after["can_revoke"]
    assert after["content_hash"] == before["content_hash"] and after["reference_snapshots"] == before["reference_snapshots"]
    assert not after["eligible"] and after["governance_hash"] != before["governance_hash"]
