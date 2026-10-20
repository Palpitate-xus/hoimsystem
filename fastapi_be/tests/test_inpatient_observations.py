"""Synthetic real API measurements: explicit clocks, original admission and immutable facts."""

import datetime
import json
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app import inpatient_observations as observations
from app.ai.context import authorize_patient
from app.ai.models import AIAuditEvent, AIPatientGrant
from app.database import get_db
from app.inpatient_observations import PointCreate, UrineCreate, source_current
from app.models import Admission, InpatientObservation, InpatientUrineInterval, NursingRecord, Registration
from app.routers import inpatient_observations as routes

NOW = datetime.datetime(2026, 10, 20, 12, 30, 45, 123456)


def measured(value, unit):
    return {"value": value, "unit": unit, "absent_reason": None}


def point_body(case, **changes):
    return {
        "patient_id": case["patient_id"],
        "admission_id": case["admission_id"],
        "observed_at": "2026-10-20T12:00:00.123456+08:00",
        "measurements": {"heart_rate": measured("0", "/min"), "spo2": {"value": None, "unit": "%", "absent_reason": "not_performed"}},
        "supplemental_oxygen": "unknown",
        "oxygen_device": None,
        "consciousness": None,
        "note": "合成原始测量，零值不能被替换成正常或未知",
        **changes,
    }


def urine_body(case, **changes):
    return {
        "patient_id": case["patient_id"],
        "admission_id": case["admission_id"],
        "start_at": "2026-10-20T08:00:00.000001+08:00",
        "end_at": "2026-10-20T09:00:00.000002+08:00",
        "volume_ml": "0",
        "absent_reason": None,
        "collection_completeness": "unknown",
        "patient_total": None,
        "collection_method": "人工量杯记录，来源仅合成测试",
        "note": "原区间；不从缺段推断总尿量",
        **changes,
    }


