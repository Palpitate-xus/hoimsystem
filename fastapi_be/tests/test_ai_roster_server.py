"""Real independent ASGI wire, authentication and immutable runtime checks."""

import asyncio
import copy
import hashlib
import json
import threading

import httpx
import pytest
from pydantic import ValidationError

from app.ai.roster_config import RosterSettings, runtime_descriptor, runtime_from_descriptor
from app.ai.roster_contract import MAX_BYTES, RosterRuntime
from app.ai.roster_protocol import RosterEnvelope
from app.ai.roster_server import create_roster_app
from tests.test_ai_roster_contract import complete_source

KEY = "synthetic-roster-independent-key-1234567890"


def settings(**values):
    return RosterSettings(AI_PROVIDER_LOCAL_ROSTER_API_KEY=KEY, **values)


def task(descriptor):
    return {
        "schema_version": "10",
        "feature_key": "roster_optimization",
        "engine": "optimizer",
        "model": descriptor["model_version"],
        "instructions": "Use only the fixed declared local roster constraints. Private synthetic prompt provenance.",
        "store": False,
        "input": {"context": {"roster_source": complete_source()}},
    }


@pytest.mark.asyncio
async def test_actual_schema10_wire_and_authenticated_metadata_without_inference():
    config = settings()
    app = create_roster_app(config)
    descriptor = runtime_descriptor(config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://independent") as client:
        assert (await client.get("/health/ready")).json() == {"ready": True}
        assert (await client.get("/capabilities")).status_code == 401
        response = await client.get("/capabilities", headers={"Authorization": "Bearer " + KEY})
        assert response.json() == descriptor
        assert KEY not in response.text
        body = task(descriptor)
        result = await client.post("/tasks", json=body, headers={"Authorization": "Bearer " + KEY})
    assert result.status_code == 200, result.text
    envelope = RosterEnvelope.model_validate(result.json())
    assert envelope.roster_analysis.solve_status == "optimal_proven"
    assert envelope.roster_analysis.instructions_digest == hashlib.sha256(body["instructions"].encode()).hexdigest()
    assert envelope.usage.input_tokens == envelope.usage.output_tokens == 0
    assert "roster_analysis" not in envelope.result.model_dump()
    assert envelope.roster_analysis.local_runtime.model_dump() == runtime_from_descriptor(descriptor)
    assert set(descriptor["core_sha256"]) == {"roster_contract", "roster_model", "roster_config", "roster_server"}
    assert descriptor["operational_validation"] == "not_provided"
    assert RosterRuntime.model_validate(runtime_from_descriptor(descriptor))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b.update(store=0),
        lambda b: b.update(store=True),
        lambda b: b.update(schema_version="9"),
        lambda b: b.update(engine="prediction"),
        lambda b: b.update(question="private arbitrary question"),
        lambda b: b["input"]["context"].update(sofa_source={}),
        lambda b: b["input"]["context"].update(roster_source=None),
        lambda b: b["input"]["context"]["roster_source"].update(private_note="actual private original must not enter public source"),
    ],
)
@pytest.mark.asyncio
async def test_strict_task_extra_mix_null_or_nonactual_false_rejected(mutation):
    config = settings()
    app = create_roster_app(config)
    body = task(runtime_descriptor(config))
    mutation(body)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://independent") as client:
        response = await client.post("/tasks", json=body, headers={"Authorization": "Bearer " + KEY})
    assert response.status_code == 422
    assert "private arbitrary question" not in response.text


@pytest.mark.asyncio
async def test_wrong_model_key_and_duplicate_json_rejected():
    config = settings()
    app = create_roster_app(config)
    body = task(runtime_descriptor(config))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://independent") as client:
        assert (await client.post("/tasks", json=body)).status_code == 401
        body["model"] = "roster:" + "0" * 64
        assert (await client.post("/tasks", json=body, headers={"Authorization": "Bearer " + KEY})).status_code == 409
        duplicate = json.dumps(body).replace('"store": false', '"store": false, "store": false')
        response = await client.post("/tasks", content=duplicate, headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
        assert response.status_code == 422
        response = await client.post("/tasks", content='{"store":NaN}', headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_utf8_request_capacity_counts_bytes_and_does_not_truncate():
    config = settings(max_request_bytes=65536)
    app = create_roster_app(config)
    body = task(runtime_descriptor(config))
    body["instructions"] = "中文原始指令" * 6000
    assert len(body["instructions"]) < 65536
    wire = json.dumps(body, ensure_ascii=False).encode()
    assert 65536 < len(wire) < MAX_BYTES
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://independent") as client:
        response = await client.post("/tasks", content=wire, headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_runtime_file_or_environment_drift_fails_closed(monkeypatch):
    import app.ai.roster_server as server

    config = settings()
    app = create_roster_app(config)
    descriptor = runtime_descriptor(config)
    changed = copy.deepcopy(descriptor)
    changed["timezone_database_digest"] = "0" * 64
    monkeypatch.setattr(server, "runtime_descriptor", lambda _: changed)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://independent") as client:
        assert (await client.get("/capabilities", headers={"Authorization": "Bearer " + KEY})).status_code == 503
    monkeypatch.setattr(server, "runtime_descriptor", lambda _: descriptor)
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ROSTER_API_KEY", "changed-independent-key-with-enough-length")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://independent") as client:
        assert (await client.get("/health/ready")).status_code == 503


@pytest.mark.asyncio
async def test_timeout_keeps_worker_slot_until_actual_thread_completion(monkeypatch):
    import app.ai.roster_server as server

    release = threading.Event()
    original = server.build_response

    def controlled(*args):
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(server, "build_response", controlled)
    config = settings(timeout_seconds=1)
    app = create_roster_app(config)
    body = task(runtime_descriptor(config))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://independent") as client:
        first = await client.post("/tasks", json=body, headers={"Authorization": "Bearer " + KEY})
        assert first.status_code == 504
        second = await client.post("/tasks", json=body, headers={"Authorization": "Bearer " + KEY})
        assert second.status_code == 429
        release.set()
        for _ in range(100):
            await asyncio.sleep(0.01)
            response = await client.post("/tasks", json=body, headers={"Authorization": "Bearer " + KEY})
            if response.status_code != 429:
                break
        assert response.status_code == 200


def test_standalone_settings_have_no_dotenv_and_require_independent_strong_key():
    assert RosterSettings.model_config["env_file"] is None
    with pytest.raises(ValidationError):
        RosterSettings(AI_PROVIDER_LOCAL_ROSTER_API_KEY="short")
