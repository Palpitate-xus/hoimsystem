"""Run real offline ASR on fixed, nonclinical synthetic English speech through the gateway."""

import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.ai.audio_files import inspect_audio
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.gateway import generate
from app.ai.models import AIProvider
from app.ai.speech_config import SpeechSettings, runtime_descriptor
from app.ai.speech_probe import inspect_speech_capabilities
from app.ai.speech_server import create_speech_app

SYNTHETIC_TEXT = "The blue bicycle is beside the garden. Please open the window."


async def main():
    config = SpeechSettings()
    if config.language not in {"auto", "en"}:
        raise ValueError("该非临床合成语音检查须设置SPEECH_LANGUAGE=en或auto，不评价中文/医疗识别效果")
    descriptor = runtime_descriptor(config)
    with tempfile.TemporaryDirectory(prefix="hoim-asr-smoke-") as directory:
        path = Path(directory) / "synthetic.wav"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-f", "lavfi", "-i", f"flite=text='{SYNTHETIC_TEXT}':voice=slt", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(path)],
            check=True,
            timeout=30,
        )
        browser_clip, silence = Path(directory) / "synthetic.webm", Path(directory) / "silence.wav"
        subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-i", str(path), "-c:a", "libopus", str(browser_clip)], check=True, timeout=30)
        subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "0.25", "-c:a", "pcm_s16le", str(silence)], check=True, timeout=30)
        provider = AIProvider(
            name="synthetic-offline-smoke",
            kind="specialist",
            api_base="http://localhost:8810",
            model=descriptor["model_version"],
            api_key_env="AI_PROVIDER_LOCAL_SPEECH_API_KEY",
            max_output_tokens=2000,
            timeout_seconds=120,
        )
        spec = FEATURE_BY_KEY["medical_transcription"]
        transport = httpx.ASGITransport(app=create_speech_app(config))
        reported = await inspect_speech_capabilities(provider, transport=transport)
        assert reported["model_version"] == descriptor["model_version"]
        cases = []
        for clip, expect_speech in ((path, True), (browser_clip, True), (silence, False)):
            raw = clip.read_bytes()
            asset_id, digest = str(uuid.uuid4()), hashlib.sha256(raw).hexdigest()
            source = {"asset_id": asset_id, "content_hash": digest, "extension": clip.suffix, "byte_size": len(raw), **inspect_audio(clip, clip.suffix)}
            source["source_id"] = f"audio:{asset_id}:{digest[:12]}"
            with clip.open("rb") as audio:
                result, _, _ = await generate(
                    provider,
                    spec,
                    spec.task_prompt,
                    {"input": {}, "context": {"audio_source": source}, "tools": {}, "evidence": [{"source_id": source["source_id"], "kind": "audio_asset"}]},
                    transport=transport,
                    audio=audio,
                )
            transcript = " ".join(item.text for item in result.transcription.segments)
            passed = all(word in transcript.lower() for word in ("blue", "bicycle", "garden", "window")) if expect_speech else not result.transcription.speech_detected
            cases.append(
                {
                    "fixture": clip.name,
                    "source_sha256": digest,
                    "source_duration_ms": source["duration_ms"],
                    "transcript": transcript,
                    "check_passed": passed,
                    "processing": result.transcription.processing.model_dump(),
                }
            )
        report = {
            "synthetic_text": SYNTHETIC_TEXT,
            "model_version": descriptor["model_version"],
            "engine_versions": descriptor["engine_versions"],
            "decoding_options": config.decoding_options(),
            "device": "cpu",
            "compute_type": "int8",
            "cpu_threads": config.cpu_threads,
            "cases": cases,
            "clinical_validation": "not_performed",
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not all(item["check_passed"] for item in cases):
            raise RuntimeError("合成语音关键字检查失败，请核对实际识别结果")


if __name__ == "__main__":
    asyncio.run(main())
