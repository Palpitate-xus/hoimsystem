"""Synthetic laboratory members preserve versioned admission-window boundaries."""

import datetime
import json
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.ai import observation_windows as windows
from app.ai.models import AIObservationWindow, AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from tests.test_ai_observation_history import configure_risk, request_for, transport_for
from tests.test_ai_observation_windows import create, values
from tests.test_ai_observation_windows import observation_case as observation_case
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks


def legacy_window(db, case):
    fields = {**values(case), "window_id": str(uuid.uuid4()), "created_by": case["doctor"].user_id, "created_at": case["now"]}
    frozen = windows.build_snapshot(db, **fields, schema_version="inpatient_window_v1")
    row = AIObservationWindow(
        **fields,
        schema_version="inpatient_window_v1",
        snapshot_json=windows.canonical_json(frozen),
        content_hash=frozen["content_hash"],
        status="active",
        revision=1,
        revoke_reason="",
    )
    db.add(row)
    db.commit()
    return row


def test_saved_v1_preserves_its_original_shape_text_hash_and_microseconds(db_session, observation_case):
    case = observation_case
    row = legacy_window(db_session, case)
    before = (row.snapshot_json, row.content_hash, row.schema_version)
    snapshot = windows.snapshot_current(db_session, case["doctor"], row)
    assert snapshot == json.loads(before[0])
    assert snapshot["schema_version"] == "inpatient_window_v1"
    assert set(snapshot) == {
        "schema_version",
        "window_id",
        "patient_id",
        "admission_id",
        "created_by",
        "created_at",
        "start_at",
        "end_at",
        "as_of",
        "snapshot_basis",
        "representation",
        "point_interval_semantics",
        "points",
        "urine_intervals",
        "quality",
        "lab_input_status",
        "model_input_validation",
        "limitations",
        "content_hash",
        "source_id",
    }
    assert snapshot["limitations"] == [
        "所选住院和UTC时段内符合截止时点的离散记录，不证明连续监护或采样完整性",
        "未前填、补零、从脉搏替代心率、从设备推测FiO2或自动计算临床评分",
        "当前快照回溯，不是历史数据库as-of重放；已撤销原值不得作为有效测量",
        "旧患者级体征、检验、护理正文和当前诊断医嘱未作为本窗口特征加载",
    ]
    assert snapshot["lab_input_status"] == "not_available_requires_explicit_admission_binding_and_reviewed_mapping"
    assert "laboratory" not in snapshot["quality"] and "lab_observations" not in snapshot
    assert snapshot["start_at"] == windows.iso(case["start"])
    assert (row.snapshot_json, row.content_hash, row.schema_version) == before


def test_saved_v1_still_rejects_changed_original_members(db_session, observation_case):
    case = observation_case
    row = legacy_window(db_session, case)
    case["point"].recorded_at += datetime.timedelta(microseconds=1)
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        windows.snapshot_current(db_session, case["doctor"], row)
    assert caught.value.status_code == 409


def test_saved_unknown_version_is_not_silently_rebuilt_as_latest(db_session, observation_case):
    case = observation_case
    row = legacy_window(db_session, case)
    row.schema_version = "inpatient_window_v999"
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        windows.snapshot_current(db_session, case["doctor"], row)
    assert caught.value.status_code == 409


def test_building_an_unknown_version_is_explicitly_rejected(db_session, observation_case):
    case = observation_case
    with pytest.raises(HTTPException) as caught:
        windows.build_snapshot(db_session, **values(case), window_id=str(uuid.uuid4()), created_by=case["doctor"].user_id, created_at=case["now"], schema_version="inpatient_window_v999")
    assert caught.value.status_code == 422


