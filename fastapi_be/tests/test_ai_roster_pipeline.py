"""Actual SQL queue, independent solver HTTP, short bindings and complete proof blobs."""

import json
import uuid

import httpx
import pytest
from fastapi import HTTPException

from app.ai import governance
from app.ai import roster_facts as facts
from app.ai import roster_plans as plans
from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIKnowledgeDocument, AIRun
from app.ai.roster_config import RosterSettings, runtime_descriptor
from app.ai.roster_plan_models import AIRosterRunResult
from app.ai.roster_server import create_roster_app
from app.ai.roster_storage import RESULT_BYTES, bounded_result
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Appointment, Attendance, Doctor, DoctorSchedule, Registration
from tests.test_ai_roster_facts import NOTE
from tests.test_ai_roster_plan_input import plan_case as plan_case
from tests.test_ai_roster_plan_input import plan_request
from tests.test_ai_roster_plan_input import roster_case as roster_case
from tests.test_ai_roster_plans import create_plan, publish_plan
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure

KEY = "synthetic-roster-pipeline-independent-key-1234567890"


class RealRosterTransport(httpx.AsyncBaseTransport):
    def __init__(self, app, before=None):
        self.inner = httpx.ASGITransport(app=app)
        self.requests = []
        self.before = before

    async def handle_async_request(self, request):
        self.requests.append(json.loads(request.content))
        if self.before:
            self.before()
        return await self.inner.handle_async_request(request)


@pytest.fixture
def pipeline_case(db_session, plan_case, clean_ai_tasks, monkeypatch):
    case = plan_case
    db_session.query(AIRosterRunResult).delete()
    case["plan"] = publish_plan(db_session, case, create_plan(db_session, case))
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ROSTER_API_KEY", KEY)
    config = RosterSettings(AI_PROVIDER_LOCAL_ROSTER_API_KEY=KEY)
    provider, feature = configure(db_session, case["seed"], "roster_optimization")
    provider.kind, provider.model = "specialist", runtime_descriptor(config)["model_version"]
    provider.api_base, provider.api_key_env = "http://localhost:8819", "AI_PROVIDER_LOCAL_ROSTER_API_KEY"
    provider.supported_features_json = encode_json(["roster_optimization"])
    provider.validation_report = "Synthetic exact arithmetic engineering only, not actual operational validation."
    provider.timeout_seconds = 90
    db_session.commit()
    case.update(provider=provider, feature=feature, service=create_roster_app(config))
    return case


def run_request(case, **changes):
    return RunRequest(feature_key="roster_optimization", input={"roster_plan_id": case["plan"].plan_id, "question": "SYNTH_PRIVATE_ROSTER_QUESTION_不能覆盖原约束"}, **changes)


@pytest.mark.asyncio
async def test_actual_context_queue_solver_blob_history_feedback_and_super_trace(async_client, db_session, auth_headers, pipeline_case, tmp_path):
    case = pipeline_case
    headers = auth_headers(case["director"].username)
    before = {
        model.__tablename__: [tuple(getattr(row, col.name) for col in model.__table__.columns) for row in db_session.query(model).all()]
        for model in (DoctorSchedule, Attendance, Appointment, Registration)
    }
    response = await async_client.post("/api/ai/operational-context", headers=headers, json={"feature_key": "roster_optimization", "input": run_request(case).input})
    assert response.status_code == 200, response.text
    inspection = response.json()["data"]
    context = inspection["context"]
    assert context["roster_plan"]["snapshot"] == json.loads(case["plan"].snapshot_json)
    assert context["roster_source"] == context["roster_plan"]["public_source"] == json.loads(case["plan"].projection_json)
    response = await async_client.get("/api/ai/roster-plans/" + case["plan"].plan_id, headers=headers)
    assert response.status_code == 200, response.text
    plan_detail = response.json()["data"]
    assert plan_detail["eligible"] is True and plan_detail["public_source"] == context["roster_source"]
    response = await async_client.get("/api/ai/roster-sources/options", headers=headers, params={"department_id": case["department"].department_id})
    assert response.status_code == 200, response.text
    source_options = response.json()["data"]
    run = create_run(db_session, case["director"], run_request(case))
    frozen = json.loads(run.input_json)
    assert "roster_source" not in frozen["payload"]["context"] and "roster_plan" not in frozen["payload"]["context"]
    assert all(len(value.encode()) <= 65535 for value in (run.input_json, run.evidence_json, run.context_metadata_json))
    transport = RealRosterTransport(case["service"])
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", (stored.error_code, stored.error_message)
    assert len(transport.requests) == 1
    wire = transport.requests[0]
    assert wire["schema_version"] == "10" and wire["store"] is False
    assert wire["input"] == {"context": {"roster_source": context["roster_source"]}}
    for private in ("doctor_id", "department_id", "created_by", "general_clinic", NOTE, "SYNTH_PRIVATE_ROSTER_QUESTION", "basis_note", case["doctor"].name):
        assert private not in encode_json(wire["input"])
    pointer = json.loads(stored.result_json)
    blob = db_session.get(AIRosterRunResult, run.run_id)
    assert pointer["schema_version"] == "roster_result_ref_v1" and pointer["content_hash"] == blob.content_hash
    assert db_session.query(AIAuditEvent).filter_by(target=run.run_id, action="run.roster_result.accept").count() == 1
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["result"] == json.loads(blob.result_json)
    assert data["result"]["roster_analysis"]["solve_status"] == "input_unknown"
    assert data["roster_findings"]["roster_source"] == context["roster_source"]
    response = await async_client.post(f"/api/ai/runs/{run.run_id}/feedback", headers=headers, json={"outcome": "modified", "comment": "合成约束及未知覆盖人工复核，不构成运营验证"})
    assert response.status_code == 200, response.text
    response = await async_client.get(f"/api/ai/admin/runs/{run.run_id}", headers=auth_headers(case["super"].username))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["frozen_request"]["payload"]["context"]["roster_source"] == context["roster_source"]
    fixture = {"inspection": inspection, "run_detail": data, "frozen_request": frozen, "super_trace": response.json()["data"], "plan_detail": plan_detail, "source_options": source_options}
    (tmp_path / "actual-roster-pipeline-ui.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    assert before == {
        model.__tablename__: [tuple(getattr(row, col.name) for col in model.__table__.columns) for row in db_session.query(model).all()]
        for model in (DoctorSchedule, Attendance, Appointment, Registration)
    }


