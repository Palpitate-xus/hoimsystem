"""Synthetic input and isolated executors verify the local adapter's intake/lifecycle."""

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from app.ai import speech_server
from app.ai.speech_config import SpeechSettings

KEY = "fixture-local-speech-credential-at-least-32-characters"
RUNTIME = "c" * 64


def config(tmp_path, **overrides):
    return SpeechSettings(model_dir=tmp_path / "not-real-weights", AI_PROVIDER_LOCAL_SPEECH_API_KEY=KEY, **overrides)


def task_for(raw=b"RIFF-fixture-not-real-speech"):
    digest = hashlib.sha256(raw).hexdigest()
    identifier = "12345678-1234-4234-8234-123456789012"
    source = {
        "asset_id": identifier,
        "content_hash": digest,
        "extension": ".wav",
        "media_type": "audio/wav",
        "byte_size": len(raw),
        "duration_ms": 250,
        "sample_rate": 8000,
        "channels": 1,
        "codec": "pcm_s16le",
        "source_id": f"audio:{identifier}:{digest[:12]}",
    }
    return {
        "schema_version": "2",
        "feature_key": "medical_transcription",
        "engine": "speech",
        "model": "fw:" + RUNTIME,
        "instructions": "完整系统与任务Prompt，仅用于隔离协议测试",
        "store": False,
        "input": {"context": {"audio_source": source}, "input": {"question": "不能冒充已听到的内容"}, "evidence": []},
    }


@pytest.fixture
def descriptor(monkeypatch):
    value = {"schema_version": "2", "feature_key": "medical_transcription", "model_version": "fw:" + RUNTIME, "clinical_validation": "not_provided"}
    monkeypatch.setattr(speech_server, "runtime_descriptor", lambda _: value)
    return value


@pytest.mark.asyncio
async def test_service_authenticates_before_parsing_and_reports_no_secret_or_model_path(tmp_path, descriptor):
    calls = []

    async def execute(*args):
        calls.append(args)

    app = speech_server.create_speech_app(config(tmp_path), executor=execute)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://speech") as client:
        assert (await client.get("/health/ready")).json() == {"ready": True}
        assert (await client.get("/capabilities")).status_code == 401
        assert (await client.post("/tasks", content=b"not even a multipart form")).status_code == 401
        response = await client.get("/capabilities", headers={"Authorization": "Bearer " + KEY})
    assert response.json() == descriptor and not calls
    assert KEY not in response.text and str(tmp_path) not in response.text


@pytest.mark.asyncio
async def test_original_bytes_are_private_then_removed_and_free_text_never_enters_recognizer(tmp_path, descriptor, monkeypatch):
    raw = b"RIFF-fixture-not-real-speech"
    paths = []
    monkeypatch.chdir(tmp_path)
    service_config = SpeechSettings(model_dir=Path("relative-weights"), AI_PROVIDER_LOCAL_SPEECH_API_KEY=KEY)

    async def execute(job, timeout):
        path = Path(job["audio_path"])
        paths.append(path)
        assert path.read_bytes() == raw and path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert job["source"]["content_hash"] == hashlib.sha256(raw).hexdigest()
        assert timeout == 110 and KEY not in json.dumps(job)
        assert job["config"]["model_dir"] == str(tmp_path / "relative-weights")
        assert "不能冒充" not in json.dumps(job, ensure_ascii=False) and "完整系统" not in json.dumps(job, ensure_ascii=False)
        assert job["instructions_digest"] == hashlib.sha256(task_for()["instructions"].encode()).hexdigest()
        return {"isolated_executor": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=speech_server.create_speech_app(service_config, executor=execute)), base_url="http://speech") as client:
        response = await client.post("/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task_for())}, files={"audio": ("potential-name-is-ignored.wav", raw, "audio/wav")})
    assert response.status_code == 200 and response.json() == {"isolated_executor": True}
    assert len(paths) == 1 and not paths[0].parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["model", "hash", "short", "size", "duration", "store", "source_id", "feature", "media", "extra_field", "oversized_body"])
async def test_invalid_or_outside_scope_attachments_never_start_recognition(variant, tmp_path, descriptor):
    raw = b"RIFF-fixture-not-real-speech"
    task = task_for(raw)
    source = task["input"]["context"]["audio_source"]
    media, extras = "audio/wav", {}
    if variant == "model":
        task["model"] = "different-model"
    elif variant == "hash":
        source["content_hash"] = "b" * 64
        source["source_id"] = f"audio:{source['asset_id']}:{source['content_hash'][:12]}"
    elif variant == "short":
        raw = raw[:-1]
    elif variant == "size":
        source["byte_size"] = 1025
    elif variant == "duration":
        source["duration_ms"] = 300001
    elif variant == "store":
        task["store"] = True
    elif variant == "source_id":
        source["source_id"] = "audio:other:forged"
    elif variant == "feature":
        task["feature_key"] = "ecg_analysis"
    elif variant == "media":
        media = "audio/mpeg"
    elif variant == "extra_field":
        extras["other"] = "not allowed"
    else:
        raw = b"x" * 120000
    calls = []

    async def execute(*args):
        calls.append(args)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=speech_server.create_speech_app(config(tmp_path, max_bytes=1024), executor=execute)), base_url="http://speech") as client:
        response = await client.post("/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task), **extras}, files={"audio": ("recording.wav", raw, media)})
    assert response.status_code in {409, 413, 422}, response.text
    assert not calls and KEY not in response.text


@pytest.mark.asyncio
async def test_busy_service_rejects_another_request_without_queuing_or_repeating_audio(tmp_path, descriptor):
    started, finish = asyncio.Event(), asyncio.Event()
    count = 0

    async def execute(*args):
        nonlocal count
        count += 1
        started.set()
        await finish.wait()
        return {"isolated_executor": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=speech_server.create_speech_app(config(tmp_path), executor=execute)), base_url="http://speech") as client:
        options = {"headers": {"Authorization": "Bearer " + KEY}, "data": {"task": json.dumps(task_for())}, "files": {"audio": ("r.wav", b"RIFF-fixture-not-real-speech", "audio/wav")}}
        first = asyncio.create_task(client.post("/tasks", **options))
        await asyncio.wait_for(started.wait(), 3)
        try:
            second = await client.post("/tasks", **options)
            assert second.status_code == 429 and count == 1
        finally:
            finish.set()
            assert (await first).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_or_cancellation_kills_child_group_and_keeps_credentials_out_of_environment(cancel, monkeypatch):
    started = asyncio.Event()
    killed = []

    class Child:
        pid = 123456789
        returncode = None

        async def communicate(self, raw):
            assert b"offline-child" in raw
            started.set()
            await asyncio.Event().wait()

        async def wait(self):
            self.returncode = -9

    async def spawn(*args, **kwargs):
        assert KEY not in json.dumps(kwargs["env"])
        assert "DATABASE_URL" not in kwargs["env"] and kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert kwargs["start_new_session"] is True
        return Child()

    monkeypatch.setattr(speech_server.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(speech_server.os, "killpg", lambda *args: killed.append(args))
    job = {"config": {"cpu_threads": 1, "max_duration_seconds": 10, "AI_PROVIDER_LOCAL_SPEECH_API_KEY": "offline-child"}}
    job_task = asyncio.create_task(speech_server.execute_job(job, 30 if cancel else 0.01))
    await started.wait()
    if cancel:
        job_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job_task
    else:
        with pytest.raises(speech_server.HTTPException) as exc:
            await job_task
        assert exc.value.status_code == 504
    assert killed and killed[0][0] == Child.pid
