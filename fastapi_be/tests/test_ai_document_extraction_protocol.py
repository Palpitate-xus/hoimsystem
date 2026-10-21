"""Real provider-envelope parsing, not model calls or HTTP integration."""

import copy
import subprocess
import sys

import pytest

from app.ai import document_evidence_contract as c
from app.ai import document_extraction_protocol as p
from tests.test_ai_document_extraction_contract import PROMPT, source, span


def reply_text():
    return c.canonical_json({"spans": [span(0, 7), span()]})


def chat(raw=None):
    return {
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "refusal": None, "content": reply_text() if raw is None else raw}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


def responses(raw=None):
    text = reply_text() if raw is None else raw
    middle = len(text) // 2
    return {
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": [
            {"type": "reasoning", "status": "completed", "summary": []},
            {
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text[:middle], "annotations": []}, {"type": "output_text", "text": text[middle:], "annotations": []}],
            },
        ],
        "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
    }


def refused(kind, value, counts=(11, 7), *, selected_source=None, instructions_digest=PROMPT):
    with pytest.raises(p.DocumentReplyError) as info:
        p.parse_provider_draft(kind, value, source() if selected_source is None else selected_source, instructions_digest)
    assert (info.value.input_tokens, info.value.output_tokens) == counts
    assert "PRIVATE_PROVIDER_SENTINEL" not in str(info.value)
    return info.value


@pytest.mark.parametrize("kind,build", [("chat", chat), ("responses", responses)])
def test_complete_provider_text_preserves_exact_codepoint_quotes_and_real_usage(kind, build):
    draft, input_tokens, output_tokens = p.parse_provider_draft(kind, build(), source(), PROMPT)
    assert (input_tokens, output_tokens) == (11, 7)
    assert draft.spans[0].quote.startswith("\ufeff") and "\r\n" in draft.spans[0].quote
    assert draft.spans[1].quote == "😀e\u0301"
    assert draft.provenance == "unverified_model_draft"
    assert draft.automatic_candidate_creation is False and draft.automatic_knowledge_publication is False


@pytest.mark.parametrize("kind,build,names", [("chat", chat, ("prompt_tokens", "completion_tokens")), ("responses", responses, ("input_tokens", "output_tokens"))])
def test_explicit_zero_usage_is_valid_and_empty_spans_do_not_assert_absence(kind, build, names):
    value = build('{"spans":[]}')
    value["usage"] = {names[0]: 0, names[1]: 0}
    draft, first, second = p.parse_provider_draft(kind, value, source(), PROMPT)
    assert (first, second) == (0, 0) and not draft.spans
    assert "空集合不表示" in draft.coverage_note


@pytest.mark.parametrize("kind,build,names", [("chat", chat, ("prompt_tokens", "completion_tokens")), ("responses", responses, ("input_tokens", "output_tokens"))])
@pytest.mark.parametrize("bad", [True, False, 7.0, "7", -1, 2000001, None])
def test_invalid_usage_is_not_coerced_and_independently_known_count_is_retained(kind, build, names, bad):
    value = build()
    value["usage"] = {names[0]: 0, names[1]: bad}
    refused(kind, value, (0, None))
    value["usage"] = {names[0]: bad, names[1]: 7}
    refused(kind, value, (None, 7))


@pytest.mark.parametrize("kind,build,names", [("chat", chat, ("prompt_tokens", "completion_tokens")), ("responses", responses, ("input_tokens", "output_tokens"))])
def test_missing_usage_counts_remain_unknown_and_never_default_to_zero(kind, build, names):
    for usage in (None, [], {}, "missing"):
        value = build()
        value["usage"] = usage
        refused(kind, value, (None, None))
    value = build()
    del value["usage"]
    refused(kind, value, (None, None))
    for present, expected in [(0, (11, None)), (1, (None, 7))]:
        value = build()
        value["usage"] = {names[present]: 11 if present == 0 else 7}
        refused(kind, value, expected)


@pytest.mark.parametrize("kind,build", [("chat", chat), ("responses", responses)])
@pytest.mark.parametrize("bad", [True, 18.0, "18", 17, -1, None])
def test_optional_total_is_an_actual_consistent_integer_and_bad_total_keeps_actual_pair(kind, build, bad):
    value = build()
    value["usage"]["total_tokens"] = bad
    refused(kind, value)


@pytest.mark.parametrize("kind,build", [("chat", chat), ("responses", responses)])
@pytest.mark.parametrize(
    "raw",
    [
        '{"spans":[],"spans":[]}',
        '{"spans":[{"start":0,"start":1}]}',
        '{"spans":NaN}',
        '{"spans":Infinity}',
        '{"spans":1e999}',
        '{"spans":[],"x":"\\ud800"}',
        '```json\n{"spans":[]}\n```',
        '{"spans":',
        "[]",
        "null",
        "PRIVATE_PROVIDER_SENTINEL",
    ],
)
def test_rejected_literal_draft_or_json_retains_received_usage(kind, build, raw):
    refused(kind, build(raw))


@pytest.mark.parametrize("kind,build", [("chat", chat), ("responses", responses)])
def test_wrong_quote_and_surrogate_cannot_become_a_verified_draft_but_usage_survives(kind, build):
    item = span()
    item["quote"] = "abc"
    refused(kind, build(c.canonical_json({"spans": [item]})))
    refused(kind, build("\ud800"))


