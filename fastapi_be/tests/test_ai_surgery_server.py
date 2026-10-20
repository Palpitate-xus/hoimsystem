"""Real standalone ASGI protocol and no-env isolation, with synthetic facts only."""

import asyncio
import hashlib
import os
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest

from app.ai import surgery_server
from app.ai.surgery_config import SurgerySettings, runtime_descriptor
from app.ai.surgery_contract import SurgeryAnalysis, canonical_json
from app.ai.surgery_model import generation_result_for_analysis, validate_analysis_binding
from tests.test_ai_surgery_contract import source_dict

KEY = "synthetic-surgery-test-key-not-a-production-credential-0000"
HEADERS = {"authorization": "Bearer " + KEY}


def settings(**kwargs):
    return SurgerySettings(AI_PROVIDER_LOCAL_SURGERY_API_KEY=KEY, **kwargs)


def task(mode="all_required_then_min_declared_cost"):
    body = source_dict()
    body["objective_mode"] = mode
    return {
        "schema_version": "12",
        "feature_key": "surgery_scheduling",
        "engine": "optimizer",
        "model": runtime_descriptor()["model_version"],
        "instructions": "仅作固定声明排程和Prompt溯源。",
        "store": False,
        "input": {"context": {"surgery_source": body}},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["all_required_then_min_declared_cost", "max_optional_scheduled_then_min_declared_cost"])
async def test_actual_asgi_two_modes_complete_proof_and_fixed_result(mode):
    body = task(mode)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=surgery_server.create_surgery_app(settings())), base_url="http://surgery") as client:
        response = await client.post("/tasks", headers=HEADERS, json=body)
    assert response.status_code == 200, response.text
    value = response.json()
    assert set(value) == {"schema_version", "feature_key", "model_version", "handled", "result", "surgery_analysis", "usage"}
    assert value["handled"] is True and value["schema_version"] == "12"
    assert value["usage"] == {"input_tokens": 0, "output_tokens": 0}
    analysis = SurgeryAnalysis.model_validate(value["surgery_analysis"])
    validate_analysis_binding(analysis, body["input"]["context"]["surgery_source"], hashlib.sha256(body["instructions"].encode()).hexdigest(), body["model"])
    assert analysis.objective_mode == mode
    assert value["result"] == generation_result_for_analysis(analysis)
    assert "surgery_analysis" not in value["result"]


@pytest.mark.asyncio
async def test_authenticated_capability_metadata_never_executes_solver(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Metadata cannot execute inference")

    monkeypatch.setattr(surgery_server, "compute_surgery", reject)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=surgery_server.create_surgery_app(settings())), base_url="http://surgery") as client:
        assert (await client.get("/capabilities")).status_code == 401
        assert (await client.get("/health/ready")).json() == {"ready": True}
        response = await client.get("/capabilities", headers=HEADERS)
    assert response.status_code == 200
    metadata = response.json()
    assert metadata["schema_version"] == "12" and metadata["feature_key"] == "surgery_scheduling"
    assert metadata["candidate_only"] is True and metadata["automatic_booking"] is False
    assert metadata["clinical_validation"] == metadata["operational_validation"] == "not_provided"
    assert len(metadata["core_sha256"]) == 4 and metadata["model_version"].startswith("surgery:")
    assert metadata["timeout_seconds"] == 90 and metadata["max_request_bytes"] == metadata["max_response_bytes"] == 8 * 1024 * 1024


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "store_zero",
        "store_true",
        "schema",
        "feature",
        "engine",
        "extra",
        "question",
        "private_source",
        "foreign_domain",
        "wrong_model",
        "timezone",
        "numeric_cost",
        "boolean_count",
        "unknown_objective",
    ],
)
async def test_closed_task_rejects_coercion_phi_and_mixed_source_modes(mutation):
    body = task()
    source = body["input"]["context"]["surgery_source"]
    if mutation.startswith("store_"):
        body["store"] = 0 if mutation == "store_zero" else True
    elif mutation in ("schema", "feature", "engine"):
        body[{"schema": "schema_version", "feature": "feature_key", "engine": "engine"}[mutation]] = {"schema": "11", "feature": "bed_forecast", "engine": "prediction"}[mutation]
    elif mutation == "extra":
        body["untrusted_metadata"] = {}
    elif mutation == "question":
        body["input"]["context"]["question"] = "private free text"
    elif mutation == "private_source":
        source["patient_name"] = "synthetic private narrative"
    elif mutation == "foreign_domain":
        body["input"]["context"]["bed_source"] = {}
    elif mutation == "wrong_model":
        body["model"] = "surgery:" + "f" * 64
    elif mutation == "timezone":
        source["period"]["business_timezone"] = "Invalid/HospitalZone"
    elif mutation == "numeric_cost":
        source["cases"][0]["penalty_if_scheduled"]["value"] = 0
    elif mutation == "boolean_count":
        source["manifest"][0]["revision"] = True
    else:
        source["objective_mode"] = "random_greedy"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=surgery_server.create_surgery_app(settings())), base_url="http://surgery") as client:
        response = await client.post("/tasks", headers=HEADERS, json=body)
    assert response.status_code == (409 if mutation == "wrong_model" else 422)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["root_duplicate", "nested_duplicate", "nan", "infinity", "invalid_utf8"])
