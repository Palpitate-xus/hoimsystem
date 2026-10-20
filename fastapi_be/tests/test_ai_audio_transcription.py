"""Synthetic bytes and mocked text verify the protocol, never real speech recognition quality."""

import copy
import hashlib
import io
import json
import wave
from email import policy
from email.parser import BytesParser

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.ai.audio_files import audio_path
from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.context import minimize_identifiers, patient_snapshot
from app.ai.governance import encode_json
from app.ai.models import AIAudioAsset, AIFeatureConfig, AIFeedback, AIProvider, AIRun, utcnow
from app.ai.runtime import claim_next_run, create_run, describe_run, execute_claimed
from app.ai.schemas import RunRequest
from app.config import settings
from app.models import Registration

KEY = "medical_transcription"


@pytest_asyncio.fixture
async def transcription_case(db_session, seed_data, tmp_path, monkeypatch, async_client, auth_headers):
    monkeypatch.setattr(settings, "AI_AUDIO_STORAGE_DIR", str(tmp_path / "private"))
    for model in (AIFeedback, AIRun, AIFeatureConfig, AIProvider, AIAudioAsset):
        db_session.query(model).delete()
    clip = io.BytesIO()
    with wave.open(clip, "wb") as writer:
        writer.setparams((1, 2, 8000, 2000, "NONE", "not compressed"))
        writer.writeframes(b"\0" * 4000)
    raw = clip.getvalue()
    encounter = Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=utcnow(), status=0)
    db_session.add(encounter)
    db_session.commit()
    response = await async_client.post(
        "/api/ai/audio-assets",
        headers=auth_headers(seed_data["doctor_user"].username),
        files={"file": ("原患者姓名录音.wav", raw, "audio/wav")},
        data={
            "patient_id": str(encounter.patient_id),
            "encounter_ref": encounter.registration_uuid,
            "authorization_confirmed": "true",
            "authorization_note": "隔离测试授权说明，不是临床采集或处理授权证明",
        },
    )
    assert response.status_code == 200, response.text
    asset = db_session.get(AIAudioAsset, response.json()["data"]["asset_id"])
    provider = AIProvider(
        name="isolated-asr",
        kind="specialist",
        api_base="http://localhost:11434",
        model="isolated-asr-v2",
        enabled=1,
        allows_patient_data=1,
        supported_features_json=encode_json([KEY]),
        validation_report="隔离协议测试，不构成语音效果或临床验证",
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key=KEY,
            provider_id=provider.provider_id,
            enabled=1,
            allowed_roles_json=encode_json(FEATURE_BY_KEY[KEY].default_roles),
            validation_status="validated",
            validation_note="隔离测试配置，不启用真实临床功能",
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    return raw, asset, encounter


def task(case, *, with_encounter=True):
    _, asset, encounter = case
    return RunRequest(
        feature_key=KEY,
        patient_id=asset.patient_id,
        encounter_ref=encounter.registration_uuid if with_encounter else None,
        input={"audio_asset_id": asset.asset_id, "question": "请忠实转写并标注待听音核对处"},
    )


def request_parts(request):
    message = BytesParser(policy=policy.default).parsebytes(b"MIME-Version: 1.0\r\nContent-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content)
    parts = {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}
    return json.loads(parts["task"].get_payload(decode=True)), parts["audio"].get_payload(decode=True), parts["audio"].get_filename()


def response_for(payload, raw):
    source = payload["input"]["context"]["audio_source"]
    return {
        "schema_version": "2",
        "feature_key": KEY,
        "model_version": "isolated-asr-v2",
        "applicable": True,
        "result": {
            "summary": "隔离模拟转写，未验证识别效果",
            "sections": [{"title": "听音复核事项", "content": "模拟不确定片段仍需核对", "source_ids": [source["source_id"]]}],
            "warnings": [],
            "missing_data": ["说话人角色未经独立核实"],
        },
        "transcription": {
            "asset_id": source["asset_id"],
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "time_basis": "relative_decoded_audio",
            "speech_detected": True,
            "language": "zh-CN",
            "segments": [
                {
                    "start_ms": 0,
                    "end_ms": 200,
                    "speaker": "speaker_1",
                    "speaker_role": "unknown",
                    "text": "仅用于协议测试的模拟内容",
                    "uncertain": True,
                    "uncertainty_note": "模拟不确定片段，不作为实际转写",
                    "source_id": source["source_id"],
                }
            ],
        },
        "usage": {"input_tokens": 5, "output_tokens": 7},
    }


def test_minimization_preserves_valid_source_ids_and_hashes_even_when_digits_resemble_a_phone():
    identifier = "12345678-1234-4234-8234-138123456789"
    content_hash = "a" * 10 + "13812345678" + "c" * 43
    source_id = "audio:" + identifier + ":aabbccddeeff"
    clean = minimize_identifiers({"audio_asset_id": identifier, "content_hash": content_hash, "source_id": source_id, "question": "联系电话13812345678"})
    assert clean["audio_asset_id"] == identifier and clean["content_hash"] == content_hash and clean["source_id"] == source_id
    assert clean["question"] == "联系电话[手机号已隐藏]"


@pytest.mark.asyncio
async def test_context_is_recording_only_and_requires_actual_authorized_asset(transcription_case, seed_data, db_session, async_client, auth_headers):
    _, asset, encounter = transcription_case
    headers = auth_headers(seed_data["doctor_user"].username)
    body = {"feature_key": KEY, "patient_id": asset.patient_id, "encounter_ref": encounter.registration_uuid, "source_refs": {"audio_asset_id": asset.asset_id}}
    response = await async_client.post("/api/ai/context", headers=headers, json=body)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["context"]["scope"] == "recording_transcription" and data["context"]["audio_source"]["recorded_at"] is None
    assert len(data["evidence"]) == 1 and data["evidence"][0]["kind"] == "audio_asset"
    serialized = encode_json(data)
    for forbidden in ("outpatient_records", "allergy_history_text", "authorization_note", "原患者姓名录音", seed_data["patient"].name):
        assert forbidden not in serialized
    assert db_session.query(AIRun).count() == 0
    missing = await async_client.post("/api/ai/context", headers=headers, json={**body, "source_refs": {}})
    assert missing.status_code == 422
    mixed = await async_client.post("/api/ai/context", headers=headers, json={**body, "source_refs": {**body["source_refs"], "record_id": seed_data["medical_record"].medical_record_id}})
    assert mixed.status_code == 422
    with pytest.raises(HTTPException) as error:
        patient_snapshot(db_session, seed_data["patient_user"], FEATURE_BY_KEY["patient_report_explanation"], asset.patient_id, source_refs={"audio_asset_id": asset.asset_id})
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_worker_transmits_exact_bytes_and_prompts_then_freezes_segmented_draft_without_notes_writes(transcription_case, seed_data, db_session, async_client, auth_headers):
    raw, asset, _ = transcription_case
    original_record = seed_data["medical_record"]
    before = (original_record.symptom, original_record.result, original_record.status)
    run = create_run(db_session, seed_data["doctor_user"], task(transcription_case))
    requests = []

    def handle(request):
        payload, received, filename = request_parts(request)
        requests.append(payload)
        assert received == raw and filename == "recording.wav"
        assert COMMON_SYSTEM_PROMPT in payload["instructions"] and FEATURE_BY_KEY[KEY].task_prompt in payload["instructions"]
        assert payload["schema_version"] == "2" and payload["model"] == "isolated-asr-v2"
        assert payload["store"] is False
        assert payload["input"]["context"]["audio_source"]["content_hash"] == hashlib.sha256(received).hexdigest()
        assert "outpatient_records" not in payload["input"]["context"]
        return httpx.Response(200, json=response_for(payload, received))

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(handle))
    db_session.refresh(run)
    assert len(requests) == 1 and run.status == "succeeded" and (run.input_tokens, run.output_tokens) == (5, 7)
    result = describe_run(run)
    assert result["result"]["transcription"]["segments"][0]["speaker_role"] == "unknown"
    assert result["audio_findings"]["audio_source"]["content_hash"] == asset.content_hash
    assert "private/" not in run.input_json and "recording.wav" not in run.input_json
    detail = await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(seed_data["doctor_user"].username))
    assert detail.status_code == 200 and "transcription" in detail.json()["data"]["result"]
    db_session.refresh(original_record)
    assert (original_record.symptom, original_record.result, original_record.status) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["hash", "range", "order", "citation", "role", "uncertainty", "timestamp_type"])
