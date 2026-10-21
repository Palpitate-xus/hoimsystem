"""Actual httpx transport requests/streams, intercepted entirely in memory."""

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from app.ai import document_change_contract as c
from app.ai import document_change_gateway as g
from app.ai.document_change_context import change_evidence, short_context
from app.ai.document_change_draft import SYSTEM_PROMPT, TASK_PROMPT, checked_source
from app.ai.document_change_view_contract import binding_for_source
from app.ai.gateway import AIExecutionError
from tests.test_ai_document_change_draft import source
from tests.test_ai_document_change_protocol import envelope
from tests.test_ai_document_evidence_contract import NOW


def provider(kind="chat", **values):
    return SimpleNamespace(
        provider_id=1,
        revision=1,
        name="合成版本文字服务",
        kind=kind,
        api_base="http://127.0.0.1:8824/v1",
        model="synthetic-change-text",
        timeout_seconds=3,
        max_output_tokens=1024,
        validation_report="仅合成工程测试",
        temperature=0.0,
        allows_patient_data=1,
        **values,
    )


def payload(src):
    bound = binding_for_source(src)
    return {
        "input": {"document_change_scope_id": src.scope.scope_id, "question": "原问题\r\n😀"},
        "context": short_context(bound, NOW).model_dump(mode="json"),
        "tools": {},
        "evidence": change_evidence(bound),
    }


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    monkeypatch.setattr(g, "provider_credential", lambda _: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_wire_contains_only_exact_public_source_question_and_fixed_prompts(kind):
    src, requests = source(), []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=envelope(kind))

    result, inputs, outputs = await g.generate_document_change(provider(kind), TASK_PROMPT, payload(src), src, transport=httpx.MockTransport(handler))
    assert (inputs, outputs) == (11, 13) and len(requests) == 1
    request = requests[0]
    body = json.loads(request.content)
    assert body["store"] is False and request.headers["accept-encoding"] == "identity"
    assert request.url.path == "/v1/" + ("chat/completions" if kind == "chat" else "responses")
    if kind == "chat":
        instructions, public = body["messages"][0]["content"], body["messages"][1]["content"]
    else:
        instructions, public = body["instructions"], body["input"][0]["content"]
        assert body["text"]["format"]["strict"] is True and body["text"]["format"]["schema"]["additionalProperties"] is False
    assert instructions == SYSTEM_PROMPT + "\n\n" + TASK_PROMPT
    assert json.loads(public) == {"document_change_source": src.model_dump(mode="json"), "question": "原问题\r\n😀"}
    assert "document_change_binding" not in public and "document_change_private_scope" not in public
    assert result.document_change.binding.instructions_digest == c.e.bytes_hash(instructions)
    assert result.document_change.requires_human_review is True and result.document_change.automatic_changes is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["source_binding", "tools", "private_scope", "input_extra", "permission", "kind"])
async def test_invalid_permissions_or_mixed_task_never_make_an_http_attempt(mutation):
    src, body, config, calls = source(), payload(source()), provider(), []
    if mutation == "source_binding":
        body["context"]["document_change_binding"]["source_digest"] = "f" * 64
    elif mutation == "tools":
        body["tools"] = {"action": "PRIVATE_SENTINEL"}
    elif mutation == "private_scope":
        body["context"]["document_change_private_scope"] = {"raw": "PRIVATE_SENTINEL"}
    elif mutation == "input_extra":
        body["input"]["document_original_id"] = src.baseline.original.original_id
    elif mutation == "permission":
        config.allows_patient_data = 0
    else:
        config.kind = "specialist"
    with pytest.raises(AIExecutionError) as info:
        await g.generate_document_change(config, TASK_PROMPT, body, src, transport=httpx.MockTransport(lambda request: calls.append(request)))
    assert info.value.model_call_attempted is False and info.value.input_tokens is None and info.value.output_tokens is None
    assert not calls and "PRIVATE_SENTINEL" not in info.value.message


@pytest.mark.asyncio
async def test_valid_source_below8mib_can_exceed_complete_provider_protocol_and_is_not_sent():
    value = source(link_count=0).model_dump(mode="json")
    text = '"' * 2200000
    value["baseline"].update(text=text, codepoint_length=len(text), raw_bytes_length=len(c.e.utf8(text)), raw_bytes_hash=c.e.bytes_hash(text))
    src = checked_source(value)
    assert len(c.e.utf8(c.e.canonical_json(src))) < c.MAX_CASE_BYTES
    calls = []
    with pytest.raises(AIExecutionError) as info:
        await g.generate_document_change(provider(), TASK_PROMPT, payload(src), src, transport=httpx.MockTransport(lambda request: calls.append(request)))
    assert info.value.code == "DOCUMENT_CHANGE_REQUEST_REJECTED" and info.value.model_call_attempted is False and not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("bad", ["wrong_quote", "duplicate_literal", "refusal", "partial_usage", "missing_usage"])
