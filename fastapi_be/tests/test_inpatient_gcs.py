"""Real synthetic HTTP/ORM GCS originals, exact UTC, explicit anchors and clinical recording rights."""

import datetime
import json

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app import inpatient_gcs as gcs
from app.ai.models import AIAuditEvent, AIPatientGrant
from app.database import get_db
from app.inpatient_observations import ObservationRevoke, canonical_json, utc_text
from app.models import Doctor, InpatientGcsObservation, NursingRecord
from app.routers import inpatient_gcs as routes
from app.routers import inpatient_observations as point_routes
from app.routers.inpatient_observations import revoke_point
from tests.test_ai_observation_windows import observation_case as observation_case
from tests.test_ai_observation_windows import point

NOTE = "合成临床人员明确核实这是同一次床旁检查，两个实际测量钟点分别保留，不从自动最近记录推定。"


def payload(case, **changes):
    return {
        "components": {"eye": {"score": 4, "absent_reason": None}, "verbal": {"score": 5, "absent_reason": None}, "motor": {"score": 6, "absent_reason": None}},
        "anchor_point": {"observation_id": case["point"].observation_id, "expected_content_hash": case["point"].content_hash},
        "same_exam_confirmed": True,
        "same_exam_basis_note": NOTE,
        "note": "合成原GCS备注；不是病历诊断或AI补分",
        **changes,
    }


def body(case, **changes):
    return {
        "patient_id": case["patient_id"],
        "admission_id": case["admission"].admission_id,
        "observed_at": utc_text(case["start"] + datetime.timedelta(minutes=1)),
        "payload": payload(case),
        **changes,
    }


@pytest.fixture
def gcs_case(db_session, observation_case, monkeypatch):
    db_session.query(InpatientGcsObservation).delete()
    db_session.query(AIPatientGrant).delete()
    db_session.commit()
    case = observation_case
    monkeypatch.setattr(gcs, "utcnow", lambda: case["now"])
    monkeypatch.setattr(routes, "utcnow", lambda: case["now"])
    monkeypatch.setattr(point_routes, "utcnow", lambda: case["now"])
    return case


@pytest_asyncio.fixture
async def gcs_client(db_session):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic-gcs") as client:
        yield client


def register(db, case, actor=None, **changes):
    row = gcs.create_source(db, actor or case["doctor"], body(case, **changes))
    db.commit()
    return row


@pytest.mark.asyncio
async def test_real_gcs_api_preserves_distinct_clocks_original_scope_exact_components_and_anchor(gcs_client, gcs_case, auth_headers, db_session):
    case = gcs_case
    original_point = (case["point"].payload_json, case["point"].content_hash, case["point"].recorded_at)
    request = body(case)
    headers = auth_headers(case["doctor"].username)
    response = await gcs_client.post("/api/inpatient-gcs", headers=headers, json=request)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    row = db_session.get(InpatientGcsObservation, data["gcs_observation_id"])
    assert data["payload"] == request["payload"] and data["derived_total"] == 15
    assert data["observed_at"] == request["observed_at"] != data["anchor_point_snapshot"]["observed_at"]
    assert data["recorded_at"] == utc_text(case["now"]) and data["schema_version"] == "inpatient_gcs_v1"
    assert data["source_id"] == f"gcs_observation:{row.gcs_observation_id}:{row.content_hash[:12]}"
    assert data["anchor_current"] is True and data["anchor_exclusion_reasons"] == [] and data["can_record"] is data["can_revoke"] is True
    assert data["anchor_point_snapshot"]["patient_id"] == data["patient_id"] == case["patient_id"]
    assert row.payload_json == canonical_json(request["payload"])
    assert (case["point"].payload_json, case["point"].content_hash, case["point"].recorded_at) == original_point
    assert db_session.query(NursingRecord).filter_by(admission_id=row.admission_id).count() == 0
    event = db_session.query(AIAuditEvent).filter_by(action="gcs_observation.create", target=row.gcs_observation_id).one()
    assert json.loads(event.detail_json) == {"content_hash": row.content_hash, "revision": 1}
    params = {"patient_id": row.patient_id, "admission_id": row.admission_id}
    listed = await gcs_client.get("/api/inpatient-gcs", headers=headers, params=params)
    assert listed.json()["data"] == {"items": [data], "total": 1, "page": 1, "page_size": 50, "can_record": True}
    fetched = await gcs_client.get(f"/api/inpatient-gcs/{row.gcs_observation_id}", headers=headers, params=params)
    assert fetched.json()["data"] == data