@pytest.fixture
def observation_case(db_session, seed_data, monkeypatch):
    monkeypatch.setattr(observations, "utcnow", lambda: NOW)
    monkeypatch.setattr(routes, "utcnow", lambda: NOW)
    rows = [
        Admission(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            admission_no="OBS" + uuid.uuid4().hex[:15],
            status=1,
            # This old unzoned clock must not be treated as UTC or used to
            # infer that a measurement belongs to a different admission.
            admission_time=datetime.datetime(2099, 1, 1),
        ),
        Admission(patient_id=seed_data["patient2"].patient_id, admission_no="OBF" + uuid.uuid4().hex[:15], status=1),
        Admission(patient_id=seed_data["patient"].patient_id, admission_no="OBX" + uuid.uuid4().hex[:15], status=1),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return {"patient_id": rows[0].patient_id, "admission_id": rows[0].admission_id, "row": rows[0], "foreign": rows[1], "other_admission": rows[2]}


@pytest_asyncio.fixture
async def observation_client(db_session):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def session_override():
        yield db_session

    app.dependency_overrides[get_db] = session_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def grant_nurse(db_session, seed_data, *, expires=False, revoked=0):
    row = AIPatientGrant(
        user_id=seed_data["nurse_user"].user_id,
        patient_id=seed_data["patient"].patient_id,
        category="inpatient",
        reason="合成观测测试明确照护授权，不借新记录作者自举",
        expires_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + datetime.timedelta(days=-1 if expires else 1),
        revoked=revoked,
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.mark.asyncio
async def test_real_point_api_retains_unknown_zero_units_microseconds_and_original_scope(observation_client, observation_case, seed_data, auth_headers, db_session):
    body = point_body(observation_case)
    headers = auth_headers(seed_data["doctor_user"].username)
    created = await observation_client.post("/api/inpatient-observations/points", headers=headers, json=body)
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    row = db_session.get(InpatientObservation, data["observation_id"])
    assert data["observed_at"] == "2026-10-20T04:00:00.123456Z"
    assert data["recorded_at"] == "2026-10-20T12:30:45.123456Z"
    assert data["payload"]["measurements"] == body["measurements"]
    assert "pulse_rate" not in data["payload"]["measurements"]
    assert data["payload"]["consciousness"] is None and data["payload"]["supplemental_oxygen"] == "unknown"
    assert data["can_revoke"] is True and data["revision"] == 1 and data["status"] == "active"
    assert data["source_id"] == f"inpatient_observation:{row.observation_id}:{row.content_hash[:12]}"
    assert observations.serialize_point(row) == {k: v for k, v in data.items() if k != "can_revoke"}
    assert row.payload_json == observations.canonical_json(data["payload"])
    assert db_session.query(NursingRecord).filter_by(admission_id=row.admission_id).count() == 0
    event = db_session.query(AIAuditEvent).filter_by(action="inpatient_observation.create", target=row.observation_id).one()
    assert json.loads(event.detail_json)["content_hash"] == row.content_hash
    assert "measurements" not in event.detail_json
    params = {"patient_id": row.patient_id, "admission_id": row.admission_id}
    listed = await observation_client.get("/api/inpatient-observations/points", headers=headers, params=params)
    assert listed.json()["data"] == {"items": [data], "total": 1, "page": 1, "page_size": 50}
    detail = await observation_client.get(f"/api/inpatient-observations/points/{row.observation_id}", headers=headers, params=params)
    assert detail.json()["data"] == data


@pytest.mark.asyncio
async def test_urine_unknown_zero_and_overlapping_original_intervals_are_never_merged(observation_client, observation_case, seed_data, auth_headers, db_session):
    headers = auth_headers(seed_data["admin_user"].username)
    first = await observation_client.post("/api/inpatient-observations/urine-intervals", headers=headers, json=urine_body(observation_case))
    assert first.status_code == 200, first.text
    a = first.json()["data"]
    second = await observation_client.post(
        "/api/inpatient-observations/urine-intervals",
        headers=headers,
        json=urine_body(observation_case, volume_ml=None, absent_reason="measurement_error", collection_completeness="partial", patient_total=False),
    )
    assert second.status_code == 200, second.text
    b = second.json()["data"]
    assert a["interval_id"] != b["interval_id"] and a["start_at"] == b["start_at"] == "2026-10-20T00:00:00.000001Z"
    assert a["end_at"] == b["end_at"] == "2026-10-20T01:00:00.000002Z"
    assert a["payload"]["volume_ml"] == "0" and a["payload"]["patient_total"] is None
    assert b["payload"]["volume_ml"] is None and b["payload"]["absent_reason"] == "measurement_error"
    assert all("rate" not in key and "risk" not in key for key in a)
    assert db_session.query(InpatientUrineInterval).filter_by(admission_id=observation_case["admission_id"]).count() == 2
    listed = await observation_client.get("/api/inpatient-observations/urine-intervals", headers=headers, params={"patient_id": a["patient_id"], "admission_id": a["admission_id"], "page_size": 1})
    assert listed.json()["data"]["total"] == 2 and len(listed.json()["data"]["items"]) == 1


@pytest.mark.parametrize("value", [0, 1.5, True, "NaN", "Infinity", "1e2", "1.123456789", "10000000000000000", " 1", "+1", "01"])
def test_measurements_reject_numeric_coercion_nonfinite_and_precision_loss(value):
    with pytest.raises(ValidationError):
        PointCreate.model_validate(point_body({"patient_id": 1, "admission_id": str(uuid.uuid4())}, measurements={"heart_rate": measured(value, "/min")}))


@pytest.mark.parametrize(
    "measurements",
    [
        {"heart_rate": measured("-1", "/min")},
        {"heart_rate": measured("80", "bpm")},
        {"fio2": measured("101", "%")},
        {"spo2": measured("-1", "%")},
        {"unknown": measured("1", "/min")},
        {"pulse_rate": {"value": None, "unit": "/min", "absent_reason": None}},
        {"pulse_rate": {"value": "0", "unit": "/min", "absent_reason": "unknown"}},
        {"pulse_rate": {"value": "0", "unit": "/min", "absent_reason": None, "normal": True}},
    ],
)
def test_explicit_measurement_semantics_and_fixed_units(measurements):
    with pytest.raises(ValidationError):
        PointCreate.model_validate(point_body({"patient_id": 1, "admission_id": str(uuid.uuid4())}, measurements=measurements))


@pytest.mark.parametrize(
    "time",
    [
        "2026-10-20T01:00:00",
        "",
        None,
        True,
        123456,
        "2026-10-20T01:00:00.1234567Z",
        "0001-01-01T00:00:00+14:00",
        "9999-12-31T23:59:59-14:00",
        "2099-01-01T01:00:00Z",
        "2026-02-30T01:00:00Z",
        "2026-10-20T01:00:00+01:60",
        "2026-10-20T01:00:00-00:99",
    ],
)
def test_point_clocks_never_guess_replace_or_truncate(time):
    with pytest.raises(ValidationError):
        PointCreate.model_validate(point_body({"patient_id": 1, "admission_id": str(uuid.uuid4())}, observed_at=time))


@pytest.mark.parametrize(
    "changes",
    [
        {"consciousness": {"system": "AVPU", "code": "new_confusion"}},
        {"consciousness": {"system": "ACVPU", "code": "normal"}},
        {"supplemental_oxygen": None},
        {"supplemental_oxygen": False},
        {"patient_id": True},
        {"admission_id": "legacy-not-a-uuid"},
        {"target_admission": "forged"},
        {"measurements": {}, "consciousness": None, "supplemental_oxygen": "unknown"},
    ],
)
def test_point_has_no_default_normal_oxygen_or_consciousness(changes):
    with pytest.raises(ValidationError):
        PointCreate.model_validate(point_body({"patient_id": 1, "admission_id": str(uuid.uuid4())}, **changes))


def test_negative_temperature_maximum_exact_decimal_and_explicit_acvpu_are_retained():
    data = PointCreate.model_validate(
        point_body(
            {"patient_id": 1, "admission_id": str(uuid.uuid4())},
            measurements={"temperature": measured("-10.12345678", "Cel"), "body_weight": measured("0", "kg"), "heart_rate": measured("9999999999999999.99999999", "/min")},
            consciousness={"system": "ACVPU", "code": "new_confusion"},
        )
    )
    assert data.measurements["temperature"].value == "-10.12345678" and data.measurements["body_weight"].value == "0"


@pytest.mark.parametrize(
    "changes",
    [
        {"volume_ml": 0},
        {"volume_ml": True},
        {"volume_ml": "-1"},
        {"volume_ml": "1.000000001"},
        {"volume_ml": None, "absent_reason": None},
        {"volume_ml": "0", "absent_reason": "unknown"},
        {"patient_total": "true"},
        {"patient_total": 1},
        {"collection_completeness": None},
        {"collection_method": " "},
        {"start_at": "2026-10-20T01:00:00Z", "end_at": "2026-10-20T01:00:00Z"},
        {"start_at": "2026-10-20T02:00:00Z", "end_at": "2026-10-20T01:00:00Z"},
        {"end_at": "2099-01-01T01:00:00Z"},
        {"end_at": "2026-10-20T01:00:00"},
    ],
)
def test_urine_requires_real_interval_explicit_value_and_collection_basis(changes):
    with pytest.raises(ValidationError):
        UrineCreate.model_validate(urine_body({"patient_id": 1, "admission_id": str(uuid.uuid4())}, **changes))


@pytest.mark.asyncio
async def test_nurse_first_entry_requires_prior_care_or_expiring_grant_and_never_self_grants(observation_client, observation_case, seed_data, auth_headers, db_session):
    headers = auth_headers(seed_data["nurse_user"].username)
    denied = await observation_client.post("/api/inpatient-observations/points", headers=headers, json=point_body(observation_case))
    assert denied.status_code == 403 and db_session.query(InpatientObservation).filter_by(admission_id=observation_case["admission_id"]).count() == 0
    grant = grant_nurse(db_session, seed_data)
    created = await observation_client.post("/api/inpatient-observations/points", headers=headers, json=point_body(observation_case))
    assert created.status_code == 200, created.text
    grant.revoked = 1
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        authorize_patient(db_session, seed_data["nurse_user"], observation_case["patient_id"], "inpatient", observation_case["admission_id"])
    assert error.value.status_code == 403
    params = {"patient_id": observation_case["patient_id"], "admission_id": observation_case["admission_id"]}
    denied_read = await observation_client.get("/api/inpatient-observations/points", headers=headers, params=params)
    assert denied_read.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["patient_user", "cashier_user", "pharmacist_user", "guide_user", "lab_tech_user", "registrar_user"])
async def test_unrelated_roles_cannot_create_or_list(role, observation_client, observation_case, seed_data, auth_headers):
    headers = auth_headers(seed_data[role].username)
    for path, body in [("points", point_body(observation_case)), ("urine-intervals", urine_body(observation_case))]:
        assert (await observation_client.post("/api/inpatient-observations/" + path, headers=headers, json=body)).status_code == 403
        assert (
            await observation_client.get(
                "/api/inpatient-observations/" + path, headers=headers, params={"patient_id": observation_case["patient_id"], "admission_id": observation_case["admission_id"]}
            )
        ).status_code == 403


@pytest.mark.asyncio
async def test_foreign_scope_missing_clock_and_discharged_create_fail_without_insert(observation_client, observation_case, seed_data, auth_headers, db_session):
    headers = auth_headers(seed_data["admin_user"].username)
    for changes in [{"patient_id": seed_data["patient2"].patient_id}, {"admission_id": observation_case["foreign"].admission_id}]:
        response = await observation_client.post("/api/inpatient-observations/points", headers=headers, json=point_body(observation_case, **changes))
        assert response.status_code == 404, response.text
    response = await observation_client.post("/api/inpatient-observations/points", headers=headers, json=point_body(observation_case, observed_at=""))
    assert response.status_code == 422
    observation_case["row"].status = 2
    db_session.commit()
    for path, body in [("points", point_body(observation_case)), ("urine-intervals", urine_body(observation_case))]:
        response = await observation_client.post("/api/inpatient-observations/" + path, headers=headers, json=body)
        assert response.status_code == 409
    assert db_session.query(InpatientObservation).filter_by(admission_id=observation_case["admission_id"]).count() == 0
    assert (await observation_client.get("/api/inpatient-observations/points", headers=headers)).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["points", "urine-intervals"])
