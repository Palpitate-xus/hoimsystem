"""Synthetic real HTTP/ORM lab sources: explicit admission, clocks, namespaces and withdrawal."""

import datetime
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException

from app import inpatient_laboratory as sources
from app.ai import lab_mappings
from app.ai.models import AIAuditEvent, AIFeatureConfig, AILabMapping, AIPatientGrant
from app.database import get_db
from app.models import Admission, InpatientLabSource, LabObservation, LabOrder, LabResult, User
from app.routers import ai_lab_mappings as mapping_routes
from app.routers import inpatient_laboratory as routes

NOW = datetime.datetime(2026, 10, 20, 12, 30, 45, 123456)
NOTE = "合成测试人工核对原申请、患者住院、原采样记录与时区依据；不声称旧钟点已知UTC。"


def published_mapping(db, super_user, observation, *, namespace=None, **changes):
    body = {
        "source_namespace": namespace or "synthetic-lis-" + uuid.uuid4().hex,
        "signature": lab_mappings.observation_signature(observation),
        "analyte_key": "creatinine" if observation.value_num is not None else "culture_result",
        "evidence_reference": "synthetic dictionary only, document 2026 page 1",
        "rationale": "Synthetic explicit identity verification; no clinical model or unit conversion validation.",
        **changes,
    }
    row = lab_mappings.create_mapping(db, super_user, body)
    db.commit()
    mapping_routes.publish_mapping(
        row.mapping_id,
        mapping_routes.MappingPublish(expected_revision=1, semantic_confirmed=True, source_signature_confirmed=True, review_note=NOTE),
        db=db,
        user=super_user,
    )
    return lab_mappings.mapping_current(db, row.mapping_id)


@pytest.fixture
def case(db_session, seed_data, monkeypatch):
    for module in (sources, routes, lab_mappings, mapping_routes):
        monkeypatch.setattr(module, "utcnow", lambda: NOW)
    suffix = uuid.uuid4().hex[:12]
    admissions = [
        Admission(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            admission_no="LAB" + suffix,
            status=2,
            admission_time=datetime.datetime(2099, 1, 1),
        ),
        Admission(patient_id=seed_data["patient"].patient_id, admission_no="OTH" + suffix, status=1),
        Admission(patient_id=seed_data["patient2"].patient_id, admission_no="FOR" + suffix, status=1),
    ]
    db_session.add_all(admissions)
    order = LabOrder(
        lab_order_id="old-order-" + suffix,
        patient_id=admissions[0].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        check_type="原分类",
        check_items="原项目中文",
        urgent=0,
        status=2,
        sample_status=1,
        create_time=datetime.datetime(2001, 2, 3, 4, 5, 6, 111111),
    )
    report = LabResult(
        lab_result_id="old-report-" + suffix,
        lab_order_id=order.lab_order_id,
        sample_id="SYN",
        result="旧报告原文；非本次推理结论",
        abnormal_flag=0,
        technician_id=seed_data["lab_tech_user"].user_id,
        auditor_id=seed_data["admin_user"].user_id,
        audit_status=1,
        report_time=datetime.datetime(2002, 3, 4, 5, 6, 7, 222222),
        audit_time=datetime.datetime(2002, 3, 5, 5, 6, 7, 333333),
    )
    observation = LabObservation(
        observation_id="old-observation-" + suffix,
        lab_result_id=report.lab_result_id,
        code_system="local",
        code="SYN-" + suffix,
        display="仅显示名不用于推断",
        value_num=Decimal("1234567890123456.12345678"),
        value_text=None,
        unit="mg/dL",
        reference_low=Decimal("0.00000000"),
        reference_high=None,
        reference_text="原参考范围",
        collected_at=datetime.datetime(2099, 5, 6, 7, 8, 9, 654321),
        method="synthetic method",
        specimen_type="synthetic serum",
        flag="unknown",
    )
    db_session.add_all([order, report, observation])
    db_session.commit()
    mapping = published_mapping(db_session, seed_data["super_admin_user"], observation)
    return {
        "patient_id": admissions[0].patient_id,
        "admission_id": admissions[0].admission_id,
        "admission": admissions[0],
        "other": admissions[1],
        "foreign": admissions[2],
        "order": order,
        "report": report,
        "observation": observation,
        "mapping": mapping,
    }


