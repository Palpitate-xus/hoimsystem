"""Global task inspection is super-admin only and preserves the actual historical request."""

import json
import uuid

import pytest

from app.ai.catalog import COMMON_SYSTEM_PROMPT
from app.ai.models import AIFeatureConfig, AIFeedback, AIProvider, utcnow
from app.ai.runtime import create_run
from app.ai.schemas import RunRequest


@pytest.fixture
def recorded_runs(seed_data, db_session):
    provider = AIProvider(
        name="trace-" + str(uuid.uuid4()),
        kind="chat",
        api_base="http://localhost:11434/v1",
        model="requested-test-model-v1",
        enabled=1,
        allows_patient_data=1,
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    config = AIFeatureConfig(
        feature_key="patient_summary",
        provider_id=provider.provider_id,
        enabled=1,
        validation_status="validated",
        validation_note="隔离测试记录，不用于临床验证",
        allowed_roles_json='["doctor","super_admin"]',
        updated_by=seed_data["super_admin_user"].user_id,
    )
    db_session.merge(config)
    db_session.commit()
    run = create_run(db_session, seed_data["doctor_user"], RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id, input={"question": "隔离测试的原始问题"}))
    run.status = "succeeded"
    run.finish_time = utcnow()
    db_session.add_all(
        [
            AIFeedback(run_id=run.run_id, reviewer_id=seed_data["doctor_user"].user_id, outcome="rejected", comment="测试驳回记录"),
            AIFeedback(run_id=run.run_id, reviewer_id=seed_data["doctor_user"].user_id, outcome="modified", comment="测试修改后反馈"),
        ]
    )
    db_session.commit()
    return run, provider


@pytest.mark.asyncio
async def test_only_super_admin_can_inspect_global_frozen_inputs(async_client, seed_data, auth_headers, recorded_runs):
    run, _ = recorded_runs
    for name in ("admin_user", "doctor_user", "patient_user", "director_user"):
        for path in ("/api/ai/admin/runs", f"/api/ai/admin/runs/{run.run_id}"):
            response = await async_client.get(path, headers=auth_headers(seed_data[name].username))
            assert response.status_code == 403
    business = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(seed_data["doctor_user"].username))
    assert business.status_code == 200
    assert "frozen_request" not in business.json()["data"]
    assert "隔离测试的原始问题" not in business.text


@pytest.mark.asyncio
async def test_trace_keeps_old_requested_model_when_provider_changes(async_client, seed_data, auth_headers, db_session, recorded_runs):
    run, provider = recorded_runs
    provider.model = "a-new-test-model"
    provider.revision += 1
    db_session.commit()
    response = await async_client.get(f"/api/ai/admin/runs/{run.run_id}", headers=auth_headers("super01"))
    assert response.status_code == 200, response.text
    trace = response.json()["data"]
    assert trace["frozen_request"]["provider_snapshot"]["model"] == "requested-test-model-v1"
    assert trace["frozen_request"]["system_prompt"] == COMMON_SYSTEM_PROMPT
    assert trace["frozen_request"]["payload"]["input"]["question"] == "隔离测试的原始问题"
    assert trace["snapshot_complete"] is True
    assert len(trace["feedback"]) == 2
    assert "api_key_env" not in trace["frozen_request"]["provider_snapshot"]


@pytest.mark.asyncio
async def test_global_filters_do_not_duplicate_runs_with_multiple_reviews(async_client, seed_data, auth_headers, recorded_runs):
    run, _ = recorded_runs
    response = await async_client.get(
        "/api/ai/admin/runs",
        headers=auth_headers("super01"),
        params={"feature_key": "patient_summary", "requested_by": seed_data["doctor_user"].user_id, "patient_id": run.patient_id, "outcome": "rejected", "page_size": 100},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == len(data["data"]) == len({item["run_id"] for item in data["data"]})
    assert any(item["run_id"] == run.run_id for item in data["data"])
    assert data["data"][0]["feedback_count"] == 2
    assert "result" not in data["data"][0]
    assert "frozen_request" not in data["data"][0]
    assert "隔离测试的原始问题" not in json.dumps(data)
