"""Synthetic actual Source proof through the text gateway; no external model call."""

# ruff: noqa: F811 -- imported pytest fixtures are injected by their names.

import copy
import json

import httpx
import pytest

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.coding_evidence_context import expand_context
from app.ai.coding_evidence_prompt import CODING_SYSTEM_PROMPT
from app.ai.coding_evidence_protocol import parse_provider_draft
from app.ai.gateway import AIExecutionError, _request, generate
from app.ai.models import AIProvider
from tests.test_ai_coding_evidence_context import bundle_for, draft_for, selected
from tests.test_ai_coding_evidence_sources import case, published  # noqa: F401
from tests.test_coding_evidence_legacy_writes import coding_case  # noqa: F401

SPEC = FEATURE_BY_KEY["drg_evidence_review"]


def provider(kind="chat"):
    return AIProvider(kind=kind, model="synthetic-text-model", api_base="http://127.0.0.1:11434/v1", api_key_env="", api_key_encrypted="", max_output_tokens=4096, timeout_seconds=5, temperature=0)


def envelope(kind, draft):
    text = draft if type(draft) is str else json.dumps(draft, ensure_ascii=False)
    if kind == "chat":
        return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": 13, "completion_tokens": 7}}
    return {"status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}], "usage": {"input_tokens": 13, "output_tokens": 7}}


def complete_data(db, c):
    row = published(db, c)
    bundle = bundle_for(db, c, row)
    context = expand_context(db, bundle.data, user=c["doctor_user"], current=True)
    data = {"input": selected(row), "context": context, "tools": {}, "evidence": bundle.evidence}
    draft = draft_for(context["coding_source"], context["coding_binding"]["projection_hash"])
    return data, draft.model_dump(mode="json")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_complete_projection_only_request_and_exact_draft_result(db_session, case, kind):
    data, draft = complete_data(db_session, case)
    seen = []

    def handle(request):
        packet = json.loads(request.content)
        seen.append(packet)
        if kind == "chat":
            assert packet["messages"][0]["content"] == CODING_SYSTEM_PROMPT + "\n\n" + SPEC.task_prompt
            model = json.loads(packet["messages"][1]["content"])
        else:
            assert packet["store"] is False and packet["instructions"] == CODING_SYSTEM_PROMPT + "\n\n" + SPEC.task_prompt
            schema = packet["text"]["format"]["schema"]
            assert schema["additionalProperties"] is False and set(schema["required"]) == {"schema_version", "source_id", "source_projection_hash", "claims"}
            assert set(schema["properties"]) == set(schema["required"])
            model = json.loads(packet["input"][0]["content"])
        assert set(model) == {"coding_source", "source_projection_hash", "question"}
        text = json.dumps(model, ensure_ascii=False)
        for private in (
            case["patient"].name,
            case["patient"].identity,
            case["home"].home_id,
            case["admission"].admission_id,
            "identity_secret",
            "expected_amount",
            "actual_amount",
            "coder_id",
            "snapshot",
        ):
            if private == "snapshot":
                assert '"snapshot"' not in text
            else:
                assert private not in text
        return httpx.Response(200, json=envelope(kind, draft))

    result, inputs, outputs = await generate(provider(kind), SPEC, SPEC.task_prompt, data, transport=httpx.MockTransport(handle))
    assert len(seen) == 1 and (inputs, outputs) == (13, 7)
    assert result.coding_analysis.model_dump(mode="json") == draft
    assert "待复核" in result.summary and "已确认编码" not in result.summary


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["wrong_source", "changed_quote", "missing_member", "extra_group"])
async def test_provider_cannot_replace_original_closure_or_add_grouping(db_session, case, attack):
    data, draft = complete_data(db_session, case)
    if attack == "wrong_source":
        draft["source_id"] = "coding_case:other"
    elif attack == "changed_quote":
        draft["claims"][0]["citations"][0]["quote"] += "编造"
    elif attack == "missing_member":
        draft["claims"] = []
    else:
        draft["group_code"] = "new-group"
    with pytest.raises(AIExecutionError) as exc:
        await generate(provider(), SPEC, SPEC.task_prompt, data, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope("chat", draft))))
    assert exc.value.code == "INVALID_PROVIDER_RESPONSE"


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("attack", ["missing_usage", "boolean_usage", "duplicate_inner_key", "refusal", "incomplete"])
def test_incomplete_or_ambiguous_provider_receipt_is_rejected(kind, attack):
    draft = {"schema_version": "coding_evidence_draft_v1", "source_id": "coding_case:synthetic", "source_projection_hash": "a" * 64, "claims": []}
    value = envelope(kind, draft)
    if attack == "missing_usage":
        del value["usage"]
    elif attack == "boolean_usage":
        value["usage"]["prompt_tokens" if kind == "chat" else "input_tokens"] = True
    elif attack == "duplicate_inner_key":
        value = envelope(kind, json.dumps(draft).replace('"claims":', '"claims":[],"claims":'))
    elif kind == "chat":
        if attack == "refusal":
            value["choices"][0]["message"]["refusal"] = "refused"
        else:
            value["choices"][0]["finish_reason"] = "length"
    elif attack == "refusal":
        value["output"][0]["content"] = [{"type": "refusal", "refusal": "refused"}]
    else:
        value["status"] = "incomplete"
    with pytest.raises(ValueError):
        parse_provider_draft(kind, value)


def test_mixed_context_wrong_feature_and_specialist_refuse_before_http(db_session, case):
    data, _ = complete_data(db_session, case)
    mixed = copy.deepcopy(data)
    mixed["context"]["inventory_source"] = {}
    for p, spec, packet in [(provider(), SPEC, mixed), (provider(), FEATURE_BY_KEY["patient_summary"], data), (provider("specialist"), SPEC, data)]:
        with pytest.raises(AIExecutionError):
            _request(p, spec, SPEC.task_prompt, packet)