@pytest_asyncio.fixture
async def client(db_session):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def session_override():
        yield db_session

    app.dependency_overrides[get_db] = session_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as session:
        yield session


def body(db, case, **changes):
    return {
        "patient_id": case["patient_id"],
        "admission_id": case["admission_id"],
        "observation_id": case["observation"].observation_id,
        "mapping_id": case["mapping"]["mapping_id"],
        "expected_source_hash": sources.load_original(db, case["observation"].observation_id, case["patient_id"])[2],
        "expected_mapping_hash": case["mapping"]["content_hash"],
        "collected_at_utc": "2026-10-19T20:21:22.654321+08:00",
        "collection_time_confirmed": True,
        "collection_time_basis_note": NOTE,
        "admission_binding_confirmed": True,
        "admission_binding_note": NOTE,
        "source_namespace_confirmed": True,
        "source_namespace_basis_note": NOTE,
        **changes,
    }


def scope(case):
    return {key: case[key] for key in ("patient_id", "admission_id")}


async def create(client, db, case, headers, **changes):
    response = await client.post("/api/inpatient-laboratory/sources", headers=headers, json=body(db, case, **changes))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def grant(db, seed, role_key):
    db.add(
        AIPatientGrant(
            user_id=seed[role_key].user_id,
            patient_id=seed["patient"].patient_id,
            category="inpatient",
            reason=NOTE,
            created_by=seed["super_admin_user"].user_id,
            expires_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + datetime.timedelta(days=1),
            revoked=0,
        )
    )
    db.commit()


@pytest.mark.asyncio
async def test_real_registration_preserves_database_decimal_old_clock_and_manual_utc(client, db_session, case, seed_data, auth_headers):
    headers = auth_headers(seed_data["doctor_user"].username)
    prior = [(r.feature_key, r.enabled, r.validation_status) for r in db_session.query(AIFeatureConfig)]
    original = sources.load_original(db_session, case["observation"].observation_id, case["patient_id"])[1]
    candidate = await client.get("/api/inpatient-laboratory/candidates", headers=headers, params=scope(case))
    assert candidate.status_code == 200
    item = next(x for x in candidate.json()["data"]["items"] if x["observation_id"] == case["observation"].observation_id)
    assert item["original"] == original and "不证明属于本次住院" in item["scope_note"]
    assert item["matching_mappings"][0]["source_namespace"]
    data = await create(client, db_session, case, headers)
    snapshot = data["snapshot"]
    assert data["collected_at_utc"] == "2026-10-19T12:21:22.654321Z"
    assert data["registered_at"] == data["available_at"] == "2026-10-20T12:30:45.123456Z"
    assert snapshot["original"] == original
    assert snapshot["original"]["observation"]["value_num"] == "1234567890123456.12345678"
    assert snapshot["original"]["observation"]["reference_low"] == "0.00000000" and snapshot["original"]["observation"]["reference_high"] is None
    assert snapshot["original"]["observation"]["collected_at"] == "2099-05-06T07:08:09.654321"
    assert snapshot["original"]["observation"]["time_basis"] == "unknown"
    assert snapshot["availability_basis"] == "server_registered_after_verification"
    assert snapshot["source_namespace_origin_basis"] == "explicit_user_attestation_no_stored_lis_origin"
    assert snapshot["original"]["observation"]["value_representation"] == "database_stored_decimal_text"
    row = db_session.get(InpatientLabSource, data["lab_source_id"])
    assert data["content_hash"] == sources.hash_content(snapshot) and row.snapshot_json == sources.canonical_json(snapshot)
    assert data["source_id"] == f"inpatient_lab:{row.lab_source_id}:{row.content_hash[:12]}"
    assert data["eligible"] is True and data["can_revoke"] is True and data["exclusion_reasons"] == []
    assert sources.source_current(db_session, row) == {k: v for k, v in data.items() if k not in {"freshness", "can_revoke"}}
    listing = (await client.get("/api/inpatient-laboratory/sources", params=scope(case), headers=headers)).json()["data"]
    assert listing == {"items": [data], "total": 1, "page": 1, "page_size": 50}
    assert (await client.get(f"/api/inpatient-laboratory/sources/{row.lab_source_id}", params=scope(case), headers=headers)).json()["data"] == data
    audit = db_session.query(AIAuditEvent).filter_by(action="inpatient_lab_source.create", target=row.lab_source_id).one()
    assert json.loads(audit.detail_json)["content_hash"] == row.content_hash and "原文" not in audit.detail_json
    assert [(r.feature_key, r.enabled, r.validation_status) for r in db_session.query(AIFeatureConfig)] == prior


