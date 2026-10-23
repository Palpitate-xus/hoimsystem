"""Actual governed SQLite context and isolated text HTTP transport; no model."""

import copy
import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import event

from app.ai import clinical_training_configuration as cfg
from app.ai import clinical_training_contract as c
from app.ai import clinical_training_gateway as g
from app.ai.clinical_training_task_prompt import SYSTEM_PROMPT, TASK_PROMPT
from app.ai.clinical_training_usage_contract import usage
from app.config import settings
from tests.test_ai_clinical_training_configuration import configured as configured
from tests.test_ai_clinical_training_configuration import selected
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case
from tests.test_ai_clinical_training_task_contract import draft, selection, source


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "127.0.0.1")
    return SimpleNamespace(kind="chat", api_base="http://127.0.0.1:1/v1", model="synthetic-only-no-model", temperature=Decimal("0.125"), timeout_seconds=5, max_output_tokens=2000, api_key_env="", api_key_encrypted="")


def envelope(kind, value, counters=None):
    result = {"usage": {"prompt_tokens": 11, "completion_tokens": 7} if kind == "chat" else {"input_tokens": 11, "output_tokens": 7}}
    if counters is not None:
        result["usage"] = counters
    raw = c.whole(value)
    if kind == "chat":
        result["choices"] = [dict(index=0, finish_reason="stop", message=dict(role="assistant", content=raw))]
    else:
        result.update(status="completed", output=[dict(type="reasoning", status="completed"), dict(type="message", role="assistant", status="completed", content=[dict(type="output_text", text=raw[:17]), dict(type="output_text", text=raw[17:])])])
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_context_whole_literal_prompt_single_call_and_closed_sql(configured, provider, kind, monkeypatch):
    case, db = configured, configured["db"]
    context = cfg.prepare_context(db, case["actor"], selected(case))
    value, chosen = context.source.model_dump(mode="json"), context.selection.model_dump(mode="json")
    provider.kind = kind
    original = "\ufeff完整Task😀\r\n\x00 末尾  "
    calls, client_options, queries = [], [], []
    real_client = g.httpx.AsyncClient

    def client(*args, **kwargs):
        client_options.append(kwargs)
        return real_client(*args, **kwargs)

    def observed(*args):
        queries.append(args[2])

    def handler(incoming):
        calls.append(incoming)
        assert not db.in_transaction() and not queries
        wire = json.loads(incoming.content)
        assert wire["store"] is False and not {"tools", "tool_choice", "previous_response_id", "conversation", "metadata"} & wire.keys()
        assert incoming.url.path == ("/v1/chat/completions" if kind == "chat" else "/v1/responses")
        assert "authorization" not in incoming.headers
        instructions = wire["messages"][0]["content"] if kind == "chat" else wire["instructions"]
        assert instructions.encode() == (SYSTEM_PROMPT + "\n\n" + original).encode()
        visible = json.loads(wire["messages"][1]["content"] if kind == "chat" else wire["input"])
        assert visible["source"] == value and visible["selection"] == chosen
        assert not {"private_hash", "review_hash", "creation_event_id", "source_uri", "patient_id"} & visible.keys()
        if kind == "chat":
            assert Decimal(str(wire["temperature"])) == Decimal("0.125")
        return httpx.Response(200, json=envelope(kind, draft(value)))

    monkeypatch.setattr(g.httpx, "AsyncClient", client)
    db.commit()
    event.listen(db.get_bind(), "before_cursor_execute", observed)
    try:
        actual, receipt, latency = await g.generate_training_feedback(provider, value, chosen, original, transport=httpx.MockTransport(handler))
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", observed)
        # The committed synthetic config belongs to this test only.
        db.execute(__import__("sqlalchemy").text("DELETE FROM hoimsystem_ai_feature_config WHERE feature_key='clinical_training'"))
        db.commit()
    assert actual.model_dump(mode="json") == draft(value) and receipt == usage(11, 7, True)
    assert type(latency) is int and latency >= 0 and len(calls) == 1 and not queries
    assert len(client_options) == 1 and client_options[0]["follow_redirects"] is False and client_options[0]["trust_env"] is False
    assert client_options[0]["timeout"].connect == 5


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("mode,expected", [("missing", (None, None)), ("input", (11, None)), ("output", (None, 7)), ("total", (None, None)), ("both", (11, 7))])
def test_valid_content_retains_actual_partial_or_absent_usage(kind, mode, expected):
    value = source()
    ikey, okey = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
    packet = envelope(kind, draft(value), {"input": {ikey: 11}, "output": {okey: 7}, "total": {"total_tokens": 18}, "both": {ikey: 11, okey: 7, "total_tokens": 18}, "missing": {}}[mode])
    actual, receipt = g.parse_reply(kind, packet, value, selection(value))
    assert actual.grade_policy == "server_score_unchanged" and receipt == usage(*expected, True)


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("bad", [True, -1, 2147483648, "1", 1.5])
def test_invalid_counter_rejects_but_keeps_other_actual_component(kind, bad):
    value = source()
    ikey, okey = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
    packet = envelope(kind, draft(value), {ikey: bad, okey: 7})
    with pytest.raises(g.TrainingCallError) as error:
        g.parse_reply(kind, packet, value, selection(value))
    assert error.value.usage == usage(None, 7, True)


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("fault", ["error", "required_action", "usage_shape", "total_bool", "total_mismatch", "total_overflow", "tool", "incomplete", "multiple", "refusal", "wrong_quote", "regrade", "foreign_objective"])
def test_model_actions_incomplete_forgery_and_usage_corruption_refuse_with_actual_partial_receipt(kind, fault):
    value = source()
    ikey = "prompt_tokens" if kind == "chat" else "input_tokens"
    packet = envelope(kind, draft(value), {ikey: 11})
    expected = usage(11, None, True)
    if fault in {"error", "required_action"}:
        packet[fault] = {"synthetic": True}
    elif fault == "usage_shape":
        packet["usage"] = []
        expected = usage(None, None, True)
    elif fault.startswith("total_"):
        packet["usage"].update({"total_tokens": {"total_bool": True, "total_mismatch": 19, "total_overflow": 4294967295}[fault]})
        if fault == "total_mismatch":
            packet["usage"]["completion_tokens" if kind == "chat" else "output_tokens"] = 7
            expected = usage(11, 7, True)
    elif fault in {"wrong_quote", "regrade", "foreign_objective"}:
        wrong = draft(value)
        if fault == "wrong_quote":
            wrong["explanations"][0]["evidence"][0]["quote"] = "伪造引用"
        elif fault == "regrade":
            wrong["matching_count"] = 0
        else:
            wrong["objective"] = "review_supplied_material"
        packet = envelope(kind, wrong, {ikey: 11})
    elif kind == "chat":
        choice = packet["choices"][0]
        if fault == "tool":
            choice["message"]["tool_calls"] = []
        elif fault == "incomplete":
            choice["finish_reason"] = "length"
        elif fault == "multiple":
            packet["choices"].append(copy.deepcopy(choice))
        else:
            choice["message"]["refusal"] = "declined"
    else:
        message = packet["output"][1]
        if fault == "tool":
            packet["output"].append(dict(type="function_call", name="sql"))
        elif fault == "incomplete":
            packet["status"] = "incomplete"
        elif fault == "multiple":
            packet["output"].append(copy.deepcopy(message))
        else:
            message["content"][0]["type"] = "refusal"
    with pytest.raises(g.TrainingCallError) as error:
        g.parse_reply(kind, packet, value, selection(value))
    assert error.value.usage == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["duplicate", "nan", "invalid_utf8", "http503", "redirect", "timeout", "connection", "stream_limit"])