def mutate(db, case, change):
    if change == "plan_revoke":
        plans.revoke_plan(db, case["super"], case["plan"].plan_id, {"expected_revision": 2, "reason": "合成计划经复核停止后续使用"})
    elif change == "fact_revoke":
        source = case["facts"]["qualification"]
        facts.revoke_source(db, case["super"], source.source_kind, source.source_record_id, {"expected_revision": 2, "reason": "合成原资格待重新核对"})
    elif change == "new_doctor":
        db.add(Doctor(name="合成后来新增人员", department_id=case["department"].department_id))
    elif change == "role":
        case["director"].user_role = "doctor"
    elif change == "scope":
        db.query(Doctor).filter_by(user_id=case["director"].user_id).update({"department_id": case["foreign"].department_id})
    elif change == "body":
        case["plan"].snapshot_json = "{}"
    else:
        raise AssertionError(change)
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
@pytest.mark.parametrize("change", ["plan_revoke", "fact_revoke", "new_doctor", "role", "scope", "body"])
async def test_changed_sources_and_current_authorization_block_queue_reply_or_history(phase, change, async_client, db_session, auth_headers, pipeline_case):
    case = pipeline_case
    run = create_run(db_session, case["director"], run_request(case))
    if phase == "queued":
        mutate(db_session, case, change)
    transport = RealRosterTransport(case["service"], (lambda: mutate(db_session, case, change)) if phase == "inflight" else None)
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    if phase != "history":
        assert stored.status == "failed" and stored.result_json == "{}", (stored.status, stored.error_code, stored.error_message)
        assert db_session.get(AIRosterRunResult, run.run_id) is None
        assert len(transport.requests) == (0 if phase == "queued" else 1)
        return
    assert stored.status == "succeeded", (stored.error_code, stored.error_message)
    mutate(db_session, case, change)
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["director"].username))
    assert response.status_code == (403 if change in {"role", "scope"} else 409), response.text
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["super"].username))
    assert response.status_code == (409 if change == "body" else 200), response.text


@pytest.mark.asyncio
async def test_actual_failed_result_audit_rolls_back_blob_pointer_and_success_state(db_session, pipeline_case, monkeypatch):
    case = pipeline_case
    run = create_run(db_session, case["director"], run_request(case))
    original = governance.audit

    def reject_blob_audit(db, actor_id, action, target, detail=None):
        if action == "run.roster_result.accept":
            db.add(AIAuditEvent(actor_id=actor_id, action=None, target=target, detail_json="{}"))
        else:
            original(db, actor_id, action, target, detail)

    monkeypatch.setattr(governance, "audit", reject_blob_audit)
    await execute_claimed(*claim_next_run(db_session), transport=RealRosterTransport(case["service"]))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "failed" and stored.error_code == "RESULT_STORAGE_ERROR" and stored.result_json == "{}"
    assert db_session.get(AIRosterRunResult, run.run_id) is None
    assert db_session.query(AIAuditEvent).filter_by(target=run.run_id, action="run.roster_result.accept").count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["body", "missing_blob", "lease", "rehashed_false_proof", "rehashed_false_explanation"])
