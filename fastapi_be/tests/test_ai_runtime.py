"""End-to-end queue and inference tests against real authorization and evidence services."""

import datetime
import json
import uuid

import httpx
import pytest

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import digest, encode_json
from app.ai.models import AIFeatureConfig, AIFeedback, AIKnowledgeDocument, AIPatientGrant, AIProvider, AIRun, utcnow
from app.ai.runtime import claim_next_run, create_run, execute_claimed, expire_interrupted_runs
from app.ai.schemas import RunRequest
from app.models import MedicalRecord, Patient, Prescription, PrescriptionReviewRule, User


@pytest.fixture(autouse=True)
def clean_ai_tasks(db_session):
    db_session.query(AIFeedback).delete()
    db_session.query(AIRun).delete()
    db_session.query(AIFeatureConfig).delete()
    db_session.query(AIProvider).delete()
    db_session.commit()


def configure(db, seed_data, key="patient_summary"):
    provider = AIProvider(
        name="runtime-" + str(uuid.uuid4()),
        api_base="http://localhost:11434/v1",
        kind="chat",
        model="isolated-test-model",
        enabled=1,
        allows_patient_data=1,
        created_by=seed_data["super_admin_user"].user_id,
    )
    db.add(provider)
    db.flush()
    config = AIFeatureConfig(
        feature_key=key,
        provider_id=provider.provider_id,
        enabled=1,
        allowed_roles_json=encode_json(FEATURE_BY_KEY[key].default_roles),
        validation_status="validated",
        validation_note="隔离测试配置，不用于临床启用",
        revision=1,
        updated_by=seed_data["super_admin_user"].user_id,
    )
    db.add(config)
    db.commit()
    return provider, config


def successful_transport(requests):
    def handle(request):
        payload = json.loads(request.content)
        task = json.loads(payload["messages"][-1]["content"])
        requests.append(task)
        source = next((item["source_id"] for item in task["evidence"] if item.get("kind") == "knowledge"), task["evidence"][0]["source_id"] if task["evidence"] else None)
        result = {"summary": "测试资料摘要", "sections": [{"title": "可核查事实", "content": "此输出仅用于隔离测试。", "source_ids": [source] if source else []}], "warnings": [], "missing_data": []}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}})

    return httpx.MockTransport(handle)


@pytest.mark.asyncio
async def test_queue_worker_result_and_feedback_do_not_mutate_business_records(async_client, seed_data, auth_headers, db_session):
    configure(db_session, seed_data)
    headers = auth_headers(seed_data["doctor_user"].username)
    before = (db_session.query(MedicalRecord).count(), db_session.query(Prescription).count())
    response = await async_client.post("/api/ai/runs", headers=headers, json={"feature_key": "patient_summary", "patient_id": seed_data["patient"].patient_id, "input": {"question": "整理患者资料"}})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "queued"
    run_id = response.json()["data"]["run_id"]
    claim = claim_next_run(db_session)
    assert claim[0] == run_id
    assert claim_next_run(db_session) is None
    requests = []
    await execute_claimed(*claim, transport=successful_transport(requests))
    detail = await async_client.get(f"/api/ai/runs/{run_id}", headers=headers)
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["status"] == "succeeded", data
    assert data["input_tokens"] == 5
    assert data["result"]["summary"] == "测试资料摘要"
    assert "task_prompt" not in detail.text
    assert seed_data["patient"].identity not in encode_json(requests)
    denied = await async_client.get(f"/api/ai/runs/{run_id}", headers=auth_headers(seed_data["patient_user"].username))
    assert denied.status_code == 403
    feedback = await async_client.post(f"/api/ai/runs/{run_id}/feedback", headers=headers, json={"outcome": "accepted", "comment": "测试确认，未执行业务写入"})
    assert feedback.status_code == 200
    assert (db_session.query(MedicalRecord).count(), db_session.query(Prescription).count()) == before


@pytest.mark.asyncio
async def test_catalog_and_context_do_not_expand_patient_role(async_client, seed_data, auth_headers):
    headers = auth_headers(seed_data["patient_user"].username)
    features = await async_client.get("/api/ai/features", headers=headers)
    keys = {item["key"] for item in features.json()["data"]}
    assert "patient_report_explanation" in keys
    assert "treatment_pathway" not in keys
    denied = await async_client.get("/api/ai/context", headers=headers, params={"feature_key": "patient_report_explanation", "patient_id": seed_data["patient2"].patient_id})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_revoked_grant_prevents_model_call_after_queuing(seed_data, db_session):
    configure(db_session, seed_data)
    user = User(username="ai-runtime-unrelated", password="test-only", user_role="doctor")
    db_session.add(user)
    db_session.flush()
    grant = AIPatientGrant(
        user_id=user.user_id,
        patient_id=seed_data["patient"].patient_id,
        category="cdss",
        reason="隔离测试诊疗用途",
        expires_at=utcnow() + datetime.timedelta(hours=1),
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(grant)
    db_session.commit()
    run = create_run(db_session, user, RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id))
    run_id = run.run_id
    grant.revoked = 1
    db_session.commit()
    claim = claim_next_run(db_session)
    requests = []
    await execute_claimed(*claim, transport=successful_transport(requests))
    db_session.expire_all()
    assert db_session.get(AIRun, run_id).status == "failed"
    assert requests == []


