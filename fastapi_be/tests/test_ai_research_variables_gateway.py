"""Actual local ASGI protocol transport over the unmodified actual Source.

Frozen model values here are explicitly controlled shape inputs, not a real
configured Task or provider qualification. Runtime/SQL is tested separately.
"""

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.ai import research_variables_gateway as gateway
from app.ai.research_variables_storage_contract import VariableTaskSnapshot
from app.ai.research_variables_task_binding import VariableTaskBinding
from app.ai.research_variables_task_contract import MAX_WIRE_BYTES, VariableTaskSource, canonical, digest
from app.ai.research_variables_task_result import validate_result
from tests.test_ai_research_variables_storage_contract import original, snapshot
from tests.test_ai_research_variables_task_result import draft, envelope


def values(kind="chat"):
    actual = original()
    raw = snapshot()
    raw["provider_snapshot"].update(kind=kind, api_base="http://localhost/v1")
    return VariableTaskSnapshot.model_validate(raw), VariableTaskBinding.model_validate(actual["binding"]), VariableTaskSource.model_validate(actual["source"])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("usage", ["full", "absent", "partial"])
async def test_one_actual_asgi_provider_request_contains_complete_public_source_only_fixed_prompts_and_real_nullable_usage(kind, usage):
    snap, binding, source = values(kind)
    calls = []
    app = FastAPI()

    @app.post("/v1/chat/completions")
    @app.post("/v1/responses")
    async def reply(request: Request):
        raw = await request.body()
        calls.append((request.url.path, raw, request.headers.get("authorization")))
        count = False if usage == "absent" else {"prompt_tokens" if kind == "chat" else "input_tokens": 11} if usage == "partial" else True
        return JSONResponse(envelope(kind, canonical(draft(source)), count))

    accepted, inputs, outputs = await gateway.generate_research_variables(snap, binding, source, credential="synthetic-not-hospital", transport=httpx.ASGITransport(app=app))
    assert len(calls) == 1
    path, raw, authorization = calls[0]
    assert path == ("/v1/responses" if kind == "responses" else "/v1/chat/completions") and authorization == "Bearer synthetic-not-hospital"
    payload = json.loads(raw)
    assert payload["store"] is False and "tools" not in payload
    public = json.loads(payload["input"][0]["content"] if kind == "responses" else payload["messages"][1]["content"])
    assert set(public) == {"research_variable_source", "question"}
    assert public["research_variable_source"] == source.model_dump(mode="json")
    assert public["question"] == snap.payload.input.question
    assert not any(word in canonical(public) for word in ("patient_ids", "request_authorization", "identity_key", "review_basis_note", "task_acl_id"))
    assert (payload["instructions"] if kind == "responses" else payload["messages"][0]["content"]) == snap.system_prompt + "\n\n" + snap.task_prompt
    assert (inputs, outputs) == ({"full": (11, 13), "absent": (None, None), "partial": (11, None)}[usage])
    assert validate_result(accepted, source, gateway.instructions_digest(snap)) == accepted


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 429, 500])
async def test_http_error_or_redirect_is_one_attempt_no_retry_no_follow_and_unknown_usage(status):
    snap, binding, source = values()
    calls = []
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def reply(request: Request):
        calls.append(request.url.path)
        return Response(status_code=status, headers={"Location": "http://localhost/should-not-follow"})

    with pytest.raises(gateway.VariableGatewayError) as error:
        await gateway.generate_research_variables(snap, binding, source, credential="", transport=httpx.ASGITransport(app=app))
    assert calls == ["/v1/chat/completions"]
    assert error.value.code == "VARIABLE_PROVIDER_HTTP" and error.value.model_call_attempted is True
    assert error.value.input_tokens is None and error.value.output_tokens is None


@pytest.mark.asyncio
async def test_actual_asgi_bad_quote_rejects_content_but_preserves_independently_reported_paid_tokens():
    snap, binding, source = values()
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def reply():
        proposed = draft(source)
        proposed["candidates"][0]["quote"] += "原文无"
        return JSONResponse(envelope("chat", canonical(proposed)))

    with pytest.raises(gateway.VariableGatewayError) as error:
        await gateway.generate_research_variables(snap, binding, source, credential="", transport=httpx.ASGITransport(app=app))
    assert error.value.code == "VARIABLE_REPLY_INVALID" and error.value.model_call_attempted is True
    assert (error.value.input_tokens, error.value.output_tokens) == (11, 13)


