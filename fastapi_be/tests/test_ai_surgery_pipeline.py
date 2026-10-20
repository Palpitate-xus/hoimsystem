"""Actual governed scenarios, durable leases, native ASGI wire and SQL proofs."""

import json
import uuid

import httpx
import pytest
from sqlalchemy import event, text

from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIFeedback, AIProvider, AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.ai.surgery_config import SurgerySettings, runtime_descriptor
from app.ai.surgery_scenario_models import AISurgeryRunResult
from app.ai.surgery_server import create_surgery_app
from app.models import SurgeryApplication, SurgerySchedule
from tests.test_ai_runtime import configure
from tests.test_ai_surgery_facts import NOTE, create
from tests.test_ai_surgery_facts import surgery_case as surgery_case
from tests.test_ai_surgery_scenarios import published_scenario, revoke_values
from tests.test_ai_surgery_snapshot import snapshot_case as snapshot_case

KEY = "synthetic-surgery-pipeline-private-key-1234567890"


class NativeSurgeryTransport(httpx.AsyncBaseTransport):
    def __init__(self, app, before=None):
        self.inner, self.before, self.requests = httpx.ASGITransport(app=app), before, []

    async def handle_async_request(self, request):
        self.requests.append(json.loads(request.content))
        if self.before is not None:
            self.before()
        return await self.inner.handle_async_request(request)


@pytest.fixture(autouse=True)
def clear_surgery_tasks(db_session):
    for model in (AIFeedback, AISurgeryRunResult, AIRun, AIFeatureConfig, AIProvider):
        db_session.query(model).delete()
    db_session.commit()


@pytest.fixture
def pipeline_case(db_session, snapshot_case, monkeypatch):
    case = snapshot_case[3]
    row = published_scenario(db_session, snapshot_case)
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SURGERY_API_KEY", KEY)
    settings = SurgerySettings(AI_PROVIDER_LOCAL_SURGERY_API_KEY=KEY)
    provider, feature = configure(db_session, case["seed"], "surgery_scheduling")
    provider.kind, provider.model = "specialist", runtime_descriptor(settings)["model_version"]
    provider.api_base, provider.api_key_env = "http://127.0.0.1:8821", "AI_PROVIDER_LOCAL_SURGERY_API_KEY"
    provider.supported_features_json, provider.timeout_seconds = encode_json(["surgery_scheduling"]), 110
    provider.allows_patient_data = True
    provider.validation_report = "Synthetic engineering only; not clinical or operational deployment validation."
    db_session.commit()
    return {**case, "scenario": row, "provider": provider, "feature": feature, "service": create_surgery_app(settings)}


def request_for(case, **changes):
    return RunRequest(feature_key="surgery_scheduling", input={"surgery_scenario_id": case["scenario"].scenario_id, "question": "SYNTH_PRIVATE_QUESTION_仅院内补充，不得加入约束或自动预订"}, **changes)


async def success(db, case):
    run = create_run(db, case["director"], request_for(case))
    transport = NativeSurgeryTransport(case["service"])
    await execute_claimed(*claim_next_run(db), transport=transport)
    db.expire_all()
    stored = db.get(AIRun, run.run_id)
    assert stored.status == "succeeded", (stored.error_code, stored.error_message)
    return stored, transport