async def test_revoke_requires_current_owner_or_admin_exact_revision_and_never_changes_frozen_content(kind, observation_client, observation_case, seed_data, auth_headers, db_session):
    owner = auth_headers(seed_data["doctor_user"].username)
    body = point_body(observation_case) if kind == "points" else urine_body(observation_case)
    created = await observation_client.post("/api/inpatient-observations/" + kind, headers=owner, json=body)
    assert created.status_code == 200, created.text
    original = created.json()["data"]
    identifier = original.get("observation_id", original.get("interval_id"))
    base = f"/api/inpatient-observations/{kind}/{identifier}"
    binding = {"patient_id": original["patient_id"], "admission_id": original["admission_id"]}
    director = auth_headers(seed_data["director_user"].username)
    detail = await observation_client.get(base, headers=director, params=binding)
    assert detail.status_code == 200 and detail.json()["data"]["can_revoke"] is False
    assert (await observation_client.post(base + "/revoke", headers=director, json={**binding, "expected_revision": 1, "reason": "非作者不可撤销"})).status_code == 403
    assert (await observation_client.post(base + "/revoke", headers=owner, json={**binding, "expected_revision": 2, "reason": "过期页面"})).status_code == 409
    revoked = await observation_client.post(base + "/revoke", headers=owner, json={**binding, "expected_revision": 1, "reason": "原记录人撤销合成错误测量"})
    assert revoked.status_code == 200, revoked.text
    data = revoked.json()["data"]
    assert data["status"] == "revoked" and data["revision"] == 2 and data["can_revoke"] is False
    assert data["content_hash"] == original["content_hash"] and data["payload"] == original["payload"] and data["source_id"] == original["source_id"]
    assert data["revoked_at"] == "2026-10-20T12:30:45.123456Z"
    assert (await observation_client.post(base + "/revoke", headers=owner, json={**binding, "expected_revision": 2, "reason": "不能恢复或重复"})).status_code == 409
    for method in ["put", "patch", "delete"]:
        assert (await getattr(observation_client, method)(base, headers=owner, params=binding)).status_code == 405
    event = db_session.query(AIAuditEvent).filter_by(target=identifier).order_by(AIAuditEvent.event_id).all()
    assert len(event) == 2 and event[-1].action.endswith(".revoke")
    model = InpatientObservation if kind == "points" else InpatientUrineInterval
    row = db_session.get(model, identifier)
    with pytest.raises(HTTPException) as error:
        source_current(db_session, row)
    assert error.value.status_code == 409
    assert source_current(db_session, row, allow_revoked=True)["status"] == "revoked"


