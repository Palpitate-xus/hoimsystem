"""Real API and database windows over synthetic admission-bound observations."""

import datetime
import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.ai import observation_windows as windows
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import minimize_identifiers, patient_snapshot
from app.ai.models import AIObservationWindow, utcnow
from app.inpatient_observations import PointPayload, UrinePayload, canonical_json, frozen_content_hash
from app.models import Admission, InpatientObservation, InpatientUrineInterval, NursingRecord
from app.routers.ai_observation_windows import WindowCreate


def point(db, case, *, observed=None, recorded=None, admission=None, identifier=None, payload=None):
    payload = PointPayload.model_validate(
        payload
        or {
            "measurements": {"heart_rate": {"value": "0", "unit": "/min", "absent_reason": None}, "spo2": {"value": None, "unit": "%", "absent_reason": "not_performed"}},
            "supplemental_oxygen": "unknown",
        }
    ).model_dump(mode="json")
    row = InpatientObservation(
        observation_id=identifier or str(uuid.uuid4()),
        patient_id=case["patient_id"],
        admission_id=admission or case["admission"].admission_id,
        observed_at=observed or case["start"],
        recorded_at=recorded or case["as_of"],
        created_by=case["doctor"].user_id,
        schema_version="inpatient_observation_v1",
        payload_json=canonical_json(payload),
        status="active",
        revision=1,
        revoke_reason="",
    )
    row.content_hash = frozen_content_hash(row, payload)
    db.add(row)
    db.flush()
    return row


def urine(db, case, *, start=None, end=None, recorded=None, payload=None):
    payload = UrinePayload.model_validate(
        payload or {"volume_ml": "0", "absent_reason": None, "collection_completeness": "complete", "patient_total": True, "collection_method": "synthetic explicit collection", "note": ""}
    ).model_dump(mode="json")
    row = InpatientUrineInterval(
        interval_id=str(uuid.uuid4()),
        patient_id=case["patient_id"],
        admission_id=case["admission"].admission_id,
        start_at=start or case["start"],
        end_at=end or case["end"],
        recorded_at=recorded or case["as_of"],
        created_by=case["doctor"].user_id,
        schema_version="urine_interval_v1",
        payload_json=canonical_json(payload),
        status="active",
        revision=1,
        revoke_reason="",
    )
    row.content_hash = frozen_content_hash(row, payload)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def observation_case(db_session, seed_data, monkeypatch):
    from app import inpatient_observations

    now = utcnow() - datetime.timedelta(seconds=1)
    monkeypatch.setattr(windows, "utcnow", lambda: now)
    monkeypatch.setattr(inpatient_observations, "utcnow", lambda: now)
    db_session.query(AIObservationWindow).delete()
    db_session.query(InpatientObservation).delete()
    db_session.query(InpatientUrineInterval).delete()
    admissions = [
        Admission(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            status=1,
            admission_time=now - datetime.timedelta(days=2),
        )
        for _ in range(2)
    ]
    db_session.add_all(admissions)
    db_session.flush()
    case = {
        "now": now,
        "start": now - datetime.timedelta(hours=3),
        "end": now - datetime.timedelta(hours=1),
        "as_of": now - datetime.timedelta(minutes=30),
        "patient_id": seed_data["patient"].patient_id,
        "admission": admissions[0],
        "other": admissions[1],
        "doctor": seed_data["doctor_user"],
        "seed": seed_data,
    }
    case["point"] = point(db_session, case, identifier="12345678-1234-4234-8234-13123456789a")
    case["urine"] = urine(db_session, case)
    db_session.commit()
    return case


def values(case):
    return {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id, "start_at": case["start"], "end_at": case["end"], "as_of": case["as_of"]}


def create(db, case, user=None):
    row = windows.create_window(db, user or case["doctor"], values(case))
    db.commit()
    return row


def body(case):
    return {key: windows.iso(value) if isinstance(value, datetime.datetime) else value for key, value in values(case).items()}


def test_snapshot_freezes_explicit_zero_unknown_raw_sources_and_utc_microseconds(db_session, observation_case):
    case = observation_case
    row = create(db_session, case)
    snapshot = windows.snapshot_current(db_session, case["doctor"], row)
    assert snapshot["content_hash"] == windows.content_hash(snapshot) == row.content_hash
    assert snapshot["source_id"] == f"observation_window:{row.window_id}:{row.content_hash[:12]}"
    assert snapshot["points"][0]["payload"]["measurements"]["heart_rate"]["value"] == "0"
    assert snapshot["points"][0]["payload"]["measurements"]["spo2"]["value"] is None
    assert snapshot["quality"]["missing_by_point"][0]["explicitly_unmeasured"] == ["spo2"]
    assert snapshot["quality"]["urine"]["volume_aggregation_performed"] is False
    assert snapshot["quality"]["urine"]["uncovered_intervals"] == []
    assert snapshot["snapshot_basis"] == "current_snapshot_retrospective"
    assert snapshot["lab_input_status"].startswith("not_available") and snapshot["model_input_validation"] == "not_provided"
    assert minimize_identifiers(snapshot, case["seed"]["patient"]) == snapshot
    assert "DATETIME(6)" in str(CreateTable(AIObservationWindow.__table__).compile(dialect=mysql.dialect()))


