"""Real native ASGI generation, public-only payloads, and altered proof rejection."""

import copy
import hashlib
import json

import httpx
import pytest

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError, _request, generate, validate_generation
from app.ai.models import AIProvider
from app.ai.supply_config import SupplySettings, runtime_descriptor
from app.ai.supply_context import supply_evidence
from app.ai.supply_contract import MAX_BYTES
from app.ai.supply_server import create_supply_app
from tests.test_ai_supply_context import binding_for_source
from tests.test_ai_supply_contract import make_source

SPEC = FEATURE_BY_KEY["supply_forecast"]
KEY = "synthetic-supply-gateway-key-0000000001"


def provider():
    return AIProvider(
        provider_id=1,
        name="Synthetic isolated supply gateway",
        kind="specialist",
        api_base="http://127.0.0.1:8822",
        api_key_env="AI_PROVIDER_LOCAL_SUPPLY_API_KEY",
        model="supply:" + "a" * 64,
        max_output_tokens=4000,
        timeout_seconds=110,
        enabled=True,
    )


def case(horizon=7):
    source = make_source()
    binding = binding_for_source(source, horizon)
    return {
        "input": {"supply_series_id": source["series_id"], "horizon_days": horizon, "question": "SYNTH_PRIVATE_QUESTION"},
        "context": {"supply_source": source, "supply_binding": binding, "supply_series": {"raw_unit_name": "SYNTH_PRIVATE_UNIT", "private_note": "SYNTH_PRIVATE_NOTE"}},
        "evidence": [supply_evidence(binding)],
    }


def test_actual_schema13_request_contains_complete_public_source_and_prompt_only():
    data = case(14)
    url, packet = _request(provider(), SPEC, SPEC.task_prompt, data)
    assert url == "http://127.0.0.1:8822/tasks"
    assert packet == {
        "schema_version": "13",
        "feature_key": SPEC.key,
        "engine": "prediction",
        "model": provider().model,
        "instructions": COMMON_SYSTEM_PROMPT + "\n\n" + SPEC.task_prompt,
        "store": False,
        "input": {"context": {"supply_source": data["context"]["supply_source"]}, "horizon_days": 14},
    }
    assert "SYNTH_PRIVATE" not in json.dumps(packet)


@pytest.mark.parametrize("key", ["supply_source", "supply_binding", "supply_series"])
@pytest.mark.parametrize("kind", ["chat", "responses", "specialist"])
def test_each_supply_original_marker_rejects_external_or_text_fallback(key, kind):
    p = provider()
    p.kind, p.model = kind, "external-model"
    with pytest.raises(AIExecutionError) as error:
        _request(p, SPEC, SPEC.task_prompt, {"input": {}, "context": {key: {}}, "evidence": []})
    assert error.value.code == "SUPPLY_ADAPTER_REQUIRED"


@pytest.mark.parametrize(
    "other",
    [
        "bed_source",
        "surgery_source",
        "roster_source",
        "sofa_source",
        "sofa_change_source",
        "news2_source",
        "audio_source",
        "ecg_source",
        "image_source",
        "forecast_source",
        "aki_source",
        "qsofa_source",
    ],
)
def test_complete_supply_result_cannot_mix_other_model_sources(other):
    with pytest.raises(AIExecutionError) as error:
        validate_generation({}, [], supply_source={}, **{other: {}})
    assert error.value.code == "INVALID_OUTPUT"


class ActualWire(httpx.AsyncBaseTransport):
    def __init__(self, app, mutation=None, raw=None):
        self.inner = httpx.ASGITransport(app=app)
        self.seen, self.mutation, self.raw = [], mutation, raw

    async def handle_async_request(self, request):
        self.seen.append(json.loads(await request.aread()))
        response = await self.inner.handle_async_request(request)
        body = await response.aread()
        if self.raw:
            body = self.raw(body)
        elif self.mutation:
            value = json.loads(body)
            self.mutation(value)
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        return httpx.Response(response.status_code, content=body, headers={"Content-Type": "application/json"})


def actual_provider(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SUPPLY_API_KEY", KEY)
    config = SupplySettings(AI_PROVIDER_LOCAL_SUPPLY_API_KEY=KEY)
    p = provider()
    p.model = runtime_descriptor(config)["model_version"]
    return p, create_supply_app(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("horizon", [7, 14])
async def test_real_native_asgi_gateway_recomputes_complete_three_target_result(monkeypatch, horizon):
    p, native = actual_provider(monkeypatch)
    data = case(horizon)
    wire = ActualWire(native)
    result, inputs, outputs = await generate(p, SPEC, SPEC.task_prompt, data, transport=wire)
    analysis = result.supply_analysis
    assert inputs == outputs == 0 and len(wire.seen) == 1
    assert analysis.horizon_days == horizon and analysis.planned_pair_count == 28 * horizon
    assert analysis.instructions_digest == hashlib.sha256((COMMON_SYSTEM_PROMPT + "\n\n" + SPEC.task_prompt).encode()).hexdigest()
    assert len(analysis.targets) == 3 and all(len(row.models) == 6 for row in analysis.targets)
    assert "SYNTH_PRIVATE" not in json.dumps(wire.seen)
    assert result.sections[0].source_ids == [data["context"]["supply_source"]["source_id"]]
    assert result.sections[1].source_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["forecast", "rational", "fold", "state", "parameter_binding", "instructions", "runtime", "target", "explanation", "citation", "extra_analysis", "handled_int"])
async def test_tampered_actual_native_receipt_never_reaches_the_ui(monkeypatch, change):
    p, native = actual_provider(monkeypatch)

    def mutate(value):
        analysis = value["supply_analysis"]
        if change == "forecast":
            analysis["targets"][0]["models"][0]["prediction"]["values"][0]["numerator"] = "999"
        elif change == "rational":
            analysis["targets"][0]["models"][0]["prediction"]["values"][0] = {"numerator": "4", "denominator": "2"}
        elif change == "fold":
            analysis["targets"][0]["models"][0]["rolling_origins"].pop()
        elif change == "state":
            analysis["targets"][0]["models"][0]["terminal_state"]["positive_count"] += 1
        elif change == "parameter_binding":
            analysis["source_binding"]["profile_content_hash"] = "f" * 64
        elif change == "instructions":
            analysis["instructions_digest"] = "f" * 64
        elif change == "runtime":
            analysis["local_runtime"]["core_sha256"]["supply_model"] = "f" * 64
        elif change == "target":
            analysis["targets"].reverse()
        elif change == "explanation":
            value["result"]["summary"] = "automatic purchase approved"
        elif change == "citation":
            value["result"]["sections"][0]["source_ids"] = ["unprovided"]
        elif change == "extra_analysis":
            analysis["purchase_quantity"] = 999
        else:
            value["handled"] = 1

    wire = ActualWire(native, mutation=mutate)
    with pytest.raises(AIExecutionError):
        await generate(p, SPEC, SPEC.task_prompt, case(), transport=wire)
    assert len(wire.seen) == 1


@pytest.mark.asyncio
async def test_over_8mib_complete_prompt_packet_refuses_before_any_http(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SUPPLY_API_KEY", KEY)
    seen = []

    def reject(request):
        seen.append(request)
        return httpx.Response(500)

    with pytest.raises(AIExecutionError) as error:
        await generate(provider(), SPEC, "x" * (MAX_BYTES + 1), copy.deepcopy(case()), transport=httpx.MockTransport(reject))
    assert error.value.code == "SUPPLY_REQUEST_LIMIT" and seen == []
