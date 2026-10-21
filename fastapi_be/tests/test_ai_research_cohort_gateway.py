"""Actual governed SQLite public Source and isolated HTTP MockTransport, no model."""

import copy
from types import SimpleNamespace

import httpx
import pytest

from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_gateway import ResearchCallError, generate_research, parse_reply, request
from app.ai.research_cohort_prompt import RESEARCH_SYSTEM_PROMPT, RESEARCH_TASK_PROMPT
from app.ai.research_cohort_receipts import usage
from tests.test_ai_research_cohort_draft import draft_for
from tests.test_ai_research_cohort_draft import public_source as public_source  # noqa: F401
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


@pytest.fixture
def provider():
    return SimpleNamespace(
        kind="chat", api_base="http://127.0.0.1:8825/v1", model="synthetic-no-model", temperature=0.2, timeout_seconds=5, max_output_tokens=2000, api_key_env="", api_key_encrypted=""
    )


def envelope(kind, draft, tokens=None):
    value = {"usage": {"prompt_tokens": 31, "completion_tokens": 9} if kind == "chat" else {"input_tokens": 31, "output_tokens": 9}}
    if tokens is not None:
        value["usage"] = tokens
    if kind == "chat":
        value["choices"] = [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": canonical_json(draft)}}]
    else:
        value.update(status="completed", output=[{"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": canonical_json(draft)}]}])
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_public_source_custom_prompt_store_false_exact_cp_reply_and_known_usage(public_source, provider, kind, db_session):
    provider.kind = kind
    draft = draft_for(public_source)
    custom = "经独立管理保存的完整Task版本\ufeff\r\n🧪，不能用默认模板代替。"
    calls = []
    db_session.commit()

    def handler(incoming):
        calls.append(incoming)
        assert not db_session.in_transaction()
        assert incoming.url.path.endswith("/chat/completions" if kind == "chat" else "/responses")
        import json

        wire = json.loads(incoming.content)
        assert wire["store"] is False and "tools" not in wire
        instructions = wire["messages"][0]["content"] if kind == "chat" else wire["instructions"]
        assert instructions == RESEARCH_SYSTEM_PROMPT + "\n\n" + custom
        visible = json.loads(wire["messages"][1]["content"] if kind == "chat" else wire["input"])
        assert visible["research_source"] == public_source and visible["question"] == "原问题🧪\r\n"
        assert not {"snapshot", "scope_id", "patient_id", "identity_secret", "parent_binding"} & visible.keys()
        return httpx.Response(200, json=envelope(kind, draft))

    actual, receipt, latency = await generate_research(provider, public_source, "原问题🧪\r\n", custom, transport=httpx.MockTransport(handler))
    assert actual == draft and receipt == usage(31, 9, True) and latency >= 0 and len(calls) == 1
    assert actual["questions"][0]["citations"][0]["quote"] == "🧪\ufeff否认胸痛\r\n"


def test_valid_complete_reply_without_usage_keeps_nullable_counts_without_fabricated_zero(public_source):
    for kind in ("chat", "responses"):
        original = envelope(kind, draft_for(public_source))
        original.pop("usage")
        draft, receipt = parse_reply(kind, original, public_source)
        assert draft == draft_for(public_source) and receipt == usage(None, None, True)


def test_refusal_action_incomplete_multiple_text_and_wrong_quote_reject_keep_actual_partial_usage(public_source):
    for kind in ("chat", "responses"):
        base = envelope(kind, draft_for(public_source), {"prompt_tokens" if kind == "chat" else "input_tokens": 53})
        variants = []
        if kind == "chat":
            for field, value in (("finish_reason", "length"), ("index", True)):
                wrong = copy.deepcopy(base)
                wrong["choices"][0][field] = value
                variants.append(wrong)
            for field, value in (("refusal", "refused"), ("tool_calls", []), ("role", "tool")):
                wrong = copy.deepcopy(base)
                wrong["choices"][0]["message"][field] = value
                variants.append(wrong)
            wrong = copy.deepcopy(base)
            wrong["choices"].append(copy.deepcopy(wrong["choices"][0]))
            variants.append(wrong)
        else:
            for field, value in (("status", "incomplete"), ("required_action", {})):
                variants.append({**copy.deepcopy(base), field: value})
            wrong = copy.deepcopy(base)
            wrong["output"].append({"type": "function_call", "name": "sql"})
            variants.append(wrong)
            wrong = copy.deepcopy(base)
            wrong["output"][0]["content"][0]["type"] = "refusal"
            variants.append(wrong)
        bad_draft = draft_for(public_source)
        bad_draft["questions"][0]["citations"][0]["quote"] = "不能伪造临床引文"
        variants.append(envelope(kind, bad_draft, {"prompt_tokens" if kind == "chat" else "input_tokens": 53}))
        for wrong in variants:
            with pytest.raises(ResearchCallError) as error:
                parse_reply(kind, wrong, public_source)
            assert error.value.usage == usage(53, None, True)


@pytest.mark.asyncio
async def test_actual_wire_duplicate_nonfinite_invalid_utf8_and_503_never_retry_or_return_body(public_source, provider):
    bodies = [b'{"choices":[],"choices":[]}', b'{"number":NaN}', b"\xff", b"{}"]
    for index, raw in enumerate(bodies):
        calls = []

        def handler(incoming):
            calls.append(incoming)
            return httpx.Response(503 if index == 3 else 200, content=raw)

        with pytest.raises(ResearchCallError) as error:
            await generate_research(provider, public_source, None, RESEARCH_TASK_PROMPT, transport=httpx.MockTransport(handler))
        assert error.value.usage == usage(None, None, True)
        assert len(calls) == 1
        if raw.decode("utf-8", errors="ignore"):
            assert raw.decode("utf-8", errors="ignore") not in error.value.message


@pytest.mark.asyncio
async def test_stream_whole_reply_limit_rejects_before_joining_and_never_retries(public_source, provider):
    calls = []

    class Oversize(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b" " * (8 * 1024 * 1024)
            yield b"x"

    def handler(incoming):
        calls.append(incoming)
        return httpx.Response(200, stream=Oversize())

    with pytest.raises(ResearchCallError) as error:
        await generate_research(provider, public_source, None, RESEARCH_TASK_PROMPT, transport=httpx.MockTransport(handler))
    assert error.value.code == "RESEARCH_RESPONSE_LIMIT" and error.value.usage == usage(None, None, True) and len(calls) == 1


@pytest.mark.asyncio
async def test_source_permission_unknown_and_invalid_provider_preflight_are_known_unattempted(public_source, provider):
    calls = []

    def handler(incoming):
        calls.append(incoming)
        return httpx.Response(500)

    denied = copy.deepcopy(public_source)
    denied["external_model_use"] = "unknown"
    with pytest.raises(ResearchCallError) as error:
        await generate_research(provider, denied, None, RESEARCH_TASK_PROMPT, transport=httpx.MockTransport(handler))
    assert error.value.usage == usage(0, 0, False)
    provider.timeout_seconds = True
    with pytest.raises(ResearchCallError) as error:
        request(provider, public_source, None, RESEARCH_TASK_PROMPT)
    assert error.value.usage == usage(0, 0, False) and calls == []


def test_codepoint_normalization_cannot_be_hidden_in_completed_responses_parts(public_source):
    draft = draft_for(public_source)
    draft["questions"][0]["citations"][0]["quote"] = draft["questions"][0]["citations"][0]["quote"].replace("\r\n", "\n")
    with pytest.raises(ResearchCallError):
        parse_reply("responses", envelope("responses", draft), public_source)