@pytest.mark.asyncio
async def test_same_patient_other_admission_cannot_read_or_revoke_and_foreign_doctor_is_denied(observation_client, observation_case, seed_data, auth_headers):
    headers = auth_headers(seed_data["admin_user"].username)
    created = (await observation_client.post("/api/inpatient-observations/points", headers=headers, json=point_body(observation_case))).json()["data"]
    base = "/api/inpatient-observations/points/" + created["observation_id"]
    other = {"patient_id": created["patient_id"], "admission_id": observation_case["other_admission"].admission_id}
    assert (await observation_client.get(base, headers=headers, params=other)).status_code == 404
    assert (await observation_client.post(base + "/revoke", headers=headers, json={**other, "expected_revision": 1, "reason": "不能跨住院"})).status_code == 404
    doctor = auth_headers(seed_data["doctor_user"].username)
    foreign = {"patient_id": observation_case["foreign"].patient_id, "admission_id": observation_case["foreign"].admission_id}
    assert (await observation_client.get("/api/inpatient-observations/points", headers=doctor, params=foreign)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("payload_json", '{"forged":true}'),
        ("content_hash", "0" * 64),
        ("schema_version", "forged_v2"),
        ("observed_at", datetime.datetime(2020, 1, 1)),
        ("recorded_at", datetime.datetime(2020, 1, 1)),
        ("created_by", 999999),
    ],
)
async def test_changed_frozen_fields_are_rejected_on_real_detail(field, value, observation_client, observation_case, seed_data, auth_headers, db_session):
    headers = auth_headers(seed_data["admin_user"].username)
    created = (await observation_client.post("/api/inpatient-observations/points", headers=headers, json=point_body(observation_case))).json()["data"]
    row = db_session.get(InpatientObservation, created["observation_id"])
    setattr(row, field, value)
    db_session.commit()
    response = await observation_client.get(
        "/api/inpatient-observations/points/" + row.observation_id,
        headers=headers,
        params={"patient_id": row.patient_id, "admission_id": row.admission_id},
    )
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_parent_reassignment_role_demotion_and_expired_grant_are_not_hidden(observation_client, observation_case, seed_data, auth_headers, db_session):
    headers = auth_headers(seed_data["admin_user"].username)
    created = (await observation_client.post("/api/inpatient-observations/points", headers=headers, json=point_body(observation_case))).json()["data"]
    row = db_session.get(InpatientObservation, created["observation_id"])
    observation_case["row"].patient_id = seed_data["patient2"].patient_id
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        source_current(db_session, row)
    assert error.value.status_code == 409
    observation_case["row"].patient_id = seed_data["patient"].patient_id
    db_session.commit()
    grant_nurse(db_session, seed_data, expires=True)
    nurse = auth_headers(seed_data["nurse_user"].username)
    params = {"patient_id": row.patient_id, "admission_id": row.admission_id}
    assert (await observation_client.get("/api/inpatient-observations/points", headers=nurse, params=params)).status_code == 403
    seed_data["admin_user"].user_role = "cashier"
    db_session.commit()
    assert (await observation_client.get("/api/inpatient-observations/points", headers=headers, params=params)).status_code == 403