@pytest.mark.parametrize(
    "field,value",
    [
        ("collection_time_confirmed", False),
        ("admission_binding_confirmed", 1),
        ("source_namespace_confirmed", "true"),
        ("source_namespace_basis_note", " " * 25),
        ("collection_time_basis_note", "short"),
        ("admission_binding_note", ""),
        ("patient_id", True),
        ("patient_id", "1"),
        ("admission_id", "not-uuid"),
        ("observation_id", ""),
        ("observation_id", "x" * 37),
        ("mapping_id", "not-uuid"),
        ("collected_at_utc", "2026-10-19T12:00:00"),
        ("collected_at_utc", "2026-10-19T12:00:00.1234567Z"),
        ("collected_at_utc", "0001-01-01T00:00:00+23:00"),
        ("value_num", "0"),
        ("source_namespace", "guess-from-display"),
        ("expected_mapping_hash", "not-hash"),
    ],
)
@pytest.mark.asyncio
async def test_request_rejects_coercion_guessed_input_and_missing_explicit_time(field, value, client, db_session, case, seed_data, auth_headers):
    before = db_session.query(InpatientLabSource).count()
    response = await client.post("/api/inpatient-laboratory/sources", headers=auth_headers(seed_data["doctor_user"].username), json=body(db_session, case, **{field: value}))
    assert response.status_code == 422, response.text
    assert db_session.query(InpatientLabSource).count() == before


@pytest.mark.parametrize("changes,status", [({"expected_source_hash": "0" * 64}, 409), ({"expected_mapping_hash": "0" * 64}, 409), ({"collected_at_utc": "2027-01-01T00:00:00Z"}, 422)])
@pytest.mark.asyncio
async def test_expected_original_mapping_hashes_and_future_sampling_are_verified(changes, status, client, db_session, case, seed_data, auth_headers):
    response = await client.post("/api/inpatient-laboratory/sources", headers=auth_headers(seed_data["doctor_user"].username), json=body(db_session, case, **changes))
    assert response.status_code == status


@pytest.mark.asyncio
async def test_zero_and_qualitative_null_are_preserved_without_interpretation(client, db_session, case, seed_data, auth_headers):
    case["observation"].value_num = Decimal("0")
    case["report"].technician_id = None  # Imported results may have no local entry actor.
    db_session.commit()
    data = await create(client, db_session, case, auth_headers(seed_data["doctor_user"].username))
    assert Decimal(data["snapshot"]["original"]["observation"]["value_num"]) == 0
    assert data["snapshot"]["original"]["report"]["review_scheme"] == "no_local_entry_actor_plus_local_reviewer"
    routes.revoke_source(data["lab_source_id"], sources.SourceRevoke(**scope(case), expected_revision=1, reason=NOTE), db=db_session, user=seed_data["doctor_user"])
    case["observation"].value_num, case["observation"].value_text, case["observation"].unit = None, "未检出；原文本不得变成0", None
    db_session.commit()
    case["mapping"] = published_mapping(db_session, seed_data["super_admin_user"], case["observation"])
    text = await create(client, db_session, case, auth_headers(seed_data["doctor_user"].username))
    assert text["snapshot"]["original"]["observation"]["value_num"] is None
    assert text["snapshot"]["original"]["observation"]["value_text"] == "未检出；原文本不得变成0"


