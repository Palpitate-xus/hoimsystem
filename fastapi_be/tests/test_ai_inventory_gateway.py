"""Actual native ASGI tasks, full physical proofs and strict public-only gateway boundaries."""

import copy
import hashlib
import json

import httpx
import pytest

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError, _request, generate, validate_generation
from app.ai.inventory_config import InventorySettings, runtime_descriptor
from app.ai.inventory_context import inventory_evidence
from app.ai.inventory_contract import MAX_BYTES
from app.ai.inventory_server import create_inventory_app
from app.ai.models import AIProvider
from tests.test_ai_inventory_capacity import maximum_source
from tests.test_ai_inventory_context import bundle
from tests.test_ai_inventory_contract import amount, candidate, refresh

SPEC = FEATURE_BY_KEY["inventory_optimization"]
KEY = "synthetic-inventory-gateway-key-0000000001"


def provider():
    return AIProvider(
        provider_id=1,
        name="Synthetic isolated inventory gateway",
        kind="specialist",
        api_base="http://127.0.0.1:8823",
        api_key_env="AI_PROVIDER_LOCAL_INVENTORY_API_KEY",
        model="inventory:" + "a" * 64,
        max_output_tokens=4000,
        timeout_seconds=110,
        enabled=True,
    )


def case(source=None):
    data = bundle(source)
    data["evidence"] = [inventory_evidence(data["context"]["inventory_binding"])]
    return data


def test_actual_schema14_request_contains_only_complete_public_source_and_prompt():
    data = case()
    url, packet = _request(provider(), SPEC, SPEC.task_prompt, data)
    assert url == "http://127.0.0.1:8823/tasks"
    assert packet == {
        "schema_version": "14",
        "feature_key": SPEC.key,
        "engine": "optimizer",
        "model": provider().model,
        "instructions": COMMON_SYSTEM_PROMPT + "\n\n" + SPEC.task_prompt,
        "store": False,
        "input": {"context": {"inventory_source": data["context"]["inventory_source"]}},
    }
    assert "never-export" not in json.dumps(packet)


@pytest.mark.parametrize("key", ["inventory_source", "inventory_binding", "inventory_scenario"])
@pytest.mark.parametrize("kind", ["chat", "responses", "specialist"])
def test_each_inventory_marker_refuses_external_or_text_fallback(key, kind):
    p = provider()
    p.kind, p.model = kind, "external-model"
    with pytest.raises(AIExecutionError) as error:
        _request(p, SPEC, SPEC.task_prompt, {"input": {}, "context": {key: {}}, "evidence": []})
    assert error.value.code == "INVENTORY_ADAPTER_REQUIRED"


