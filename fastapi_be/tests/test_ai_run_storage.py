"""Exact persisted UTF-8 limits, including source duplicates and the full envelope."""

import json

import pytest
from fastapi import HTTPException

from app.ai import runtime
from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIPromptVersion, AIRun
from app.ai.news2_sources import create_assessment
from app.ai.schemas import RunRequest
from app.inpatient_observations import canonical_json, frozen_content_hash
from app.models import Admission, MedicalRecord, Prescription
from tests.test_ai_news2_pipeline import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_news2_pipeline import news2_case as news2_case
from tests.test_ai_news2_pipeline import observation_case as observation_case
from tests.test_ai_news2_pipeline import request_for
from tests.test_ai_observation_windows import create


def counts(db):
    return {model.__tablename__: db.query(model).count() for model in (AIRun, AIAuditEvent, Admission, MedicalRecord, Prescription)}


def request_json(case):
    return request_for(case).model_dump(mode="json")


def filled_utf8(char, size):
    count, remainder = divmod(size, len(char.encode()))
    return char * count + "x" * remainder


@pytest.mark.parametrize("field", ["input_json", "evidence_json", "context_metadata_json"])
@pytest.mark.parametrize("char", ["x", "合"])
@pytest.mark.parametrize("size", [65535, 65536])
def test_each_exact_serialized_column_respects_byte_boundary_without_mutating_text(field, char, size):
    empty = encode_json({"value": ""})
    original = encode_json({"value": filled_utf8(char, size - len(empty.encode()))})
    assert len(original.encode()) == size
    serialized = {"input_json": "{}", "evidence_json": "[]", "context_metadata_json": "{}", field: original}
    before = serialized.copy()
    if size == 65535:
        runtime._check_run_storage_json(serialized)
    else:
        with pytest.raises(HTTPException) as caught:
            runtime._check_run_storage_json(serialized)
        assert caught.value.status_code == 422
    assert serialized == before and serialized[field] is original


@pytest.mark.asyncio
async def test_legal_two_thousand_chinese_note_is_rejected_atomically_before_queue_storage(async_client, auth_headers, db_session, news2_case):
    case = news2_case
    point = case["point"]
    payload = json.loads(point.payload_json)
    payload["note"] = "合" * 2000
    point.payload_json = canonical_json(payload)
    point.content_hash = frozen_content_hash(point, payload)
    db_session.commit()
    window = create(db_session, case)
    req = json.loads(case["assessment"].snapshot_json)["attestation"]
    req.update(window_id=window.window_id, expected_window_hash=window.content_hash, point_id=point.observation_id, expected_point_hash=point.content_hash)
    assessment = create_assessment(db_session, case["doctor"], req)
    db_session.commit()
    assert len(window.snapshot_json.encode()) < 40000 and len(assessment.snapshot_json.encode()) < 65535
    before = counts(db_session)
    source_before = (point.payload_json, point.content_hash, window.snapshot_json, assessment.snapshot_json)
    request = RunRequest(
        feature_key="deterioration_risk",
        patient_id=case["patient_id"],
        encounter_ref=case["admission"].admission_id,
        input={"observation_window_id": window.window_id, "news2_assessment_id": assessment.assessment_id},
    )
    response = await async_client.post("/api/ai/runs", headers=auth_headers(case["doctor"].username), json=request.model_dump(mode="json"))
    assert response.status_code == 422, response.text
    assert "65535" in response.text and "UTF-8" in response.text
    assert counts(db_session) == before
    db_session.expire_all()
    assert (point.payload_json, point.content_hash, window.snapshot_json, assessment.snapshot_json) == source_before


def prepare_boundary_prompt(db, case, target, char):
    # Measure a real, fully assembled run, then choose a valid immutable Prompt
    # to reach the exact storage boundary. The clinical payload stays unchanged.
    case["provider"].validation_report += "x" * 3000
    assert len(case["provider"].validation_report) <= 5000
    db.commit()
    calibration = runtime.create_run(db, case["doctor"], request_for(case))
    envelope = json.loads(calibration.input_json)
    envelope["task_prompt"] = ""
    overhead = len(encode_json(envelope).encode())
    prompt = filled_utf8(char, target - overhead)
    assert 30 <= len(prompt) <= 20000
    db.delete(calibration)
    latest = db.query(AIPromptVersion).filter_by(feature_key="deterioration_risk").order_by(AIPromptVersion.version.desc()).first()
    saved = AIPromptVersion(
        feature_key="deterioration_risk",
        version=latest.version + 1 if latest else 1,
        task_prompt=prompt,
        change_note="Synthetic complete storage envelope boundary",
        created_by=case["seed"]["super_admin_user"].user_id,
    )
    db.add(saved)
    db.flush()
    case["feature"].active_prompt_id = saved.prompt_id
    db.commit()
    return prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("char", ["x", "合"])
@pytest.mark.parametrize("target", [65535, 65536])
async def test_actual_http_creation_checks_complete_envelope_with_prompt_and_preserves_exact_boundary(char, target, async_client, auth_headers, db_session, news2_case):
    case = news2_case
    prompt = prepare_boundary_prompt(db_session, case, target, char)
    before = counts(db_session)
    response = await async_client.post("/api/ai/runs", headers=auth_headers(case["doctor"].username), json=request_json(case))
    if target == 65536:
        assert response.status_code == 422, response.text
        assert counts(db_session) == before
        return
    assert response.status_code == 200, response.text
    stored = db_session.get(AIRun, response.json()["data"]["run_id"])
    assert len(stored.input_json.encode()) == 65535
    frozen = json.loads(stored.input_json)
    assert frozen["task_prompt"] == prompt
    assert len(encode_json(frozen["payload"])) < runtime.settings.AI_MAX_CONTEXT_CHARS * 2
    assert stored.input_json == encode_json(frozen)
    assert stored.evidence_json == encode_json(frozen["payload"]["evidence"])
    assert json.loads(stored.context_metadata_json)["context_digest"] == stored.context_digest
    after = counts(db_session)
    assert after[AIRun.__tablename__] == before[AIRun.__tablename__] + 1
    assert after[AIAuditEvent.__tablename__] == before[AIAuditEvent.__tablename__] + 1
    assert all(after[model.__tablename__] == before[model.__tablename__] for model in (Admission, MedicalRecord, Prescription))


@pytest.mark.asyncio
async def test_existing_ascii_payload_budget_still_precedes_storage_without_writes(async_client, auth_headers, db_session, news2_case, monkeypatch):
    case = news2_case
    monkeypatch.setattr(runtime.settings, "AI_MAX_CONTEXT_CHARS", 10000)
    before = counts(db_session)
    request = request_json(case)
    request["input"]["question"] = "x" * 12000
    response = await async_client.post("/api/ai/runs", headers=auth_headers(case["doctor"].username), json=request)
    assert response.status_code == 422 and "组合后的资料" in response.text
    assert counts(db_session) == before