@pytest.mark.asyncio
async def test_duplicate_response_keys_and_nonfinite_values_are_not_accepted_or_normalized():
    snap, binding, source = values()
    for raw in ('{"choices":[],"choices":[]}', '{"usage":{"prompt_tokens":NaN}}'):
        calls = []

        async def reply(request):
            calls.append(1)
            return httpx.Response(200, content=raw.encode())

        with pytest.raises(gateway.VariableGatewayError) as error:
            await gateway.generate_research_variables(snap, binding, source, credential="", transport=httpx.MockTransport(reply))
        assert calls == [1] and error.value.model_call_attempted is True
        assert error.value.input_tokens is None and error.value.output_tokens is None


@pytest.mark.asyncio
async def test_stream_total_deadline_covers_slow_chunks_and_response_bytes_are_bounded_without_retry():
    snap, binding, source = values()
    real_timeout = gateway.asyncio.timeout
    calls = []

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{"
            await asyncio.sleep(0.05)
            yield b"}"

    class Oversize(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * MAX_WIRE_BYTES
            yield b"x"

    for stream, code in ((Slow, "VARIABLE_PROVIDER_ERROR"), (Oversize, "VARIABLE_RESPONSE_LIMIT")):

        async def reply(request):
            calls.append(1)
            return httpx.Response(200, stream=stream())

        # Test-only deadline shortening; actual provider contract remains3..120s.
        gateway.asyncio.timeout = lambda seconds: real_timeout(0.01 if stream is Slow else seconds)
        try:
            with pytest.raises(gateway.VariableGatewayError) as error:
                await gateway.generate_research_variables(snap, binding, source, credential="", transport=httpx.MockTransport(reply))
        finally:
            gateway.asyncio.timeout = real_timeout
        assert error.value.code == code and error.value.model_call_attempted is True
        assert error.value.input_tokens is None and error.value.output_tokens is None
    assert calls == [1, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("credential", [None, "\r\nInjected: private", "x" * 8193, "非法Header"])
async def test_invalid_credential_never_calls_transport_and_has_definitely_unattempted_receipt(credential):
    snap, binding, source = values()
    calls = []

    async def reply(request):
        calls.append(1)
        return httpx.Response(200)

    with pytest.raises(gateway.VariableGatewayError) as error:
        await gateway.generate_research_variables(snap, binding, source, credential=credential, transport=httpx.MockTransport(reply))
    assert not calls and error.value.model_call_attempted is False


def test_whole_request_budget_includes_real_system_task_and_json_protocol_escaping_beyond_legal_source_bytes():
    snap, binding, source = values()
    raw = source.model_dump(mode="json")
    raw["documents"][0]["literal"] = '"' * 2_100_000
    raw["documents_hash"] = digest(raw["documents"])
    source = VariableTaskSource.model_validate(raw)
    assert 4_000_000 < len(canonical(source).encode()) < MAX_WIRE_BYTES
    # Controlled pure capacity case, not a replacement for SQL authority: update
    # the matching independent fixture anchors so only WHOLE wire size fails.
    bound = binding.model_dump(mode="json")
    bound["documents_hash"] = source.documents_hash
    bound["source_projection_hash"], bound["source_bytes"] = digest(source), len(canonical(source).encode())
    binding = VariableTaskBinding.model_validate(bound)
    value = snap.model_dump(mode="json")
    value["payload"]["context"]["research_variable_binding"]["source_projection_hash"] = binding.source_projection_hash
    value["payload"]["context"]["research_variable_binding"]["binding_hash"] = digest(binding)
    value["payload"]["evidence"][0].update(source_digest=binding.source_projection_hash, documents_hash=source.documents_hash)
    snap = VariableTaskSnapshot.model_validate(value)
    with pytest.raises(gateway.VariableGatewayError) as error:
        gateway.build_request(snap, binding, source)
    assert error.value.code == "VARIABLE_REQUEST_REJECTED" and error.value.model_call_attempted is False
    assert "escaping/envelope" in str(error.value.__cause__)
