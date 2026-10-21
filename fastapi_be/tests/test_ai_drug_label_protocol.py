"""Complete single provider envelopes and independent actual usage counts."""

import copy

import pytest

from app.ai import document_evidence_contract as d
from app.ai.drug_label_draft import MAX_JSON_BYTES
from app.ai.drug_label_protocol import DrugLabelReplyError, parse_provider_draft
from tests.test_ai_drug_label_draft import INSTRUCTIONS, reply
from tests.test_ai_drug_label_draft import source as _source

source = _source


def envelope(kind, source, *, counts=(13, 7)):
    raw = d.canonical_json(reply(source))
    if kind == "chat":
        return {
            "usage": dict(prompt_tokens=counts[0], completion_tokens=counts[1], total_tokens=sum(counts)),
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": raw}}],
        }
    return {
        "status": "completed",
        "usage": dict(input_tokens=counts[0], output_tokens=counts[1], total_tokens=sum(counts)),
        "output": [
            {"type": "reasoning", "status": "completed", "summary": []},
            {"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": raw[:5]}, {"type": "output_text", "text": raw[5:]}]},
        ],
    }


def assistant(kind, value):
    return value["choices"][0]["message"] if kind == "chat" else value["output"][1]


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("counts", [(13, 7), (0, 0), (0, 7), (13, 0), (2000000, 2000000)])
def test_one_complete_text_reply_binds_original_and_exact_known_counts(source, kind, counts):
    value, inputs, outputs = parse_provider_draft(kind, envelope(kind, source, counts=counts), source, INSTRUCTIONS)
    assert (inputs, outputs) == counts
    assert value.fields[0].spans[0].quote == "合成成分"
    assert value.binding.instructions_digest == INSTRUCTIONS
    assert value.binding.source == source.binding


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("axis", ["missing", "bool", "negative", "float", "string", "too_large", "null"])
@pytest.mark.parametrize("side", [0, 1])
def test_invalid_or_missing_usage_retains_independently_known_companion(source, kind, axis, side):
    value = envelope(kind, source)
    keys = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
    key = keys[side]
    if axis == "missing":
        del value["usage"][key]
    else:
        value["usage"][key] = {"bool": True, "negative": -1, "float": 1.0, "string": "1", "too_large": 2000001, "null": None}[axis]
    with pytest.raises(DrugLabelReplyError) as invalid:
        parse_provider_draft(kind, value, source, INSTRUCTIONS)
    actual = (invalid.value.input_tokens, invalid.value.output_tokens)
    assert actual == ((None, 7) if side == 0 else (13, None))


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("total", [False, "20", 20.0, -1, 21, None])
def test_bad_optional_total_never_erases_actual_individual_usage(source, kind, total):
    value = envelope(kind, source)
    value["usage"]["total_tokens"] = total
    with pytest.raises(DrugLabelReplyError) as invalid:
        parse_provider_draft(kind, value, source, INSTRUCTIONS)
    assert (invalid.value.input_tokens, invalid.value.output_tokens) == (13, 7)


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_absent_optional_total_does_not_fabricate_or_require_one(source, kind):
    value = envelope(kind, source)
    del value["usage"]["total_tokens"]
    _, inputs, outputs = parse_provider_draft(kind, value, source, INSTRUCTIONS)
    assert (inputs, outputs) == (13, 7)


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize(
    "axis",
    [
        "error",
        "incomplete",
        "root_refusal",
        "root_action",
        "assistant_action",
        "assistant_refusal",
        "wrong_role",
        "multiple_messages",
        "incomplete_message",
        "bad_json",
        "model_action",
        "wrong_quote",
        "missing_usage",
        "non_dict_usage",
        "large_envelope",
    ],
)
def test_refusal_incomplete_multiple_actions_or_invalid_draft_are_rejected_with_paid_receipt(source, kind, axis):
    value = envelope(kind, source)
    msg = assistant(kind, value)
    if axis == "error":
        value["error"] = {"message": "synthetic provider error"}
    elif axis == "incomplete":
        value["incomplete_details"] = {"reason": "max_output_tokens"}
    elif axis == "root_refusal":
        value["refusal"] = "refused"
    elif axis == "root_action":
        value["actions"] = []
    elif axis == "assistant_action":
        msg["tool_calls"] = [{"function": {"name": "update_catalog"}}]
    elif axis == "assistant_refusal":
        msg["refusal"] = "refused"
    elif axis == "wrong_role":
        msg["role"] = "tool"
    elif axis == "multiple_messages":
        if kind == "chat":
            value["choices"].append(copy.deepcopy(value["choices"][0]))
        else:
            value["output"].append(copy.deepcopy(msg))
    elif axis == "incomplete_message":
        if kind == "chat":
            value["choices"][0]["finish_reason"] = "length"
        else:
            msg["status"] = "incomplete"
    elif axis in {"bad_json", "model_action", "wrong_quote"}:
        raw = '{"fields":[],"fields":[]}'
        if axis == "model_action":
            raw = '{"fields":[],"actions":["prescribe"]}'
        elif axis == "wrong_quote":
            proposed = reply(source)
            proposed["fields"][0]["spans"][0]["quote"] = "不存在的原文"
            raw = d.canonical_json(proposed)
        if kind == "chat":
            msg["content"] = raw
        else:
            msg["content"] = [{"type": "output_text", "text": raw}]
    elif axis == "missing_usage":
        del value["usage"]
    elif axis == "non_dict_usage":
        value["usage"] = []
    else:
        value["untrusted_extra_metadata"] = "文" * (MAX_JSON_BYTES // 3 + 1)
    with pytest.raises(DrugLabelReplyError) as invalid:
        parse_provider_draft(kind, value, source, INSTRUCTIONS)
    assert (invalid.value.input_tokens, invalid.value.output_tokens) == ((None, None) if axis in {"missing_usage", "non_dict_usage"} else (13, 7))


@pytest.mark.parametrize("axis", ["choice_action", "bad_index_bool", "bad_index_one", "audio", "content_list", "function_call"])
def test_chat_rejects_nontext_index_or_choice_actions(source, axis):
    value = envelope("chat", source)
    msg = assistant("chat", value)
    choice = value["choices"][0]
    if axis == "choice_action":
        choice["function_calls"] = []
    elif axis.startswith("bad_index"):
        choice["index"] = False if axis == "bad_index_bool" else 1
    elif axis == "audio":
        msg["audio"] = {}
    elif axis == "content_list":
        msg["content"] = [{"type": "text", "text": msg["content"]}]
    else:
        msg["function_call"] = {}
    with pytest.raises(DrugLabelReplyError) as invalid:
        parse_provider_draft("chat", value, source, INSTRUCTIONS)
    assert (invalid.value.input_tokens, invalid.value.output_tokens) == (13, 7)


@pytest.mark.parametrize("axis", ["root_status", "reasoning_status", "reasoning_action", "tool_output", "refusal_part", "action_part", "missing_part", "nontext_part", "truncated_parts"])
def test_responses_rejects_hidden_actions_and_incomplete_or_nontext_parts(source, axis):
    value = envelope("responses", source)
    msg = assistant("responses", value)
    if axis == "root_status":
        value["status"] = "in_progress"
    elif axis == "reasoning_status":
        value["output"][0]["status"] = "incomplete"
    elif axis == "reasoning_action":
        value["output"][0]["required_action"] = {}
    elif axis == "tool_output":
        value["output"].append({"type": "function_call", "name": "update_catalog"})
    elif axis == "refusal_part":
        msg["content"][0]["refusal"] = "refused"
    elif axis == "action_part":
        msg["content"][0]["actions"] = []
    elif axis == "missing_part":
        msg["content"] = []
    elif axis == "nontext_part":
        msg["content"][0]["type"] = "output_image"
    else:
        msg["content"].pop()
    with pytest.raises(DrugLabelReplyError) as invalid:
        parse_provider_draft("responses", value, source, INSTRUCTIONS)
    assert (invalid.value.input_tokens, invalid.value.output_tokens) == (13, 7)


@pytest.mark.parametrize("value", [None, [], "{}", 0, True])
def test_non_envelopes_do_not_invent_usage(source, value):
    with pytest.raises(DrugLabelReplyError) as invalid:
        parse_provider_draft("chat", value, source, INSTRUCTIONS)
    assert invalid.value.input_tokens is None and invalid.value.output_tokens is None


def test_wrong_provider_kind_never_guesses_a_parser_or_usage(source):
    with pytest.raises(DrugLabelReplyError) as invalid:
        parse_provider_draft("specialist", envelope("chat", source), source, INSTRUCTIONS)
    assert invalid.value.input_tokens is None and invalid.value.output_tokens is None
