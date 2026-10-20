"""Synthetic native signals and isolated executors test the optional ECG service boundary."""

import asyncio
import hashlib
import json
import signal
import sys
from array import array
from pathlib import Path

import httpx
import pytest

from app.ai import ecg_server
from app.ai.ecg_config import ECGSettings
from app.ai.ecg_model import LEADS

KEY = "fixture-ecg-service-credential-at-least-32-characters"
RUNTIME = "c" * 64


def bind_source(raw, source):
    """Bind entirely synthetic native bytes without requiring an actual header or patient."""
    source["signal_hash"] = hashlib.sha256(raw).hexdigest()
    identity = {"format": "wfdb16", "header_hash": source["header_hash"], "signal_hash": source["signal_hash"]}
    source["content_hash"] = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    source["source_id"] = f"ecg:{source['asset_id']}:{source['content_hash'][:12]}"
    return source


def native_case(*, reordered=False):
    names = LEADS[5:] + LEADS[:5] if reordered else list(LEADS)
    leads = []
    for name in names:
        index = LEADS.index(name)
        leads.append({"name": name, "gain": ["1000", "2", "1000000"][index % 3], "baseline": -350 + index * 40, "unit": ["mV", "uV", "V"][index % 3], "missing_samples": 0})
    values = array("h", (((sample * (LEADS.index(lead["name"]) + 1)) % 1800) - 900 + lead["baseline"] for sample in range(1000) for lead in leads))
    if sys.byteorder != "little":
        values.byteswap()
    raw = values.tobytes()
    source = {
        "asset_id": "12345678-1234-4234-8234-123456789012",
        "header_hash": hashlib.sha256(b"synthetic calibration header identity; no patient").hexdigest(),
        "signal_byte_size": 24000,
        "signal_metadata": {"format": "wfdb16", "sample_rate_hz": "100", "sample_count": 1000, "channels": 12, "duration_ms": 10000, "missing_sample_value": -32768, "leads": leads},
    }
    return raw, bind_source(raw, source)


def task_for(source=None):
    if source is None:
        _, source = native_case()
    return {
        "schema_version": "3",
        "feature_key": "ecg_analysis",
        "engine": "signal",
        "model": "ssl-ecg:" + RUNTIME,
        "instructions": "完整系统与独立心电任务Prompt，仅用于隔离协议验证，不构成诊疗指示",
        "store": False,
        "input": {"context": {"ecg_source": source}, "input": {"question": "不能把问题或头注释补造为原始心电"}, "evidence": []},
    }


def config(tmp_path, **options):
    return ECGSettings(model_dir=tmp_path / "not-real-weights", AI_PROVIDER_LOCAL_ECG_API_KEY=KEY, **options)


