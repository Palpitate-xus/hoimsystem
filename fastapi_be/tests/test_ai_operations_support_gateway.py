"""Actual mock HTTP protocols, complete wire budgets and independent usage."""

import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.ai import operations_support_contract as c
from app.ai import operations_support_gateway as gateway
from app.ai import operations_support_projection as projection
from app.ai.operations_support_protocol import MAX_BYTES, model_wire
from app.ai.operations_support_task_prompt import SYSTEM_PROMPT, TASK_PROMPT
from app.ai.operations_support_usage_contract import OperationsUsage, usage
from tests.test_ai_operations_support_task_contract import result, setup_source


@pytest.fixture
def provider():
    return SimpleNamespace(
        kind="chat", api_base="http://127.0.0.1:1/v1", model="synthetic-operations-model", temperature=Decimal("0.125"), timeout_seconds=5, max_output_tokens=2000, api_key_env="", api_key_encrypted=""
    )


def envelope(kind, value, counts=None):
    packet = {"usage": {"prompt_tokens": 11, "completion_tokens": 13} if kind == "chat" else {"input_tokens": 11, "output_tokens": 13}}
    if counts is not None:
        packet["usage"] = counts
    if kind == "chat":
        packet["choices"] = [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": c.canonical_json(value)}}]
    else:
        packet.update(status="completed", output=[{"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": c.canonical_json(value)}]}])
    return packet


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_single_http_full_public_source_custom_prompt_no_tools_and_exact_quote(provider, kind, db_session):
    source, selection = setup_source()
    expected = result(source, selection)
    provider.kind = kind
    custom = "\ufeff实际独立Task版本\r\n😀\x00  尾部  "
    calls = []
    db_session.commit()

    def handle(incoming):
        calls.append(incoming)
        assert not db_session.in_transaction()
        assert incoming.url.path == ("/v1/chat/completions" if kind == "chat" else "/v1/responses")
        wire = json.loads(incoming.content)
        assert wire["store"] is False and "tools" not in wire
        instructions = wire["messages"][0]["content"] if kind == "chat" else wire["instructions"]
        assert instructions == SYSTEM_PROMPT + "\n\n" + custom
        visible = json.loads(wire["messages"][1]["content"] if kind == "chat" else wire["input"])
        assert visible["source"] == source.model_dump(mode="json")
        assert visible["selection"] == selection.model_dump(mode="json")
        assert not {"private", "patient_id", "identity_json", "review_basis", "api_key_env"} & visible.keys()
        return httpx.Response(200, json=envelope(kind, expected))

    actual, receipt, latency = await gateway.generate_operations(provider, source, selection, custom, transport=httpx.MockTransport(handle))
    assert actual.model_dump() == expected and receipt == usage(11, 13, True) and latency >= 0 and len(calls) == 1
    assert actual.manual_checks[0].instruction_reference.quote == "X"


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("fault", ["truncated", "action", "refusal", "multiple", "quote", "source_hash", "invented_command", "verified_status"])
def test_invalid_or_action_response_retains_actual_partial_paid_usage(kind, fault):
    source, selection = setup_source()
    draft = result(source, selection)
    if fault == "quote":
        draft["observations"][0]["evidence"][0]["quote"] = "invented"
    elif fault == "source_hash":
        draft["source_sha256"] = "0" * 64
    elif fault == "invented_command":
        draft["commands"] = ["invented"]
    elif fault == "verified_status":
        draft["status"] = "verified"
    packet = envelope(kind, draft, {"prompt_tokens" if kind == "chat" else "input_tokens": 11})
    message = packet["choices"][0]["message"] if kind == "chat" else packet["output"][0]
    if fault == "truncated":
        if kind == "chat":
            packet["choices"][0]["finish_reason"] = "length"
        else:
            packet["status"] = "incomplete"
    elif fault == "action":
        message["tool_calls"] = []
    elif fault == "refusal":
        message["refusal"] = "合成拒绝"
    elif fault == "multiple":
        if kind == "chat":
            packet["choices"] *= 2
        else:
            packet["output"] *= 2
    with pytest.raises(gateway.OperationsCallError) as exc:
        gateway.parse_reply(kind, packet, source, selection)
    assert exc.value.code == "INVALID_OPERATIONS_RESPONSE" and exc.value.usage == usage(11, None, True)
    assert "invented" not in str(exc.value)


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize(
    "counts,expected",
    [
        (None, (None, None)),
        ({}, (None, None)),
        ({"input": 11}, (11, None)),
        ({"input": False, "output": 13}, (None, 13)),
        ({"input": 0, "output": 0}, (0, 0)),
        ({"input": -1, "output": 2147483648}, (None, None)),
    ],
)
def test_missing_partial_false_zero_and_invalid_counts_stay_independent(kind, counts, expected):
    source, selection = setup_source()
    packet = envelope(kind, result(source, selection))
    if counts is None:
        packet.pop("usage")
    else:
        keys = {"input": "prompt_tokens" if kind == "chat" else "input_tokens", "output": "completion_tokens" if kind == "chat" else "output_tokens"}
        packet["usage"] = {keys[key]: value for key, value in counts.items()}
    actual, receipt = gateway.parse_reply(kind, packet, source, selection)
    assert actual.source_id == source.source_id and receipt == usage(*expected, True)


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_inconsistent_total_is_rejected_without_discarding_two_actual_counts(kind):
    source, selection = setup_source()
    packet = envelope(kind, result(source, selection))
    packet["usage"]["total_tokens"] = 999
    with pytest.raises(gateway.OperationsCallError) as exc:
        gateway.parse_reply(kind, packet, source, selection)
    assert exc.value.usage == usage(11, 13, True)


