"""Completed provider envelopes with exact original receipts, no remote calls."""

import copy
import json

import pytest

from app.ai.satisfaction_protocol import ACTION_FIELDS, SatisfactionReplyError, parse_provider_draft
from tests.test_ai_satisfaction_draft import example


def packet(kind):
    source, reply = example()
    text = json.dumps(reply)
    if kind == "chat":
        envelope = {"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}
    else:
        envelope = {
            "status": "completed",
            "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
        }
    return source, envelope


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_complete_reply_returns_typed_partial_draft_and_actual_tokens(kind):
    source, envelope = packet(kind)
    before = copy.deepcopy(envelope)
    draft, input_tokens, output_tokens = parse_provider_draft(kind, envelope, source)
    assert (input_tokens, output_tokens) == (7, 3)
    assert draft.coverage == "partial_themes_no_population_or_causality_claim"
    assert len(draft.themes) == 1 and envelope == before


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("value", [None, True, -1, 1.0, "3", 2000001])
@pytest.mark.parametrize("position", [0, 1])
def test_invalid_usage_keeps_the_other_actual_receipt_without_inventing_zero(kind, value, position):
    source, envelope = packet(kind)
    names = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
    envelope["usage"][names[position]] = value
    with pytest.raises(SatisfactionReplyError) as caught:
        parse_provider_draft(kind, envelope, source)
    assert (caught.value.input_tokens, caught.value.output_tokens) == ((None, 3) if position == 0 else (7, None))


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_explicit_zero_tokens_remain_known_zero(kind):
    source, envelope = packet(kind)
    envelope["usage"] = {key: 0 for key in envelope["usage"]}
    assert parse_provider_draft(kind, envelope, source)[1:] == (0, 0)


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("field", ACTION_FIELDS)
def test_provider_root_action_even_empty_is_rejected_with_actual_usage(kind, field):
    source, envelope = packet(kind)
    envelope[field] = []
    with pytest.raises(SatisfactionReplyError) as caught:
        parse_provider_draft(kind, envelope, source)
    assert (caught.value.input_tokens, caught.value.output_tokens) == (7, 3)


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize(
    "mutation",
    [
        "missing_usage",
        "missing_output_tokens",
        "wrong_total",
        "boolean_total",
        "error",
        "incomplete",
        "wrong_role",
        "refusal",
        "action",
        "invalid_json",
        "foreign_source",
        "multiple_messages",
        "incomplete_message",
        "nontext",
    ],
)
def test_incomplete_refused_or_malformed_output_never_becomes_satisfaction_theme_draft(kind, mutation):
    source, envelope = packet(kind)
    message = envelope["choices"][0]["message"] if kind == "chat" else envelope["output"][0]
    if mutation == "missing_usage":
        del envelope["usage"]
    elif mutation == "missing_output_tokens":
        del envelope["usage"]["completion_tokens" if kind == "chat" else "output_tokens"]
    elif mutation in {"wrong_total", "boolean_total"}:
        envelope["usage"]["total_tokens"] = 11 if mutation == "wrong_total" else True
    elif mutation == "error":
        envelope["error"] = {"message": "synthetic upstream error"}
    elif mutation == "incomplete":
        envelope["incomplete_details"] = {}
    elif mutation == "wrong_role":
        message["role"] = "tool"
    elif mutation == "refusal":
        message["refusal"] = ""
    elif mutation == "action":
        message["tool_calls"] = []
    elif mutation in {"invalid_json", "foreign_source"}:
        text = "not json" if mutation == "invalid_json" else "{}"
        if kind == "chat":
            message["content"] = text
        else:
            message["content"][0]["text"] = text
    elif mutation == "multiple_messages":
        envelope["choices" if kind == "chat" else "output"] *= 2
    elif mutation == "incomplete_message":
        if kind == "chat":
            envelope["choices"][0]["finish_reason"] = "length"
        else:
            message["status"] = "in_progress"
    else:
        if kind == "chat":
            message["content"] = []
        else:
            message["content"][0]["type"] = "image"
    with pytest.raises(SatisfactionReplyError) as caught:
        parse_provider_draft(kind, envelope, source)
    expected = (None, None) if mutation == "missing_usage" else (7, None) if mutation == "missing_output_tokens" else (7, 3)
    assert (caught.value.input_tokens, caught.value.output_tokens) == expected


@pytest.mark.parametrize("location", ["reasoning", "message", "part"])
def test_responses_hidden_actions_and_incomplete_reasoning_rejected(location):
    source, envelope = packet("responses")
    if location == "reasoning":
        envelope["output"].insert(0, {"type": "reasoning", "status": "completed", "actions": []})
    elif location == "message":
        envelope["output"][0]["function_call"] = {}
    else:
        envelope["output"][0]["content"][0]["tool_calls"] = []
    with pytest.raises(SatisfactionReplyError) as caught:
        parse_provider_draft("responses", envelope, source)
    assert (caught.value.input_tokens, caught.value.output_tokens) == (7, 3)


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_wrong_complete_safe_projection_preserves_paid_receipt_but_no_result(kind):
    source, envelope = packet(kind)
    source["safe_snapshot"]["reviews"][0]["recorded_score"] = 4
    with pytest.raises(SatisfactionReplyError) as caught:
        parse_provider_draft(kind, envelope, source)
    assert (caught.value.input_tokens, caught.value.output_tokens) == (7, 3)
