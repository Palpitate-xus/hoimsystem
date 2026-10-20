"""Controlled recognizer objects verify full iteration and faithful wrapper behavior."""

import sys
from array import array
from types import SimpleNamespace

import pytest

from app.ai import speech_worker
from app.ai.speech_config import SpeechSettings


@pytest.fixture
def job(tmp_path, monkeypatch):
    config = SpeechSettings(model_dir=tmp_path, AI_PROVIDER_LOCAL_SPEECH_API_KEY="offline-fixture-credential-not-a-real-secret", language="en")
    descriptor = {
        "model_version": "fw:" + "a" * 64,
        "engine": "faster-whisper",
        "engine_versions": {"faster-whisper": "1.2.1"},
        "model_revision": "b" * 40,
        "model_digest": "c" * 64,
        "runtime_digest": "a" * 64,
        "decoding_options_hash": "d" * 64,
    }
    monkeypatch.setattr(speech_worker, "runtime_descriptor", lambda _: descriptor)
    monkeypatch.setattr(speech_worker, "decode_native", lambda *_: (array("f", [0.0]) * 63040, 3940))
    return {
        "config": {**config.model_dump(mode="json", exclude={"api_key"}), "AI_PROVIDER_LOCAL_SPEECH_API_KEY": "offline-fixture-credential-not-a-real-secret"},
        "audio_path": str(tmp_path / "unused.wav"),
        "model_version": descriptor["model_version"],
        "instructions_digest": "e" * 64,
        "source": {"asset_id": "12345678-1234-4234-8234-123456789012", "content_hash": "f" * 64, "duration_ms": 3940, "source_id": "fixture-only"},
    }


def test_acoustic_model_gets_all_samples_and_end_estimate_is_retained_in_uncertainty_note(job, monkeypatch):
    exhausted = []

    class Model:
        def __init__(self, *args, **kwargs):
            assert kwargs["device"] == "cpu" and kwargs["local_files_only"] is True

        def transcribe(self, samples, **kwargs):
            assert len(samples) == 63040 and kwargs["task"] == "transcribe" and kwargs["vad_filter"] is True
            assert "initial_prompt" not in kwargs and "hotwords" not in kwargs

            def segments():
                yield SimpleNamespace(start=0.0, end=4.0, text="  fixture text, not real ASR  ")
                exhausted.append(True)

            return segments(), SimpleNamespace(language="en")

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    result = speech_worker.recognize(job)
    assert exhausted == [True]
    transcript = result["transcription"]
    assert transcript["processing"]["iterator_exhausted"] is True and transcript["processing"]["submitted_samples"] == 63040
    segment = transcript["segments"][0]
    assert segment["end_ms"] == 3940 and "4000ms" in segment["uncertainty_note"] and "3940ms" in segment["uncertainty_note"]
    assert segment["text"] == "fixture text, not real ASR" and segment["speaker"] == segment["speaker_role"] == "unknown"


@pytest.mark.parametrize("failure", ["partial", "text_limit", "outside_source"])
def test_failed_iteration_or_invalid_segments_never_return_partial_transcription(failure, job, monkeypatch):
    class Model:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, *args, **kwargs):
            def segments():
                yield SimpleNamespace(start=0.0, end=1.0, text="first fixture segment")
                if failure == "partial":
                    raise RuntimeError("fixture failure after partial output")
                yield SimpleNamespace(start=4.0 if failure == "outside_source" else 1.0, end=5.0, text="x" * 2001 if failure == "text_limit" else "outside")

            return segments(), SimpleNamespace(language="en")

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    with pytest.raises((ValueError, RuntimeError)):
        speech_worker.recognize(job)