async def test_actual_transport_failure_whole_response_limit_and_no_retry(provider, mode):
    value, calls = source(), []

    class Oversize(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b" " * (8 * 1024 * 1024)
            yield b"x"

    def handler(incoming):
        calls.append(incoming)
        if mode == "timeout":
            raise httpx.ReadTimeout("synthetic-only")
        if mode == "connection":
            raise httpx.ConnectError("synthetic-only")
        if mode == "stream_limit":
            return httpx.Response(200, stream=Oversize())
        status = 503 if mode == "http503" else 302 if mode == "redirect" else 200
        return httpx.Response(status, content={"duplicate": b'{"choices":[],"choices":[]}', "nan": b'{"number":NaN}', "invalid_utf8": b"\xff"}.get(mode, b"private-provider-error-sentinel"), headers={"Location": "https://unapproved.invalid/v1"} if status == 302 else {})

    with pytest.raises(g.TrainingCallError) as error:
        await g.generate_training_feedback(provider, value, selection(value), TASK_PROMPT, transport=httpx.MockTransport(handler))
    assert error.value.usage == usage(None, None, True) and len(calls) == 1
    assert "private-provider-error-sentinel" not in error.value.message
    if mode == "stream_limit":
        assert error.value.code == "TRAINING_RESPONSE_LIMIT"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["kind", "model", "timeout", "tokens", "temperature", "endpoint", "foreign_source", "prompt", "credential"])
async def test_invalid_preflight_is_proven_unattempted_without_network(provider, fault):
    value, chosen, prompt, calls = source(), selection(source()), TASK_PROMPT, []
    if fault == "kind":
        provider.kind = "vision"
    elif fault == "model":
        provider.model = ""
    elif fault == "timeout":
        provider.timeout_seconds = True
    elif fault == "tokens":
        provider.max_output_tokens = 0
    elif fault == "temperature":
        provider.temperature = Decimal("NaN")
    elif fault == "endpoint":
        provider.api_base = "http://127.0.0.1:1/v1/"
    elif fault == "foreign_source":
        chosen["patient_id"] = 1
    elif fault == "prompt":
        prompt = "x" * 65536
    else:
        provider.api_key_env = "HOIM_TRAINING_SYNTHETIC_MISSING_CREDENTIAL"

    def handler(incoming):
        calls.append(incoming)
        return httpx.Response(500)

    with pytest.raises(g.TrainingCallError) as error:
        await g.generate_training_feedback(provider, value, chosen, prompt, transport=httpx.MockTransport(handler))
    assert error.value.usage == usage(0, 0, False) and calls == []
