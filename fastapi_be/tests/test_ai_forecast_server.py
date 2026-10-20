"""Actual offline ASGI statistics execution with synthetic aggregate counts only."""

import asyncio
import hashlib
import subprocess
import sys
import threading

import httpx
import pytest

from app.ai import forecast_server
from app.ai.forecast_config import ForecastSettings, runtime_descriptor
from app.ai.forecast_contract import ForecastAnalysis, ForecastSource
from app.ai.forecast_model import validate_analysis_binding
from tests.test_ai_forecast_contract import make_source, rebind

KEY = "synthetic-forecast-service-credential-at-least-32-characters"


def task_for(source=None, horizon=14):
    return {
        "schema_version": "5",
        "feature_key": "visit_forecast",
        "engine": "prediction",
        "model": runtime_descriptor()["model_version"],
        "instructions": "synthetic complete system+feature Prompt; no patient identities",
        "store": False,
        "input": {"context": {"forecast_source": source or make_source()}, "horizon_days": horizon},
    }


def configuration(**options):
    return ForecastSettings(AI_PROVIDER_LOCAL_FORECAST_API_KEY=KEY, **options)


@pytest.mark.asyncio
async def test_authentication_precedes_body_parsing_and_capabilities_never_execute(monkeypatch):
    app = forecast_server.create_forecast_app(configuration())

    def forbidden(*_):
        raise AssertionError("capability metadata must not run forecasting")

    monkeypatch.setattr(forecast_server, "build_response", forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://forecast") as client:
        assert (await client.get("/health/ready")).json() == {"ready": True}
        assert (await client.get("/capabilities")).status_code == 401
        assert (await client.post("/tasks", content=b"x" * 140000)).status_code == 401
        response = await client.get("/capabilities", headers={"Authorization": "Bearer " + KEY})
    capabilities = response.json()
    assert response.status_code == 200 and capabilities["schema_version"] == "5"
    assert capabilities["horizon_days"] == [7, 14] and capabilities["history_min_days"] == 112
    assert KEY not in response.text and "site-packages" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("horizon", [7, 14])
async def test_actual_service_returns_full_recomputable_forecast_and_bound_prompt(horizon):
    source = make_source(values=[0] * 112)
    task = task_for(source, horizon)
    app = forecast_server.create_forecast_app(configuration())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://forecast", headers={"Authorization": "Bearer " + KEY}) as client:
        response = await client.post("/tasks", json=task)
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result) == {"schema_version", "feature_key", "model_version", "applicable", "result", "forecast_analysis", "usage"}
    assert set(result["result"]) == {"summary", "sections", "warnings", "missing_data"}
    assert result["usage"] == {"input_tokens": 0, "output_tokens": 0}
    assert result["result"]["sections"][0]["source_ids"] == [source["source_id"]]
    assert len(result["result"]["missing_data"]) == 2
    assert any("as-of" in value for value in result["result"]["warnings"])
    assert any("3条" in value for value in result["result"]["warnings"])
    analysis = ForecastAnalysis.model_validate(result["forecast_analysis"])
    validate_analysis_binding(analysis, ForecastSource.model_validate(source), horizon, hashlib.sha256(task["instructions"].encode()).hexdigest(), task["model"])
    assert len(analysis.forecast) == horizon and analysis.backtest.forecast_pair_count == 28 * horizon


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,status",
    [
        ("model", 409),
        ("version", 422),
        ("feature", 422),
        ("engine", 422),
        ("store", 422),
        ("store_zero", 422),
        ("horizon_string", 422),
        ("horizon_float", 422),
        ("horizon_bool", 422),
        ("unknown_context", 422),
        ("unknown_input", 422),
        ("unknown_task", 422),
        ("hash", 422),
        ("missing_date", 422),
        ("missing_coverage", 422),
        ("oversize", 413),
    ],
)
async def test_service_rejects_changed_contract_before_numeric_execution(change, status, monkeypatch):
    task = task_for()
    app = forecast_server.create_forecast_app(configuration())

    def forbidden(*_):
        raise AssertionError("invalid task must not execute")

    monkeypatch.setattr(forecast_server, "build_response", forbidden)
    if change == "model":
        task["model"] = "stat-forecast:" + "a" * 64
    elif change == "version":
        task["schema_version"] = "1"
    elif change == "feature":
        task["feature_key"] = "roster_plan"
    elif change == "engine":
        task["engine"] = "llm"
    elif change == "store":
        task["store"] = True
    elif change == "store_zero":
        task["store"] = 0
    elif change.startswith("horizon_"):
        task["input"]["horizon_days"] = {"horizon_string": "7", "horizon_float": 7.0, "horizon_bool": True}[change]
    elif change == "unknown_context":
        task["input"]["context"]["patient"] = {"name": "must never be sent"}
    elif change == "unknown_input":
        task["input"]["evidence"] = []
    elif change == "unknown_task":
        task["temperature"] = 0
    elif change == "hash":
        task["input"]["context"]["forecast_source"]["observations"][0]["value"] += 1
    elif change == "missing_date":
        source = task["input"]["context"]["forecast_source"]
        source["observations"][5]["date"] = source["observations"][6]["date"]
        rebind(source)
    elif change == "missing_coverage":
        del task["input"]["context"]["forecast_source"]["coverage_status"]
    else:
        task["instructions"] = "x" * 140000
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://forecast", headers={"Authorization": "Bearer " + KEY}) as client:
        response = await client.post("/tasks", json=task)
    assert response.status_code == status, response.text
    assert KEY not in response.text and "must never" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b'{"schema_version":"5","schema_version":"1"}', b'{"x":NaN}', b'{"x":Infinity}', b"\xff", b"not-json"])