@pytest.mark.asyncio
async def test_patient_selector_is_scoped_to_real_care_relationships(async_client, seed_data, auth_headers):
    headers = auth_headers(seed_data["patient_user"].username)
    options = await async_client.get("/api/ai/patients", headers=headers, params={"feature_key": "patient_report_explanation"})
    assert {item["patient_id"] for item in options.json()["data"]} == {seed_data["patient"].patient_id}
    assert seed_data["patient"].identity not in options.text
    doctors = await async_client.get("/api/ai/patients", headers=auth_headers(seed_data["doctor_user"].username), params={"feature_key": "patient_summary"})
    assert seed_data["patient"].patient_id in {item["patient_id"] for item in doctors.json()["data"]}
    assert seed_data["patient2"].patient_id not in {item["patient_id"] for item in doctors.json()["data"]}


@pytest.mark.asyncio
async def test_existing_clinical_rows_carry_the_ids_needed_for_ai_context(async_client, seed_data, auth_headers):
    pharmacy = await async_client.get("/api/pharmacy/dispenseList", headers=auth_headers(seed_data["pharmacist_user"].username))
    assert pharmacy.status_code == 200
    row = next(item for item in pharmacy.json()["data"] if item["uuid"] == seed_data["prescription"].prescription_id)
    assert row["patient_id"] == seed_data["patient"].patient_id
    notes = await async_client.get("/api/medicalRecord/getList", headers=auth_headers(seed_data["doctor_user"].username))
    assert notes.status_code == 200
    records = notes.json()["data"]
    assert records
    # Verify the public row contract rather than depending on fixture profile insertion order.
    assert all("patient_id" in item and "registration_uuid" in item for item in records)


@pytest.mark.asyncio
async def test_emergency_triage_does_not_wait_for_model_configuration(async_client, seed_data, auth_headers, db_session):
    response = await async_client.post(
        "/api/ai/runs", headers=auth_headers(seed_data["patient_user"].username), json={"feature_key": "conversational_triage", "input": {"question": "持续胸痛，呼吸困难"}}
    )
    assert response.status_code == 422
    assert "不要等待 AI" in response.text
    assert db_session.query(AIRun).count() == 0


@pytest.mark.asyncio
async def test_clinical_input_requires_explicit_provider_data_permission(async_client, seed_data, auth_headers, db_session):
    provider, _ = configure(db_session, seed_data, "guideline_qa")
    provider.allows_patient_data = 0
    db_session.commit()
    response = await async_client.post("/api/ai/runs", headers=auth_headers(seed_data["doctor_user"].username), json={"feature_key": "guideline_qa", "input": {"question": "说明诊疗资料缺口"}})
    assert response.status_code == 409
    assert "处理患者资料" in response.text


def reviewed_knowledge(db, seed_data):
    content = "测试知识：问诊资料缺失时先核对临床记录，本文仅用于隔离测试，不提供实际诊疗建议。"
    row = AIKnowledgeDocument(
        title="队列知识-" + str(uuid.uuid4()),
        version="test",
        source_uri="hospital://test/runtime",
        content=content,
        content_hash=digest(content),
        feature_keys_json='["guideline_qa"]',
        status="published",
        reviewed_by=seed_data["super_admin_user"].user_id,
        reviewed_at=utcnow(),
        created_by=seed_data["super_admin_user"].user_id,
    )
    db.add(row)
    db.commit()
    return row


@pytest.mark.asyncio
async def test_retired_knowledge_is_rechecked_before_inference(seed_data, db_session):
    configure(db_session, seed_data, "guideline_qa")
    document = reviewed_knowledge(db_session, seed_data)
    run = create_run(db_session, seed_data["doctor_user"], RunRequest(feature_key="guideline_qa", input={"question": "问诊资料缺失如何核对临床记录"}))
    run_id = run.run_id
    document.status = "retired"
    db_session.commit()
    requests = []
    await execute_claimed(*claim_next_run(db_session), transport=successful_transport(requests))
    db_session.expire_all()
    assert db_session.get(AIRun, run_id).status == "failed"
    assert requests == []


@pytest.mark.asyncio
async def test_changed_provider_cannot_silently_process_an_old_task(seed_data, db_session):
    provider, _ = configure(db_session, seed_data)
    run = create_run(db_session, seed_data["doctor_user"], RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id))
    run_id = run.run_id
    provider.revision += 1
    db_session.commit()
    requests = []
    await execute_claimed(*claim_next_run(db_session), transport=successful_transport(requests))
    db_session.expire_all()
    assert db_session.get(AIRun, run_id).error_code == "TASK_NO_LONGER_AUTHORIZED"
    assert requests == []