@pytest.fixture
def laboratory_case(db_session, observation_case, monkeypatch):
    from app import inpatient_laboratory
    from app.ai import lab_mappings
    from app.ai.lab_mappings import create_mapping, mapping_current
    from app.inpatient_laboratory import create_source, load_original
    from app.models import LabObservation, LabOrder, LabResult
    from app.routers import ai_lab_mappings
    from app.routers import inpatient_laboratory as source_routes
    from app.routers.ai_lab_mappings import MappingPublish, publish_mapping

    case = observation_case
    clock = {"now": case["now"]}
    for module in (inpatient_laboratory, lab_mappings, ai_lab_mappings, source_routes):
        monkeypatch.setattr(module, "utcnow", lambda: clock["now"])
    namespace = "synthetic-lab-" + str(uuid.uuid4())
    mappings = {}

    def make(
        *, numeric="0", qualitative=None, collected=None, registered=None, admission=None, code="SYNTHETIC-CREAT", method="synthetic-method", specimen="synthetic-specimen", note=None, report_text=None
    ):
        numeric_value = Decimal(numeric) if numeric is not None else None
        value_kind = "numeric" if numeric is not None else "qualitative"
        signature = {"code_system": "local", "code": code, "unit": "umol/L" if numeric is not None else None, "method": method, "specimen_type": specimen, "value_kind": value_kind}
        mapping_key = windows.canonical_json(signature)
        clock["now"] = case["as_of"] - datetime.timedelta(minutes=15)
        if mapping_key not in mappings:
            mapping = create_mapping(
                db_session,
                case["seed"]["super_admin_user"],
                {
                    "source_namespace": namespace,
                    "signature": signature,
                    "analyte_key": "creatinine" if numeric is not None else "culture_result",
                    "evidence_reference": "synthetic-only-reviewed-local-identity",
                    "rationale": "Synthetic exact project identity for engineering checks, no clinical inference or validation.",
                },
            )
            publish_mapping(
                mapping.mapping_id,
                MappingPublish(
                    expected_revision=1, semantic_confirmed=True, source_signature_confirmed=True, review_note="Synthetic review of this exact namespace, units and method; no model validation."
                ),
                db_session,
                case["seed"]["super_admin_user"],
            )
            mappings[mapping_key] = mapping
        mapping = mappings[mapping_key]
        order = LabOrder(
            patient_id=case["patient_id"],
            doctor_id=case["seed"]["doctor"].doctor_id,
            check_type="Synthetic original laboratory",
            check_items="Synthetic exact code only",
            status=2,
            sample_status=1,
            create_time=datetime.datetime(2001, 2, 3, 4, 5, 6, 123456),
        )
        db_session.add(order)
        db_session.flush()
        report = LabResult(
            lab_order_id=order.lab_order_id,
            sample_id="synthetic-sample",
            result=report_text if report_text is not None else note or "Synthetic original report, not a clinical result.",
            abnormal_flag=0,
            technician_id=case["seed"]["lab_tech_user"].user_id,
            auditor_id=case["seed"]["admin_user"].user_id,
            audit_status=1,
            report_time=datetime.datetime(2001, 2, 3, 4, 5, 7, 654321),
            audit_time=datetime.datetime(2001, 2, 3, 4, 5, 8, 123456),
        )
        db_session.add(report)
        db_session.flush()
        observation = LabObservation(
            lab_result_id=report.lab_result_id,
            **{key: signature[key] for key in ("code_system", "code", "unit", "method", "specimen_type")},
            display="Synthetic source identity",
            value_num=numeric_value,
            value_text=qualitative,
            reference_low=None,
            reference_high=None,
            reference_text=None,
            flag="unknown",
            collected_at=datetime.datetime(2001, 2, 3, 4, 5, 5, 123456),
        )
        db_session.add(observation)
        db_session.commit()
        clock["now"] = registered or case["as_of"]
        _, _, raw_hash = load_original(db_session, observation.observation_id, case["patient_id"])
        mapped = mapping_current(db_session, mapping.mapping_id)
        source = create_source(
            db_session,
            case["doctor"],
            {
                "patient_id": case["patient_id"],
                "admission_id": (admission or case["admission"]).admission_id,
                "observation_id": observation.observation_id,
                "mapping_id": mapping.mapping_id,
                "expected_source_hash": raw_hash,
                "expected_mapping_hash": mapped["content_hash"],
                "collected_at_utc": windows.iso(collected or case["start"]),
                "collection_time_confirmed": True,
                "collection_time_basis_note": note or "Synthetic explicit UTC sample verification; old clock is not independently known.",
                "admission_binding_confirmed": True,
                "admission_binding_note": "Synthetic explicit original-admission verification, no date-derived association.",
                "source_namespace_confirmed": True,
                "source_namespace_basis_note": "Synthetic explicit namespace verification; legacy tables have no stored LIS origin.",
            },
        )
        db_session.commit()
        clock["now"] = case["now"]
        return {"source": source, "mapping": mapping, "observation": observation, "report": report, "order": order}

    return {"case": case, "make": make, "clock": clock}


