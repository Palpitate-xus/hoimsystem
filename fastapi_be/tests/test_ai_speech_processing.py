"""Gateway rejects incomplete recognition reports; fixture text is not real ASR."""

import copy
import hashlib
import io

import httpx
import pytest

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError, generate
from app.ai.models import AIProvider

KEY = "medical_transcription"
SPEC = FEATURE_BY_KEY[KEY]
PROMPT_HASH = hashlib.sha256((COMMON_SYSTEM_PROMPT + "\n\n" + SPEC.task_prompt).encode()).hexdigest()
RUNTIME = "b" * 64
SOURCE = {
    "asset_id": "12345678-1234-4234-8234-123456789012",
    "content_hash": "a" * 64,
    "source_id": "audio:12345678-1234-4234-8234-123456789012:aaaaaaaaaaaa",
    "duration_ms": 250,
    "extension": ".wav",
    "media_type": "audio/wav",
}


def response():
    return {
        "schema_version": "2",
        "feature_key": KEY,
        "model_version": "fw:" + RUNTIME,
        "applicable": True,
        "result": {"summary": "隔离协议测试，无真实识别", "sections": [], "warnings": [], "missing_data": []},
        "transcription": {
            "asset_id": SOURCE["asset_id"],
            "content_hash": SOURCE["content_hash"],
            "time_basis": "relative_decoded_audio",
            "speech_detected": True,
            "language": "en",
            "segments": [
                {
                    "start_ms": 0,
                    "end_ms": 250,
                    "speaker": "unknown",
                    "speaker_role": "unknown",
                    "text": "isolated text",
                    "uncertain": True,
                    "uncertainty_note": "fixture only",
                    "source_id": SOURCE["source_id"],
                }
            ],
            "processing": {
                "engine": "faster-whisper",
                "engine_version": "1.2.1",
                "model_revision": "c" * 40,
                "model_digest": "d" * 64,
                "runtime_digest": RUNTIME,
                "decoding_options_hash": "e" * 64,
                "instructions_digest": PROMPT_HASH,
                "decoded_duration_ms": 250,
                "processed_duration_ms": 250,
                "submitted_samples": 4000,
                "sample_rate": 16000,
                "iterator_exhausted": True,
                "vad_filter": True,
                "translation": False,
                "diarization": False,
                "prompt_handling": "acoustic_only",
                "timestamp_policy": "estimated_bounded_to_source",
            },
        },
        "usage": {"input_tokens": 5, "output_tokens": 7},
    }


async def call(value):
    provider = AIProvider(kind="specialist", api_base="http://localhost:11434", model="fw:" + RUNTIME, max_output_tokens=2000, timeout_seconds=30)
    return await generate(
        provider,
        SPEC,
        SPEC.task_prompt,
        {"context": {"audio_source": SOURCE}, "evidence": [{"source_id": SOURCE["source_id"]}]},
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=value)),
        audio=io.BytesIO(b"fixture"),
    )


@pytest.mark.asyncio
async def test_complete_input_report_is_preserved_without_claiming_recognition_accuracy():
    result, inputs, outputs = await call(response())
    assert result.transcription.processing.model_dump() == response()["transcription"]["processing"]
    assert (inputs, outputs) == (5, 7) and result.transcription.segments[0].uncertain


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["missing", "partial", "not_exhausted", "sample_count", "source_duration", "instructions", "runtime", "translation", "diarization", "float_count"])
async def test_invalid_processing_reports_are_rejected_and_reported_usage_survives(variant):
    value = copy.deepcopy(response())
    processing = value["transcription"]["processing"]
    if variant == "missing":
        del value["transcription"]["processing"]
    elif variant == "partial":
        processing["processed_duration_ms"] = 125
    elif variant == "not_exhausted":
        processing["iterator_exhausted"] = False
    elif variant == "sample_count":
        processing["submitted_samples"] = 2000
    elif variant == "source_duration":
        processing.update(decoded_duration_ms=500, processed_duration_ms=500, submitted_samples=8000)
    elif variant == "instructions":
        processing["instructions_digest"] = "0" * 64
    elif variant == "runtime":
        processing["runtime_digest"] = "0" * 64
    elif variant == "float_count":
        processing["submitted_samples"] = 4000.0
    else:
        processing[variant] = True
    with pytest.raises(AIExecutionError) as exc:
        await call(value)
    assert exc.value.code in {"INVALID_OUTPUT", "SPEECH_RUNTIME_MISMATCH", "SPEECH_PROCESSING_MISMATCH"}
    assert (exc.value.input_tokens, exc.value.output_tokens) == (5, 7)
