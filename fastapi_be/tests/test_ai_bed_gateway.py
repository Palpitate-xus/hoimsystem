"""Actual gateway/native ASGI, public-only schema11 and recomputed exact statistics."""

import copy
import hashlib
import json

import httpx
import pytest

from app.ai.bed_config import BedSettings, runtime_descriptor
from app.ai.bed_contract import MAX_BYTES, hash_content
from app.ai.bed_server import create_bed_app
from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError, _request, generate
from app.ai.models import AIProvider
from tests.test_ai_bed_contract import make_source
from tests.test_ai_bed_server import KEY

SPEC = FEATURE_BY_KEY["bed_forecast"]
PROMPT = "仅按受审实占床位及四类实际流转事件序列做固定预测；未来容量仅为审核情景。"


def case(horizon=7):
    source = make_source()
    bound = {
        "schema_version": "bed_context_binding_v1",
        "series_id": source["series_id"],
        "department_id": 1,
        "ward_id": 2,
        "revision": 2,
        **{
            key: source[key]
            for key in (
                "source_id",
                "content_hash",
                "scope_token",
                "member_manifest_hash",
                "historical_collection_digest",
                "current_membership_digest",
                "future_scenario_collection_digest",
                "rule_id",
                "recipe_digest",
                "input_policy_digest",
            )
        },
        "series_governance_hash": source["governance_hash"],
        "projection_hash": hash_content(source),
        "collection_digest": hash_content("synthetic complete private Ward collection"),
        "horizon_days": horizon,
    }
    return {
        "input": {"bed_series_id": source["series_id"], "horizon_days": horizon, "question": "SYNTH_PRIVATE_BED_QUESTION"},
        "context": {"bed_source": source, "bed_binding": bound, "bed_series": {"private_note": "SYNTH_PRIVATE_BED_NOTE", "ward_name": "SYNTH_PRIVATE_WARD_NAME"}},
        "evidence": [{"source_id": source["source_id"], "kind": "operational_record", "title": "受审完整物理床位序列", "content": "SYNTH_PRIVATE_EVIDENCE"}],
    }


def provider():
    config = BedSettings(AI_PROVIDER_LOCAL_BED_API_KEY=KEY)
    return AIProvider(
        provider_id=1,
        name="Synthetic isolated physical-bed statistics",
        kind="specialist",
        api_base="http://127.0.0.1:8820",
        api_key_env="AI_PROVIDER_LOCAL_BED_API_KEY",
        model=runtime_descriptor(config)["model_version"],
        max_output_tokens=4000,
        timeout_seconds=110,
        enabled=True,
    ), create_bed_app(config)


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


@pytest.mark.asyncio
@pytest.mark.parametrize("horizon", [7, 14])
async def test_actual_wire_keeps_only_complete_public_source_explicit_horizon_and_full_prompt(monkeypatch, horizon):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_BED_API_KEY", KEY)
    p, app = provider()
    data, wire = case(horizon), ActualWire(app)
    result, inputs, outputs = await generate(p, SPEC, PROMPT, data, transport=wire)
    assert inputs == outputs == 0
    assert result.bed_analysis.horizon_days == horizon
    assert result.bed_analysis.instructions_digest == hashlib.sha256((COMMON_SYSTEM_PROMPT + "\n\n" + PROMPT).encode()).hexdigest()
    assert len(result.bed_analysis.targets) == 5
    assert len(wire.seen) == 1
    packet = wire.seen[0]
    assert packet["schema_version"] == "11" and packet["engine"] == "prediction" and packet["store"] is False
    assert packet["input"] == {"context": {"bed_source": data["context"]["bed_source"]}, "horizon_days": horizon}
    assert packet["instructions"] == COMMON_SYSTEM_PROMPT + "\n\n" + PROMPT
    outbound = json.dumps(packet, ensure_ascii=False)
    assert all(private not in outbound for private in ("SYNTH_PRIVATE", '"department_id"', '"ward_id"', '"bed_binding"', '"bed_series"', '"question"'))


