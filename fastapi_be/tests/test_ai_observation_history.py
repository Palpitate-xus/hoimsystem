"""Real queue and result APIs recheck every frozen admission-window source."""

import json

import httpx
import pytest
from sqlalchemy import delete

from app.ai.governance import encode_json
from app.ai.models import AIPatientGrant, AIRun
from app.ai.observation_windows import iso
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Admission, Department, Doctor
from tests.test_ai_observation_windows import create, point
from tests.test_ai_observation_windows import observation_case as observation_case
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure


def configure_risk(db, seed, key="deterioration_risk"):
    provider, feature = configure(db, seed, key)
    provider.kind = "specialist"
    provider.supported_features_json = encode_json([key])
    provider.validation_report = "Synthetic protocol fixture only; no medical or population validation."
    db.commit()
    return provider, feature


def transport_for(sent, before=None):
    def handle(request):
        task = json.loads(request.content)
        sent.append(task)
        if before:
            before()
        source = task["input"]["context"]["observation_window"]["source_id"]
        return httpx.Response(
            200,
            json={
                "schema_version": "1",
                "feature_key": task["feature_key"],
                "model_version": task["model"],
                "applicable": True,
                "result": {
                    "summary": "Synthetic window protocol, no predicted clinical risk.",
                    "sections": [{"title": "Original bounded observations", "content": "Only synthetic original records; no diagnosis, score or urine aggregation.", "source_ids": [source]}],
                    "warnings": [],
                    "missing_data": [],
                },
            },
        )

    return httpx.MockTransport(handle)


def request_for(case, row, key="deterioration_risk"):
    return RunRequest(
        feature_key=key, patient_id=case["patient_id"], encounter_ref=case["admission"].admission_id, input={"observation_window_id": row.window_id, "question": "仅复核所选冻结窗，不能补造风险"}
    )