async def test_actual_raw_bytes_reject_duplicates_nonfinite_and_invalid_utf8(kind):
    raw = canonical_json(task())
    if kind == "root_duplicate":
        raw = raw.replace('"store":false', '"store":false,"store":false')
    elif kind == "nested_duplicate":
        raw = raw.replace('"required":true', '"required":true,"required":true')
    elif kind in ("nan", "infinity"):
        raw = raw.replace('"value":"0"', '"value":' + ("NaN" if kind == "nan" else "Infinity"), 1)
    raw = b"\xff" if kind == "invalid_utf8" else raw.encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=surgery_server.create_surgery_app(settings())), base_url="http://surgery") as client:
        response = await client.post("/tasks", headers={**HEADERS, "content-type": "application/json"}, content=raw)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_streamed_full_utf8_request_capacity_is_checked_before_parsing():
    app = surgery_server.create_surgery_app(settings(max_request_bytes=65536))
    body = task()
    body["instructions"] = "字" * 30000
    assert len(body["instructions"]) < 65536 < len(canonical_json(body).encode())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://surgery") as client:
        assert (await client.post("/tasks", json={})).status_code == 401
        assert (await client.post("/tasks", headers=HEADERS, content="{}")).status_code == 422
        assert (await client.post("/tasks", headers=HEADERS, content=canonical_json(body).encode(), extensions={})).status_code == 422
        assert (await client.post("/tasks", headers={**HEADERS, "content-type": "application/json"}, content=canonical_json(body).encode())).status_code == 413


@pytest.mark.asyncio
async def test_complete_response_utf8_capacity_never_truncates_success(monkeypatch):
    monkeypatch.setattr(surgery_server, "generation_result_for_analysis", lambda _: {"summary": "字" * 3000000, "sections": [], "warnings": [], "missing_data": []})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=surgery_server.create_surgery_app(settings())), base_url="http://surgery") as client:
        response = await client.post("/tasks", headers=HEADERS, json=task())
    assert response.status_code == 422 and "surgery_analysis" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("key,value", [("SURGERY_TIMEOUT_SECONDS", "88"), ("AI_PROVIDER_LOCAL_SURGERY_API_KEY", KEY + "changed"), ("PYTHONTZPATH", "/invalid/no-timezone")])
async def test_environment_drift_rejects_stale_runtime(monkeypatch, key, value):
    app = surgery_server.create_surgery_app(settings())
    monkeypatch.setenv(key, value)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://surgery") as client:
        assert (await client.get("/capabilities", headers=HEADERS)).status_code == 503


@pytest.mark.asyncio
async def test_timeout_keeps_slot_until_real_worker_completion(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def held(*args):
        started.set()
        release.wait(5)
        return {}

    monkeypatch.setattr(surgery_server, "build_response", held)
    app = surgery_server.create_surgery_app(settings(timeout_seconds=1))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://surgery") as client:
        pending = asyncio.create_task(client.post("/tasks", headers=HEADERS, json=task()))
        assert await asyncio.to_thread(started.wait, 2)
        try:
            assert (await pending).status_code == 504
            assert (await client.post("/tasks", headers=HEADERS, json=task())).status_code == 429
        finally:
            release.set()
        await asyncio.sleep(0.05)
        assert (await client.post("/tasks", headers=HEADERS, json=task())).status_code == 200


def test_actual_four_core_import_and_settings_cannot_read_dotenv_or_hospital_modules(tmp_path):
    program = """
import os,sys,socket
from pathlib import Path
class Block:
 def find_spec(self,name,path=None,target=None):
  if name in ('app.config','app.database','app.models') or name.startswith(('sqlalchemy', 'app.ai.forecast_', 'app.ai.bed_', 'app.ai.roster_')):
   raise AssertionError('Forbidden hospital/legacy imports: '+name)
sys.meta_path.insert(0,Block())
def audit(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
  name=Path(os.fsdecode(args[0])).name
  if name=='.env' or name.startswith('.env.'):
   raise AssertionError('No dotenv reads')
sys.addaudithook(audit)
def no_network(*args,**kwargs): raise AssertionError('No network')
socket.create_connection=no_network
socket.getaddrinfo=no_network
from app.ai.surgery_server import create_surgery_app
from app.ai.surgery_config import SurgerySettings,runtime_descriptor
settings=SurgerySettings(AI_PROVIDER_LOCAL_SURGERY_API_KEY='synthetic-strong-key-00000000000000000')
assert settings.model_config['env_file'] is None
assert runtime_descriptor(settings)['automatic_booking'] is False
assert 'app.database' not in sys.modules and 'app.config' not in sys.modules
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1]), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-c", program], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
