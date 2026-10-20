"""Real gateway -> independent ASGI service wire with frozen public Source binding."""

import json

import httpx
import pytest

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError, _request, generate
from app.ai.models import AIProvider
from app.ai.sofa_config import SofaSettings, runtime_descriptor
from app.ai.sofa_contract import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, hash_content
from app.ai.sofa_server import create_sofa_app
from tests.test_ai_sofa_change import change_source
from tests.test_ai_sofa_contract import identifier, sha
from tests.test_ai_sofa_model import complete_source
from tests.test_ai_sofa_server import KEY

SPEC = FEATURE_BY_KEY["sepsis_risk"]
PROMPT = "完整SOFA-1六轴；只核实全部原事实、精确运算与部分上下界。"


def case(mode="daily"):
    source = complete_source() if mode == "daily" else change_source()
    rule = source if mode == "daily" else source["current"]
    key = "sofa_source" if mode == "daily" else "sofa_change_source"
    rid = "sofa_assessment_id" if mode == "daily" else "sofa_change_assessment_id"
    aid = source["assessment_id" if mode == "daily" else "change_assessment_id"]
    bound = {
        "schema_version": "sofa_context_binding_v1",
        "kind": mode,
        "patient_id": 17,
        "admission_id": identifier("private-admission"),
        "assessment_id": aid,
        "source_id": source["source_id"],
        "content_hash": source["content_hash"],
        "governance_hash": source["assessment_governance_hash"],
        "projection_hash": hash_content(source),
        "rule_id": rule["rule_id"],
        "recipe_digest": rule["recipe_digest"],
        "policy_digest": rule["policy_digest"],
    }
    ids = [source["source_id"], rule["rule_profile_source_id"]]
    if mode == "change":
        ids += [source["current"]["source_id"], source["infection"]["source_id"]]
        if source["baseline"]["mode"] == "observed":
            ids.append(source["baseline"]["source"]["source_id"])
    return {
        "input": {rid: aid, "question": "PHI question: synthetic-private-question"},
        "context": {
            key: source,
            "sofa_binding": bound,
            "scope": "inpatient_sofa1_assessment" if mode == "daily" else "inpatient_sofa1_change",
            "sofa_assessment": {"snapshot": {"note": "synthetic-private-note", "patient_name": "synthetic-private-patient", "stream_external": "synthetic-private-stream"}},
        },
        "evidence": [
            {"source_id": item, "kind": "rule" if item == rule["rule_profile_source_id"] else "clinical_record", "title": "完整原件", "content": "synthetic-private-evidence"} for item in ids
        ],
    }


def provider():
    config = SofaSettings(AI_PROVIDER_LOCAL_SOFA_API_KEY=KEY)
    descriptor = runtime_descriptor(config)
    return AIProvider(
        provider_id=identifier("provider"),
        name="Synthetic isolated SOFA",
        kind="specialist",
        api_base="http://127.0.0.1:8818",
        api_key_env="AI_PROVIDER_LOCAL_SOFA_API_KEY",
        model=descriptor["model_version"],
        max_output_tokens=4000,
        timeout_seconds=30,
        enabled=True,
    ), create_sofa_app(config)


class ActualWire(httpx.AsyncBaseTransport):
    def __init__(self, app, mutate=None, raw=None):
        self.asgi = httpx.ASGITransport(app=app)
        self.seen = []
        self.mutate = mutate
        self.raw = raw

    async def handle_async_request(self, request):
        self.seen.append(json.loads(await request.aread()))
        response = await self.asgi.handle_async_request(request)
        body = await response.aread()
        if self.raw is not None:
            body = self.raw(body)
        elif self.mutate is not None:
            value = json.loads(body)
            self.mutate(value)
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        return httpx.Response(response.status_code, content=body, headers={"Content-Type": "application/json"})


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["daily", "change"])
async def test_actual_gateway_wire_recomputes_and_sends_public_only(mode, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SOFA_API_KEY", KEY)
    p, app = provider()
    wire = ActualWire(app)
    data = case(mode)
    result, inputs, outputs = await generate(p, SPEC, PROMPT, data, transport=wire)
    assert inputs == outputs == 0
    native = result.sofa_analysis if mode == "daily" else result.sofa_change_analysis
    assert native.instructions_digest == sha(COMMON_SYSTEM_PROMPT + "\n\n" + PROMPT)
    assert (native.complete_total_score if mode == "daily" else native.complete_delta) == 0
    assert len(wire.seen) == 1
    packet = wire.seen[0]
    assert packet["schema_version"] == "9" and packet["store"] is False
    assert packet["input"] == {"context": {("sofa_source" if mode == "daily" else "sofa_change_source"): data["context"]["sofa_source" if mode == "daily" else "sofa_change_source"]}}
    outbound = json.dumps(packet, ensure_ascii=False)
    for private in ["synthetic-private-question", "synthetic-private-note", "synthetic-private-patient", "synthetic-private-stream", "synthetic-private-evidence", "private-admission"]:
        assert private not in outbound
    assert '"patient_id"' not in outbound and '"admission_id"' not in outbound and '"sofa_binding"' not in outbound


@pytest.mark.parametrize("field", ["governance_hash", "recipe_digest", "policy_digest"])
def test_frozen_binding_all_governance_and_fixed_policy_fields_match_before_wire(field):
    p, _ = provider()
    data = case()
    data["context"]["sofa_binding"][field] = sha("forged")
    with pytest.raises(AIExecutionError):
        _request(p, SPEC, PROMPT, data)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["daily", "change"])