def revoke_member(db, case, member, target):
    if target == "mapping":
        from app.routers.ai_lab_mappings import MappingRevoke, revoke_mapping

        revoke_mapping(member["mapping"].mapping_id, MappingRevoke(expected_revision=2, reason="Synthetic explicit withdrawal"), db, case["seed"]["super_admin_user"])
    else:
        from app.inpatient_laboratory import SourceRevoke
        from app.routers.inpatient_laboratory import revoke_source

        revoke_source(
            member["source"].lab_source_id,
            SourceRevoke(patient_id=case["patient_id"], admission_id=case["admission"].admission_id, expected_revision=1, reason="Synthetic explicit withdrawal"),
            db,
            case["doctor"],
        )


def test_new_v2_empty_laboratory_is_an_unknown_subset_not_normal(db_session, observation_case):
    case = observation_case
    snapshot = windows.snapshot_current(db_session, case["doctor"], create(db_session, case))
    assert snapshot["schema_version"] == "inpatient_window_v2"
    assert snapshot["lab_observations"] == []
    quality = snapshot["quality"]["laboratory"]
    assert quality["member_count"] == quality["eligible_count"] == 0
    assert quality["not_all_labs_confirmed"] is True and quality["query_truncated"] is False
    assert quality["unit_conversion_performed"] is False and quality["clinical_scores_calculated"] is False
    assert snapshot["model_input_validation"] == "not_provided"
    assert snapshot["lab_input_status"] == "not_available_no_eligible_governed_sources"


def test_v2_preserves_zero_qualitative_values_and_all_three_distinct_clocks(db_session, laboratory_case):
    case = laboratory_case["case"]
    numeric = laboratory_case["make"]()
    qualitative = laboratory_case["make"](numeric=None, qualitative="No growth reported", code="SYNTHETIC-CULTURE")
    snapshot = windows.snapshot_current(db_session, case["doctor"], create(db_session, case))
    assert len(snapshot["lab_observations"]) == 2
    by_id = {item["lab_source_id"]: item for item in snapshot["lab_observations"]}
    first = by_id[numeric["source"].lab_source_id]
    original = first["snapshot"]["original"]
    assert original["observation"]["value_num"] == "0" and original["observation"]["value_text"] is None
    assert original["observation"]["collected_at"] == "2001-02-03T04:05:05.123456"
    assert original["observation"]["time_basis"] == original["report"]["time_basis"] == "unknown"
    assert first["collected_at_utc"] == windows.iso(case["start"])
    assert first["available_at"] == first["registered_at"] == windows.iso(case["as_of"])
    assert first["snapshot"]["availability_basis"] == "server_registered_after_verification"
    second = by_id[qualitative["source"].lab_source_id]
    assert second["snapshot"]["original"]["observation"]["value_num"] is None
    assert second["snapshot"]["original"]["observation"]["value_text"] == "No growth reported"
    assert snapshot["quality"]["laboratory"]["eligible_numeric_count"] == snapshot["quality"]["laboratory"]["eligible_qualitative_count"] == 1


def test_v2_cutoff_and_membership_do_not_disclose_other_admissions_or_late_registration(db_session, laboratory_case):
    case, make = laboratory_case["case"], laboratory_case["make"]
    left = make(collected=case["start"])
    right = make(collected=case["end"])
    outside = make(collected=case["start"] - datetime.timedelta(microseconds=1))
    other = make(admission=case["other"])
    late = make(registered=case["as_of"] + datetime.timedelta(microseconds=1))
    snapshot = windows.snapshot_current(db_session, case["doctor"], create(db_session, case))
    assert {item["lab_source_id"] for item in snapshot["lab_observations"]} == {left["source"].lab_source_id, right["source"].lab_source_id}
    assert snapshot["quality"]["laboratory"]["member_count"] == 2
    text = windows.canonical_json(snapshot)
    for member in (outside, other, late):
        assert member["source"].lab_source_id not in text and member["observation"].observation_id not in text


