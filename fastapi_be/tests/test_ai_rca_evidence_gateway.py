"""Real local ASGI text envelopes on synthetic pure Sources, no model or SQL.

Provider replies are explicit mock text, not evidence of inference quality or
current Source eligibility. Current authority and worker integration are separate.
"""

import asyncio
import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_gateway as g
from app.ai import rca_evidence_task_contract as t
from app.ai.rca_evidence_task_prompt import SYSTEM_PROMPT, TASK_PROMPT
from app.config import settings
from tests.test_ai_rca_evidence_contract import CASE, TIME, source_dict
from tests.test_ai_rca_evidence_protocol import envelope
from tests.test_ai_rca_evidence_task_contract import binding


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "synthetic.invalid")
    return SimpleNamespace(
        kind="chat",
        model="synthetic-rca-text",
        allows_patient_data=1,
        api_base="https://synthetic.invalid/v1",
        max_output_tokens=4096,
        timeout_seconds=3,
        temperature=Decimal("0.25"),
        api_key_env="",
        api_key_encrypted=None,
    )


def data(source=None):
    source = c.validate_source(source or source_dict())
    bound = binding(source)
    context = t.expand_public_context(t.short_context(bound, TIME), source)
    return {"input": {"rca_evidence_case_id": CASE, "question": "仅合成问题🙂\r\n"}, "context": context, "tools": {}, "evidence": t.evidence_for_binding(bound)}


def service(callback):
    app = FastAPI()
    seen = []

    @app.post("/v1/{path:path}")
    async def reply(request: Request, path: str):
        body = await request.body()
        seen.append((request.url.path, body, dict(request.headers)))
        result = callback(request, body)
        if hasattr(result, "__await__"):
            result = await result
        return result

    return httpx.ASGITransport(app=app), seen


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_real_asgi_public_only_wire_complete_literal_reply_and_actual_usage(provider, kind):
    provider.kind = kind
    packet = data()
    transport, seen = service(lambda request, raw: JSONResponse(envelope(kind)))
    result, inputs, outputs = await g.generate_rca_evidence(provider, TASK_PROMPT, packet, transport=transport)
    assert (inputs, outputs) == (11, 13) and len(seen) == 1
    path, raw, headers = seen[0]
    value = json.loads(raw)
    assert path.endswith("/responses" if kind == "responses" else "/chat/completions")
    assert value["store"] is False and headers["content-type"] == "application/json"
    instructions = value["instructions"] if kind == "responses" else value["messages"][0]["content"]
    public = json.loads(value["input"][0]["content"] if kind == "responses" else value["messages"][1]["content"])
    assert instructions == SYSTEM_PROMPT + "\n\n" + TASK_PROMPT
    assert public == {"rca_source": source_dict(), "question": packet["input"]["question"]}
    assert all(key not in public for key in ("event_id", "patient_id_at_capture", "identity_secret", "requested_by", "event_grant", "rca_evidence_binding"))
    assert result.rca_evidence_draft.instructions_digest == t.instructions_digest(SYSTEM_PROMPT, TASK_PROMPT)
    assert "未核实" in result.summary and result.sections[0].source_ids == [public["rca_source"]["source_id"]]
    if kind == "responses":
        schema = value["text"]["format"]["schema"]
        assert schema["additionalProperties"] is False and set(schema["required"]) == {"hypotheses", "clarification_questions"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "axis", ["no_permission", "bool_permission", "specialist", "temperature_nan", "temperature_bool", "output_bool", "timeout_bool", "foreign_input", "private_context", "wrong_evidence", "whole_wire"]
)
async def test_preflight_rejection_makes_no_http_attempt_and_never_truncates(provider, axis):
    packet = data()
    if axis == "no_permission":
        provider.allows_patient_data = 0
    elif axis == "bool_permission":
        provider.allows_patient_data = True
    elif axis == "specialist":
        provider.kind = "specialist"
    elif axis == "temperature_nan":
        provider.temperature = float("nan")
    elif axis == "temperature_bool":
        provider.temperature = True
    elif axis == "output_bool":
        provider.max_output_tokens = True
    elif axis == "timeout_bool":
        provider.timeout_seconds = True
    elif axis == "foreign_input":
        packet["input"]["patient_id"] = 1
    elif axis == "private_context":
        packet["context"]["private_raw_rca"] = "private sentinel"
    elif axis == "wrong_evidence":
        packet["evidence"] = []
    else:
        source = source_dict()
        for item in source["items"]:
            item["text"] += "\\" * 1048576
            item["text_hash"] = hashlib.sha256(item["text"].encode()).hexdigest()
        assert len(c.canonical(c.validate_source(source)).encode()) < c.MAX_WIRE_BYTES
        packet = data(source)
    transport, seen = service(lambda request, raw: JSONResponse(envelope("chat")))
    with pytest.raises(g.RcaEvidenceGatewayError) as failure:
        await g.generate_rca_evidence(provider, TASK_PROMPT, packet, transport=transport)
    assert not seen and failure.value.model_call_attempted is False
    assert failure.value.input_tokens is failure.value.output_tokens is None


