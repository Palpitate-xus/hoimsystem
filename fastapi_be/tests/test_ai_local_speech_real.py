"""Opt-in real offline recognizer through upload, task worker and frozen result.

Uses fixed nonclinical TTS and isolated database fixtures, never real patient recordings.
"""

import hashlib
import os
import subprocess

import httpx
import pytest

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.governance import encode_json
from app.ai.models import AIFeatureConfig, AIProvider, AIRun, utcnow
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.ai.speech_config import SpeechSettings, runtime_descriptor
from app.ai.speech_server import create_speech_app
from app.config import settings
from app.models import Registration


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("HOIM_SPEECH_REAL_MODEL_DIR"), reason="Requires explicitly prepared local weights and optional speech runtime")
async def test_synthetic_audio_registration_to_actual_recognition_and_frozen_review(db_session, seed_data, async_client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AI_AUDIO_STORAGE_DIR", str(tmp_path / "private"))
    credential = "isolated-real-asr-test-not-a-production-credential"
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SPEECH_API_KEY", credential)
    config = SpeechSettings(model_dir=os.environ["HOIM_SPEECH_REAL_MODEL_DIR"], AI_PROVIDER_LOCAL_SPEECH_API_KEY=credential, language="en")
    descriptor = runtime_descriptor(config)
    path = tmp_path / "nonclinical-synthetic.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "flite=text='The blue bicycle is beside the garden. Please open the window.':voice=slt",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
        timeout=30,
    )
    raw = path.read_bytes()
    encounter = Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=utcnow(), status=0)
    db_session.add(encounter)
    db_session.commit()
    headers = auth_headers(seed_data["doctor_user"].username)
    response = await async_client.post(
        "/api/ai/audio-assets",
        headers=headers,
        files={"file": (path.name, raw, "audio/wav")},
        data={
            "patient_id": str(encounter.patient_id),
            "encounter_ref": encounter.registration_uuid,
            "authorization_confirmed": "true",
            "authorization_note": "固定非临床合成语音与隔离测试患者，不是实际临床授权证明",
        },
    )
    assert response.status_code == 200, response.text
    asset_id = response.json()["data"]["asset_id"]
    spec = FEATURE_BY_KEY["medical_transcription"]
    provider = AIProvider(
        name="opt-in-real-cpu-test",
        kind="specialist",
        api_base="http://localhost:8810",
        model=descriptor["model_version"],
        api_key_env="AI_PROVIDER_LOCAL_SPEECH_API_KEY",
        enabled=1,
        allows_patient_data=1,
        timeout_seconds=120,
        supported_features_json=encode_json([spec.key]),
        validation_report="仅隔离合成语音联调，不构成临床质量验证",
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key=spec.key,
            provider_id=provider.provider_id,
            enabled=1,
            allowed_roles_json=encode_json(spec.default_roles),
            validation_status="validated",
            validation_note="隔离测试开关，不修改真实配置或声称医疗验证",
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    record = seed_data["medical_record"]
    before = (record.symptom, record.result, record.status)
    run = create_run(
        db_session, seed_data["doctor_user"], RunRequest(feature_key=spec.key, patient_id=encounter.patient_id, encounter_ref=encounter.registration_uuid, input={"audio_asset_id": asset_id})
    )
    await execute_claimed(*claim_next_run(db_session), transport=httpx.ASGITransport(app=create_speech_app(config)))
    db_session.refresh(run)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    result = await async_client.get("/api/ai/runs/" + run.run_id, headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    transcript = data["result"]["transcription"]
    assert transcript["asset_id"] == asset_id and transcript["content_hash"] == hashlib.sha256(raw).hexdigest()
    text = " ".join(row["text"] for row in transcript["segments"]).lower()
    assert all(word in text for word in ("blue", "bicycle", "garden", "window"))
    assert all(row["speaker"] == row["speaker_role"] == "unknown" and row["uncertain"] for row in transcript["segments"])
    processing = transcript["processing"]
    assert processing["iterator_exhausted"] is True and processing["processed_duration_ms"] == data["audio_findings"]["audio_source"]["duration_ms"]
    assert processing["instructions_digest"] == hashlib.sha256((COMMON_SYSTEM_PROMPT + "\n\n" + spec.task_prompt).encode()).hexdigest()
    db_session.refresh(record)
    assert (record.symptom, record.result, record.status) == before
    assert db_session.query(AIRun).count() == 1