def test_v1_freeze_ignores_laboratory_registration_and_mapping_withdrawal(db_session, laboratory_case):
    case = laboratory_case["case"]
    row = legacy_window(db_session, case)
    before = (row.snapshot_json, row.content_hash)
    member = laboratory_case["make"]()
    assert windows.snapshot_current(db_session, case["doctor"], row) == json.loads(before[0])
    revoke_member(db_session, case, member, "mapping")
    assert windows.snapshot_current(db_session, case["doctor"], row) == json.loads(before[0])
    assert (row.snapshot_json, row.content_hash) == before


@pytest.mark.parametrize("target", ["source", "mapping"])
def test_withdrawal_invalidates_old_v2_and_new_window_binds_excluded_original(db_session, laboratory_case, target):
    case = laboratory_case["case"]
    member = laboratory_case["make"]()
    row = create(db_session, case)
    before = (row.snapshot_json, row.content_hash, member["source"].snapshot_json, member["source"].content_hash)
    revoke_member(db_session, case, member, target)
    with pytest.raises(HTTPException) as caught:
        windows.snapshot_current(db_session, case["doctor"], row)
    assert caught.value.status_code == 409
    fresh = windows.snapshot_current(db_session, case["doctor"], create(db_session, case))
    laboratory = fresh["lab_observations"][0]
    assert laboratory["eligible"] is False and laboratory["exclusion_reasons"] == [f"{target}_revoked"]
    assert fresh["quality"]["laboratory"]["member_count"] == 1 and fresh["quality"]["laboratory"]["eligible_count"] == 0
    assert fresh["quality"]["laboratory"]["excluded_sources"] == [{"source_id": laboratory["source_id"], "reasons": [f"{target}_revoked"]}]
    assert (row.snapshot_json, row.content_hash, member["source"].snapshot_json, member["source"].content_hash) == before


def test_same_time_identity_duplicates_conflicts_and_distinct_names_are_not_resolved(db_session, laboratory_case):
    case, make = laboratory_case["case"], laboratory_case["make"]
    first = make(numeric="1.00")
    second = make(numeric="1.000")
    make(numeric="2", code="SYNTHETIC-OTHER")
    row = create(db_session, case)
    frozen = windows.snapshot_current(db_session, case["doctor"], row)
    groups = frozen["quality"]["laboratory"]["same_time_groups"]
    assert len(groups) == 1 and groups[0]["state"] == "duplicate_same_value"
    assert len(groups[0]["source_ids"]) == 2 and len(frozen["lab_observations"]) == 3
    assert groups[0]["identity"]["code"] == "SYNTHETIC-CREAT"
    third = make(numeric="3")
    with pytest.raises(HTTPException):
        windows.snapshot_current(db_session, case["doctor"], row)
    fresh = windows.snapshot_current(db_session, case["doctor"], create(db_session, case))
    groups = fresh["quality"]["laboratory"]["same_time_groups"]
    assert len(groups) == 1 and groups[0]["state"] == "conflicting_values_or_reference" and len(groups[0]["source_ids"]) == 3
    assert {item["lab_source_id"] for item in fresh["lab_observations"]} >= {item["source"].lab_source_id for item in (first, second, third)}


def test_typed_database_quantities_survive_free_text_minimization_and_raw_hash_binding(db_session, laboratory_case):
    case = laboratory_case["case"]
    quantity = "13812345678.00000000"
    note = "Synthetic original source note " + quantity + " " + case["seed"]["patient"].name
    member = laboratory_case["make"](numeric=quantity, note=note)
    frozen = windows.snapshot_current(db_session, case["doctor"], create(db_session, case))
    item = frozen["lab_observations"][0]
    assert item["snapshot"]["original"]["observation"]["value_num"] == quantity
    assert "result" not in item["snapshot"]["original"]["report"]
    assert "13812345678" not in item["snapshot"]["collection_time_basis_note"]
    assert item["raw_original_hash"] == member["source"].raw_original_hash
    assert note in member["source"].snapshot_json and item["governance_hash"]