@pytest.mark.parametrize(
    "other",
    [
        "bed_source",
        "surgery_source",
        "roster_source",
        "supply_source",
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
def test_inventory_proof_cannot_mix_other_model_sources(other):
    with pytest.raises(AIExecutionError) as error:
        validate_generation({}, [], inventory_source={}, **{other: {}})
    assert error.value.code == "INVALID_OUTPUT"


class ActualWire(httpx.AsyncBaseTransport):
    def __init__(self, native, mutation=None):
        self.inner = httpx.ASGITransport(app=native)
        self.seen, self.mutation, self.response_bytes = [], mutation, 0

    async def handle_async_request(self, request):
        self.seen.append(json.loads(await request.aread()))
        response = await self.inner.handle_async_request(request)
        body = await response.aread()
        if self.mutation:
            value = json.loads(body)
            self.mutation(value)
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self.response_bytes = len(body)
        return httpx.Response(response.status_code, content=body, headers={"Content-Type": "application/json"})


def actual_provider(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_INVENTORY_API_KEY", KEY)
    config = InventorySettings(AI_PROVIDER_LOCAL_INVENTORY_API_KEY=KEY)
    p = provider()
    p.model = runtime_descriptor(config)["model_version"]
    return p, create_inventory_app(config)


@pytest.mark.asyncio
async def test_real_asgi_gateway_recomputes_all_candidate_days_and_exact_cost(monkeypatch):
    p, native = actual_provider(monkeypatch)
    source = case()["context"]["inventory_source"]
    source["candidates"].append(candidate("actual gateway baseline", []))
    refresh(source)
    data = case(source)
    wire = ActualWire(native)
    result, inputs, outputs = await generate(p, SPEC, SPEC.task_prompt, data, transport=wire)
    analysis = result.inventory_analysis
    assert inputs == outputs == 0 and len(wire.seen) == 1
    assert analysis.candidate_count == 2 and all(len(row.daily) == 3 for row in analysis.candidate_results)
    assert analysis.candidate_results[0].total_cost.model_dump() == {"numerator": "5", "denominator": "2"}
    assert analysis.candidate_results[1].total_cost.model_dump() == {"numerator": "0", "denominator": "1"}
    assert analysis.best_among_declared_candidates and analysis.automatically_selected_candidate is None
    assert analysis.instructions_digest == hashlib.sha256((COMMON_SYSTEM_PROMPT + "\n\n" + SPEC.task_prompt).encode()).hexdigest()
    assert "never-export" not in json.dumps(wire.seen)
    assert result.sections[0].source_ids == [source["source_id"]] and result.sections[1].source_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cost", "rational", "day_balance", "omitted_candidate", "best", "instructions", "runtime", "explanation", "citation", "extra_analysis", "handled_int"])
async def test_tampered_actual_native_receipt_is_rejected_before_result_exposure(monkeypatch, change):
    p, native = actual_provider(monkeypatch)

    def mutate(value):
        analysis = value["inventory_analysis"]
        if change == "cost":
            analysis["candidate_results"][0]["total_cost"]["numerator"] = "999"
        elif change == "rational":
            analysis["candidate_results"][0]["total_cost"] = {"numerator": "10", "denominator": "4"}
        elif change == "day_balance":
            analysis["candidate_results"][0]["daily"][0]["closing_total"]["numerator"] = "999"
        elif change == "omitted_candidate":
            analysis["candidate_results"] = []
        elif change == "best":
            analysis["best_known_feasible_candidate_ids"] = []
        elif change == "instructions":
            analysis["instructions_digest"] = "f" * 64
        elif change == "runtime":
            analysis["local_runtime"]["core_sha256"]["inventory_model"] = "f" * 64
        elif change == "explanation":
            value["result"]["summary"] = "automatic purchase approved"
        elif change == "citation":
            value["result"]["sections"][0]["source_ids"] = ["unprovided"]
        elif change == "extra_analysis":
            analysis["auto_purchase"] = True
        else:
            value["handled"] = 1

    wire = ActualWire(native, mutate)
    with pytest.raises(AIExecutionError):
        await generate(p, SPEC, SPEC.task_prompt, case(), transport=wire)
    assert len(wire.seen) == 1


@pytest.mark.asyncio
async def test_all256_unknown_candidates_and_set_gap_survive_complete_receipt(monkeypatch):
    p, native = actual_provider(monkeypatch)
    source = maximum_source(256, 0, 1)
    source["candidate_set_review"] = "unknown"
    for row in source["candidates"]:
        row["plan_fixed_fee"] = amount(None, True)
    wire = ActualWire(native)
    result, _, _ = await generate(p, SPEC, SPEC.task_prompt, case(source), transport=wire)
    assert result.inventory_analysis.unknown_count == 256
    assert len(result.missing_data) == 257 and result.missing_data[-1] == "declared_candidate_set_not_confirmed"
    assert not result.inventory_analysis.best_among_declared_candidates


@pytest.mark.asyncio
async def test_complete_native_proof_over_general512k_limit_keeps_all4096_lots(monkeypatch):
    p, native = actual_provider(monkeypatch)
    wire = ActualWire(native)
    result, _, _ = await generate(p, SPEC, SPEC.task_prompt, case(maximum_source()), transport=wire)
    assert 512 * 1024 < wire.response_bytes <= MAX_BYTES
    assert len(result.inventory_analysis.candidate_results[0].terminal_lots) == 4096
    assert len(result.inventory_analysis.candidate_results[0].daily) == 31


@pytest.mark.asyncio
async def test_full_request_above8mib_is_refused_before_http(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_INVENTORY_API_KEY", KEY)
    seen = []

    def response(request):
        seen.append(request)
        return httpx.Response(500)

    with pytest.raises(AIExecutionError) as error:
        await generate(provider(), SPEC, "x" * (MAX_BYTES + 1), copy.deepcopy(case()), transport=httpx.MockTransport(response))
    assert error.value.code == "INVENTORY_REQUEST_LIMIT" and seen == []
