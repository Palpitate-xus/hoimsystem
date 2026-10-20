"""Actual outbound contracts and rejection before any surgery HTTP invocation."""

import copy

import httpx
import pytest
from pydantic import ValidationError

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError, _request, generate, validate_generation
from app.ai.models import AIProvider
from app.ai.surgery_context import binding_for, surgery_evidence
from app.ai.surgery_contract import MAX_BYTES
from app.ai.surgery_protocol import SurgeryExplanation, SurgeryUsage
from tests.test_ai_surgery_contract import source_dict, uid

SPEC = FEATURE_BY_KEY["surgery_scheduling"]
PROMPT = "仅按受审完整病例、明确阶段原时刻和完整资源求解；结果为待专业复核候选，不自动预订。"


def provider():
    return AIProvider(
        provider_id=1,
        name="Synthetic isolated surgery gateway",
        kind="specialist",
        api_base="http://127.0.0.1:8821",
        api_key_env="AI_PROVIDER_LOCAL_SURGERY_API_KEY",
        model="surgery:" + "a" * 64,
        max_output_tokens=4000,
        timeout_seconds=110,
        enabled=True,
    )


def case():
    source = source_dict()
    bound = binding_for(source, pool_id=uid(500), department_id=2)
    return {
        "input": {"surgery_scenario_id": source["scenario_id"], "question": "SYNTH_PRIVATE_QUESTION"},
        "context": {"surgery_source": source, "surgery_binding": bound, "surgery_scenario": {"case_name": "SYNTH_PRIVATE_CASE", "private_note": "SYNTH_PRIVATE_NOTE"}},
        "evidence": [surgery_evidence(bound)],
    }


def test_actual_request_has_schema12_complete_public_projection_and_full_prompt_only():
    data = case()
    url, packet = _request(provider(), SPEC, PROMPT, data)
    assert url == "http://127.0.0.1:8821/tasks"
    assert packet == {
        "schema_version": "12",
        "feature_key": SPEC.key,
        "engine": SPEC.engine,
        "model": provider().model,
        "instructions": COMMON_SYSTEM_PROMPT + "\n\n" + PROMPT,
        "store": False,
        "input": {"context": {"surgery_source": data["context"]["surgery_source"]}},
    }
    assert "SYNTH_PRIVATE" not in str(packet)
    assert data["input"]["question"] == "SYNTH_PRIVATE_QUESTION"


@pytest.mark.parametrize(
    "field",
    [
        "scenario_id",
        "source_id",
        "content_hash",
        "governance_hash",
        "projection_hash",
        "scope_token",
        "original_scope_hash",
        "collection_digest",
        "case_collection_digest",
        "resource_collection_digest",
        "busy_collection_digest",
        "fact_collection_digest",
        "manifest_digest",
        "rule_id",
        "rule_version",
        "profile_token",
        "profile_content_hash",
        "profile_governance_hash",
        "recipe_hash",
        "input_policy_hash",
    ],
)
def test_each_original_source_collection_or_rule_binding_is_checked_before_http(field):
    data = case()
    data["context"]["surgery_binding"][field] = "forged"
    with pytest.raises(AIExecutionError) as error:
        _request(provider(), SPEC, PROMPT, data)
    assert error.value.code == "SURGERY_SOURCE_REQUIRED"


@pytest.mark.parametrize("wrong", ["text", "other_feature", "external", "no_binding", "no_source", "old_reference", "objective_override", "resource_override"])
def test_wrong_adapter_or_client_overrides_are_rejected_before_http(wrong):
    p, data, spec = provider(), case(), SPEC
    if wrong == "text":
        p.kind = "chat"
    elif wrong == "other_feature":
        spec = FEATURE_BY_KEY["operations_qa"]
    elif wrong == "external":
        p.model = "external-optimizer"
    elif wrong == "no_binding":
        data["context"].pop("surgery_binding")
    elif wrong == "no_source":
        data["context"].pop("surgery_source")
    elif wrong == "old_reference":
        data["input"]["roster_plan_id"] = data["input"].pop("surgery_scenario_id")
    elif wrong == "objective_override":
        data["input"]["objective_mode"] = "max_optional_scheduled_then_min_declared_cost"
    else:
        data["input"]["room_capacity"] = 999
    with pytest.raises(AIExecutionError):
        _request(p, spec, PROMPT, data)


@pytest.mark.parametrize("key", ["surgery_source", "surgery_binding", "surgery_scenario"])
@pytest.mark.parametrize("kind", ["chat", "responses", "specialist"])
def test_each_protected_surgery_context_key_cannot_fall_back_to_another_model(key, kind):
    p = provider()
    p.kind, p.model = kind, "external-model"
    with pytest.raises(AIExecutionError) as error:
        _request(p, SPEC, PROMPT, {"input": {}, "context": {key: {}}, "evidence": []})
    assert error.value.code == "SURGERY_ADAPTER_REQUIRED"


@pytest.mark.parametrize(
    "other", ["bed_source", "roster_source", "sofa_source", "news2_source", "audio_source", "ecg_source", "image_source", "forecast_source", "aki_source", "qsofa_source", "sofa_change_source"]
)
def test_complete_surgery_result_cannot_be_mixed_with_another_native_source(other):
    with pytest.raises(AIExecutionError) as error:
        validate_generation({}, [], surgery_source={}, **{other: {}})
    assert error.value.code == "INVALID_OUTPUT"


@pytest.mark.parametrize("value", [True, "0", 0.0, -1, 2000001])
@pytest.mark.parametrize("field", ["input_tokens", "output_tokens"])
def test_usage_requires_actual_bounded_integers(value, field):
    data = {"input_tokens": 0, "output_tokens": 0, field: value}
    with pytest.raises(ValidationError):
        SurgeryUsage.model_validate(data)


@pytest.mark.parametrize("field", ["summary", "sections", "warnings", "missing_data"])
def test_explanation_cannot_omit_any_fixed_field(field):
    value = {"summary": "受审候选", "sections": [], "warnings": [], "missing_data": []}
    value.pop(field)
    with pytest.raises(ValidationError):
        SurgeryExplanation.model_validate(value)


@pytest.mark.asyncio
async def test_complete_request_over_8mib_is_rejected_before_any_http(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SURGERY_API_KEY", "synthetic-surgery-gateway-key-00000001")
    seen = []

    def rejected_request(request):
        seen.append(request)
        return httpx.Response(500)

    with pytest.raises(AIExecutionError) as error:
        await generate(provider(), SPEC, "x" * (MAX_BYTES + 1), copy.deepcopy(case()), transport=httpx.MockTransport(rejected_request))
    assert error.value.code == "SURGERY_REQUEST_LIMIT"
    assert seen == []