@pytest.mark.parametrize("component,maximum", [("eye", 4), ("verbal", 5), ("motor", 6)])
@pytest.mark.parametrize("value", [0, True, 1.0, "1", -1, 7])
def test_gcs_never_coerces_bool_float_text_or_out_of_range_component(component, maximum, value):
    data = {"eye": {"score": 4, "absent_reason": None}, "verbal": {"score": 5, "absent_reason": None}, "motor": {"score": 6, "absent_reason": None}}
    data[component]["score"] = value
    with pytest.raises(ValidationError):
        gcs.Components.model_validate(data)
    data[component]["score"] = maximum + 1
    with pytest.raises(ValidationError):
        gcs.Components.model_validate(data)


@pytest.mark.parametrize("component,maximum", [("eye", 4), ("verbal", 5), ("motor", 6)])
def test_all_actual_integer_component_values_are_retained(component, maximum):
    for value in range(1, maximum + 1):
        data = {"eye": {"score": 4, "absent_reason": None}, "verbal": {"score": 5, "absent_reason": None}, "motor": {"score": 6, "absent_reason": None}}
        data[component]["score"] = value
        assert gcs.Components.model_validate(data).model_dump()[component]["score"] == value


@pytest.mark.parametrize("reason", ["not_testable", "not_recorded"])
def test_nt_retains_original_components_and_never_manufactures_total(db_session, gcs_case, reason):
    data = payload(gcs_case)
    data["components"]["verbal"] = {"score": None, "absent_reason": reason}
    row = register(db_session, gcs_case, payload=data)
    source = gcs.source_current(db_session, row)
    assert source["payload"]["components"]["verbal"] == {"score": None, "absent_reason": reason}
    assert source["derived_total"] is None and source["payload"]["components"]["motor"]["score"] == 6


@pytest.mark.parametrize(
    "changes",
    [
        {"score": None, "absent_reason": None},
        {"score": 1, "absent_reason": "not_testable"},
        {"score": None, "absent_reason": "unknown"},
        {"score": None, "absent_reason": "NT"},
    ],
)
def test_gcs_missing_semantics_must_be_explicit(changes):
    with pytest.raises(ValidationError):
        gcs.Component.model_validate(changes)


def test_generic_unanchored_source_is_allowed_but_not_claimed_current_anchor(db_session, gcs_case):
    row = register(db_session, gcs_case, payload=payload(gcs_case, anchor_point=None, same_exam_confirmed=False, same_exam_basis_note=None))
    data = gcs.source_current(db_session, row)
    assert row.anchor_point_id is None and data["anchor_point_snapshot"] is None
    assert data["derived_total"] == 15 and data["anchor_current"] is False
    assert data["anchor_exclusion_reasons"] == ["no_explicit_original_point_anchor"]


@pytest.mark.parametrize(
    "changes",
    [
        {"same_exam_confirmed": False},
        {"same_exam_confirmed": 1},
        {"same_exam_basis_note": None},
        {"same_exam_basis_note": " " * 25},
        {"anchor_point": None},
        {"anchor_point": None, "same_exam_confirmed": False, "same_exam_basis_note": NOTE},
    ],
)
def test_same_exam_link_is_explicit_and_unanchored_cannot_claim_a_link(gcs_case, changes):
    with pytest.raises(ValidationError):
        gcs.GcsPayload.model_validate(payload(gcs_case, **changes))


