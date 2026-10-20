"""Actual gateway -> standalone schema10 ASGI -> full proof recomputation."""

import copy
import hashlib
import json

import httpx
import pytest

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError, _request, generate
from app.ai.models import AIProvider
from app.ai.roster_config import RosterSettings, runtime_descriptor
from app.ai.roster_contract import MAX_BYTES, hash_content
from app.ai.roster_server import create_roster_app
from tests.test_ai_roster_contract import complete_source
from tests.test_ai_roster_server import KEY

SPEC = FEATURE_BY_KEY["roster_optimization"]
PROMPT = "仅依据声明的日期需求、资格、可用性和工时约束提供有证明界限的排班候选。"


def case(mode="meet_targets_min_penalty"):
    source = complete_source()
    source["objective_mode"] = mode
    bound = {
        "schema_version": "roster_context_binding_v1",
        "plan_id": source["problem_id"],
        "department_id": 1,
        "revision": 2,
        "source_id": source["source_id"],
        "content_hash": source["content_hash"],
        "problem_governance_hash": source["problem_governance_hash"],
        "projection_hash": hash_content(source),
        "scope_binding_hash": source["scope_binding_hash"],
        "manifest_digest": source["manifest_digest"],
        "collection_digest": hash_content("synthetic complete collection"),
        "rule_id": source["rule_id"],
        "recipe_digest": source["recipe_digest"],
        "input_policy_digest": source["input_policy_digest"],
    }
    return {
        "input": {"roster_plan_id": source["problem_id"], "question": "synthetic-private-question"},
        "context": {
            "roster_source": source,
            "roster_binding": bound,
            "scope": "department",
            "department_ids": [1],
            "roster_plan": {"private_note": "synthetic-private-note", "doctor_name": "synthetic-private-doctor", "leave_health_reason": "synthetic-private-health", "private_doctor_id": 1234567},
        },
        "evidence": [{"source_id": source["source_id"], "kind": "operational_record", "title": "完整受审原计划", "content": "synthetic-private-evidence"}],
    }


def provider():
    config = RosterSettings(AI_PROVIDER_LOCAL_ROSTER_API_KEY=KEY)
    return AIProvider(
        provider_id=1,
        name="Synthetic isolated roster",
        kind="specialist",
        api_base="http://127.0.0.1:8819",
        api_key_env="AI_PROVIDER_LOCAL_ROSTER_API_KEY",
        model=runtime_descriptor(config)["model_version"],
        max_output_tokens=4000,
        timeout_seconds=110,
        enabled=True,
    ), create_roster_app(config)