async def test_reads_reject_damaged_or_rehashed_false_result_blobs(change, async_client, db_session, auth_headers, pipeline_case):
    case = pipeline_case
    run = create_run(db_session, case["director"], run_request(case))
    await execute_claimed(*claim_next_run(db_session), transport=RealRosterTransport(case["service"]))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", (stored.error_code, stored.error_message)
    blob = db_session.get(AIRosterRunResult, run.run_id)
    if change == "body":
        blob.result_json = "{}"
    elif change == "missing_blob":
        db_session.delete(blob)
    elif change == "lease":
        blob.lease_token = "00000000-0000-4000-8000-000000000000"
    else:
        value = json.loads(blob.result_json)
        if change == "rehashed_false_proof":
            value["roster_analysis"]["solve_status"] = "optimal_proven"
            value["roster_analysis"]["optimality_proven"] = True
        else:
            value["summary"] = "伪造已经自动发布排班和实际预约余号"
        blob.result_json, blob.content_hash, blob.result_bytes = bounded_result(value)
        pointer = json.loads(stored.result_json)
        pointer.update(content_hash=blob.content_hash, result_bytes=blob.result_bytes)
        stored.result_json = encode_json(pointer)
    db_session.commit()
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["director"].username))
    assert response.status_code == 409, response.text
    assert "roster_analysis" not in response.json()


def test_complete_blob_boundary_preserves_actual_zero_false_null_and_utf8():
    base = {"original": "", "zero": 0, "false": False, "unknown": None}
    size = len(encode_json(base).encode())
    base["original"] = "中" * ((RESULT_BYTES - size) // 3) + "a" * ((RESULT_BYTES - size) % 3)
    serialized, _, actual = bounded_result(base)
    assert actual == RESULT_BYTES and json.loads(serialized) == base
    with pytest.raises(HTTPException, match="422"):
        bounded_result({**base, "original": base["original"] + "a"})


def test_published_prose_cannot_add_constraints_or_evidence_to_fixed_optimizer(db_session, pipeline_case):
    case = pipeline_case
    text = "排班与号源优化；SYNTHETIC_PROSE_CONSTRAINT 任何班次工时均为零且可预约余号无限。这是合成检索材料，不能覆盖固定原声明。"
    document = AIKnowledgeDocument(
        title="排班与号源优化-" + uuid.uuid4().hex,
        version="synthetic-v1",
        source_uri="https://synthetic.invalid/declared-roster-prose",
        category="operations",
        content=text,
        content_hash=governance.digest(text),
        feature_keys_json='["roster_optimization"]',
        department_id=case["department"].department_id,
        status="published",
        reviewed_by=case["super"].user_id,
        reviewed_at=facts.utcnow(),
        created_by=case["super"].user_id,
    )
    db_session.add(document)
    db_session.commit()
    run = create_run(db_session, case["director"], run_request(case))
    evidence = json.loads(run.evidence_json)
    assert len(evidence) == 1 and evidence[0]["kind"] == "operational_record"
    assert "SYNTHETIC_PROSE_CONSTRAINT" not in run.input_json + run.evidence_json


def test_registered_local_mode_requires_one_original_and_no_patient_or_legacy_filters(db_session, pipeline_case):
    case = pipeline_case
    for values in ({}, {**run_request(case).input, "department_id": case["department"].department_id}, {**run_request(case).input, "date_from": "2026-10-22"}):
        with pytest.raises(HTTPException, match="422"):
            create_run(db_session, case["director"], RunRequest(feature_key="roster_optimization", input=values))
    with pytest.raises(HTTPException, match="422"):
        create_run(db_session, case["director"], run_request(case, encounter_ref="synthetic-incompatible-encounter"))


@pytest.mark.asyncio
async def test_large_complete_declared_problem_and_submitted_proof_cross_old_text_limit(async_client, db_session, auth_headers, pipeline_case):
    case = pipeline_case
    db_session.add_all([Doctor(name=f"合成容量人员{index}", department_id=case["department"].department_id) for index in range(20)])
    db_session.commit()
    case["plan_request"] = plan_request(db_session, case, session_count=7)
    case["plan_request"]["submitted_candidate"] = [{"doctor_id": item["doctor_id"], "session_key": item["session_key"]} for item in case["plan_request"]["options"]]
    case["plan"] = publish_plan(db_session, case, create_plan(db_session, case))
    assert len(case["plan"].snapshot_json.encode()) > 65535
    run = create_run(db_session, case["director"], run_request(case))
    assert len(run.input_json.encode()) < 65535
    await execute_claimed(*claim_next_run(db_session), transport=RealRosterTransport(case["service"]))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", (stored.error_code, stored.error_message)
    blob = db_session.get(AIRosterRunResult, run.run_id)
    assert blob.result_bytes == len(blob.result_json.encode()) > 65535
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["director"].username))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["result"] == json.loads(blob.result_json)