@pytest.mark.parametrize("revoked", [False, True])
def test_combined_row_limit_includes_laboratory_and_revoked_members(db_session, laboratory_case, monkeypatch, revoked):
    case = laboratory_case["case"]
    member = laboratory_case["make"]()
    if revoked:
        revoke_member(db_session, case, member, "source")
    monkeypatch.setattr(windows, "MAX_ROWS", 2)
    with pytest.raises(HTTPException) as caught:
        create(db_session, case)
    assert caught.value.status_code == 422 and "合计" in caught.value.detail


def test_laboratory_expansion_that_exceeds_context_budget_is_rejected(db_session, laboratory_case, monkeypatch):
    from app.config import settings

    case = laboratory_case["case"]
    laboratory_case["make"]()
    legacy = legacy_window(db_session, case)
    monkeypatch.setattr(settings, "AI_MAX_CONTEXT_CHARS", len(legacy.snapshot_json.encode()) + 200)
    with pytest.raises(HTTPException) as caught:
        create(db_session, case)
    assert caught.value.status_code == 422 and "字节" in caught.value.detail


def test_long_parent_report_is_omitted_but_complete_original_content_remains_bound(db_session, laboratory_case):
    case = laboratory_case["case"]
    member = laboratory_case["make"](report_text="UNRELATED-FUTURE-REPORT-FACTS:" + "x" * 45000)
    row = create(db_session, case)
    snapshot = windows.snapshot_current(db_session, case["doctor"], row)
    item = snapshot["lab_observations"][0]
    assert item["window_projection"] == snapshot["laboratory_projection"]["schema_version"] == "risk_lab_projection_v1"
    assert snapshot["laboratory_projection"]["omitted_parent_fields"] == ["original.report.result", "original.order.check_type", "original.order.check_items"]
    assert "result" not in item["snapshot"]["original"]["report"]
    assert "check_type" not in item["snapshot"]["original"]["order"] and "check_items" not in item["snapshot"]["original"]["order"]
    assert "UNRELATED-FUTURE-REPORT-FACTS" not in windows.canonical_json(snapshot)
    assert "UNRELATED-FUTURE-REPORT-FACTS" in member["source"].snapshot_json
    frozen = row.snapshot_json
    member["report"].result += " Changed parent text remains integrity relevant even when omitted."
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        windows.snapshot_current(db_session, case["doctor"], row)
    assert caught.value.status_code == 409
    assert row.snapshot_json == frozen


@pytest.mark.parametrize("target", ["source", "mapping"])
def test_changed_withdrawal_text_cannot_hide_behind_the_same_privacy_placeholder(db_session, laboratory_case, target):
    case = laboratory_case["case"]
    member = laboratory_case["make"]()
    revoke_member(db_session, case, member, target)
    record = member["mapping"] if target == "mapping" else member["source"]
    record.revoke_reason = "Synthetic withdrawn identity 13812345678"
    db_session.commit()
    row = create(db_session, case)
    before = windows.snapshot_current(db_session, case["doctor"], row)
    record.revoke_reason = "Synthetic withdrawn identity 13912345678"
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        windows.snapshot_current(db_session, case["doctor"], row)
    assert caught.value.status_code == 409
    after = windows.snapshot_current(db_session, case["doctor"], create(db_session, case))
    key = "mapping_current" if target == "mapping" else None
    old = before["lab_observations"][0]
    new = after["lab_observations"][0]
    assert (old[key] if key else old)["revoke_reason"] == (new[key] if key else new)["revoke_reason"]
    assert old["governance_hash"] != new["governance_hash"]