async def test_ambiguous_or_nonfinite_json_is_rejected(body):
    app = forecast_server.create_forecast_app(configuration())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://forecast", headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}) as client:
        response = await client.post("/tasks", content=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_deep_json_below_byte_limit_is_rejected_without_forecasting(monkeypatch):
    config = configuration()
    app = forecast_server.create_forecast_app(config)
    calls = []

    def forbidden(*args):
        calls.append(args)
        raise AssertionError("invalid deep input must not execute forecasting")

    monkeypatch.setattr(forecast_server, "build_response", forbidden)
    body = '{"x":' + "[" * 10000 + "0" + "]" * 10000 + "}"
    assert len(body.encode()) < config.max_request_bytes
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://forecast",
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
    ) as client:
        response = await client.post("/tasks", content=body)
    assert response.status_code == 422
    assert not calls


@pytest.mark.asyncio
async def test_body_limit_applies_to_streamed_bytes_without_content_length():
    app = forecast_server.create_forecast_app(configuration())

    async def large_body():
        for _ in range(20):
            yield b" " * 10000

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://forecast", headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}) as client:
        response = await client.post("/tasks", content=large_body())
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_runtime_changes_stop_ready_capabilities_and_task(monkeypatch):
    app = forecast_server.create_forecast_app(configuration())
    original = runtime_descriptor()
    monkeypatch.setattr(forecast_server, "runtime_descriptor", lambda _: {**original, "runtime_digest": "f" * 64})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://forecast", headers={"Authorization": "Bearer " + KEY}) as client:
        responses = [await client.get("/health/ready"), await client.get("/capabilities"), await client.post("/tasks", json=task_for())]
    assert all(response.status_code == 503 for response in responses)


@pytest.mark.asyncio
async def test_service_rejects_concurrent_task_without_running_a_second_forecast(monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = forecast_server.build_response

    def blocked(*args):
        started.set()
        if not release.wait(3):
            raise AssertionError("test failed to release synthetic compute")
        return original(*args)

    app = forecast_server.create_forecast_app(configuration())
    monkeypatch.setattr(forecast_server, "build_response", blocked)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://forecast", headers={"Authorization": "Bearer " + KEY}) as client:
        first = asyncio.create_task(client.post("/tasks", json=task_for()))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            second = await client.post("/tasks", json=task_for())
            assert second.status_code == 429
        finally:
            release.set()
        assert (await first).status_code == 200


def test_service_import_and_runtime_need_no_hospital_configuration_database_or_weights():
    program = "import sys; from app.ai.forecast_server import create_forecast_app; from app.ai.forecast_config import runtime_descriptor; d=runtime_descriptor(); assert not any(k in sys.modules for k in ['app.config','app.database','app.models','app.main','numpy','torch']); print(d['engine'])"
    completed = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=True, timeout=10)
    assert completed.stdout.strip() == "stdlib-statistical-forecast"


def test_service_refuses_short_key_and_does_not_read_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("AI_PROVIDER_LOCAL_FORECAST_API_KEY=private-real-key-must-not-load\n")
    with pytest.raises(ValueError):
        forecast_server.create_forecast_app(ForecastSettings(AI_PROVIDER_LOCAL_FORECAST_API_KEY="short"))