async def test_adapter_segment_or_source_errors_are_rejected_with_reported_usage_retained(variant, transcription_case, seed_data, db_session):
    run = create_run(db_session, seed_data["doctor_user"], task(transcription_case))

    def handle(request):
        payload, received, _ = request_parts(request)
        response = response_for(payload, received)
        segment = response["transcription"]["segments"][0]
        if variant == "hash":
            response["transcription"]["content_hash"] = "0" * 64
        if variant == "range":
            segment["end_ms"] = 1000
        if variant == "order":
            segment["start_ms"] = 100
            other = copy.deepcopy(segment)
            other["start_ms"], other["end_ms"] = 0, 50
            response["transcription"]["segments"].append(other)
        if variant == "citation":
            segment["source_id"] = "fabricated-audio"
        if variant == "role":
            segment["speaker_role"] = "doctor"
        if variant == "uncertainty":
            segment["uncertainty_note"] = ""
        if variant == "timestamp_type":
            segment["start_ms"] = True
        return httpx.Response(200, json=response)

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(handle))
    db_session.refresh(run)
    assert run.status == "failed" and run.result_json == "{}" and (run.input_tokens, run.output_tokens) == (5, 7)
    assert run.error_code in {"AUDIO_SOURCE_MISMATCH", "INVALID_AUDIO_SEGMENT", "INVALID_OUTPUT"}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["withdraw", "bytes", "care"])