class ActualWire(httpx.AsyncBaseTransport):
    def __init__(self, app, mutation=None, raw=None):
        self.inner = httpx.ASGITransport(app=app)
        self.seen = []
        self.mutation = mutation
        self.raw = raw

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
@pytest.mark.parametrize("mode", ["meet_targets_min_penalty", "max_slots_then_min_penalty"])
async def test_actual_wire_uses_only_public_source_and_recomputes_each_objective(mode, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ROSTER_API_KEY", KEY)
    p, app = provider()
    data = case(mode)
    wire = ActualWire(app)
    result, inputs, outputs = await generate(p, SPEC, PROMPT, data, transport=wire)
    assert inputs == outputs == 0
    analysis = result.roster_analysis
    assert analysis.instructions_digest == hashlib.sha256((COMMON_SYSTEM_PROMPT + "\n\n" + PROMPT).encode()).hexdigest()
    assert analysis.solve_status == "optimal_proven"
    assert analysis.solution.total_planned_slots == (5 if mode == "meet_targets_min_penalty" else 8)
    assert len(wire.seen) == 1
    packet = wire.seen[0]
    assert packet["schema_version"] == "10" and packet["engine"] == "optimizer" and packet["store"] is False
    assert packet["input"] == {"context": {"roster_source": data["context"]["roster_source"]}}
    outbound = json.dumps(packet, ensure_ascii=False)
    assert all(
        private not in outbound
        for private in (
            "synthetic-private-question",
            "synthetic-private-note",
            "synthetic-private-doctor",
            "synthetic-private-health",
            "synthetic-private-evidence",
            '"department_id"',
            '"roster_binding"',
            '"private_doctor_id"',
        )
    )


@pytest.mark.parametrize(
    "field", ["source_id", "content_hash", "problem_governance_hash", "projection_hash", "scope_binding_hash", "manifest_digest", "rule_id", "recipe_digest", "input_policy_digest"]
)
def test_every_public_frozen_binding_identity_checked_before_wire(field):
    p, _ = provider()
    data = case()
    data["context"]["roster_binding"][field] = hash_content("forged")
    with pytest.raises(AIExecutionError):
        _request(p, SPEC, PROMPT, data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.update(model_version="roster:" + "0" * 64),
        lambda v: v.update(handled=1),
        lambda v: v.update(handled=False),
        lambda v: v["usage"].update(input_tokens=True),
        lambda v: v["usage"].update(input_tokens="0"),
        lambda v: v["usage"].update(input_tokens=0.0),
        lambda v: v["usage"].update(output_tokens=-1),
        lambda v: v["usage"].update(output_tokens=2000001),
        lambda v: v["usage"].update(cost=0),
        lambda v: v.update(extra="private"),
        lambda v: v.update(sofa_analysis=None),
        lambda v: v["result"].update(summary="伪造最优与自动发布声明"),
        lambda v: v["result"].update(warnings=[]),
        lambda v: v["result"].update(missing_data=["fabricated"]),
        lambda v: v["result"].update(roster_analysis={}),
    ],
)
async def test_strict_envelope_and_fixed_explanations_reject_tampering(mutation, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ROSTER_API_KEY", KEY)
    p, app = provider()
    with pytest.raises(AIExecutionError):
        await generate(p, SPEC, PROMPT, case(), transport=ActualWire(app, mutation))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        lambda a: a.update(instructions_digest="b" * 64),
        lambda a: a.update(optimality_proven=1),
        lambda a: a.update(solve_status="feasible_not_proven"),
        lambda a: a["source_binding"].update(projection_hash="0" * 64),
        lambda a: a["optimistic_search"].update(expanded_nodes=999),
        lambda a: a["optimistic_search"].update(frontier_digest="0" * 64),
        lambda a: a["solution"]["checks"][0].update(status="unknown"),
        lambda a: a["solution"].update(cost_points=1),
        lambda a: a["solution"]["session_allocations"][0].update(capacity_headroom=2),
        lambda a: a["local_runtime"].update(timezone_database_digest="0" * 64),
        lambda a: a["local_runtime"]["core_sha256"].update(roster_model="0" * 64),
    ],
)
async def test_whole_math_frontier_actual_candidate_and_metadata_recomputation(mutation, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ROSTER_API_KEY", KEY)
    p, app = provider()

    def alter(value):
        mutation(value["roster_analysis"])

    with pytest.raises(AIExecutionError):
        await generate(p, SPEC, PROMPT, case(), transport=ActualWire(app, alter))


@pytest.mark.asyncio
async def test_utf8_request_limit_before_any_provider_access(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ROSTER_API_KEY", KEY)
    p, app = provider()
    wire = ActualWire(app)
    with pytest.raises(AIExecutionError) as exc:
        await generate(p, SPEC, "医" * (MAX_BYTES // 3 + 1), case(), transport=wire)
    assert exc.value.code == "ROSTER_REQUEST_LIMIT"
    assert wire.seen == []


@pytest.mark.asyncio
async def test_response_limit_counts_full_utf8_bytes(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ROSTER_API_KEY", KEY)
    p, app = provider()
    wire = ActualWire(app, raw=lambda _: json.dumps({"summary": "医" * (MAX_BYTES // 3 + 1)}, ensure_ascii=False).encode())
    with pytest.raises(AIExecutionError) as exc:
        await generate(p, SPEC, PROMPT, case(), transport=wire)
    assert exc.value.code == "RESPONSE_TOO_LARGE"


def test_reference_override_and_non_roster_mode_fail_before_wire():
    p, _ = provider()
    data = case()
    data["input"]["cost_points"] = 0
    with pytest.raises(AIExecutionError):
        _request(p, SPEC, PROMPT, data)
    data = case()
    for mode in ("chat", "responses", "specialist"):
        changed = copy.copy(p)
        changed.kind = mode
        changed.model = "generic-text-model"
        with pytest.raises(AIExecutionError):
            _request(changed, SPEC, PROMPT, data)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [lambda b: b.replace(b'"input_tokens":0', b'"input_tokens":0,"input_tokens":0'), lambda b: b.replace(b'"input_tokens":0', b'"input_tokens":NaN,"input_tokens":0')])
async def test_duplicate_or_nonfinite_json_cannot_be_hidden_by_last_key_wins(raw, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ROSTER_API_KEY", KEY)
    p, app = provider()
    with pytest.raises(AIExecutionError):
        await generate(p, SPEC, PROMPT, case(), transport=ActualWire(app, raw=raw))