@pytest.mark.asyncio
async def test_actual_governed_scenario_queue_native_blob_history_feedback_and_super_frozen_trace(db_session, pipeline_case, async_client, auth_headers, tmp_path):
    db, case = db_session, pipeline_case
    before = {
        model.__tablename__: [(row.application_id if model is SurgeryApplication else row.schedule_id, row.status) for row in db.query(model).all()] for model in (SurgeryApplication, SurgerySchedule)
    }
    headers = auth_headers(case["director"].username)
    response = await async_client.post("/api/ai/operational-context", headers=headers, json={"feature_key": "surgery_scheduling", "input": request_for(case).input})
    assert response.status_code == 200, response.text
    inspection = response.json()["data"]
    context = inspection["context"]
    assert context["surgery_scenario"]["snapshot"] == json.loads(case["scenario"].snapshot_json)
    assert context["surgery_source"] == json.loads(case["scenario"].projection_json)
    response = await async_client.post("/api/ai/runs", headers=headers, json=request_for(case).model_dump(mode="json"))
    assert response.status_code == 200, response.text
    receipt = response.json()["data"]
    assert receipt["status"] == "queued" and "surgery_findings" not in receipt and "result" not in receipt
    transport = NativeSurgeryTransport(case["service"])
    await execute_claimed(*claim_next_run(db), transport=transport)
    db.expire_all()
    run = db.get(AIRun, receipt["run_id"])
    assert run.status == "succeeded", (run.error_code, run.error_message)
    snapshot = json.loads(run.input_json)
    assert "surgery_source" not in snapshot["payload"]["context"] and "surgery_scenario" not in snapshot["payload"]["context"]
    assert snapshot["payload"]["tools"] == {} and len(snapshot["payload"]["evidence"]) == 1
    assert all(len(value.encode()) <= 65535 for value in (run.input_json, run.result_json, run.context_metadata_json, run.evidence_json))
    assert len(transport.requests) == 1
    packet = transport.requests[0]
    assert packet["schema_version"] == "12" and packet["store"] is False
    assert packet["input"] == {"context": {"surgery_source": context["surgery_source"]}}
    assert packet["instructions"] == snapshot["system_prompt"] + "\n\n" + snapshot["task_prompt"]
    serialized = encode_json(packet["input"])
    assert all(
        private not in serialized
        for private in (
            NOTE,
            "SYNTH_PRIVATE_QUESTION",
            "basis_note",
            '"patient_id":',
            '"doctor_id":',
            '"user_id":',
            '"department_id":',
            case["pool"].pool_id,
            case["application"].application_id,
            case["patient"].name,
        )
    )
    blob = db.get(AISurgeryRunResult, run.run_id)
    pointer = json.loads(run.result_json)
    assert pointer["schema_version"] == "surgery_result_ref_v1" and pointer["content_hash"] == blob.content_hash
    assert blob.result_bytes == len(blob.result_json.encode())
    response = await async_client.get("/api/ai/runs/" + run.run_id, headers=headers)
    assert response.status_code == 200, response.text
    detail = response.json()["data"]
    assert detail["result"] == json.loads(blob.result_json)
    assert detail["result"]["surgery_analysis"]["solve_status"] == "optimal_proven"
    assert detail["surgery_findings"]["surgery_binding"] == context["surgery_binding"]
    assert detail["surgery_findings"]["surgery_source"] == context["surgery_source"]
    response = await async_client.get(
        "/api/ai/runs", headers=headers, params={"feature_key": "surgery_scheduling", "surgery_pool_id": case["pool"].pool_id, "surgery_scenario_id": case["scenario"].scenario_id}
    )
    assert response.status_code == 200 and [row["run_id"] for row in response.json()["data"]] == [run.run_id], response.text
    response = await async_client.post("/api/ai/runs/" + run.run_id + "/feedback", headers=headers, json={"outcome": "modified", "comment": "合成排程工程核对，不等于实际临床或运营验证"})
    assert response.status_code == 200, response.text
    response = await async_client.get("/api/ai/admin/runs/" + run.run_id, headers=auth_headers(case["super"].username))
    assert response.status_code == 200, response.text
    trace = response.json()["data"]
    assert trace["frozen_request"]["payload"]["context"]["surgery_source"] == context["surgery_source"]
    assert trace["frozen_request"]["payload"]["context"]["surgery_scenario"]["frozen_task_view"] is True
    assert all(value is False for key, value in trace["frozen_request"]["payload"]["context"]["surgery_scenario"].items() if key in {"can_record", "can_review", "can_revoke", "automatic_booking"})
    after = {
        model.__tablename__: [(row.application_id if model is SurgeryApplication else row.schedule_id, row.status) for row in db.query(model).all()] for model in (SurgeryApplication, SurgerySchedule)
    }
    assert before == after
    (tmp_path / "actual-surgery-pipeline-ui.json").write_text(json.dumps({"inspection": inspection, "receipt": receipt, "run_detail": detail, "super_trace": trace}, ensure_ascii=False, indent=2))


def change_current(db, case, kind):
    from app.ai import surgery_scenarios as scenarios
    from app.models import Doctor

    if kind == "scenario":
        scenarios.revoke_scenario(db, case["super"], case["scenario"].scenario_id, revoke_values(case["scenario"]))
    elif kind == "new_fact":
        create(db, case, "duration_observation")
    elif kind == "role":
        case["director"].user_role = "nurse"
    elif kind == "scope":
        db.query(Doctor).filter_by(doctor_id=case["director_doctor"].doctor_id).update({"department_id": case["foreign"].department_id})
    elif kind == "care":
        case["admission"].department_id = case["foreign"].department_id
    elif kind == "config":
        case["feature"].revision += 1
        case["provider"].revision += 1
    else:
        raise AssertionError(kind)
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
@pytest.mark.parametrize("kind", ["scenario", "new_fact", "role", "scope", "care"])
async def test_complete_sources_and_authority_are_rechecked_at_each_phase(phase, kind, db_session, pipeline_case, async_client, auth_headers):
    db, case = db_session, pipeline_case
    headers = auth_headers(case["director"].username)
    if phase == "history":
        run, wire = await success(db, case)
        change_current(db, case, kind)
        result = await async_client.get("/api/ai/runs/" + run.run_id, headers=headers)
        assert result.status_code in {403, 409}, result.text
        feedback = await async_client.post("/api/ai/runs/" + run.run_id + "/feedback", headers=headers, json={"outcome": "accepted", "comment": "不得用旧来源继续复核"})
        assert feedback.status_code in {403, 409}
        trace = await async_client.get("/api/ai/admin/runs/" + run.run_id, headers=auth_headers(case["super"].username))
        assert trace.status_code == 200, trace.text
        assert trace.json()["data"]["result"] == json.loads(db.get(AISurgeryRunResult, run.run_id).result_json)
        assert trace.json()["data"]["surgery_findings"]["surgery_scenario"]["frozen_task_view"] is True
        assert db.query(AIFeedback).filter_by(run_id=run.run_id).count() == 0
    else:
        run = create_run(db, case["director"], request_for(case))
        if phase == "queued":
            change_current(db, case, kind)
        wire = NativeSurgeryTransport(case["service"], before=(lambda: change_current(db, case, kind)) if phase == "inflight" else None)
        await execute_claimed(*claim_next_run(db), transport=wire)
        db.expire_all()
        stored = db.get(AIRun, run.run_id)
        assert stored.status == "failed" and stored.result_json == "{}", (stored.status, stored.error_code)
        assert db.get(AISurgeryRunResult, run.run_id) is None
        assert len(wire.requests) == int(phase == "inflight")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["cancel", "lease", "config"])