async def test_rejected_paid_reply_keeps_actual_nullable_usage(kind, bad):
    value = envelope(kind)
    expected = 11, 13
    if bad == "wrong_quote":
        raw = '{"changes":[{"kind":"baseline_excerpt_question","baseline_spans":[{"start":0,"end":1,"quote":"X"}],"candidate_spans":[],"review_note":"未核实","clarification_question":"请核实？"}]}'
        value = envelope(kind, raw)
    elif bad == "duplicate_literal":
        value = envelope(kind, '{"changes":[],"changes":[]}')
    elif bad == "refusal":
        message = value["choices"][0]["message"] if kind == "chat" else value["output"][1]
        message["refusal"] = "PRIVATE_SENTINEL"
    elif bad == "partial_usage":
        value["usage"].pop("completion_tokens" if kind == "chat" else "output_tokens")
        expected = 11, None
    else:
        value.pop("usage")
        expected = None, None
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=value)

    with pytest.raises(AIExecutionError) as info:
        await g.generate_document_change(provider(kind), TASK_PROMPT, payload(source()), source(), transport=httpx.MockTransport(handler))
    assert len(requests) == 1 and info.value.model_call_attempted is True
    assert (info.value.input_tokens, info.value.output_tokens) == expected and "PRIVATE_SENTINEL" not in info.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b'{"usage":{},"usage":{}}', b'{"usage":NaN}', b'{"usage":1e999}', b"[]", b"\xff"])
async def test_whole_provider_json_ambiguity_nonfinite_or_invalid_utf8_has_no_trusted_receipt(raw):
    with pytest.raises(AIExecutionError) as info:
        await g.generate_document_change(provider(), TASK_PROMPT, payload(source()), source(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw)))
    assert info.value.model_call_attempted is True and (info.value.input_tokens, info.value.output_tokens) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 429, 500])
async def test_error_response_is_never_followed_or_retried_but_received_usage_is_kept(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "PRIVATE_SENTINEL", "usage": {"prompt_tokens": 11}}, headers={"location": "http://127.0.0.1:1/not-followed"})

    with pytest.raises(AIExecutionError) as info:
        await g.generate_document_change(provider(), TASK_PROMPT, payload(source()), source(), transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and info.value.code == "DOCUMENT_CHANGE_PROVIDER_HTTP"
    assert (info.value.input_tokens, info.value.output_tokens) == (11, None) and info.value.model_call_attempted is True


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, delay=0):
        self.chunks, self.delay, self.yielded, self.closed = chunks, delay, 0, False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.yielded += 1
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_streaming8mib_boundary_refuses_extra_before_append_or_reading_more():
    stream = Stream([b" " * c.MAX_CASE_BYTES, b"x", b"must-not-be-read"])
    with pytest.raises(AIExecutionError) as info:
        await g.generate_document_change(provider(), TASK_PROMPT, payload(source()), source(), transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)))
    assert info.value.code == "DOCUMENT_CHANGE_RESPONSE_LIMIT" and stream.closed and stream.yielded == 2


@pytest.mark.asyncio
async def test_compressed_response_is_rejected_before_any_decompression_or_body_read():
    stream = Stream([b"not-a-gzip-stream"])
    with pytest.raises(AIExecutionError) as info:
        await g.generate_document_change(
            provider(), TASK_PROMPT, payload(source()), source(), transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream, headers={"content-encoding": "gzip"}))
        )
    assert info.value.code == "DOCUMENT_CHANGE_RESPONSE_ENCODING" and stream.closed and stream.yielded == 0


@pytest.mark.asyncio
async def test_continuous_slow_chunks_do_not_reset_the_complete_actual_deadline():
    stream = Stream([b" "] * 30, delay=0.2)
    began = time.monotonic()
    with pytest.raises(AIExecutionError) as info:
        await g.generate_document_change(provider(), TASK_PROMPT, payload(source()), source(), transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)))
    assert info.value.code == "DOCUMENT_CHANGE_PROVIDER_TIMEOUT" and info.value.model_call_attempted is True
    assert stream.closed and 0 < stream.yielded < 20 and time.monotonic() - began < 4.5