@pytest.mark.asyncio
async def test_namespace_choice_is_explicit_and_mismatched_mapping_is_rejected(client, db_session, case, seed_data, auth_headers):
    second = published_mapping(db_session, seed_data["super_admin_user"], case["observation"])
    headers = auth_headers(seed_data["doctor_user"].username)
    response = await client.get("/api/inpatient-laboratory/candidates", params=scope(case), headers=headers)
    item = next(x for x in response.json()["data"]["items"] if x["observation_id"] == case["observation"].observation_id)
    assert {x["mapping_id"] for x in item["matching_mappings"]} == {case["mapping"]["mapping_id"], second["mapping_id"]}
    data = await create(client, db_session, case, headers, mapping_id=second["mapping_id"], expected_mapping_hash=second["content_hash"])
    assert data["snapshot"]["source_namespace"] == second["source_namespace"]
    case["observation"].method = "different method"
    db_session.commit()
    response = await client.post("/api/inpatient-laboratory/sources", headers=headers, json=body(db_session, case))
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_one_active_registration_cross_admission_constraint_and_cas_withdrawal(client, db_session, case, seed_data, auth_headers):
    headers = auth_headers(seed_data["admin_user"].username)
    first = await create(client, db_session, case, headers)
    audit_before = db_session.query(AIAuditEvent).filter_by(action="inpatient_lab_source.create").count()
    duplicate = await client.post("/api/inpatient-laboratory/sources", headers=headers, json=body(db_session, case, admission_id=case["other"].admission_id))
    assert duplicate.status_code == 409
    assert db_session.query(AIAuditEvent).filter_by(action="inpatient_lab_source.create").count() == audit_before
    endpoint = f"/api/inpatient-laboratory/sources/{first['lab_source_id']}/revoke"
    request = {**scope(case), "expected_revision": 2, "reason": NOTE}
    assert (await client.post(endpoint, headers=headers, json=request)).status_code == 409
    request["expected_revision"] = 1
    withdrawn = await client.post(endpoint, headers=headers, json=request)
    assert withdrawn.status_code == 200
    data = withdrawn.json()["data"]
    assert data["status"] == "revoked" and data["revision"] == 2 and data["content_hash"] == first["content_hash"]
    assert data["snapshot"] is None and data["eligible"] is False
    assert db_session.get(InpatientLabSource, first["lab_source_id"]).active_observation_id is None
    assert (await client.post(endpoint, headers=headers, json=request)).status_code == 409
    replacement = await create(client, db_session, case, headers, admission_id=case["other"].admission_id)
    assert replacement["lab_source_id"] != first["lab_source_id"] and replacement["status"] == "active"
    for method in ("PUT", "PATCH", "DELETE"):
        assert (await client.request(method, f"/api/inpatient-laboratory/sources/{first['lab_source_id']}", headers=headers, params=scope(case))).status_code == 405


@pytest.mark.asyncio
async def test_nurse_reads_with_prior_care_but_cannot_create_and_author_does_not_grant_care(client, db_session, case, seed_data, auth_headers):
    data = await create(client, db_session, case, auth_headers(seed_data["doctor_user"].username))
    nurse_headers = auth_headers(seed_data["nurse_user"].username)
    endpoint = f"/api/inpatient-laboratory/sources/{data['lab_source_id']}"
    assert (await client.get(endpoint, headers=nurse_headers, params=scope(case))).status_code == 403
    # A corrupt/imported created_by cannot bootstrap permission to the admission.
    row = db_session.get(InpatientLabSource, data["lab_source_id"])
    row.created_by = seed_data["nurse_user"].user_id
    db_session.commit()
    assert (await client.get(endpoint, headers=nurse_headers, params=scope(case))).status_code == 403
    grant(db_session, seed_data, "nurse_user")
    row.created_by = seed_data["doctor_user"].user_id
    db_session.commit()
    assert (await client.get(endpoint, headers=nurse_headers, params=scope(case))).status_code == 200
    assert (await client.post("/api/inpatient-laboratory/sources", headers=nurse_headers, json=body(db_session, case))).status_code == 403