@pytest.mark.parametrize(
    "field",
    [
        "series_id",
        "source_id",
        "content_hash",
        "series_governance_hash",
        "projection_hash",
        "scope_token",
        "member_manifest_hash",
        "historical_collection_digest",
        "current_membership_digest",
        "future_scenario_collection_digest",
        "rule_id",
        "recipe_digest",
        "input_policy_digest",
        "horizon_days",
    ],
)
def test_each_public_frozen_binding_identity_or_horizon_must_match_before_http(field):
    p, _ = provider()
    data = case()
    data["context"]["bed_binding"][field] = 14 if field == "horizon_days" else hash_content("synthetic forgery")
    with pytest.raises(AIExecutionError, match="须选择一件已审核完整床位序列"):
        _request(p, SPEC, PROMPT, data)


@pytest.mark.parametrize("wrong", ["text", "other_feature", "external_model", "no_binding", "no_source", "old_reference", "override_quantity"])
def test_wrong_protocol_feature_or_source_overrides_are_rejected_before_http(wrong):
    p, _ = provider()
    data, spec = case(), SPEC
    if wrong == "text":
        p.kind = "chat"
    elif wrong == "other_feature":
        spec = FEATURE_BY_KEY["operations_qa"]
    elif wrong == "external_model":
        p.model = "external-statistical-adapter"
    elif wrong == "no_binding":
        data["context"].pop("bed_binding")
    elif wrong == "no_source":
        data["context"].pop("bed_source")
    elif wrong == "old_reference":
        data["input"]["roster_plan_id"] = data["input"].pop("bed_series_id")
    else:
        data["input"]["occupied_beds"] = 0
    with pytest.raises(AIExecutionError):
        _request(p, spec, PROMPT, data)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["handled_int", "schema", "runtime", "usage_bool", "usage_negative", "extra", "horizon", "point", "metric", "capacity", "explanation", "citation"])
async def test_actual_native_response_tampering_cannot_change_proof_numbers_or_fixed_explanation(monkeypatch, change):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_BED_API_KEY", KEY)
    p, app = provider()

    def mutation(value):
        if change == "handled_int":
            value["handled"] = 1
        elif change == "schema":
            value["schema_version"] = "10"
        elif change == "runtime":
            value["model_version"] = "bed:" + "0" * 64
        elif change == "usage_bool":
            value["usage"]["input_tokens"] = True
        elif change == "usage_negative":
            value["usage"]["output_tokens"] = -1
        elif change == "extra":
            value["unreviewed_extra"] = {}
        elif change == "horizon":
            value["bed_analysis"]["horizon_days"] = 14
        elif change == "point":
            value["bed_analysis"]["targets"][0]["forecast"][0]["point"] = {"numerator": "999", "denominator": "1"}
        elif change == "metric":
            value["bed_analysis"]["targets"][0]["backtest"]["baselines"][0]["by_lead"][0]["metrics"]["actual_sum"] = "999"
        elif change == "capacity":
            value["bed_analysis"]["future_pressure"] = []
        elif change == "explanation":
            value["result"]["summary"] = "未经固定程序支持的未来占床确定性结论"
        else:
            value["result"]["sections"][0]["source_ids"] = ["forged-source"]

    with pytest.raises(AIExecutionError):
        await generate(p, SPEC, PROMPT, case(), transport=ActualWire(app, mutation))


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [lambda body: body[:-1] + b',"handled":true}', lambda body: body[:-1] + b',"not_finite":NaN}', lambda body: b"x" * (MAX_BYTES + 1)])
async def test_duplicate_keys_nonfinite_and_actual_oversized_response_rejected(monkeypatch, raw):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_BED_API_KEY", KEY)
    p, app = provider()
    with pytest.raises(AIExecutionError):
        await generate(p, SPEC, PROMPT, case(), transport=ActualWire(app, raw=raw))


@pytest.mark.asyncio
async def test_complete_request_with_prompt_over_8mib_is_rejected_without_a_request(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_BED_API_KEY", KEY)
    p, app = provider()
    wire = ActualWire(app)
    with pytest.raises(AIExecutionError, match="床位完整原件及Prompt超过8MiB"):
        await generate(p, SPEC, "x" * (MAX_BYTES + 1), copy.deepcopy(case()), transport=wire)
    assert wire.seen == []