@pytest.mark.parametrize(
    "mutation",
    [
        "no_choices",
        "two_choices",
        "length",
        "content_filter",
        "tool_finish",
        "user_role",
        "refusal",
        "empty_refusal",
        "tool_calls",
        "function_call",
        "actions",
        "audio",
        "index_bool",
        "index_nonzero",
        "nontext",
        "missing_message",
        "choice_action",
    ],
)
def test_chat_requires_one_stopped_assistant_text_without_refusal_or_actions(mutation):
    value = chat()
    choice = value["choices"][0]
    message = choice["message"]
    if mutation == "no_choices":
        value["choices"] = []
    elif mutation == "two_choices":
        value["choices"].append(copy.deepcopy(choice))
    elif mutation in ("length", "content_filter", "tool_finish"):
        choice["finish_reason"] = "tool_calls" if mutation == "tool_finish" else mutation
    elif mutation == "user_role":
        message["role"] = "user"
    elif mutation in ("refusal", "empty_refusal"):
        message["refusal"] = "PRIVATE_PROVIDER_SENTINEL" if mutation == "refusal" else ""
    elif mutation in ("tool_calls", "function_call", "actions", "audio"):
        message[mutation] = [] if mutation == "tool_calls" else {"external": "PRIVATE_PROVIDER_SENTINEL"}
    elif mutation in ("index_bool", "index_nonzero"):
        choice["index"] = True if mutation == "index_bool" else 1
    elif mutation == "nontext":
        message["content"] = [{"type": "text", "text": reply_text()}]
    elif mutation == "choice_action":
        choice["required_action"] = {"function_call": "external_action"}
    else:
        del choice["message"]
    refused("chat", value)


@pytest.mark.parametrize(
    "mutation",
    [
        "response_incomplete",
        "response_failed",
        "output_not_list",
        "two_messages",
        "message_incomplete",
        "role_user",
        "no_message",
        "tool",
        "reasoning_incomplete",
        "empty_content",
        "refusal_part",
        "part_refusal_field",
        "message_action",
        "nontext_part",
        "reasoning_action",
        "part_action",
    ],
)
def test_responses_requires_one_completed_assistant_and_only_complete_output_text(mutation):
    value = responses()
    message = value["output"][1]
    if mutation in ("response_incomplete", "response_failed"):
        value["status"] = "incomplete" if mutation == "response_incomplete" else "failed"
    elif mutation == "output_not_list":
        value["output"] = reply_text()
    elif mutation == "two_messages":
        value["output"].append(copy.deepcopy(message))
    elif mutation == "message_incomplete":
        message["status"] = "in_progress"
    elif mutation == "role_user":
        message["role"] = "user"
    elif mutation == "no_message":
        value["output"].pop()
    elif mutation == "tool":
        value["output"].append({"type": "function_call", "name": "external_action", "arguments": "{}"})
    elif mutation == "reasoning_incomplete":
        value["output"][0]["status"] = "in_progress"
    elif mutation == "empty_content":
        message["content"] = []
    elif mutation == "refusal_part":
        message["content"] = [{"type": "refusal", "refusal": "PRIVATE_PROVIDER_SENTINEL"}]
    elif mutation == "part_refusal_field":
        message["content"][0]["refusal"] = ""
    elif mutation == "message_action":
        message["tool_calls"] = [{"name": "external_action"}]
    elif mutation == "reasoning_action":
        value["output"][0]["actions"] = [{"name": "external_action"}]
    elif mutation == "part_action":
        message["content"][0]["function_call"] = {"name": "external_action"}
    else:
        message["content"][0]["text"] = False
    refused("responses", value)


@pytest.mark.parametrize("kind,build", [("chat", chat), ("responses", responses)])
@pytest.mark.parametrize("field", ["error", "incomplete_details", "required_action", "actions"])
def test_contradictory_provider_error_or_action_rejected_even_if_text_looks_complete(kind, build, field):
    value = build()
    value[field] = {"message": "PRIVATE_PROVIDER_SENTINEL"}
    refused(kind, value)


def test_responses_cumulative_utf8_budget_is_checked_before_joining_all_parts():
    value = responses()
    value["output"][1]["content"] = [{"type": "output_text", "text": "😀" * 8192}, {"type": "output_text", "text": "😀" * 8192}]
    refused("responses", value)


@pytest.mark.parametrize("kind,value", [("specialist", {}), ("unknown", chat()), ("chat", None), ("responses", [])])
def test_unconfigured_kind_or_non_object_envelope_has_no_invented_usage(kind, value):
    refused(kind, value, (None, None))


def test_bad_frozen_source_or_prompt_preserves_received_usage_without_protocol_downgrade():
    changed = source()
    changed.text += "changed"
    refused("chat", chat(), selected_source=changed)
    refused("responses", responses(), selected_source={"text": "caller supplied"})
    refused("chat", chat(), instructions_digest=True)


def test_module_has_no_hospital_database_settings_or_network_transport_imports():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import app.ai.document_extraction_protocol; assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy','httpx'))"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