@pytest.mark.asyncio
async def test_database_conflict_rolls_back_new_source_and_audit_together(observation_client, observation_case, seed_data, auth_headers, db_session, monkeypatch):
    headers = auth_headers(seed_data["admin_user"].username)
    created = (await observation_client.post("/api/inpatient-observations/points", headers=headers, json=point_body(observation_case))).json()["data"]
    fixed_id = uuid.UUID(created["observation_id"])
    monkeypatch.setattr(routes.uuid, "uuid4", lambda: fixed_id)
    conflict = await observation_client.post("/api/inpatient-observations/points", headers=headers, json=point_body(observation_case, note="独立错误请求不应留下第二条审计或覆盖原内容"))
    assert conflict.status_code == 409, conflict.text
    assert db_session.query(InpatientObservation).filter_by(admission_id=observation_case["admission_id"]).count() == 1
    assert db_session.query(AIAuditEvent).filter_by(action="inpatient_observation.create", target=str(fixed_id)).count() == 1
    assert db_session.get(InpatientObservation, str(fixed_id)).content_hash == created["content_hash"]


@pytest.mark.asyncio
async def test_closed_admission_keeps_readable_original_and_super_can_revoke_other_author(observation_client, observation_case, seed_data, auth_headers, db_session):
    owner = auth_headers(seed_data["doctor_user"].username)
    created = (await observation_client.post("/api/inpatient-observations/points", headers=owner, json=point_body(observation_case))).json()["data"]
    observation_case["row"].status = 2
    db_session.commit()
    binding = {"patient_id": created["patient_id"], "admission_id": created["admission_id"]}
    base = "/api/inpatient-observations/points/" + created["observation_id"]
    assert (await observation_client.get(base, headers=owner, params=binding)).status_code == 200
    super_headers = auth_headers(seed_data["super_admin_user"].username)
    response = await observation_client.post(base + "/revoke", headers=super_headers, json={**binding, "expected_revision": 1, "reason": "超管保留原值并撤销错误来源"})
    assert response.status_code == 200 and response.json()["data"]["revoked_by"] == seed_data["super_admin_user"].user_id