@pytest.mark.parametrize("role", ["lab_tech_user", "cashier_user", "patient_user", "guide_user"])
@pytest.mark.asyncio
async def test_unrelated_roles_cannot_read_or_register(role, client, db_session, case, seed_data, auth_headers):
    headers = auth_headers(seed_data[role].username)
    assert (await client.get("/api/inpatient-laboratory/sources", headers=headers, params=scope(case))).status_code == 403
    assert (await client.post("/api/inpatient-laboratory/sources", headers=headers, json=body(db_session, case))).status_code == 403


@pytest.mark.asyncio
async def test_scope_is_mandatory_real_original_admission_and_admin_cannot_revoke_other_owner(client, db_session, case, seed_data, auth_headers):
    doctor = auth_headers(seed_data["doctor_user"].username)
    data = await create(client, db_session, case, doctor)
    endpoint = f"/api/inpatient-laboratory/sources/{data['lab_source_id']}"
    assert (await client.get(endpoint, headers=doctor)).status_code == 422
    assert (await client.get(endpoint, headers=auth_headers(seed_data["admin_user"].username), params={**scope(case), "admission_id": case["other"].admission_id})).status_code == 409
    assert (await client.get(endpoint, headers=doctor, params={**scope(case), "admission_id": case["foreign"].admission_id})).status_code == 404
    assert (await client.post(endpoint + "/revoke", headers=auth_headers(seed_data["admin_user"].username), json={**scope(case), "expected_revision": 1, "reason": NOTE})).status_code == 403
    assert (await client.get("/api/ai/admin/lab-sources", headers=auth_headers(seed_data["admin_user"].username))).status_code == 403
    assert (await client.get("/api/ai/admin/lab-sources", headers=auth_headers(seed_data["super_admin_user"].username), params=scope(case))).json()["data"]["total"] == 1


@pytest.mark.parametrize("field", ["value_num", "audit_time", "auditor_id", "order_patient", "source_hash", "mapping_hash", "deleted_observation", "deleted_admission"])
@pytest.mark.asyncio
async def test_stale_clinical_or_parent_source_blocks_ordinary_but_super_can_audit_and_withdraw(field, client, db_session, case, seed_data, auth_headers):
    doctor = auth_headers(seed_data["doctor_user"].username)
    data = await create(client, db_session, case, doctor)
    row = db_session.get(InpatientLabSource, data["lab_source_id"])
    if field == "value_num":
        case["observation"].value_num = Decimal("1.00000000")
    elif field == "audit_time":
        case["report"].audit_time += datetime.timedelta(seconds=1)
    elif field == "auditor_id":
        case["report"].auditor_id = case["report"].technician_id
    elif field == "order_patient":
        case["order"].patient_id = seed_data["patient2"].patient_id
    elif field == "source_hash":
        row.content_hash = "0" * 64
    elif field == "mapping_hash":
        db_session.get(AILabMapping, case["mapping"]["mapping_id"]).content_hash = "0" * 64
    elif field == "deleted_observation":
        db_session.query(LabObservation).filter_by(observation_id=case["observation"].observation_id).delete(synchronize_session=False)
    elif field == "deleted_admission":
        db_session.query(Admission).filter_by(admission_id=case["admission_id"]).delete(synchronize_session=False)
    db_session.commit()
    with pytest.raises(HTTPException):
        sources.source_current(db_session, row, allow_revoked=True)
    ordinary = await client.get(f"/api/inpatient-laboratory/sources/{row.lab_source_id}", params=scope(case), headers=doctor)
    if field == "deleted_admission":
        assert ordinary.status_code == 404
    else:
        assert ordinary.status_code == 200 and ordinary.json()["data"]["snapshot"] is None and ordinary.json()["data"]["freshness"]["state"] == "stale"
    super_headers = auth_headers(seed_data["super_admin_user"].username)
    audit = await client.get(f"/api/ai/admin/lab-sources/{row.lab_source_id}", headers=super_headers)
    assert audit.status_code == 200 and audit.json()["data"]["snapshot"] == data["snapshot"]
    assert audit.json()["data"]["eligible"] is False
    revoked = await client.post(f"/api/inpatient-laboratory/sources/{row.lab_source_id}/revoke", headers=super_headers, json={**scope(case), "expected_revision": 1, "reason": NOTE})
    assert revoked.status_code == 200 and revoked.json()["data"]["status"] == "revoked"
    assert db_session.get(InpatientLabSource, row.lab_source_id).active_observation_id is None


