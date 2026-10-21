"""Actual synthetic source resolution and bounded text-adapter HTTP envelopes."""

import copy
import json

import httpx
import pytest

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.document_extraction_context import extraction_context
from app.ai.document_extraction_contract import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_TASK_PROMPT
from app.ai.document_extraction_prompt import instructions_digest
from app.ai.gateway import AIExecutionError, _request, generate
from app.ai.models import AIProvider
from tests.test_ai_document_evidence_sources import document_case  # noqa: F401 -- imported pytest fixture
from tests.test_ai_document_extraction_context import extraction_case  # noqa: F401 -- imported pytest fixture


@pytest.fixture
def gateway_case(extraction_case):  # noqa: F811 -- pytest injects imported fixture
    db, actor, _, original = extraction_case
    values = {"document_original_id": original.snapshot.original_id}
    context = extraction_context(db, actor, values)
    provider = AIProvider(
        provider_id=71,
        revision=1,
        name="synthetic document",
        kind="chat",
        api_base="http://localhost:11434/v1",
        model="synthetic-document",
        timeout_seconds=10,
        max_output_tokens=2000,
        temperature=0.2,
        allows_patient_data=1,
    )
    data = {"input": values, "context": context.data, "tools": {}, "evidence": context.evidence}
    return provider, data, original


def reply(data):
    text = data["context"]["document_source"]["text"]
    return {"spans": [{"proposed_heading": "待审核原文位置", "clause_kind": "other", "start": 0, "end": len(text), "quote": text}]}


def envelope(kind, raw):
    if kind == "chat":
        return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": raw}}], "usage": {"prompt_tokens": 11, "completion_tokens": 13}}
    return {
        "status": "completed",
        "output": [{"type": "message", "status": "completed", "role": "assistant", "content": [{"type": "output_text", "text": raw}]}],
        "usage": {"input_tokens": 11, "output_tokens": 13},
    }


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.asyncio
async def test_text_request_sends_complete_source_only_and_returns_unreviewed_exact_spans(gateway_case, kind):
    provider, data, original = gateway_case
    provider.kind = kind
    requests = []

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == ("/v1/chat/completions" if kind == "chat" else "/v1/responses")
        system = body["messages"][0]["content"] if kind == "chat" else body["instructions"]
        public = json.loads(body["messages"][-1]["content"] if kind == "chat" else body["input"][-1]["content"])
        assert system == EXTRACTION_SYSTEM_PROMPT + "\n\n" + EXTRACTION_TASK_PROMPT
        assert set(public) == {"document_source", "question"}
        assert public["document_source"]["text"] == original.snapshot.text
        assert original.governance.review_basis_note not in request.content.decode()
        assert "authorization_note" not in request.content.decode() and "document_review" not in request.content.decode()
        if kind == "responses":
            assert body["store"] is False and body["text"]["format"]["strict"] is True
            assert body["text"]["format"]["schema"]["required"] == ["spans"]
        return httpx.Response(200, json=envelope(kind, json.dumps(reply(data), ensure_ascii=False)))

    result, inputs, outputs = await generate(provider, FEATURE_BY_KEY["guideline_ingestion"], EXTRACTION_TASK_PROMPT, data, transport=httpx.MockTransport(handle))
    assert len(requests) == 1 and (inputs, outputs) == (11, 13)
    assert result.document_extraction.spans[0].quote == original.snapshot.text
    assert result.document_extraction.provenance == "unverified_model_draft"
    assert result.document_extraction.instructions_digest == instructions_digest(EXTRACTION_TASK_PROMPT)
    assert result.document_extraction.automatic_candidate_creation is False


@pytest.mark.parametrize("damage", ["quote", "truncated", "partial_usage", "duplicate_json"])
@pytest.mark.asyncio
async def test_rejected_reply_retains_only_actual_usage_and_never_accepts_partial_draft(gateway_case, damage):
    provider, data, _ = gateway_case
    draft = reply(data)
    if damage == "quote":
        draft["spans"][0]["quote"] = "错误原文"
    raw = json.dumps(draft, ensure_ascii=False)
    if damage == "duplicate_json":
        raw = '{"spans":[],"spans":[]}'
    returned = envelope("chat", raw)
    if damage == "truncated":
        returned["choices"][0]["finish_reason"] = "length"
    if damage == "partial_usage":
        del returned["usage"]["completion_tokens"]
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=returned)

    with pytest.raises(AIExecutionError) as rejected:
        await generate(provider, FEATURE_BY_KEY["guideline_ingestion"], EXTRACTION_TASK_PROMPT, data, transport=httpx.MockTransport(handle))
    assert len(requests) == 1 and rejected.value.code == "DOCUMENT_PROVIDER_REPLY_INVALID"
    assert rejected.value.input_tokens == 11
    assert rejected.value.output_tokens == (None if damage == "partial_usage" else 13)
    assert rejected.value.usage_receipt["complete"] is (damage != "partial_usage")


@pytest.mark.parametrize("damage", ["wrong_feature", "specialist", "purpose", "tools", "private_context"])
def test_wrong_scope_or_unreviewed_payload_cannot_fall_back_to_general_chat(gateway_case, damage):
    provider, original, _ = gateway_case
    data = copy.deepcopy(original)
    spec = FEATURE_BY_KEY["guideline_ingestion"]
    if damage == "wrong_feature":
        spec = FEATURE_BY_KEY["guideline_qa"]
    elif damage == "specialist":
        provider.kind = "specialist"
    elif damage == "purpose":
        provider.allows_patient_data = 0
    elif damage == "tools":
        data["tools"] = {"unrelated": "不能外发"}
    else:
        data["context"]["unrelated"] = "不能外发"
    with pytest.raises(AIExecutionError) as rejected:
        _request(provider, spec, EXTRACTION_TASK_PROMPT, data)
    assert rejected.value.code in {"DOCUMENT_SOURCE_MODE", "DOCUMENT_SOURCE_REQUIRED"}


@pytest.mark.asyncio
async def test_whole_model_request_capacity_is_checked_before_any_transport(gateway_case):
    provider, data, _ = gateway_case
    requests = []
    with pytest.raises(AIExecutionError) as rejected:
        await generate(provider, FEATURE_BY_KEY["guideline_ingestion"], "汉" * 200000, data, transport=httpx.MockTransport(lambda request: requests.append(request)))
    assert rejected.value.code == "DOCUMENT_REQUEST_LIMIT" and requests == []