@pytest.mark.asyncio
async def test_oversized_identifiers_and_pagination_are_validation_errors(observation_client, observation_case, seed_data, auth_headers):
    headers = auth_headers(seed_data["admin_user"].username)
    binding = {"patient_id": observation_case["patient_id"], "admission_id": observation_case["admission_id"]}
    for params in [{**binding, "patient_id": 2**100}, {**binding, "page": 2**100}, {**binding, "page_size": 101}]:
        response = await observation_client.get("/api/inpatient-observations/points", headers=headers, params=params)
        assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_outpatient_uuid_collision_cannot_substitute_for_real_admission_care(observation_client, observation_case, seed_data, auth_headers, db_session):
    observation_case["row"].doctor_id = None
    observation_case["row"].department_id = None
    db_session.add(
        Registration(
            registration_uuid=observation_case["admission_id"],
            patient_id=observation_case["patient_id"],
            doctor_id=seed_data["doctor"].doctor_id,
            status=0,
        )
    )
    db_session.commit()
    headers = auth_headers(seed_data["doctor_user"].username)
    denied = await observation_client.post("/api/inpatient-observations/points", headers=headers, json=point_body(observation_case))
    assert denied.status_code == 409 and "冲突" in denied.json()["detail"]
    assert db_session.query(InpatientObservation).filter_by(admission_id=observation_case["admission_id"]).count() == 0