async def test_inflight_receipt_or_configuration_change_cannot_accept_old_proof(kind, db_session, pipeline_case):
    db, case = db_session, pipeline_case
    run = create_run(db, case["director"], request_for(case))
    original_lease = None

    def changed():
        nonlocal original_lease
        db.expire_all()
        current = db.get(AIRun, run.run_id)
        original_lease = current.lease_token
        if kind == "cancel":
            current.status = "cancelled"
        elif kind == "lease":
            current.lease_token = str(uuid.uuid4())
        else:
            change_current(db, case, "config")
        db.commit()

    wire = NativeSurgeryTransport(case["service"], before=changed)
    await execute_claimed(*claim_next_run(db), transport=wire)
    db.expire_all()
    current = db.get(AIRun, run.run_id)
    assert current.result_json == "{}" and db.get(AISurgeryRunResult, run.run_id) is None
    assert current.status == ("cancelled" if kind == "cancel" else "running" if kind == "lease" else "failed")
    if kind == "lease":
        assert current.lease_token != original_lease


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["sql_audit_failure", "audit_role_change", "audit_parent_change"])
async def test_real_acceptance_audit_sql_and_postwrite_authority_failure_roll_back_complete_acceptance(fault, db_session, pipeline_case):
    db, case = db_session, pipeline_case
    run = create_run(db, case["director"], request_for(case))
    original_name = case["application"].surgery_name
    triggered = []

    def audit_inserted(connection, cursor, statement, parameters, context, executemany):
        if not statement.lower().startswith("insert into hoimsystem_ai_audit_event") or triggered:
            return
        if not any(values.get("action") == "run.surgery_result.accept" for values in context.compiled_parameters):
            return
        triggered.append(fault)
        if fault == "sql_audit_failure":
            cursor.execute("INSERT INTO hoimsystem_ai_audit_event(actor_id,action,target,detail_json,create_time) VALUES(1,NULL,'synthetic-failure','{}','2026-10-20 12:00:00')")
        elif fault == "audit_role_change":
            connection.execute(text("UPDATE hoimsystem_users SET user_role='nurse' WHERE user_id=:id"), {"id": case["director"].user_id})
        else:
            connection.execute(text("UPDATE hoimsystem_surgery_application SET surgery_name='synthetic-parent-changed' WHERE application_id=:id"), {"id": case["application"].application_id})

    engine = db.get_bind()
    event.listen(engine, "after_cursor_execute", audit_inserted)
    try:
        await execute_claimed(*claim_next_run(db), transport=NativeSurgeryTransport(case["service"]))
    finally:
        event.remove(engine, "after_cursor_execute", audit_inserted)
    db.expire_all()
    current = db.get(AIRun, run.run_id)
    assert triggered == [fault]
    assert (current.status, current.error_code, current.result_json) == ("failed", "RESULT_STORAGE_ERROR", "{}")
    assert db.get(AISurgeryRunResult, run.run_id) is None
    assert db.query(AIAuditEvent).filter_by(target=run.run_id, action="run.surgery_result.accept").count() == 0
    assert case["director"].user_role == "director" and case["application"].surgery_name == original_name


@pytest.mark.asyncio
async def test_pseudonymous_case_facts_still_require_explicit_provider_patient_data_approval(db_session, pipeline_case, async_client, auth_headers):
    case = pipeline_case
    case["provider"].allows_patient_data = False
    db_session.commit()
    response = await async_client.post("/api/ai/runs", headers=auth_headers(case["director"].username), json=request_for(case).model_dump(mode="json"))
    assert response.status_code == 409 and "患者资料" in response.text
    assert db_session.query(AIRun).count() == 0 and db_session.query(AISurgeryRunResult).count() == 0