def test_responses_complete_text_parts_are_concatenated_without_whitespace_or_unicode_changes():
    source, selection = setup_source()
    packet = envelope("responses", result(source, selection))
    raw = packet["output"][0]["content"][0]["text"]
    packet["output"][0]["content"] = [{"type": "output_text", "text": raw[:17]}, {"type": "output_text", "text": raw[17:]}]
    actual, receipt = gateway.parse_reply("responses", packet, source, selection)
    assert actual.model_dump() == result(source, selection) and receipt == usage(11, 13, True)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_double_escaped_request_budget_refuses_before_http(provider, kind):
    source, selection = setup_source()
    provider.kind = kind

    def with_text(length):
        value = source.model_dump(mode="json")
        text = "\\" * length
        value["documents"][0].update(text=text, text_sha256=__import__("hashlib").sha256(text.encode()).hexdigest())
        return projection.OperationsSupportSource.model_validate(value, strict=True)

    legal = with_text(2**21 - 16384)
    endpoint, payload, _ = gateway.request(provider, legal, selection, TASK_PROMPT)
    assert len(c.canonical_json(payload).encode()) < MAX_BYTES
    larger = with_text(2**21)
    pure_wire, _ = model_wire(larger, selection, TASK_PROMPT)
    assert len(c.canonical_json(larger).encode()) < MAX_BYTES and len(c.canonical_json(pure_wire).encode()) < MAX_BYTES
    calls = []

    def handle(req):
        calls.append(req)
        return httpx.Response(500)

    with pytest.raises(gateway.OperationsCallError) as exc:
        await gateway.generate_operations(provider, larger, selection, TASK_PROMPT, transport=httpx.MockTransport(handle))
    assert exc.value.code == "OPERATIONS_REQUEST_LIMIT" and exc.value.usage == usage(0, 0, False) and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["host", "model", "timeout", "temperature", "credential"])
async def test_configuration_failure_never_dispatches_or_fabricates_paid_use(provider, fault, monkeypatch):
    source, selection = setup_source()
    if fault == "host":
        provider.api_base = "https://unapproved.invalid/v1"
    elif fault == "model":
        provider.model = " "
    elif fault == "timeout":
        provider.timeout_seconds = True
    elif fault == "temperature":
        provider.temperature = Decimal("NaN")
    else:

        def refuse(_):
            raise HTTPException(503, "合成凭据错误含PRIVATE_SENTINEL")

        monkeypatch.setattr(gateway, "provider_credential", refuse)
    calls = []
    with pytest.raises(gateway.OperationsCallError) as exc:
        await gateway.generate_operations(provider, source, selection, TASK_PROMPT, transport=httpx.MockTransport(lambda req: calls.append(req)))
    assert exc.value.usage == usage(0, 0, False) and calls == [] and "PRIVATE_SENTINEL" not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["redirect", "timeout", "duplicate_key", "nonfinite", "utf8", "oversize"])
async def test_one_attempt_response_failure_remains_unknown_and_never_retries(provider, fault):
    source, selection = setup_source()
    calls = []

    def handle(req):
        calls.append(req)
        if fault == "timeout":
            raise httpx.ReadTimeout("PRIVATE_SENTINEL", request=req)
        if fault == "redirect":
            return httpx.Response(307, headers={"Location": "https://unapproved.invalid/PRIVATE_SENTINEL"})
        if fault == "duplicate_key":
            raw = b'{"usage":{},"usage":{}}'
        elif fault == "nonfinite":
            raw = b'{"usage":{"prompt_tokens":NaN}}'
        elif fault == "utf8":
            raw = b"\xff"
        else:
            raw = b" " * (MAX_BYTES + 1)
        return httpx.Response(200, content=raw)

    with pytest.raises(gateway.OperationsCallError) as exc:
        await gateway.generate_operations(provider, source, selection, TASK_PROMPT, transport=httpx.MockTransport(handle))
    assert len(calls) == 1 and exc.value.usage == usage(None, None, True) and "PRIVATE_SENTINEL" not in str(exc.value)


@pytest.mark.parametrize("change", [{"input_tokens": False}, {"input_tokens": -1}, {"complete": False}, {"model_call_attempted": None}, {"model_call_attempted": False}])
def test_usage_cannot_convert_unknown_or_paid_count_to_proven_zero(change):
    with pytest.raises(ValueError):
        OperationsUsage.model_validate({**usage(11, 13, True), **change}, strict=True)


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("reported_inputs", [11, None])
def test_valid_optional_total_never_infers_missing_components_or_invalidates_complete_content(kind, reported_inputs):
    source, selection = setup_source()
    counts = {"total_tokens": 99}
    if reported_inputs is not None:
        counts["prompt_tokens" if kind == "chat" else "input_tokens"] = reported_inputs
    packet = envelope(kind, result(source, selection), counts)
    draft, receipt = gateway.parse_reply(kind, packet, source, selection)
    assert draft.model_dump() == result(source, selection) and receipt == usage(reported_inputs, None, True)


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("total", [False, -1, 24.0])
def test_explicit_invalid_total_rejects_but_retains_known_companion_count(kind, total):
    source, selection = setup_source()
    packet = envelope(kind, result(source, selection), {"prompt_tokens" if kind == "chat" else "input_tokens": 11, "total_tokens": total})
    with pytest.raises(gateway.OperationsCallError) as exc:
        gateway.parse_reply(kind, packet, source, selection)
    assert exc.value.usage == usage(11, None, True)