async def test_queued_source_changes_prevent_any_model_call_even_without_encounter_header(change, transcription_case, seed_data, db_session):
    raw, asset, encounter = transcription_case
    run = create_run(db_session, seed_data["doctor_user"], task(transcription_case, with_encounter=False))
    if change == "withdraw":
        asset.status, asset.revision = "withdrawn", 2
    if change == "bytes":
        audio_path(asset.asset_id).write_bytes(raw[:-1] + b"x")
    if change == "care":
        encounter.doctor_id = None
    db_session.commit()
    requests = []
    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(lambda request: (requests.append(request), httpx.Response(500))[1]))
    db_session.refresh(run)
    assert requests == [] and run.status == "failed" and run.error_code == "TASK_NO_LONGER_AUTHORIZED"


@pytest.mark.asyncio
async def test_inflight_withdrawal_discards_result_and_non_super_history_is_revoked(transcription_case, seed_data, db_session, async_client, auth_headers):
    _, asset, _ = transcription_case
    run = create_run(db_session, seed_data["doctor_user"], task(transcription_case))

    def handle(request):
        payload, received, _ = request_parts(request)
        asset.status, asset.revision = "withdrawn", 2
        db_session.commit()
        return httpx.Response(200, json=response_for(payload, received))

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(handle))
    db_session.refresh(run)
    assert run.status == "failed" and run.result_json == "{}" and (run.input_tokens, run.output_tokens) == (5, 7)
    assert (await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(seed_data["doctor_user"].username))).status_code == 403
    listing = await async_client.get("/api/ai/runs", headers=auth_headers(seed_data["doctor_user"].username))
    assert listing.status_code == 200 and listing.json()["data"] == []
    audit = await async_client.get("/api/ai/admin/runs/" + run.run_id, headers=auth_headers("super01"))
    assert audit.status_code == 200 and audit.json()["data"]["frozen_request"]["payload"]["context"]["audio_source"]["revision"] == 1