def test_utc_endpoints_future_late_and_other_admission_never_leak_even_counts(db_session, observation_case):
    case = observation_case
    at_end = point(db_session, case, observed=case["end"])
    early = point(db_session, case, observed=case["start"] - datetime.timedelta(microseconds=1))
    future = point(db_session, case, observed=case["end"] + datetime.timedelta(microseconds=1))
    other = point(db_session, case, admission=case["other"].admission_id)
    late = point(db_session, case, recorded=case["now"])
    row = create(db_session, case)
    snapshot = windows.snapshot_current(db_session, case["doctor"], row)
    assert {item["observation_id"] for item in snapshot["points"]} == {case["point"].observation_id, at_end.observation_id}
    encoded = canonical_json(snapshot)
    assert all(item.observation_id not in encoded for item in (early, future, other, late))
    before = row.snapshot_json
    point(db_session, case, recorded=case["now"])
    db_session.commit()
    assert canonical_json(windows.snapshot_current(db_session, case["doctor"], row)) == before


def test_same_time_numeric_oxygen_and_consciousness_duplicates_are_not_selected_or_merged(db_session, observation_case):
    case = observation_case
    original = json.loads(case["point"].payload_json)
    point(db_session, case, payload=original)
    changed = {
        **original,
        "measurements": {**original["measurements"], "heart_rate": {"value": "90", "unit": "/min", "absent_reason": None}},
        "supplemental_oxygen": "yes",
        "consciousness": {"system": "AVPU", "code": "voice"},
    }
    point(db_session, case, payload=changed)
    snapshot = windows.snapshot_current(db_session, case["doctor"], create(db_session, case))
    assert len(snapshot["points"]) == 3
    conflicts = {item["measurement_code"]: item for item in snapshot["quality"]["same_time_groups"]}
    assert conflicts["heart_rate"]["state"] == conflicts["supplemental_oxygen"]["state"] == conflicts["consciousness"]["state"] == "conflicting_values_or_missing_state"
    assert conflicts["spo2"]["state"] == "duplicate_same_value"
    assert snapshot["quality"]["continuous_monitoring_confirmed"] is False


def test_urine_overlap_cross_boundary_partial_and_unknown_have_no_volume_or_rate_aggregation(db_session, observation_case):
    case = observation_case
    urine(db_session, case, start=case["start"] - datetime.timedelta(minutes=30), end=case["start"] + datetime.timedelta(minutes=30))
    urine(
        db_session,
        case,
        start=case["start"] + datetime.timedelta(minutes=30),
        end=case["end"],
        payload={"volume_ml": None, "absent_reason": "unknown", "collection_completeness": "partial", "patient_total": False, "collection_method": "synthetic uncertain collection"},
    )
    snapshot = windows.snapshot_current(db_session, case["doctor"], create(db_session, case))
    report = snapshot["quality"]["urine"]
    assert len(snapshot["urine_intervals"]) == 3 and report["eligible_coverage_intervals"] == []
    assert len(report["overlap_groups"][0]["source_ids"]) == 3
    assert report["uncovered_intervals"] == [{"start_at": windows.iso(case["start"]), "end_at": windows.iso(case["end"])}]
    assert report["volume_aggregation_performed"] is report["rate_calculation_performed"] is False
    reasons = {reason for item in report["excluded_intervals"] for reason in item["reasons"]}
    assert {"crosses_window_boundary_no_proration", "collection_not_complete", "not_confirmed_patient_total", "volume_not_measured", "overlapping_intervals"} <= reasons


@pytest.mark.parametrize(
    "value", ["2026-10-20T01:02:03.1234567Z", "2026-W43-2T01:02:03Z", "2026-10-20T01:02Z", "2026-10-20T01:02:03", "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59", True, 0]
)
def test_window_clock_parser_rejects_ambiguous_or_precision_losing_input(value, observation_case):
    from pydantic import ValidationError

    data = body(observation_case)
    data["as_of"] = value
    with pytest.raises(ValidationError):
        WindowCreate.model_validate(data)