def mutate(db, case, collection, change):
    row = case[collection]
    if change == "delete":
        db.delete(row)
    elif change == "reassign":
        row.admission_id = case["other"].admission_id
    elif change == "content":
        payload = json.loads(row.payload_json)
        payload["note"] = "Changed original source after freeze"
        row.payload_json = encode_json(payload)
    elif change == "revoke":
        row.status, row.revision = "revoked", 2
        row.revoked_at, row.revoked_by, row.revoke_reason = case["now"], case["doctor"].user_id, "Original source revoked"
    elif change == "member":
        point(db, case)
    else:
        raise AssertionError(change)
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["deterioration_risk", "sepsis_risk", "aki_risk"])
async def test_actual_source_queue_specialist_and_read_are_only_window_bound(key, async_client, auth_headers, seed_data, db_session, observation_case):
    case = observation_case
    configure_risk(db_session, seed_data, key)
    window = create(db_session, case)
    run = create_run(db_session, case["doctor"], request_for(case, window, key))
    sent = []
    await execute_claimed(*claim_next_run(db_session), transport=transport_for(sent))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", stored.error_message
    assert len(sent) == 1 and sent[0]["engine"] == "prediction"
    payload = sent[0]["input"]
    assert set(payload["context"]) == {"scope", "observation_window", "selected_sources", "missing_data", "snapshot_time"}
    assert "laboratory_trends" not in payload["tools"] and "critical_value_workflow" not in payload["tools"]
    assert "latest_vitals" not in encode_json(payload) and "reviewed_observations" not in encode_json(payload)
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert response.status_code == 200
    assert response.json()["data"]["observation_findings"] == payload["context"]["observation_window"]
    assert payload["context"]["observation_window"]["as_of"] == iso(case["as_of"])


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
@pytest.mark.parametrize("collection", ["point", "urine"])
@pytest.mark.parametrize("change", ["delete", "reassign", "content", "revoke"])
async def test_every_original_change_stops_queue_discards_inflight_and_blocks_ordinary_history(phase, collection, change, async_client, auth_headers, seed_data, db_session, observation_case):
    case = observation_case
    configure_risk(db_session, seed_data)
    window = create(db_session, case)
    run = create_run(db_session, case["doctor"], request_for(case, window))
    claim = claim_next_run(db_session)
    sent = []
    if phase == "queued":
        mutate(db_session, case, collection, change)
    await execute_claimed(*claim, transport=transport_for(sent, before=(lambda: mutate(db_session, case, collection, change)) if phase == "inflight" else None))
    db_session.expire_all()
    saved = db_session.get(AIRun, run.run_id)
    if phase != "history":
        assert saved.status == "failed" and json.loads(saved.result_json) == {}
        assert len(sent) == (0 if phase == "queued" else 1)
        return
    assert saved.status == "succeeded"
    frozen = (saved.input_json, saved.result_json, saved.context_digest, saved.evidence_json)
    path = "/api/ai/runs/" + run.run_id
    assert (await async_client.get(path, headers=auth_headers(case["doctor"].username))).status_code == 200
    mutate(db_session, case, collection, change)
    assert (await async_client.get(path, headers=auth_headers(case["doctor"].username))).status_code == 403
    supers = await async_client.get(path, headers=auth_headers(seed_data["super_admin_user"].username))
    assert supers.status_code == 200
    db_session.expire_all()
    saved = db_session.get(AIRun, run.run_id)
    assert (saved.input_json, saved.result_json, saved.context_digest, saved.evidence_json) == frozen
    window_detail = await async_client.get(
        f"/api/ai/observation-windows/{window.window_id}", headers=auth_headers(case["doctor"].username), params={"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id}
    )
    assert window_detail.status_code == 200 and window_detail.json()["data"]["snapshot"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
@pytest.mark.parametrize("change", ["member", "window_revoke", "admission_reassign"])
async def test_member_set_window_governance_and_parent_changes_are_bound(phase, change, async_client, auth_headers, seed_data, db_session, observation_case):
    case = observation_case
    configure_risk(db_session, seed_data)
    window = create(db_session, case)
    run = create_run(db_session, case["doctor"], request_for(case, window))
    claim = claim_next_run(db_session)

    def change_source():
        if change == "member":
            point(db_session, case)
        elif change == "admission_reassign":
            case["admission"].patient_id = seed_data["patient2"].patient_id
        else:
            window.status, window.revision = "revoked", 2
            window.revoked_at, window.revoked_by, window.revoke_reason = case["now"], case["doctor"].user_id, "Synthetic window revoke"
        db_session.commit()

    if phase == "queued":
        change_source()
    sent = []
    await execute_claimed(*claim, transport=transport_for(sent, before=change_source if phase == "inflight" else None))
    db_session.expire_all()
    saved = db_session.get(AIRun, run.run_id)
    if phase != "history":
        assert saved.status == "failed" and len(sent) == (0 if phase == "queued" else 1)
    else:
        assert saved.status == "succeeded"
        frozen = (saved.input_json, saved.result_json, saved.context_digest)
        change_source()
        path = "/api/ai/runs/" + run.run_id
        assert (await async_client.get(path, headers=auth_headers(case["doctor"].username))).status_code == 403
        assert (await async_client.get(path, headers=auth_headers(seed_data["super_admin_user"].username))).status_code == 200
        db_session.expire_all()
        saved = db_session.get(AIRun, run.run_id)
        assert (saved.input_json, saved.result_json, saved.context_digest) == frozen


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["grant", "director"])
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
async def test_current_selected_admission_grant_or_department_must_still_exist(phase, kind, async_client, auth_headers, seed_data, db_session, observation_case):
    import datetime

    case = observation_case
    configure_risk(db_session, seed_data)
    if kind == "grant":
        user = seed_data["nurse_user"]
        permission = AIPatientGrant(
            patient_id=case["patient_id"],
            user_id=user.user_id,
            category="inpatient",
            created_by=seed_data["super_admin_user"].user_id,
            reason="Synthetic explicit current care grant",
            expires_at=case["now"] + datetime.timedelta(hours=2),
            revoked=0,
        )
        db_session.add(permission)
    else:
        user = seed_data["director_user"]
        permission = db_session.query(Doctor).filter_by(user_id=user.user_id).first()
        if permission is None:
            permission = Doctor(user_id=user.user_id, department_id=case["admission"].department_id)
            db_session.add(permission)
        permission.department_id = case["admission"].department_id
    db_session.commit()
    window = create(db_session, case, user=user)
    run = create_run(db_session, user, request_for(case, window))
    await execute_claimed(*claim_next_run(db_session), transport=transport_for([]))

    def withdraw_access():
        if kind == "grant":
            permission.revoked = 1
        else:
            department = Department(name="Synthetic transferred department")
            db_session.add(department)
            db_session.flush()
            # seed_data adds a separate real Doctor row for each invocation;
            # remove every department relation for this same fixture identity.
            for doctor in db_session.query(Doctor).filter_by(user_id=user.user_id).all():
                doctor.department_id = department.department_id
        db_session.commit()

    if phase == "history":
        withdraw_access()
        path = "/api/ai/runs/" + run.run_id
        assert (await async_client.get(path, headers=auth_headers(user.username))).status_code == 403
        assert (await async_client.get(path, headers=auth_headers(seed_data["super_admin_user"].username))).status_code == 200
    else:
        # A second original queued task exercises the same access loss before
        # sending or between the actual provider call and receipt persistence.
        pending = create_run(db_session, user, request_for(case, window))
        claim = claim_next_run(db_session)
        if phase == "queued":
            withdraw_access()
        sent = []
        await execute_claimed(*claim, transport=transport_for(sent, before=withdraw_access if phase == "inflight" else None))
        db_session.expire_all()
        saved = db_session.get(AIRun, pending.run_id)
        assert saved.status == "failed" and len(sent) == (0 if phase == "queued" else 1)


@pytest.mark.asyncio
async def test_new_late_recording_does_not_invalidate_frozen_cutoff_or_expose_its_existence(async_client, auth_headers, seed_data, db_session, observation_case):
    case = observation_case
    configure_risk(db_session, seed_data)
    window = create(db_session, case)
    run = create_run(db_session, case["doctor"], request_for(case, window))
    late = point(db_session, case, recorded=case["now"])
    db_session.commit()
    sent = []
    await execute_claimed(*claim_next_run(db_session), transport=transport_for(sent))
    db_session.expire_all()
    assert db_session.get(AIRun, run.run_id).status == "succeeded"
    assert late.observation_id not in encode_json(sent)
    assert (await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(case["doctor"].username))).status_code == 200


