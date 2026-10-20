"""Synthetic native pixels and isolated executors test the optional image service boundary."""

import asyncio
import hashlib
import json
import os
import signal
import subprocess
import sys
from array import array
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.ai import imaging_config, imaging_server
from app.ai.imaging_config import ImagingSettings
from app.ai.imaging_model import REPOSITORY, REVISION

KEY = "fixture-imaging-service-credential-at-least-32-characters"
RUNTIME = "c" * 64


def test_service_settings_ignore_dotenv_and_import_no_hospital_or_ml_runtime(tmp_path):
    (tmp_path / ".env").write_text("DATABASE_URL=synthetic-hospital-secret-must-not-load\nIMAGING_CPU_THREADS=15\nAI_PROVIDER_LOCAL_IMAGING_API_KEY=synthetic-dotenv-secret\n")
    project = Path(__file__).resolve().parents[1]
    environment = {key: value for key, value in os.environ.items() if key in {"PATH", "SYSTEMROOT", "LD_LIBRARY_PATH", "LANG", "LC_ALL"}}
    environment.update({"PYTHONPATH": str(project), "IMAGING_MODEL_DIR": "relative-model", "AI_PROVIDER_LOCAL_IMAGING_API_KEY": KEY})
    code = """
import sys
from pathlib import Path
from app.ai import imaging_config, imaging_contract, imaging_preprocessing, imaging_server
assert not {'app.config', 'app.database', 'app.models', 'torch', 'numpy', 'safetensors'}.intersection(sys.modules)
assert imaging_config.ImagingSettings.model_config['env_file'] is None
config = imaging_config.ImagingSettings()
assert config.cpu_threads == 4
assert config.model_dir == Path.cwd() / 'relative-model'
assert config.api_key.get_secret_value().startswith('fixture-imaging-service-')
print('isolated image settings and imports passed')
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=environment, check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "isolated image settings and imports passed"
    assert "synthetic-hospital-secret" not in result.stdout + result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cpu_threads", "max_bytes", "timeout_seconds", "model", "dependencies", "implementation", "recipe"])
async def test_actual_runtime_descriptor_and_config_changes_disable_stale_service(change, tmp_path, monkeypatch):
    manifest = SimpleNamespace(digest="a" * 64, repository=REPOSITORY, revision=REVISION)
    versions = {"torch": "2.14.1+cpu", "numpy": "2.4.4", "safetensors": "0.8.0"}
    monkeypatch.setattr(imaging_config, "verify_model", lambda _: manifest)
    monkeypatch.setattr(imaging_config, "version", lambda name: versions[name])
    service_config, calls = config(tmp_path), []

    async def execute(*args):
        calls.append(args)

    app = imaging_server.create_imaging_app(service_config, executor=execute)
    if change == "cpu_threads":
        service_config.cpu_threads = 2
    elif change == "max_bytes":
        service_config.max_bytes = 1024
    elif change == "timeout_seconds":
        service_config.timeout_seconds = 3
    elif change == "model":
        manifest.digest = "b" * 64
    elif change == "dependencies":
        versions["numpy"] = "2.5.4"
    elif change == "implementation":
        original_read = Path.read_bytes
        monkeypatch.setattr(Path, "read_bytes", lambda path: original_read(path) + (b"\nsynthetic implementation change" if path.name == "imaging_worker.py" else b""))
    else:
        monkeypatch.setattr(imaging_config, "PREPROCESSING", {**imaging_config.PREPROCESSING, "synthetic_change": "must invalidate identity"})
    raw, source = native_case()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://imaging") as client:
        results = [
            await client.get("/health/ready"),
            await client.get("/capabilities", headers={"Authorization": "Bearer " + KEY}),
            await client.post("/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task_for(source))}, files={"image": ("pixels.i32le", raw, "application/octet-stream")}),
        ]
    assert all(response.status_code == 503 for response in results) and not calls
    assert all(KEY not in response.text and str(tmp_path) not in response.text for response in results)


def bind_source(raw, source):
    """Bind synthetic actual int32LE samples and original-source provenance."""
    source["pixel_hash"] = hashlib.sha256(raw).hexdigest()
    source["pixel_byte_size"] = len(raw)
    source["byte_size"] = source["original_byte_size"] + len(raw)
    identity = {"format": "dicom_i32le_v1", "original_hash": source["original_hash"], "pixel_hash": source["pixel_hash"]}
    source["content_hash"] = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    source["source_id"] = f"image:{source['asset_id']}:{source['content_hash'][:12]}"
    return source


def native_case(*, rows=224, columns=225, modality="DX", bits_stored=12, monochrome="MONOCHROME2"):
    """All metadata are technical parser fields; this is not a patient chest radiograph."""
    count, maximum = rows * columns, (1 << bits_stored) - 1
    values = array("i", ((index * 13) % (maximum + 1) for index in range(count)))
    if sys.byteorder != "little":
        values.byteswap()
    raw = values.tobytes()
    original = b"Synthetic original-image identity, never supplied to the model." * 16
    source = {
        "asset_id": "12345678-1234-4234-8234-123456789012",
        "imaging_order_id": "22345678-1234-4234-8234-123456789012",
        "order_status": 0,
        "original_hash": hashlib.sha256(original).hexdigest(),
        "original_byte_size": len(original),
        "image_metadata": {
            "format": "dicom_i32le_v1",
            "rows": rows,
            "columns": columns,
            "frames": 1,
            "bits_allocated": 8 if bits_stored == 8 else 16,
            "bits_stored": bits_stored,
            "high_bit": bits_stored - 1,
            "pixel_representation": 0,
            "photometric_interpretation": monochrome,
            "transfer_syntax_uid": "1.2.840.10008.1.2.1",
            "sop_class_uid": "1.2.840.10008.5.1.4.1.1.1.1" if modality == "DX" else "1.2.840.10008.5.1.4.1.1.1",
            "rescale_slope": 1.0,
            "rescale_intercept": 0.0,
            "rescale_declared": True,
            "rescale_type": "unknown",
            "window_presets": [{"center": 13812345678.0, "width": 999.0}],
            "voi_lut_function": "LINEAR",
            "padding": None,
            "presentation_lut_shape": "INVERSE" if monochrome == "MONOCHROME1" else "IDENTITY",
            "invert_display": monochrome == "MONOCHROME1",
            "presentation_intent_type": "FOR PRESENTATION",
            "valid_min_stored": 0,
            "valid_max_stored": maximum if count >= maximum + 1 else max((index * 13) % (maximum + 1) for index in range(count)),
            "valid_pixel_count": count,
            "modality": modality,
            "body_part_examined": "CHEST",
            "view_position": "PA",
            "image_laterality": "unknown",
            "burned_in_annotation": "unknown",
            "coordinate_space": "source_pixels",
            "orientation": "stored_row_column_unmodified",
            "study_uid_hash": hashlib.sha256(b"synthetic study").hexdigest(),
            "series_uid_hash": hashlib.sha256(b"synthetic series").hexdigest(),
            "instance_uid_hash": hashlib.sha256(b"synthetic instance").hexdigest(),
            "pixel_spacing_mm": None,
            "imager_pixel_spacing_mm": None,
        },
    }
    return raw, bind_source(raw, source)


def task_for(source=None):
    if source is None:
        _, source = native_case()
    return {
        "schema_version": "4",
        "feature_key": "imaging_detection",
        "engine": "vision",
        "model": "xrv:" + RUNTIME,
        "instructions": "完整系统与独立心电任务Prompt，仅用于隔离协议验证，不构成诊疗指示",
        "store": False,
        "input": {"context": {"image_source": source}, "input": {"question": "不能把问题或头注释补造为原始心电"}, "evidence": []},
    }


def config(tmp_path, **options):
    return ImagingSettings(model_dir=tmp_path / "not-real-weights", AI_PROVIDER_LOCAL_IMAGING_API_KEY=KEY, **options)


@pytest.fixture
def descriptor(monkeypatch):
    value = {"schema_version": "4", "feature_key": "imaging_detection", "model_version": "xrv:" + RUNTIME, "clinical_validation": "not_provided"}
    monkeypatch.setattr(imaging_server, "runtime_descriptor", lambda _: value)
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["version", "missing_weights"])
async def test_changed_runtime_cannot_keep_serving_stale_capabilities_or_accept_new_tasks(change, tmp_path, descriptor, monkeypatch):
    calls = []

    async def execute(*args):
        calls.append(args)

    app = imaging_server.create_imaging_app(config(tmp_path), executor=execute)
    if change == "version":
        monkeypatch.setattr(imaging_server, "runtime_descriptor", lambda _: {**descriptor, "model_version": "xrv:" + "f" * 64})
    else:

        def missing(_):
            raise ValueError("private-model-path-and-secret-must-not-escape")

        monkeypatch.setattr(imaging_server, "runtime_descriptor", missing)
    raw, source = native_case()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://imaging") as client:
        responses = [
            await client.get("/health/ready"),
            await client.get("/capabilities", headers={"Authorization": "Bearer " + KEY}),
            await client.post("/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task_for(source))}, files={"image": ("pixels.i32le", raw, "application/octet-stream")}),
        ]
    assert all(response.status_code == 503 and "private-model-path" not in response.text for response in responses)
    assert not calls


@pytest.mark.asyncio
async def test_authentication_precedes_parsing_and_capabilities_contain_no_secret_or_model_path(tmp_path, descriptor):
    calls = []

    async def execute(*args):
        calls.append(args)

    app = imaging_server.create_imaging_app(config(tmp_path), executor=execute)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://imaging") as client:
        assert (await client.get("/health/ready")).json() == {"ready": True}
        assert (await client.get("/capabilities")).status_code == 401
        assert (await client.post("/tasks", content=b"not multipart or valid JSON")).status_code == 401
        assert (await client.post("/tasks", headers={"Authorization": "Bearer wrong"}, content=b"x" * 120000)).status_code == 401
        response = await client.get("/capabilities", headers={"Authorization": "Bearer " + KEY})
    assert response.status_code == 200 and response.json() == descriptor and not calls
    assert KEY not in response.text and str(tmp_path) not in response.text


@pytest.mark.asyncio
async def test_actual_native_bytes_are_private_then_removed_and_job_contains_digest_without_prompt_question_or_service_key(tmp_path, descriptor, monkeypatch):
    raw, source = native_case()
    task = task_for(source)
    paths = []
    monkeypatch.chdir(tmp_path)
    service_config = ImagingSettings(model_dir=Path("relative-weights"), AI_PROVIDER_LOCAL_IMAGING_API_KEY=KEY)

    async def execute(job, timeout):
        path = Path(job["image_path"])
        paths.append(path)
        assert path.read_bytes() == raw and path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700 and path.name == "pixels.i32le"
        assert job["source"] == source and timeout == 60
        assert job["instructions_digest"] == hashlib.sha256(task["instructions"].encode()).hexdigest()
        assert job["config"]["model_dir"] == str(tmp_path / "relative-weights")
        serialized = json.dumps(job, ensure_ascii=False)
        assert KEY not in serialized and "完整系统" not in serialized and "不能把问题" not in serialized
        assert "potential-patient-name" not in serialized
        assert set(job) == {"image_path", "source", "model_version", "instructions_digest", "config"}
        return {"isolated_executor": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=imaging_server.create_imaging_app(service_config, executor=execute)), base_url="http://imaging") as client:
        response = await client.post(
            "/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task)}, files={"image": ("potential-patient-name.i32le", raw, "application/octet-stream")}
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
        "duplicate_image",
        "signed",
        "slope",
        "intercept",
        "body_part",
        "view",
        "sop_mismatch",
        "frames",
        "float_dimension",
        "bits_stored",
        "metadata_extra",
        "canceled",
        "bad_order",
        "valid_count",
        "oversized_body",
        "oversized_task",
    ],
)
async def test_invalid_native_scope_and_multipart_inputs_never_start_executor_and_remove_partial_files(variant, tmp_path, descriptor, monkeypatch):
    raw, source = native_case()
    task = task_for(source)
    metadata = source["image_metadata"]
    media, extras = "application/octet-stream", []
    if variant == "model":
        task["model"] = "different-model"
    elif variant == "hash":
        bind_source(b"x" * len(raw), source)
    elif variant == "short":
        raw = raw[:-4]
    elif variant == "long":
        raw += b"xxxx"
    elif variant == "store":
        task["store"] = True
    elif variant == "source_id":
        source["source_id"] = "image:other:forged"
    elif variant == "combined_hash":
        source["content_hash"] = "0" * 64
        source["source_id"] = f"image:{source['asset_id']}:{source['content_hash'][:12]}"
    elif variant == "feature":
        task["feature_key"] = "medical_transcription"
    elif variant == "media":
        media = "application/dicom"
    elif variant == "extra_field":
        extras = [("other", (None, "not allowed"))]
    elif variant == "signed":
        metadata["pixel_representation"] = 1
    elif variant in {"slope", "intercept"}:
        metadata["rescale_" + variant] = 2.0
    elif variant == "body_part":
        metadata["body_part_examined"] = "ABDOMEN"
    elif variant == "view":
        metadata["view_position"] = "LL"
    elif variant == "sop_mismatch":
        metadata["modality"] = "CR"
    elif variant == "frames":
        metadata["frames"] = 2
    elif variant == "float_dimension":
        metadata["rows"] = float(metadata["rows"])
    elif variant == "bits_stored":
        metadata["bits_stored"] = 7
    elif variant == "metadata_extra":
        metadata["PatientName"] = "do-not-forward-synthetic-identity"
    elif variant == "canceled":
        source["order_status"] = 5
    elif variant == "bad_order":
        source["imaging_order_id"] = "not-real-order"
    elif variant == "valid_count":
        metadata["valid_pixel_count"] -= 1
    elif variant == "oversized_body":
        raw = b"x" * (224 * 225 * 4 + imaging_server.MAX_TASK_BYTES + 16384)
    elif variant == "oversized_task":
        task["instructions"] = "界" * 40000
    parts = [("task", (None, json.dumps(task))), ("image", ("pixels.i32le", raw, media)), *extras]
    if variant == "duplicate_task":
        parts.insert(0, ("task", (None, json.dumps(task))))
    elif variant == "duplicate_image":
        parts.append(("image", ("another.i32le", raw, media)))
    calls, directories = [], []
    original_directory = imaging_server.tempfile.TemporaryDirectory

    def tracked_directory(*args, **kwargs):
        directory = original_directory(*args, dir=tmp_path, **kwargs)
        directories.append(Path(directory.name))
        return directory

    monkeypatch.setattr(imaging_server.tempfile, "TemporaryDirectory", tracked_directory)

    async def execute(*args):
        calls.append(args)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=imaging_server.create_imaging_app(config(tmp_path, max_bytes=224 * 225 * 4), executor=execute)), base_url="http://imaging"
    ) as client:
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

    app = imaging_server.create_imaging_app(config(tmp_path, max_bytes=1024), executor=execute)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://imaging") as client:
        response = await client.post(
            "/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task_for(source))}, files={"image": ("pixels.i32le", raw, "application/octet-stream")}
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

    app = imaging_server.create_imaging_app(config(tmp_path), executor=execute)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://imaging") as client:
        first = asyncio.create_task(
            client.post("/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task_for(source))}, files={"image": ("pixels.i32le", raw, "application/octet-stream")})
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
        path = Path(job["image_path"])
        paths.append(path)
        assert path.exists()
        started.set()
        if failure == "executor":
            raise imaging_server.HTTPException(503, "isolated executor unavailable")
        await asyncio.Event().wait()

    app = imaging_server.create_imaging_app(config(tmp_path), executor=execute)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://imaging") as client:
        request = asyncio.create_task(
            client.post("/tasks", headers={"Authorization": "Bearer " + KEY}, data={"task": json.dumps(task_for(source))}, files={"image": ("pixels.i32le", raw, "application/octet-stream")})
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
    monkeypatch.setenv("DATABASE_URL", "must-not-reach-imaging-child")
    monkeypatch.setenv("AI_PROVIDER_LOCAL_IMAGING_API_KEY", KEY)
    monkeypatch.setenv("UNRELATED_SERVICE_SECRET", "must-not-reach-imaging-child")

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
        assert args[1:] == ("-m", "app.ai.imaging_worker")
        environment = kwargs["env"]
        assert KEY not in json.dumps(environment)
        assert not {"DATABASE_URL", "AI_PROVIDER_LOCAL_IMAGING_API_KEY", "UNRELATED_SERVICE_SECRET"}.intersection(environment)
        assert environment["HF_HUB_OFFLINE"] == "1" and environment["HF_HUB_DISABLE_TELEMETRY"] == "1"
        assert environment["OMP_NUM_THREADS"] == environment["MKL_NUM_THREADS"] == "2"
        assert kwargs["start_new_session"] is True and kwargs["stderr"] is asyncio.subprocess.DEVNULL
        child = Child()
        children.append(child)
        return child

    monkeypatch.setattr(imaging_server.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(imaging_server.os, "killpg", lambda *args: killed.append(args))
    job = {"config": {"cpu_threads": 2, "AI_PROVIDER_LOCAL_IMAGING_API_KEY": "offline-child"}}
    task = asyncio.create_task(imaging_server.execute_job(job, 30 if cancel else 0.01))
    await asyncio.wait_for(started.wait(), 3)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(imaging_server.HTTPException) as exc:
            await task
        assert exc.value.status_code == 504
    assert killed == [(Child.pid, signal.SIGKILL)] and children[0].returncode == -9