@pytest.mark.parametrize("change", ["reversed", "future", "after_cutoff", "oversize_time", "outpatient", "patient", "too_many", "bytes"])
def test_creation_refuses_invalid_scope_and_incomplete_bounded_query(change, db_session, observation_case, monkeypatch):
    case, args = observation_case, values(observation_case)
    if change == "reversed":
        args["start_at"] = args["end_at"]
    elif change == "future":
        args["as_of"] = case["now"] + datetime.timedelta(seconds=1)
    elif change == "after_cutoff":
        args["end_at"] = case["as_of"] + datetime.timedelta(seconds=1)
    elif change == "oversize_time":
        args["start_at"] = args["end_at"] - datetime.timedelta(hours=168, microseconds=1)
    elif change == "outpatient":
        args["admission_id"] = "00000000-0000-4000-8000-000000000001"
    elif change == "patient":
        args["patient_id"] = case["seed"]["patient2"].patient_id
    elif change == "too_many":
        monkeypatch.setattr(windows, "MAX_ROWS", 1)
    else:
        monkeypatch.setattr(windows, "MAX_SNAPSHOT_BYTES", 20)
    with pytest.raises(HTTPException):
        windows.create_window(db_session, case["doctor"], args)
    assert db_session.query(AIObservationWindow).count() == 0


def test_v2_uses_independent_storage_budget_without_rewriting_frozen_content_or_legacy_policy(db_session, observation_case, monkeypatch):
    case = observation_case
    row = windows.create_window(db_session, case["doctor"], values(case))
    frozen = row.snapshot_json
    monkeypatch.setattr(windows.settings, "AI_MAX_CONTEXT_CHARS", 20)
    assert canonical_json(windows.snapshot_current(db_session, case["doctor"], row)) == frozen
    with pytest.raises(HTTPException) as caught:
        windows.build_snapshot(db_session, **values(case), window_id=row.window_id, created_by=row.created_by, created_at=row.created_at, schema_version=windows.LEGACY_SCHEMA_VERSION)
    assert caught.value.status_code == 422