@pytest.mark.asyncio
async def test_daily_quota_and_preview_permissions_are_enforced(async_client, seed_data, auth_headers, db_session):
    _, config = configure(db_session, seed_data)
    config.daily_limit = 1
    db_session.commit()
    headers = auth_headers(seed_data["doctor_user"].username)
    body = {"feature_key": "patient_summary", "patient_id": seed_data["patient"].patient_id}
    preview = await async_client.post("/api/ai/runs", headers=headers, json={**body, "preview": True})
    assert preview.status_code == 403
    assert (await async_client.post("/api/ai/runs", headers=headers, json=body)).status_code == 200
    quota = await async_client.post("/api/ai/runs", headers=headers, json=body)
    assert quota.status_code == 429


@pytest.mark.asyncio
async def test_cancelled_and_interrupted_tasks_are_not_automatically_replayed(async_client, seed_data, auth_headers, db_session):
    configure(db_session, seed_data)
    run = create_run(db_session, seed_data["doctor_user"], RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id))
    run_id = run.run_id
    cancel = await async_client.post(f"/api/ai/runs/{run_id}/cancel", headers=auth_headers(seed_data["doctor_user"].username))
    assert cancel.status_code == 200
    assert claim_next_run(db_session) is None
    interrupted = create_run(db_session, seed_data["doctor_user"], RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id))
    claim_next_run(db_session)
    db_session.refresh(interrupted)
    interrupted.start_time = utcnow() - datetime.timedelta(minutes=11)
    db_session.commit()
    assert expire_interrupted_runs(db_session) == 1
    db_session.refresh(interrupted)
    assert interrupted.status == "failed"
    assert interrupted.error_code == "WORKER_INTERRUPTED"
    assert claim_next_run(db_session) is None


@pytest.mark.asyncio
async def test_clinical_preview_is_labelled_and_does_not_enable_the_feature(async_client, seed_data, auth_headers, db_session):
    _, config = configure(db_session, seed_data)
    config.enabled = 0
    config.validation_status = "unreviewed"
    db_session.commit()
    body = {"feature_key": "patient_summary", "patient_id": seed_data["patient"].patient_id}
    normal = await async_client.post("/api/ai/runs", headers=auth_headers(seed_data["doctor_user"].username), json=body)
    assert normal.status_code == 409
    preview = await async_client.post("/api/ai/runs", headers=auth_headers("super01"), json={**body, "preview": True})
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["preview"] == 1
    db_session.refresh(config)
    assert config.enabled == 0


@pytest.mark.asyncio
async def test_expired_queue_item_cannot_make_a_billable_request(seed_data, db_session):
    configure(db_session, seed_data)
    run = create_run(db_session, seed_data["doctor_user"], RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id))
    run.create_time = utcnow() - datetime.timedelta(hours=1)
    db_session.commit()
    claim = claim_next_run(db_session)
    requests = []
    await execute_claimed(*claim, transport=successful_transport(requests))
    db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_code == "TASK_EXPIRED"
    assert requests == []


@pytest.mark.asyncio
async def test_changed_patient_context_before_inference_does_not_call_provider(seed_data, db_session):
    configure(db_session, seed_data)
    run = create_run(db_session, seed_data["doctor_user"], RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id))
    seed_data["patient"].allergy_history = "测试排队期间新增过敏记录"
    db_session.commit()
    claim = claim_next_run(db_session)
    requests = []
    await execute_claimed(*claim, transport=successful_transport(requests))
    db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_code == "TASK_CONTEXT_CHANGED"
    assert requests == []


@pytest.mark.asyncio
async def test_changed_prescription_rules_before_inference_do_not_use_stale_tool_results(seed_data, db_session):
    configure(db_session, seed_data, "interaction_review")
    run = create_run(
        db_session,
        seed_data["doctor_user"],
        RunRequest(feature_key="interaction_review", patient_id=seed_data["patient"].patient_id, input={"prescription_id": seed_data["prescription"].prescription_id}),
    )
    db_session.add(
        PrescriptionReviewRule(
            rule_type="contraindication", drug_a=seed_data["pharmaceutical"].name, severity=3, message="测试新增审方规则", source="测试", version="test", status=1, create_time=utcnow()
        )
    )
    db_session.commit()
    claim = claim_next_run(db_session)
    requests = []
    await execute_claimed(*claim, transport=successful_transport(requests))
    db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_code == "TASK_TOOLS_CHANGED"
    assert requests == []


@pytest.mark.asyncio
async def test_context_change_during_inference_rejects_output_and_keeps_actual_usage(seed_data, db_session):
    from app import database

    configure(db_session, seed_data)
    run = create_run(db_session, seed_data["doctor_user"], RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id))
    claim = claim_next_run(db_session)
    requests = []
    baseline = successful_transport(requests)

    def change_during_model_call(request):
        with database.SessionLocal() as session:
            session.get(Patient, seed_data["patient"].patient_id).allergy_history = "测试推理期间新增过敏记录"
            session.commit()
        return baseline.handle_request(request)

    await execute_claimed(*claim, transport=httpx.MockTransport(change_during_model_call))
    db_session.refresh(run)
    assert len(requests) == 1
    assert run.status == "failed"
    assert run.error_code == "TASK_CONTEXT_CHANGED"
    assert (run.input_tokens, run.output_tokens) == (5, 7)
    assert json.loads(run.result_json) == {}
