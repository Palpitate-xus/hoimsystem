"""Real bounded HTTP adapter through MockTransport, no external model/worker."""

import copy
import json

import httpx
import pytest

from app.ai import document_evidence_contract as d
from app.ai import drug_label_gateway as gateway
from app.ai.drug_label_context_contract import expand_public_context
from app.ai.drug_label_draft import MAX_JSON_BYTES, TASK_PROMPT
from app.config import settings
from tests.test_ai_drug_label_sources import label_case as _label_case
from tests.test_ai_drug_label_storage import make_task

label_case = _label_case


@pytest.fixture
def request_case(label_case, monkeypatch):
    case = make_task(label_case)
    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "synthetic.invalid")
    payload = copy.deepcopy(case.snapshot["payload"])
    payload["context"] = expand_public_context(payload["context"], case.public)
    case.payload = payload
    return case


def envelope(kind, reply=None):
    raw = d.canonical_json({"fields": []} if reply is None else reply)
    if kind == "chat":
        return {"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": raw}}], "usage": {"prompt_tokens": 13, "completion_tokens": 7, "total_tokens": 20}}
    return {
        "status": "completed",
        "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": raw}]}],
        "usage": {"input_tokens": 13, "output_tokens": 7, "total_tokens": 20},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_source_only_text_envelope_exact_wire_and_typed_result(request_case, kind):
    case = request_case
    case.provider.kind = kind
    seen = []

    def handler(request):
        value = json.loads(request.content)
        seen.append(value)
        assert request.headers["Content-Type"] == "application/json"
        assert request.url.path.endswith("/responses" if kind == "responses" else "/chat/completions")
        public = json.loads(value["input"][0]["content"] if kind == "responses" else value["messages"][1]["content"])
        assert public == {"drug_label_source": case.public.model_dump(mode="json"), "question": case.snapshot["payload"]["input"]["question"]}
        assert case.seed not in request.content.decode() and '"basis_note":' not in request.content.decode() and '"pharmaceutical_id":' not in request.content.decode()
        return httpx.Response(200, json=envelope(kind))

    result, inputs, outputs = await gateway.generate_drug_label(case.provider, TASK_PROMPT, case.payload, transport=httpx.MockTransport(handler))
    assert (inputs, outputs) == (13, 7) and len(seen) == 1 and result.drug_label_extraction.fields == []
    assert result.drug_label_extraction.binding.source == case.public.binding
    if kind == "responses":
        assert seen[0]["store"] is False and seen[0]["text"]["format"]["strict"] is True
        schema = seen[0]["text"]["format"]["schema"]
        assert schema["additionalProperties"] is False and schema["required"] == list(schema["properties"])


@pytest.mark.asyncio
@pytest.mark.parametrize("axis", ["no_permission", "wrong_kind", "foreign_input", "private_context", "whole_wrapper"])
async def test_preflight_rejects_before_any_model_request(request_case, axis):
    case = request_case
    payload = copy.deepcopy(case.payload)
    prompt = TASK_PROMPT
    seen = []
    if axis == "no_permission":
        case.provider.allows_patient_data = 0
    elif axis == "wrong_kind":
        case.provider.kind = "specialist"
    elif axis == "foreign_input":
        payload["input"]["patient_id"] = 1
    elif axis == "private_context":
        payload["context"]["mapping_seed"] = case.seed
    else:
        prompt = "x" * MAX_JSON_BYTES

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=envelope("chat"))

    with pytest.raises(gateway.DrugLabelGatewayError) as failure:
        await gateway.generate_drug_label(case.provider, prompt, payload, transport=httpx.MockTransport(handler))
    assert failure.value.model_call_attempted is False and not seen
    assert failure.value.input_tokens is failure.value.output_tokens is None


@pytest.mark.asyncio
@pytest.mark.parametrize("axis", ["partial_usage", "wrong_literal", "tool", "duplicate_json", "redirect", "timeout", "oversize"])
async def test_actual_http_failure_keeps_only_real_independent_usage_and_never_retries(request_case, axis):
    case = request_case
    seen = []
    body = envelope("chat")
    if axis == "partial_usage":
        del body["usage"]["completion_tokens"]
        body["usage"].pop("total_tokens")
    elif axis == "wrong_literal":
        body = envelope("chat", {"fields": [{"field": "composition", "spans": [{"start": 0, "end": 1, "quote": "伪"}], "review_question": "请药师核对原文。"}]})
    elif axis == "tool":
        body["choices"][0]["message"]["tool_calls"] = []

    def handler(request):
        seen.append(request)
        if axis == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if axis == "redirect":
            return httpx.Response(307, headers={"Location": "https://synthetic.invalid/other"})
        if axis == "duplicate_json":
            return httpx.Response(200, content=b'{"usage":{},"usage":{}}')
        if axis == "oversize":
            return httpx.Response(200, content=b" " * (MAX_JSON_BYTES + 1))
        return httpx.Response(200, json=body)

    with pytest.raises(gateway.DrugLabelGatewayError) as failure:
        await gateway.generate_drug_label(case.provider, TASK_PROMPT, case.payload, transport=httpx.MockTransport(handler))
    assert len(seen) == 1 and failure.value.model_call_attempted is True
    expected = (13, None) if axis == "partial_usage" else (13, 7) if axis in {"wrong_literal", "tool"} else (None, None)
    assert (failure.value.input_tokens, failure.value.output_tokens) == expected