@pytest.mark.parametrize("offset", [0, -1])
def test_v2_complete_original_window_capacity_counts_utf8_bytes_at_exact_boundary(offset, db_session, observation_case, monkeypatch):
    case = observation_case
    row = windows.create_window(db_session, case["doctor"], values(case))
    assert len(row.snapshot_json.encode("utf-8")) > len(row.snapshot_json)
    monkeypatch.setattr(windows, "MAX_SNAPSHOT_BYTES", len(row.snapshot_json.encode("utf-8")) + offset)
    if offset == 0:
        assert canonical_json(windows.snapshot_current(db_session, case["doctor"], row)) == row.snapshot_json
    else:
        with pytest.raises(HTTPException) as caught:
            windows.snapshot_current(db_session, case["doctor"], row)
        assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_real_api_scope_revoke_and_super_audit_without_enabling_model(async_client, auth_headers, db_session, observation_case):
    case = observation_case
    headers = auth_headers(case["doctor"].username)
    created = await async_client.post("/api/ai/observation-windows", headers=headers, json=body(case))
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    identifier = data["window_id"]
    assert data["freshness"]["state"] == "current" and data["snapshot"]["content_hash"] == data["content_hash"]
    listed = await async_client.get("/api/ai/observation-windows", headers=headers, params={"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id})
    assert listed.json()["data"][0]["freshness"]["state"] == "not_checked"
    assert (await async_client.get("/api/ai/admin/observation-windows", headers=auth_headers(case["seed"]["admin_user"].username))).status_code == 403
    denied = await async_client.post(
        f"/api/ai/observation-windows/{identifier}/revoke", headers=auth_headers(case["seed"]["admin_user"].username), json={"expected_revision": 1, "reason": "other author cannot govern"}
    )
    assert denied.status_code == 403
    revoked = await async_client.post(f"/api/ai/observation-windows/{identifier}/revoke", headers=headers, json={"expected_revision": 1, "reason": "synthetic explicit revocation"})
    assert revoked.status_code == 200 and revoked.json()["data"]["snapshot"] is None
    assert revoked.json()["data"]["freshness"]["state"] == "revoked"
    audit = await async_client.get(f"/api/ai/admin/observation-windows/{identifier}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert audit.status_code == 200 and audit.json()["data"]["snapshot"] == data["snapshot"]
    assert (await async_client.post(f"/api/ai/observation-windows/{identifier}/revoke", headers=headers, json={"expected_revision": 2, "reason": "cannot restore"})).status_code == 409


@pytest.mark.asyncio
async def test_nurse_cannot_bootstrap_care_from_authorship_of_new_sources(async_client, auth_headers, db_session, observation_case):
    case = observation_case
    case["point"].created_by = case["seed"]["nurse_user"].user_id
    case["point"].content_hash = frozen_content_hash(case["point"], json.loads(case["point"].payload_json))
    db_session.commit()
    response = await async_client.post("/api/ai/observation-windows", headers=auth_headers(case["seed"]["nurse_user"].username), json=body(case))
    assert response.status_code == 403
    db_session.add(NursingRecord(patient_id=case["patient_id"], admission_id=case["other"].admission_id, nurse_id=case["seed"]["nurse_user"].user_id, record_time=case["now"], create_time=case["now"]))
    db_session.commit()
    assert (await async_client.post("/api/ai/observation-windows", headers=auth_headers(case["seed"]["nurse_user"].username), json=body(case))).status_code == 403


@pytest.mark.parametrize("feature", ["deterioration_risk", "sepsis_risk", "aki_risk"])
def test_risk_snapshot_is_only_frozen_window_and_never_generic_future_context(feature, db_session, observation_case):
    case = observation_case
    row = create(db_session, case)
    bundle = patient_snapshot(
        db_session, case["doctor"], FEATURE_BY_KEY[feature], case["patient_id"], case["admission"].admission_id, {"observation_window_id": row.window_id, "question": "only task text"}
    )
    assert set(bundle.data) == {"scope", "observation_window", "selected_sources", "missing_data", "snapshot_time"}
    assert bundle.data["observation_window"]["window_id"] == row.window_id
    assert {entry["source_id"] for entry in bundle.evidence} >= {bundle.data["observation_window"]["source_id"]}
    for refs in [{}, {"icu_score_id": "1"}, {"observation_window_id": row.window_id, "latest_vitals": {"future": True}}, {"observation_window_id": row.window_id, "question": False}]:
        with pytest.raises(HTTPException) as caught:
            patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY[feature], case["patient_id"], case["admission"].admission_id, refs)
        assert caught.value.status_code == 422
    with pytest.raises(HTTPException):
        patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY["handover_summary"], case["patient_id"], case["admission"].admission_id, {"observation_window_id": row.window_id})


def test_legal_decimal_quantities_remain_exact_while_identical_free_text_is_hidden(db_session, observation_case):
    case = observation_case
    quantity = "13812345678.00000000"
    source = point(
        db_session,
        case,
        payload={"measurements": {"heart_rate": {"value": quantity, "unit": "/min", "absent_reason": None}}, "supplemental_oxygen": "unknown", "note": quantity + " " + case["seed"]["patient"].name},
    )
    urine_source = urine(
        db_session, case, payload={"volume_ml": quantity, "absent_reason": None, "collection_completeness": "complete", "patient_total": True, "collection_method": "synthetic " + quantity}
    )
    snapshot = windows.snapshot_current(db_session, case["doctor"], create(db_session, case))
    measured = next(item for item in snapshot["points"] if item["observation_id"] == source.observation_id)
    collected = next(item for item in snapshot["urine_intervals"] if item["interval_id"] == urine_source.interval_id)
    assert measured["payload"]["measurements"]["heart_rate"]["value"] == collected["payload"]["volume_ml"] == quantity
    assert "13812345678" not in measured["payload"]["note"] and "13812345678" not in collected["payload"]["collection_method"]
    assert case["seed"]["patient"].name not in measured["payload"]["note"]
    assert json.loads(source.payload_json)["note"].startswith(quantity), "Original source content remains intact"


@pytest.mark.asyncio
async def test_window_detail_requires_matching_explicit_patient_admission_scope(async_client, auth_headers, db_session, observation_case):
    case = observation_case
    row = create(db_session, case)
    headers = auth_headers(case["doctor"].username)
    path = f"/api/ai/observation-windows/{row.window_id}"
    assert (await async_client.get(path, headers=headers)).status_code == 422
    assert (await async_client.get(path, headers=headers, params={"patient_id": case["patient_id"], "admission_id": case["other"].admission_id})).status_code == 409
    response = await async_client.get(path, headers=headers, params={"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id})
    assert response.status_code == 200 and response.json()["data"]["freshness"]["state"] == "current"


def test_already_revoked_originals_are_bound_as_members_but_not_active_measurements(db_session, observation_case):
    case = observation_case
    original = case["point"]
    original.status, original.revision = "revoked", 2
    original.revoked_at, original.revoked_by, original.revoke_reason = case["now"], case["doctor"].user_id, "Original synthetic record revoked"
    db_session.commit()
    snapshot = windows.snapshot_current(db_session, case["doctor"], create(db_session, case))
    assert snapshot["quality"]["point_count"] == 1
    assert snapshot["points"][0]["status"] == "revoked"
    assert snapshot["quality"]["missing_by_point"] == []
    assert all(item["unique_numeric_observation_times"] == 0 for item in snapshot["quality"]["measurement_gaps"])