@pytest.mark.parametrize("clock", ["2026-10-20T12:00:00", "2026-10-20T12:00:00.1234567Z", True, "2099-01-01T00:00:00Z", "2026-10-20T12:00:00+01:60"])
def test_observed_clock_requires_explicit_valid_precise_real_time(gcs_case, clock):
    with pytest.raises(ValidationError):
        gcs.GcsCreate.model_validate(body(gcs_case, observed_at=clock))


@pytest.mark.parametrize("change", ["other_admission", "wrong_hash", "future_anchor"])
def test_anchor_full_original_scope_and_hash_cannot_be_inferred_or_rebound(db_session, gcs_case, change):
    data = body(gcs_case)
    if change == "other_admission":
        row = point(db_session, gcs_case, admission=gcs_case["other"].admission_id)
        data["payload"]["anchor_point"] = {"observation_id": row.observation_id, "expected_content_hash": row.content_hash}
    elif change == "wrong_hash":
        data["payload"]["anchor_point"]["expected_content_hash"] = "0" * 64
    else:
        gcs_case["point"].recorded_at = gcs_case["now"] + datetime.timedelta(seconds=1)
        from app.inpatient_observations import frozen_content_hash

        gcs_case["point"].content_hash = frozen_content_hash(gcs_case["point"], json.loads(gcs_case["point"].payload_json))
        data["payload"]["anchor_point"]["expected_content_hash"] = gcs_case["point"].content_hash
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        gcs.create_source(db_session, gcs_case["doctor"], data)
    assert error.value.status_code == 409
    assert db_session.query(InpatientGcsObservation).count() == 0


@pytest.mark.parametrize("role", ["admin_user", "super_admin_user"])
@pytest.mark.asyncio
async def test_management_rights_do_not_create_clinical_gcs_originals(gcs_client, gcs_case, auth_headers, role):
    response = await gcs_client.post("/api/inpatient-gcs", headers=auth_headers(gcs_case["seed"][role].username), json=body(gcs_case))
    assert response.status_code == 403
    listed = await gcs_client.get(
        "/api/inpatient-gcs", headers=auth_headers(gcs_case["seed"][role].username), params={"patient_id": gcs_case["patient_id"], "admission_id": gcs_case["admission"].admission_id}
    )
    if listed.status_code == 200:
        assert listed.json()["data"]["can_record"] is False


def test_super_requires_actual_doctor_entity_and_clinical_care_even_with_management_scope(db_session, gcs_case):
    super_user = gcs_case["seed"]["super_admin_user"]
    doctor = Doctor(user_id=super_user.user_id, name="Synthetic clinical Super", department_id=gcs_case["seed"]["department"].department_id)
    db_session.add(doctor)
    db_session.flush()
    with pytest.raises(HTTPException) as error:
        gcs.create_source(db_session, super_user, body(gcs_case))
    assert error.value.status_code == 403
    gcs_case["admission"].doctor_id = doctor.doctor_id
    db_session.commit()
    row = register(db_session, gcs_case, actor=super_user)
    assert row.created_by == super_user.user_id