@pytest.mark.asyncio
@pytest.mark.parametrize("axis", ["partial_usage", "bad_quote", "tool", "duplicate", "nonfinite", "invalid_utf8", "redirect", "oversize"])
async def test_actual_response_rejection_keeps_only_real_paid_usage_and_one_attempt(provider, axis):
    body = envelope("chat")
    if axis == "partial_usage":
        del body["usage"]["completion_tokens"]
        body["usage"].pop("total_tokens")
    elif axis == "bad_quote":
        raw = json.loads(body["choices"][0]["message"]["content"])
        raw["hypotheses"][0]["supporting_quotes"][0]["quote"] = "伪引文"
        body["choices"][0]["message"]["content"] = c.canonical(raw)
    elif axis == "tool":
        body["choices"][0]["message"]["tool_calls"] = []

    def response(request, raw):
        if axis == "duplicate":
            return Response(b'{"usage":{},"usage":{}}', media_type="application/json")
        if axis == "nonfinite":
            return Response(b'{"usage":NaN}', media_type="application/json")
        if axis == "invalid_utf8":
            return Response(b"\xff", media_type="application/json")
        if axis == "redirect":
            return Response(status_code=307, headers={"Location": "https://synthetic.invalid/other"})
        if axis == "oversize":

            async def chunks():
                for _ in range(9):
                    yield b" " * 1048576

            return StreamingResponse(chunks(), media_type="application/json")
        return JSONResponse(body)

    transport, seen = service(response)
    with pytest.raises(g.RcaEvidenceGatewayError) as failure:
        await g.generate_rca_evidence(provider, TASK_PROMPT, data(), transport=transport)
    assert len(seen) == 1 and failure.value.model_call_attempted is True
    expected = (11, None) if axis == "partial_usage" else (11, 13) if axis in {"bad_quote", "tool"} else (None, None)
    assert (failure.value.input_tokens, failure.value.output_tokens) == expected


@pytest.mark.asyncio
async def test_total_upload_response_deadline_bounds_continuous_slow_progress_without_retry(provider):
    finished = []

    async def slowly_complete(request, raw):
        async def progress():
            try:
                for _ in range(24):
                    await asyncio.sleep(0.25)
                    yield b" "
            finally:
                finished.append(True)

        return StreamingResponse(progress(), media_type="application/json")

    transport, seen = service(slowly_complete)
    started = asyncio.get_running_loop().time()
    with pytest.raises(g.RcaEvidenceGatewayError) as failure:
        await g.generate_rca_evidence(provider, TASK_PROMPT, data(), transport=transport)
    elapsed = asyncio.get_running_loop().time() - started
    assert 2.8 <= elapsed < 5 and len(seen) == 1 and finished == [True]
    assert failure.value.model_call_attempted is True and failure.value.input_tokens is None