@pytest.mark.asyncio
async def test_super_frozen_audit_survives_original_admission_deletion_but_cannot_execute_again(async_client, auth_headers, seed_data, db_session, observation_case):
    case = observation_case
    configure_risk(db_session, seed_data)
    window = create(db_session, case)
    run = create_run(db_session, case["doctor"], request_for(case, window))
    await execute_claimed(*claim_next_run(db_session), transport=transport_for([]))
    db_session.expire_all()
    saved = db_session.get(AIRun, run.run_id)
    assert saved.status == "succeeded"
    frozen = (saved.input_json, saved.result_json, saved.context_digest)
    db_session.execute(delete(Admission).where(Admission.admission_id == case["admission"].admission_id))
    db_session.commit()
    path = "/api/ai/runs/" + run.run_id
    assert (await async_client.get(path, headers=auth_headers(case["doctor"].username))).status_code == 403
    assert (await async_client.get(path, headers=auth_headers(seed_data["super_admin_user"].username))).status_code == 200
    audit = await async_client.get(f"/api/ai/admin/observation-windows/{window.window_id}", headers=auth_headers(seed_data["super_admin_user"].username))
    assert audit.status_code == 200 and audit.json()["data"]["snapshot"] is not None
    db_session.expire_all()
    saved = db_session.get(AIRun, run.run_id)
    assert (saved.input_json, saved.result_json, saved.context_digest) == frozen