def test_nurse_needs_actual_prior_care_grant_not_source_authorship(db_session, gcs_case):
    nurse = gcs_case["seed"]["nurse_user"]
    with pytest.raises(HTTPException) as error:
        gcs.create_source(db_session, nurse, body(gcs_case))
    assert error.value.status_code == 403
    grant = AIPatientGrant(
        user_id=nurse.user_id,
        patient_id=gcs_case["patient_id"],
        category="inpatient",
        reason=NOTE,
        expires_at=gcs_case["now"] + datetime.timedelta(hours=1),
        revoked=0,
        created_by=gcs_case["seed"]["super_admin_user"].user_id,
    )
    db_session.add(grant)
    db_session.commit()
    assert register(db_session, gcs_case, actor=nurse).created_by == nurse.user_id
    grant.revoked = 1
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        gcs.authorize_scope(db_session, nurse, gcs_case["patient_id"], gcs_case["admission"].admission_id)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_revoke_cas_keeps_full_raw_original_and_super_audit_after_anchor_revoke(gcs_client, gcs_case, auth_headers, db_session):
    case = gcs_case
    row = register(db_session, case)
    original = (row.payload_json, row.anchor_snapshot_json, row.content_hash)
    revoke_point(
        case["point"].observation_id, ObservationRevoke(patient_id=case["patient_id"], admission_id=case["admission"].admission_id, expected_revision=1, reason=NOTE), case["doctor"], db_session
    )
    data = gcs.source_current(db_session, row)
    assert data["anchor_current"] is False and data["derived_total"] == 15
    request = {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id, "expected_revision": 1, "reason": NOTE}
    super_headers = auth_headers(case["seed"]["super_admin_user"].username)
    response = await gcs_client.post(f"/api/inpatient-gcs/{row.gcs_observation_id}/revoke", headers=super_headers, json=request)
    assert response.status_code == 200, response.text
    revoked = response.json()["data"]
    assert revoked["status"] == "revoked" and revoked["revision"] == 2 and revoked["can_revoke"] is False
    assert (row.payload_json, row.anchor_snapshot_json, row.content_hash) == original
    assert revoked["governance_hash"] != data["governance_hash"]
    duplicate = await gcs_client.post(f"/api/inpatient-gcs/{row.gcs_observation_id}/revoke", headers=super_headers, json=request)
    assert duplicate.status_code == 409
    audit = await gcs_client.get(f"/api/ai/admin/gcs-sources/{row.gcs_observation_id}", headers=super_headers)
    assert audit.status_code == 200 and audit.json()["data"]["payload"] == data["payload"] and audit.json()["data"]["anchor_current"] is False
    assert db_session.query(AIAuditEvent).filter_by(action="gcs_observation.revoke", target=row.gcs_observation_id).count() == 1


@pytest.mark.parametrize("mutation", ["payload", "clock", "scope", "anchor_index", "anchor_snapshot", "governance"])
def test_current_check_rejects_actual_stored_source_tampering(db_session, gcs_case, mutation):
    row = register(db_session, gcs_case)
    if mutation == "payload":
        raw = json.loads(row.payload_json)
        raw["note"] += "被修改"
        row.payload_json = canonical_json(raw)
    elif mutation == "clock":
        row.observed_at += datetime.timedelta(microseconds=1)
    elif mutation == "scope":
        row.admission_id = gcs_case["other"].admission_id
    elif mutation == "anchor_index":
        row.anchor_point_id = None
    elif mutation == "anchor_snapshot":
        raw = json.loads(row.anchor_snapshot_json)
        raw["payload"]["note"] = "altered"
        row.anchor_snapshot_json = canonical_json(raw)
    else:
        row.revision = 2
    if mutation == "governance":
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError, match="ck_inpatient_gcs_governance"):
            db_session.flush()
        db_session.rollback()
        return
    db_session.flush()
    with pytest.raises(HTTPException) as error:
        gcs.source_current(db_session, row)
    assert error.value.status_code == 409
    db_session.rollback()


@pytest.mark.asyncio
async def test_source_and_audit_are_rolled_back_together_on_actual_audit_failure(gcs_client, gcs_case, auth_headers, db_session, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic actual audit persistence failure")

    monkeypatch.setattr(routes, "audit", fail)
    before = db_session.query(InpatientGcsObservation).count()
    with pytest.raises(RuntimeError, match="actual audit"):
        await gcs_client.post("/api/inpatient-gcs", headers=auth_headers(gcs_case["doctor"].username), json=body(gcs_case))
    assert db_session.query(InpatientGcsObservation).count() == before
    row = register(db_session, gcs_case)
    with pytest.raises(RuntimeError, match="actual audit"):
        await gcs_client.post(
            f"/api/inpatient-gcs/{row.gcs_observation_id}/revoke",
            headers=auth_headers(gcs_case["doctor"].username),
            json={"patient_id": row.patient_id, "admission_id": row.admission_id, "expected_revision": 1, "reason": NOTE},
        )
    db_session.refresh(row)
    assert row.status == "active" and row.revision == 1 and row.revoked_at is None