@pytest.mark.asyncio
async def test_mapping_revocation_is_current_governance_not_new_eligible_numeric_input(client, db_session, case, seed_data, auth_headers):
    data = await create(client, db_session, case, auth_headers(seed_data["doctor_user"].username))
    row = db_session.get(InpatientLabSource, data["lab_source_id"])
    mapping_routes.revoke_mapping(case["mapping"]["mapping_id"], mapping_routes.MappingRevoke(expected_revision=2, reason=NOTE), db=db_session, user=seed_data["super_admin_user"])
    with pytest.raises(HTTPException):
        sources.source_current(db_session, row)
    current = sources.source_current(db_session, row, allow_revoked=True)
    assert current["eligible"] is False and current["exclusion_reasons"] == ["mapping_revoked"]
    assert current["mapping_current"]["status"] == "revoked" and current["mapping_current"]["revision"] == 3
    assert current["content_hash"] == data["content_hash"] and current["snapshot"]["mapping"]["status"] == "published"
    ordinary = await client.get(f"/api/inpatient-laboratory/sources/{row.lab_source_id}", params=scope(case), headers=auth_headers(seed_data["doctor_user"].username))
    assert ordinary.json()["data"]["snapshot"] is None


def test_workflow_critical_and_sync_updates_do_not_rewrite_clinical_source(db_session, case, seed_data):
    row = sources.create_source(db_session, seed_data["doctor_user"], body(db_session, case))
    db_session.commit()
    snapshot = row.snapshot_json
    case["report"].critical_status = 4
    case["report"].critical_handling_note = "后续闭环，不更改临床值"
    case["report"].critical_handled_time = NOW
    case["order"].last_sync_time = NOW
    case["order"].integration_status = "synced"
    db_session.commit()
    assert sources.source_current(db_session, row)["eligible"] is True and row.snapshot_json == snapshot


def test_mapping_published_after_registration_is_rejected_in_creation_and_current(db_session, case, seed_data, monkeypatch):
    monkeypatch.setattr(sources, "utcnow", lambda: NOW - datetime.timedelta(seconds=1))
    with pytest.raises(HTTPException) as caught:
        sources.create_source(db_session, seed_data["doctor_user"], body(db_session, case))
    assert caught.value.status_code == 409
    monkeypatch.setattr(sources, "utcnow", lambda: NOW)
    row = sources.create_source(db_session, seed_data["doctor_user"], body(db_session, case))
    db_session.commit()
    row.registered_at = row.available_at = NOW - datetime.timedelta(seconds=1)
    snapshot = json.loads(row.snapshot_json)
    snapshot["registered_at"] = snapshot["available_at"] = sources.utc_text(row.registered_at)
    row.snapshot_json, row.content_hash = sources.canonical_json(snapshot), sources.hash_content(snapshot)
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        sources.source_current(db_session, row, allow_revoked=True)
    assert caught.value.status_code == 409