@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.update(model_version="sofa1:" + "0" * 64),
        lambda x: x.update(handled=1),
        lambda x: x.update(handled=False),
        lambda x: x["usage"].update(input_tokens=True),
        lambda x: x["usage"].update(input_tokens="0"),
        lambda x: x["usage"].update(input_tokens=0.0),
        lambda x: x["usage"].update(output_tokens=-1),
        lambda x: x["usage"].update(output_tokens=2000001),
        lambda x: x["usage"].update(cost=0),
        lambda x: x.update(extra="private"),
        lambda x: x["result"].update(summary="伪造诊断治疗"),
        lambda x: x["result"].update(warnings=[]),
    ],
)
async def test_strict_wire_envelope_and_fixed_result_reject_tampering(mode, mutation, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SOFA_API_KEY", KEY)
    p, app = provider()
    with pytest.raises(AIExecutionError):
        await generate(p, SPEC, PROMPT, case(mode), transport=ActualWire(app, mutation))


@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["daily", "change"])
@pytest.mark.parametrize(
    "mutation",
    [
        lambda a: a.update(instructions_digest=sha("different prompt")),
        lambda a: a["local_runtime"].update(model_version="sofa1:" + "0" * 64),
        lambda a: a.update(diagnosis_provided=0),
        lambda a: a["source_binding"].update(projection_hash=sha("wrong source")),
    ],
)
async def test_complete_native_prompt_runtime_boolean_and_projection_binding(mode, mutation, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SOFA_API_KEY", KEY)
    p, app = provider()
    key = "sofa_analysis" if mode == "daily" else "sofa_change_analysis"

    def mutate(value):
        mutation(value[key])

    with pytest.raises(AIExecutionError):
        await generate(p, SPEC, PROMPT, case(mode), transport=ActualWire(app, mutate))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["daily", "change"])
async def test_candidate_fraction_or_baseline_proof_tamper_even_unchanged_total_rejected(mode, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SOFA_API_KEY", KEY)
    p, app = provider()

    def mutate(value):
        analysis = value["sofa_analysis"] if mode == "daily" else value["sofa_change_analysis"]["baseline_analysis"]["analysis"]
        analysis["domains"][0]["candidates"][0]["calculations"][0]["exact"]["numerator"] = "401"

    with pytest.raises(AIExecutionError) as exc:
        await generate(p, SPEC, PROMPT, case(mode), transport=ActualWire(app, mutate))
    assert exc.value.code == "SOFA_BINDING_MISMATCH"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["daily", "change"])
async def test_mixed_native_field_even_null_rejected(mode, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SOFA_API_KEY", KEY)
    p, app = provider()
    other = "sofa_change_analysis" if mode == "daily" else "sofa_analysis"

    def mutate(value):
        value[other] = None

    with pytest.raises(AIExecutionError):
        await generate(p, SPEC, PROMPT, case(mode), transport=ActualWire(app, mutate))


@pytest.mark.asyncio
async def test_request_utf8_budget_is_8mib_before_any_transport(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SOFA_API_KEY", KEY)
    p, app = provider()
    wire = ActualWire(app)
    with pytest.raises(AIExecutionError) as exc:
        await generate(p, SPEC, "医" * (MAX_REQUEST_BYTES // 3 + 1), case(), transport=wire)
    assert exc.value.code == "SOFA_REQUEST_LIMIT" and not wire.seen


@pytest.mark.asyncio
async def test_response_utf8_budget_uses_bytes_not_characters(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SOFA_API_KEY", KEY)
    p, app = provider()

    def mutate(value):
        value["oversize_utf8"] = "医" * (MAX_RESPONSE_BYTES // 3 + 1)

    with pytest.raises(AIExecutionError) as exc:
        await generate(p, SPEC, PROMPT, case(), transport=ActualWire(app, mutate))
    assert exc.value.code == "RESPONSE_TOO_LARGE"


@pytest.mark.parametrize("mode", ["daily", "change"])
def test_adapter_refuses_other_text_provider_and_wrong_feature(mode):
    p, _ = provider()
    data = case(mode)
    p.kind = "chat"
    with pytest.raises(AIExecutionError):
        _request(p, SPEC, PROMPT, data)
    p.kind = "specialist"
    with pytest.raises(AIExecutionError):
        _request(p, FEATURE_BY_KEY["handover_summary"], PROMPT, data)
    p.model = "other:model"
    with pytest.raises(AIExecutionError):
        _request(p, SPEC, PROMPT, data)
