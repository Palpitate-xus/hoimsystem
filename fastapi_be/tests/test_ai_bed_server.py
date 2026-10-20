"""Actual independent ASGI authentication, strict schema11 and runtime boundaries."""

import asyncio
import hashlib
import os
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest

from app.ai import bed_server
from app.ai.bed_config import BedSettings, runtime_descriptor
from app.ai.bed_contract import BedAnalysis, canonical_json
from app.ai.bed_model import generation_result_for_analysis, validate_analysis_binding
from tests.test_ai_bed_contract import make_source

KEY = "synthetic-bed-key-never-use-in-production-000"
HEADERS = {"authorization": "Bearer " + KEY}


def settings(**extra):
    return BedSettings(AI_PROVIDER_LOCAL_BED_API_KEY=KEY, **extra)


def task(value=None, horizon=7):
    return {
        "schema_version": "11",
        "feature_key": "bed_forecast",
        "engine": "prediction",
        "model": runtime_descriptor()["model_version"],
        "instructions": "固定物理占床统计，仅作Prompt溯源。",
        "store": False,
        "input": {"context": {"bed_source": value if value is not None else make_source()}, "horizon_days": horizon},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("horizon", [7, 14])
async def test_actual_asgi_native_complete_numeric_binding_and_fixed_explanation(horizon):
    body = task(horizon=horizon)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bed_server.create_bed_app(settings())), base_url="http://bed") as client:
        response = await client.post("/tasks", headers=HEADERS, json=body)
    assert response.status_code == 200, response.text
    value = response.json()
    assert set(value) == {"schema_version", "feature_key", "model_version", "handled", "result", "bed_analysis", "usage"}
    assert value["schema_version"] == "11" and value["handled"] is True
    assert value["usage"] == {"input_tokens": 0, "output_tokens": 0}
    analysis = BedAnalysis.model_validate(value["bed_analysis"])
    validate_analysis_binding(
        analysis,
        body["input"]["context"]["bed_source"],
        horizon,
        hashlib.sha256(body["instructions"].encode()).hexdigest(),
        body["model"],
    )
    assert value["result"] == generation_result_for_analysis(analysis)
    assert "bed_analysis" not in value["result"] and len(response.content) > 65535


@pytest.mark.asyncio
async def test_capabilities_is_authenticated_metadata_without_inference(monkeypatch):
    def no_inference(*args, **kwargs):
        raise AssertionError("Capabilities must not execute a forecast")

    monkeypatch.setattr(bed_server, "compute_bed", no_inference)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bed_server.create_bed_app(settings())), base_url="http://bed") as client:
        assert (await client.get("/capabilities")).status_code == 401
        descriptor = (await client.get("/capabilities", headers=HEADERS)).json()
        assert (await client.get("/health/ready")).json() == {"ready": True}
    assert descriptor["schema_version"] == "11" and descriptor["feature_key"] == "bed_forecast"
    assert descriptor["forecast_only"] is True and descriptor["operational_validation"] == "not_provided"
    assert descriptor["model_version"].startswith("bed:") and len(descriptor["core_sha256"]) == 4
    assert descriptor["timeout_seconds"] == 90 and descriptor["max_response_bytes"] == 8 * 1024 * 1024


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation", ["store_zero", "store_true", "horizon_float", "horizon_string", "schema", "feature", "engine", "extra", "question", "source_extra", "wrong_model", "invalid_timezone"]
)
async def test_native_task_is_closed_and_never_mixes_other_modes(mutation):
    body = task()
    if mutation == "store_zero":
        body["store"] = 0
    elif mutation == "store_true":
        body["store"] = True
    elif mutation == "horizon_float":
        body["input"]["horizon_days"] = 7.0
    elif mutation == "horizon_string":
        body["input"]["horizon_days"] = "7"
    elif mutation in {"schema", "feature", "engine"}:
        body[{"schema": "schema_version", "feature": "feature_key", "engine": "engine"}[mutation]] = {"schema": "10", "feature": "visit_forecast", "engine": "optimizer"}[mutation]
    elif mutation == "extra":
        body["arbitrary_model_metadata"] = "untrusted"
    elif mutation == "question":
        body["input"]["context"]["question"] = "private free text must not be accepted"
    elif mutation == "source_extra":
        body["input"]["context"]["bed_source"]["patient_name"] = "private patient"
    elif mutation == "invalid_timezone":
        body["input"]["context"]["bed_source"]["timezone"] = "Invalid/Zone"
    else:
        body["model"] = "bed:" + "f" * 64
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bed_server.create_bed_app(settings())), base_url="http://bed") as client:
        response = await client.post("/tasks", headers=HEADERS, json=body)
    assert response.status_code == (409 if mutation == "wrong_model" else 422)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["duplicate_root", "duplicate_nested", "nan", "unicode"])