def change_laboratory(db, laboratory_case, member, change):
    case = laboratory_case["case"]
    if change in {"source", "mapping"}:
        revoke_member(db, case, member, change)
    elif change == "original_value":
        member["observation"].value_num = Decimal("7")
    elif change == "parent_review":
        member["report"].audit_status = 0
    elif change == "parent_narrative":
        member["report"].result += " Changed parent text, even though omitted from risk input."
    elif change == "member":
        laboratory_case["make"]()
    elif change == "delete":
        db.delete(member["source"])
    elif change == "reassign":
        member["source"].admission_id = case["other"].admission_id
    else:
        raise AssertionError(change)
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
@pytest.mark.parametrize("change", ["source", "mapping", "original_value", "parent_review", "parent_narrative", "member", "delete", "reassign"])
async def test_laboratory_changes_stop_queue_discard_inflight_and_block_ordinary_history(phase, change, async_client, auth_headers, seed_data, db_session, laboratory_case):
    case = laboratory_case["case"]
    configure_risk(db_session, seed_data)
    member = laboratory_case["make"]()
    row = create(db_session, case)
    run = create_run(db_session, case["doctor"], request_for(case, row))
    claim = claim_next_run(db_session)
    if phase == "queued":
        change_laboratory(db_session, laboratory_case, member, change)
    sent = []
    await execute_claimed(*claim, transport=transport_for(sent, before=(lambda: change_laboratory(db_session, laboratory_case, member, change)) if phase == "inflight" else None))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    if phase != "history":
        assert stored.status == "failed" and json.loads(stored.result_json) == {}
        assert len(sent) == (0 if phase == "queued" else 1)
        return
    assert stored.status == "succeeded", stored.error_message
    frozen = (stored.input_json, stored.result_json, stored.evidence_json, stored.context_digest)
    path = "/api/ai/runs/" + run.run_id
    assert (await async_client.get(path, headers=auth_headers(case["doctor"].username))).status_code == 200
    change_laboratory(db_session, laboratory_case, member, change)
    assert (await async_client.get(path, headers=auth_headers(case["doctor"].username))).status_code == 403
    supers = await async_client.get(path, headers=auth_headers(seed_data["super_admin_user"].username))
    assert supers.status_code == 200 and supers.json()["data"]["observation_findings"]["lab_observations"]
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert (stored.input_json, stored.result_json, stored.evidence_json, stored.context_digest) == frozen


@pytest.mark.asyncio
@pytest.mark.parametrize("feature", ["deterioration_risk", "sepsis_risk", "aki_risk"])
async def test_actual_risk_payload_cites_lab_and_mapping_without_old_patient_data_or_clinical_scores(feature, async_client, auth_headers, seed_data, db_session, laboratory_case):
    case = laboratory_case["case"]
    configure_risk(db_session, seed_data, feature)
    member = laboratory_case["make"](numeric="13812345678.00000000", report_text="UNRELATED-PARENT-TEXT-OMITTED:" + "x" * 45000)
    row = create(db_session, case)
    run = create_run(db_session, case["doctor"], request_for(case, row, feature))
    sent = []
    await execute_claimed(*claim_next_run(db_session), transport=transport_for(sent))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", stored.error_message
    payload = sent[0]["input"]
    assert "UNRELATED-PARENT-TEXT-OMITTED" not in windows.canonical_json(payload)
    snapshot = payload["context"]["observation_window"]
    source = snapshot["lab_observations"][0]
    assert source["snapshot"]["original"]["observation"]["value_num"] == "13812345678.00000000"
    assert source["observation_id"] == member["observation"].observation_id
    assert {source["source_id"], source["snapshot"]["mapping"]["source_id"]} <= {item["source_id"] for item in payload["evidence"]}
    assert "laboratory_trends" not in payload["tools"] and "critical_value_workflow" not in payload["tools"]
    assert "reviewed_observations" not in payload["context"] and "latest_vitals" not in payload["context"]
    assert snapshot["model_input_validation"] == "not_provided" and snapshot["quality"]["laboratory"]["clinical_scores_calculated"] is False
    response = await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(case["doctor"].username))
    assert response.status_code == 200 and response.json()["data"]["observation_findings"] == snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_new_late_lab_registration_does_not_change_frozen_window_payload_or_history(legacy, async_client, auth_headers, seed_data, db_session, laboratory_case):
    case = laboratory_case["case"]
    configure_risk(db_session, seed_data)
    row = legacy_window(db_session, case) if legacy else create(db_session, case)
    run = create_run(db_session, case["doctor"], request_for(case, row))
    frozen_window = row.snapshot_json
    late = laboratory_case["make"](registered=case["now"])
    sent = []
    await execute_claimed(*claim_next_run(db_session), transport=transport_for(sent))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", stored.error_message
    assert late["source"].lab_source_id not in windows.canonical_json(sent) and late["observation"].observation_id not in windows.canonical_json(sent)
    assert windows.snapshot_current(db_session, case["doctor"], row) == json.loads(frozen_window)
    assert (await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(case["doctor"].username))).status_code == 200
