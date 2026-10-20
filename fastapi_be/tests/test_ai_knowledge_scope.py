"""Changing only department applicability must invalidate queued and inflight guidance."""

import json
import uuid

import httpx
import pytest

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import digest, encode_json
from app.ai.models import AIFeatureConfig, AIFeedback, AIKnowledgeDocument, AIProvider, AIRun, utcnow
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Department, Doctor, User


@pytest.mark.asyncio
@pytest.mark.parametrize("inflight", [False, True])
async def test_department_change_without_text_change_invalidates_guideline_applicability(inflight, seed_data, db_session):
    for model in (AIFeedback, AIRun, AIFeatureConfig, AIProvider, AIKnowledgeDocument):
        db_session.query(model).delete()
    key = "guideline_qa"
    first = seed_data["department"]
    second = Department(name="另一适用科室" + str(uuid.uuid4())[:8])
    actor = User(username="scope-" + uuid.uuid4().hex[:12], password="isolated-test", user_role="doctor")
    db_session.add_all([second, actor])
    db_session.flush()
    profile = Doctor(user_id=actor.user_id, name="范围测试医生", department_id=first.department_id)
    provider = AIProvider(
        name="scope-isolated", kind="chat", api_base="http://localhost:11434/v1", model="isolated", enabled=1, allows_patient_data=1, created_by=seed_data["super_admin_user"].user_id
    )
    db_session.add_all([profile, provider])
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key=key,
            provider_id=provider.provider_id,
            enabled=1,
            allowed_roles_json=encode_json(FEATURE_BY_KEY[key].default_roles),
            validation_status="validated",
            validation_note="隔离测试，不构成临床验证",
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    content = "医学指南问答：仅用于测试原适用科室，调科后须核对新的适用依据。"
    db_session.add(
        AIKnowledgeDocument(
            title="科室适用规范",
            version="test",
            source_uri="hospital://isolated/scope",
            content=content,
            content_hash=digest(content),
            feature_keys_json=encode_json([key]),
            department_id=first.department_id,
            status="published",
            reviewed_by=seed_data["super_admin_user"].user_id,
            reviewed_at=utcnow(),
            created_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    run = create_run(db_session, actor, RunRequest(feature_key=key, input={"question": "医学指南问答测试"}))
    assert json.loads(run.context_metadata_json)["department_ids"] == [first.department_id]
    if not inflight:
        profile.department_id = second.department_id
        db_session.commit()
    requests = []

    def handle(request):
        payload = json.loads(json.loads(request.content)["messages"][-1]["content"])
        requests.append(payload)
        profile.department_id = second.department_id
        db_session.commit()
        source = next(item["source_id"] for item in payload["evidence"] if item["kind"] == "knowledge")
        result = {"summary": "隔离范围测试", "sections": [{"title": "依据", "content": "待核对", "source_ids": [source]}], "warnings": [], "missing_data": []}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}})

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(handle))
    db_session.refresh(run)
    assert len(requests) == int(inflight) and run.status == "failed" and run.result_json == "{}"
    assert run.error_code == "TASK_DEPARTMENT_SCOPE_CHANGED"
    assert (run.input_tokens, run.output_tokens) == ((5, 7) if inflight else (0, 0))