async def test_json_parser_rejects_ambiguous_or_invalid_original_bytes(mutation):
    raw = canonical_json(task())
    if mutation == "duplicate_root":
        raw = raw.replace('"store":false', '"store":false,"store":false')
    elif mutation == "duplicate_nested":
        raw = raw.replace('"horizon_days":7', '"horizon_days":7,"horizon_days":7')
    elif mutation == "nan":
        raw = raw.replace('"value":12', '"value":NaN')
    raw = b"\xff" if mutation == "unicode" else raw.encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bed_server.create_bed_app(settings())), base_url="http://bed") as client:
        response = await client.post("/tasks", headers={**HEADERS, "content-type": "application/json"}, content=raw)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_auth_and_content_type_and_streamed_utf8_size_limits():
    app = bed_server.create_bed_app(settings(max_request_bytes=65536))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bed") as client:
        assert (await client.post("/tasks", json={})).status_code == 401
        assert (await client.post("/tasks", headers=HEADERS, content="{}")).status_code == 422
        response = await client.post("/tasks", headers=HEADERS, json=task())
        assert response.status_code == 413


@pytest.mark.asyncio
async def test_runtime_or_environment_change_invalidates_metadata(monkeypatch):
    app = bed_server.create_bed_app(settings())
    monkeypatch.setenv("BED_TIMEOUT_SECONDS", "88")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bed") as client:
        assert (await client.get("/capabilities", headers=HEADERS)).status_code == 503


@pytest.mark.asyncio
async def test_timeout_retains_busy_slot_until_actual_worker_finishes(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def work(*args):
        started.set()
        release.wait(5)
        return {}

    monkeypatch.setattr(bed_server, "build_response", work)
    app = bed_server.create_bed_app(settings(timeout_seconds=1))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bed") as client:
        pending = asyncio.create_task(client.post("/tasks", headers=HEADERS, json=task()))
        assert await asyncio.to_thread(started.wait, 2)
        try:
            assert (await pending).status_code == 504
            assert (await client.post("/tasks", headers=HEADERS, json=task())).status_code == 429
        finally:
            release.set()
        await asyncio.sleep(0.05)
        assert (await client.post("/tasks", headers=HEADERS, json=task())).status_code == 200


def test_four_core_import_and_settings_cannot_read_dotenv_or_import_hospital_modules(tmp_path):
    script = """
import os,sys
from pathlib import Path
from pydantic_settings import BaseSettings
class Block:
 def find_spec(self,fullname,path=None,target=None):
  if fullname in ('app.config','app.database','app.models') or fullname.startswith(('app.ai.forecast_', 'app.ai.models')):
   raise AssertionError('No hospital or legacy forecast imports: '+fullname)
sys.meta_path.insert(0,Block())
def audit(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
  name=Path(os.fsdecode(args[0])).name
  if name=='.env' or name.startswith('.env.'):
   raise AssertionError('No dotenv reads')
sys.addaudithook(audit)
from app.ai.bed_contract import RECIPE
from app.ai.bed_model import compute_bed
from app.ai.bed_server import create_bed_app
from app.ai.bed_config import BedSettings
settings=BedSettings(AI_PROVIDER_LOCAL_BED_API_KEY='synthetic-strong-test-key-0000000000000')
assert settings.model_config['env_file'] is None
assert 'app.database' not in sys.modules and 'app.config' not in sys.modules
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1]), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