@pytest.fixture
def descriptor(monkeypatch):
    value = {"schema_version": "3", "feature_key": "ecg_analysis", "model_version": "ssl-ecg:" + RUNTIME, "clinical_validation": "not_provided"}
    monkeypatch.setattr(ecg_server, "runtime_descriptor", lambda _: value)
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["version", "missing_weights"])
async def test_changed_runtime_cannot_keep_serving_stale_capabilities_or_accept_new_tasks(change, tmp_path, descriptor, monkeypatch):
    calls = []

    async def execute(*args):
        calls.append(args)

    app = ecg_server.create_ecg_app(config(tmp_path), executor=execute)
    if change == "version":
        monkeypatch.setattr(ecg_server, "runtime_descriptor", lambda _: {**descriptor, "model_version": "ssl-ecg:" + "f" * 64})
    else:

        def missing(_):
            raise ValueError("private-model-path-and-secret-must-not-escape")

        monkeypatch.setattr(ecg_server, "runtime_descriptor", missing)
    raw, source = native_case()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ecg") as client:
        responses = [
            await client.get("/health/ready"),
            await client.get("/capabilities", headers={"Authorization": "Bearer " + KEY}),
            await client.post("/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task_for(source))}, files={"waveform": ("signal.dat", raw, "application/octet-stream")}),
        ]
    assert all(response.status_code == 503 and "private-model-path" not in response.text for response in responses)
    assert not calls


@pytest.mark.asyncio
async def test_authentication_precedes_parsing_and_capabilities_contain_no_secret_or_model_path(tmp_path, descriptor):
    calls = []

    async def execute(*args):
        calls.append(args)

    app = ecg_server.create_ecg_app(config(tmp_path), executor=execute)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ecg") as client:
        assert (await client.get("/health/ready")).json() == {"ready": True}
        assert (await client.get("/capabilities")).status_code == 401
        assert (await client.post("/tasks", content=b"not multipart or valid JSON")).status_code == 401
        assert (await client.post("/tasks", headers={"Authorization": "Bearer wrong"}, content=b"x" * 120000)).status_code == 401
        response = await client.get("/capabilities", headers={"Authorization": "Bearer " + KEY})
    assert response.status_code == 200 and response.json() == descriptor and not calls
    assert KEY not in response.text and str(tmp_path) not in response.text


@pytest.mark.asyncio
async def test_actual_native_bytes_are_private_then_removed_and_job_contains_digest_without_prompt_question_or_service_key(tmp_path, descriptor, monkeypatch):
    raw, source = native_case(reordered=True)
    task = task_for(source)
    paths = []
    monkeypatch.chdir(tmp_path)
    service_config = ECGSettings(model_dir=Path("relative-weights"), AI_PROVIDER_LOCAL_ECG_API_KEY=KEY)

    async def execute(job, timeout):
        path = Path(job["waveform_path"])
        paths.append(path)
        assert path.read_bytes() == raw and path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700 and path.name == "signal.dat"
        assert job["source"] == source and timeout == 30
        assert job["instructions_digest"] == hashlib.sha256(task["instructions"].encode()).hexdigest()
        assert job["config"]["model_dir"] == str(tmp_path / "relative-weights")
        serialized = json.dumps(job, ensure_ascii=False)
        assert KEY not in serialized and "完整系统" not in serialized and "不能把问题" not in serialized
        assert "potential-patient-name" not in serialized
        assert set(job) == {"waveform_path", "source", "model_version", "instructions_digest", "config"}
        return {"isolated_executor": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ecg_server.create_ecg_app(service_config, executor=execute)), base_url="http://ecg") as client:
        response = await client.post(
            "/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task)}, files={"waveform": ("potential-patient-name.dat", raw, "application/octet-stream")}
        )
    assert response.status_code == 200 and response.json() == {"isolated_executor": True}
    assert len(paths) == 1 and not paths[0].parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant",
    [
        "model",
        "hash",
        "short",
        "long",
        "store",
        "source_id",
        "combined_hash",
        "feature",
        "media",
        "extra_field",
        "duplicate_task",
        "duplicate_waveform",
        "missing_lead",
        "MLII",
        "rate",
        "fractional_rate",
        "duration",
        "sample_count",
        "missing_declared",
        "oversized_body",
        "oversized_task",
    ],
)
async def test_invalid_native_scope_and_multipart_inputs_never_start_executor_and_remove_partial_files(variant, tmp_path, descriptor, monkeypatch):
    raw, source = native_case()
    task = task_for(source)
    metadata = source["signal_metadata"]
    media, extras = "application/octet-stream", []
    if variant == "model":
        task["model"] = "different-model"
    elif variant == "hash":
        # Keep the declared identity internally consistent while sending different actual bytes.
        bind_source(b"x" * len(raw), source)
    elif variant == "short":
        raw = raw[:-2]
    elif variant == "long":
        raw += b"xx"
    elif variant == "store":
        task["store"] = True
    elif variant == "source_id":
        source["source_id"] = "ecg:other:forged"
    elif variant == "combined_hash":
        source["content_hash"] = "0" * 64
        source["source_id"] = f"ecg:{source['asset_id']}:{source['content_hash'][:12]}"
    elif variant == "feature":
        task["feature_key"] = "medical_transcription"
    elif variant == "media":
        media = "text/plain"
    elif variant == "extra_field":
        extras = [("other", (None, "not allowed"))]
    elif variant == "missing_lead":
        metadata["leads"].pop()
    elif variant == "MLII":
        metadata["leads"][1]["name"] = "MLII"
    elif variant in {"rate", "fractional_rate"}:
        metadata["sample_rate_hz"] = "250" if variant == "rate" else "100.1"
    elif variant == "duration":
        metadata["duration_ms"] = 10001
    elif variant == "sample_count":
        metadata["sample_count"] = 999
    elif variant == "missing_declared":
        metadata["leads"][0]["missing_samples"] = 1
    elif variant == "oversized_body":
        raw = b"x" * 150000
    elif variant == "oversized_task":
        task["instructions"] = "界" * 40000
    parts = [("task", (None, json.dumps(task))), ("waveform", ("signal.dat", raw, media)), *extras]
    if variant == "duplicate_task":
        parts.insert(0, ("task", (None, json.dumps(task))))
    elif variant == "duplicate_waveform":
        parts.append(("waveform", ("another.dat", raw, media)))
    calls, directories = [], []
    original_directory = ecg_server.tempfile.TemporaryDirectory

    def tracked_directory(*args, **kwargs):
        directory = original_directory(*args, dir=tmp_path, **kwargs)
        directories.append(Path(directory.name))
        return directory

    monkeypatch.setattr(ecg_server.tempfile, "TemporaryDirectory", tracked_directory)

    async def execute(*args):
        calls.append(args)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ecg_server.create_ecg_app(config(tmp_path, max_bytes=24000), executor=execute)), base_url="http://ecg") as client:
        response = await client.post("/tasks", headers={"Authorization": "Bearer " + KEY}, files=parts)
    assert response.status_code in {409, 413, 422}, response.text
    assert not calls and KEY not in response.text
    assert all(not directory.exists() for directory in directories)


