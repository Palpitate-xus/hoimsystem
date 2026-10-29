"""Exercise malformed provider replies through the public text adapter boundary."""

import json
import logging

import httpx
import pytest

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError, generate
from app.ai.models import AIProvider

MISSING = object()
PRIVATE = "synthetic-provider-secret-and-patient-details"


def valid_result():
    return {
        "summary": "合成资料摘要",
        "sections": [{"title": "记录", "content": "已核对合成来源。", "source_ids": ["known-source"]}],
        "warnings": [],
        "missing_data": [],
    }


def envelope(kind, *, usage=MISSING, text=None):
    text = json.dumps(valid_result(), ensure_ascii=False) if text is None else text
    if kind == "chat":
        value = {"choices": [{"finish_reason": "stop", "message": {"content": text}}]}
    else:
        value = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}
    if usage is not MISSING:
        value["usage"] = usage
    return value


async def invoke(kind, value):
    provider = AIProvider(
        kind=kind,
        api_base="http://localhost:11434/v1",
        model="synthetic-error-boundaries",
        api_key_env="",
        api_key_encrypted="",
        timeout_seconds=3,
        max_attempts=1,
        max_output_tokens=2000,
        temperature=0.2,
    )
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=value)

    try:
        return await generate(
            provider,
            FEATURE_BY_KEY["patient_summary"],
            "整理合成记录",
            {"evidence": [{"source_id": "known-source"}]},
            transport=httpx.MockTransport(respond),
        )
    finally:
        # A received response is never replayed to repair its structure.
        assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("usage", [MISSING, None, {}], ids=["missing", "null", "empty"])
async def test_valid_result_without_a_usage_receipt_keeps_counts_unknown(kind, usage):
    result, inputs, outputs = await invoke(kind, envelope(kind, usage=usage))
    assert result.summary == "合成资料摘要"
    assert inputs is None and outputs is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("direction", ["input", "output"])
async def test_partial_usage_keeps_the_known_count_and_does_not_fill_the_missing_count(kind, direction):
    keys = {"chat": ("prompt_tokens", "completion_tokens"), "responses": ("input_tokens", "output_tokens")}[kind]
    index = 0 if direction == "input" else 1
    usage = {keys[index]: 7}
    _result, inputs, outputs = await invoke(kind, envelope(kind, usage=usage))
    assert (inputs, outputs) == ((7, None) if index == 0 else (None, 7))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("count", [0, 2_000_000])
async def test_actual_zero_and_bounded_integer_usage_are_preserved(kind, count):
    keys = {"chat": ("prompt_tokens", "completion_tokens"), "responses": ("input_tokens", "output_tokens")}[kind]
    _result, inputs, outputs = await invoke(kind, envelope(kind, usage={keys[0]: count, keys[1]: count}))
    assert (inputs, outputs) == (count, count)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("value", [True, False, 1.9, 0.0, "7", PRIVATE, -1, 2_000_001, [], {}])
async def test_invalid_token_counts_are_rejected_without_coercion_or_truncation(kind, value):
    keys = {"chat": ("prompt_tokens", "completion_tokens"), "responses": ("input_tokens", "output_tokens")}[kind]
    body = envelope(kind, usage={keys[0]: value, keys[1]: 7})
    body["untrusted_error_message"] = PRIVATE
    with pytest.raises(AIExecutionError) as caught:
        await invoke(kind, body)
    assert caught.value.code == "INVALID_PROVIDER_RESPONSE"
    assert PRIVATE not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("usage", [[], "7", True, 7])
async def test_nonobject_usage_is_a_safe_provider_response_error(kind, usage):
    with pytest.raises(AIExecutionError) as caught:
        await invoke(kind, envelope(kind, usage=usage))
    assert caught.value.code == "INVALID_PROVIDER_RESPONSE"
    assert PRIVATE not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("nested", [False, True], ids=["top-level", "nested"])
async def test_inner_model_json_rejects_duplicate_keys(kind, nested):
    raw = json.dumps(valid_result(), ensure_ascii=False)
    if nested:
        raw = raw.replace('"content": "已核对合成来源。"', '"content": "' + PRIVATE + '", "content": "已核对合成来源。"')
    else:
        raw = raw.replace('"summary": "合成资料摘要"', '"summary": "' + PRIVATE + '", "summary": "合成资料摘要"')
    with pytest.raises(AIExecutionError) as caught:
        await invoke(kind, envelope(kind, text=raw))
    assert caught.value.code == "INVALID_PROVIDER_RESPONSE"
    assert PRIVATE not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,body",
    [
        ("chat", {"choices": [None]}),
        ("chat", {"choices": [{"finish_reason": "stop", "message": None}]}),
        ("chat", {"choices": [{"finish_reason": "stop", "message": {"content": []}}]}),
        ("responses", {"status": "completed", "output": [None]}),
        ("responses", {"status": "completed", "output": [{"type": "message", "content": [None]}]}),
        ("responses", {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": None}]}]}),
    ],
    ids=["null-choice", "null-message", "nontext-chat-content", "null-output-item", "null-content-item", "nontext-responses-content"],
)
async def test_malformed_envelopes_are_classified_without_escaping_attribute_errors(kind, body):
    body["untrusted_error_message"] = PRIVATE
    with pytest.raises(AIExecutionError) as caught:
        await invoke(kind, body)
    assert caught.value.code == "INVALID_PROVIDER_RESPONSE"
    assert PRIVATE not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_unfinished_generations_keep_the_incomplete_response_code(kind):
    body = envelope(kind)
    if kind == "chat":
        body["choices"][0]["finish_reason"] = "length"
    else:
        body["status"] = "incomplete"
    with pytest.raises(AIExecutionError) as caught:
        await invoke(kind, body)
    assert caught.value.code == "INCOMPLETE_RESPONSE"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_explicit_refusals_keep_a_safe_refusal_code_without_provider_text(kind):
    body = envelope(kind)
    if kind == "chat":
        body["choices"][0]["message"]["refusal"] = PRIVATE
    else:
        body["output"][0]["content"] = [{"type": "refusal", "refusal": PRIVATE}]
    with pytest.raises(AIExecutionError) as caught:
        await invoke(kind, body)
    assert caught.value.code == "MODEL_REFUSAL"
    assert PRIVATE not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_provider_refusal_details_do_not_appear_in_debug_logs(kind, caplog):
    caplog.set_level(logging.DEBUG)
    body = envelope(kind)
    if kind == "chat":
        body["choices"][0]["message"]["refusal"] = PRIVATE
    else:
        body["output"][0]["content"] = [{"type": "refusal", "refusal": PRIVATE}]
    with pytest.raises(AIExecutionError) as caught:
        await invoke(kind, body)
    assert PRIVATE not in str(caught.value)
    assert PRIVATE not in "\n".join(record.getMessage() for record in caplog.records)