def test_stale_actor_object_cannot_create_after_current_role_loss(db_session, case, seed_data):
    actor = SimpleNamespace(user_id=seed_data["doctor_user"].user_id, user_role="doctor")
    db_session.query(User).filter_by(user_id=actor.user_id).update({"user_role": "nurse"})
    db_session.commit()
    grant(db_session, seed_data, "doctor_user")
    with pytest.raises(HTTPException) as caught:
        sources.create_source(db_session, actor, body(db_session, case))
    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_source_and_revoke_as_same_transaction(client, db_session, case, seed_data, auth_headers, monkeypatch):
    headers = auth_headers(seed_data["doctor_user"].username)
    data = await create(client, db_session, case, headers)
    monkeypatch.setattr(routes, "audit", lambda db, actor, *args: db.add(AIAuditEvent(actor_id=actor, action=None, target="synthetic-invalid-audit", detail_json="{}")))
    endpoint = f"/api/inpatient-laboratory/sources/{data['lab_source_id']}/revoke"
    failed = await client.post(endpoint, headers=headers, json={**scope(case), "expected_revision": 1, "reason": NOTE})
    assert failed.status_code == 409
    row = db_session.get(InpatientLabSource, data["lab_source_id"])
    assert row.status == "active" and row.revision == 1 and row.active_observation_id == case["observation"].observation_id
    original = case["observation"]
    fields = {column.name: getattr(original, column.name) for column in LabObservation.__table__.columns if column.name not in {"observation_id", "collected_at"}}
    another = LabObservation(**fields, observation_id="audit-" + uuid.uuid4().hex[:25], collected_at=original.collected_at + datetime.timedelta(seconds=1))
    db_session.add(another)
    db_session.commit()
    case["observation"] = another
    failed_create = await client.post("/api/inpatient-laboratory/sources", headers=headers, json=body(db_session, case))
    assert failed_create.status_code == 409
    assert db_session.query(InpatientLabSource).filter_by(observation_id=another.observation_id).count() == 0


@pytest.mark.parametrize("field,value", [("audit_status", 0), ("auditor_id", None), ("technician_id", "same_auditor"), ("order_status", 1)])
@pytest.mark.asyncio
async def test_original_review_requirements_are_checked_before_registration(field, value, client, db_session, case, seed_data, auth_headers):
    request = body(db_session, case)
    if field == "order_status":
        case["order"].status = value
    else:
        setattr(case["report"], field, case["report"].auditor_id if value == "same_auditor" else value)
    db_session.commit()
    response = await client.post("/api/inpatient-laboratory/sources", headers=auth_headers(seed_data["doctor_user"].username), json=request)
    assert response.status_code == 409
    assert db_session.query(InpatientLabSource).filter_by(observation_id=case["observation"].observation_id).count() == 0


@pytest.mark.parametrize("state", ["draft", "revoked"])
@pytest.mark.asyncio
async def test_unpublished_or_revoked_mapping_cannot_register_new_source(state, client, db_session, case, seed_data, auth_headers):
    if state == "draft":
        mapping = lab_mappings.create_mapping(
            db_session,
            seed_data["super_admin_user"],
            {
                "source_namespace": "synthetic-draft-" + uuid.uuid4().hex,
                "signature": lab_mappings.observation_signature(case["observation"]),
                "analyte_key": "creatinine",
                "evidence_reference": "synthetic review only",
                "rationale": NOTE,
            },
        )
        db_session.commit()
        changes = {"mapping_id": mapping.mapping_id, "expected_mapping_hash": mapping.content_hash}
    else:
        mapping_routes.revoke_mapping(case["mapping"]["mapping_id"], mapping_routes.MappingRevoke(expected_revision=2, reason=NOTE), db=db_session, user=seed_data["super_admin_user"])
        changes = {}
    response = await client.post("/api/inpatient-laboratory/sources", headers=auth_headers(seed_data["doctor_user"].username), json=body(db_session, case, **changes))
    assert response.status_code == 409