@pytest.mark.asyncio
async def test_deployment_byte_limit_is_checked_before_executor(tmp_path, descriptor):
    raw, source = native_case()
    calls = []

    async def execute(*args):
        calls.append(args)

    app = ecg_server.create_ecg_app(config(tmp_path, max_bytes=1024), executor=execute)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ecg") as client:
        response = await client.post(
            "/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task_for(source))}, files={"waveform": ("signal.dat", raw, "application/octet-stream")}
        )
    assert response.status_code == 413 and not calls


@pytest.mark.asyncio
async def test_busy_service_rejects_second_request_before_parsing_and_does_not_repeat_inference(tmp_path, descriptor):
    raw, source = native_case()
    started, finish = asyncio.Event(), asyncio.Event()
    count = 0

    async def execute(*args):
        nonlocal count
        count += 1
        started.set()
        await finish.wait()
        return {"isolated_executor": True}

    app = ecg_server.create_ecg_app(config(tmp_path), executor=execute)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ecg") as client:
        first = asyncio.create_task(
            client.post("/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task_for(source))}, files={"waveform": ("signal.dat", raw, "application/octet-stream")})
        )
        await asyncio.wait_for(started.wait(), 3)
        try:
            second = await client.post("/tasks", headers={"Authorization": "Bearer " + KEY}, content=b"not a multipart request")
            assert second.status_code == 429 and count == 1
        finally:
            finish.set()
            assert (await first).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["executor", "cancel"])
async def test_executor_failure_and_request_cancellation_remove_native_tempfiles(failure, tmp_path, descriptor):
    raw, source = native_case()
    paths, started = [], asyncio.Event()

    async def execute(job, _):
        path = Path(job["waveform_path"])
        paths.append(path)
        assert path.exists()
        started.set()
        if failure == "executor":
            raise ecg_server.HTTPException(503, "isolated executor unavailable")
        await asyncio.Event().wait()

    app = ecg_server.create_ecg_app(config(tmp_path), executor=execute)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ecg") as client:
        request = asyncio.create_task(
            client.post("/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task_for(source))}, files={"waveform": ("signal.dat", raw, "application/octet-stream")})
        )
        await asyncio.wait_for(started.wait(), 3)
        if failure == "executor":
            assert (await request).status_code == 503
        else:
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
    assert len(paths) == 1 and not paths[0].parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_and_cancellation_kill_child_group_and_strip_credentials_from_environment(cancel, monkeypatch):
    started, killed, children = asyncio.Event(), [], []
    monkeypatch.setenv("DATABASE_URL", "must-not-reach-ecg-child")
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ECG_API_KEY", KEY)
    monkeypatch.setenv("UNRELATED_SERVICE_SECRET", "must-not-reach-ecg-child")

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
        assert args[1:] == ("-m", "app.ai.ecg_worker")
        environment = kwargs["env"]
        assert KEY not in json.dumps(environment)
        assert not {"DATABASE_URL", "AI_PROVIDER_LOCAL_ECG_API_KEY", "UNRELATED_SERVICE_SECRET"}.intersection(environment)
        assert environment["HF_HUB_OFFLINE"] == "1" and environment["HF_HUB_DISABLE_TELEMETRY"] == "1"
        assert environment["OMP_NUM_THREADS"] == environment["MKL_NUM_THREADS"] == "2"
        assert kwargs["start_new_session"] is True and kwargs["stderr"] is asyncio.subprocess.DEVNULL
        child = Child()
        children.append(child)
        return child

    monkeypatch.setattr(ecg_server.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(ecg_server.os, "killpg", lambda *args: killed.append(args))
    job = {"config": {"cpu_threads": 2, "AI_PROVIDER_LOCAL_ECG_API_KEY": "offline-child"}}
    task = asyncio.create_task(ecg_server.execute_job(job, 30 if cancel else 0.01))
    await asyncio.wait_for(started.wait(), 3)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(ecg_server.HTTPException) as exc:
            await task
        assert exc.value.status_code == 504
    assert killed == [(Child.pid, signal.SIGKILL)] and children[0].returncode == -9
