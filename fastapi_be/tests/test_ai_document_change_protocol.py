"""Completed provider protocol with actual receipts; pure synthetic, no HTTP."""

import copy
import subprocess
import sys

import pytest

from app.ai import document_change_protocol as p
from app.ai.document_change_contract import e
from tests.test_ai_document_change_draft import PROMPT, change, source


def envelope(kind, raw=None):
    text = e.canonical_json({"changes": [change()]}) if raw is None else raw
    if kind == "chat":
        return {"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": 11, "completion_tokens": 13}}
    return {
        "status": "completed",
        "output": [{"type": "reasoning", "status": "completed"}, {"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text}]}],
        "usage": {"input_tokens": 11, "output_tokens": 13},
    }


def rejected(kind, value, counts=(11, 13)):
    with pytest.raises(p.DocumentChangeReplyError) as info:
        p.parse_provider_draft(kind, value, source(), PROMPT)
    assert (info.value.input_tokens, info.value.output_tokens) == counts
    assert "PRIVATE_SENTINEL" not in str(info.value)


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_completed_provider_only_supplies_changes_server_binds_originals_and_overlap(kind):
    draft, inputs, outputs = p.parse_provider_draft(kind, envelope(kind), source(), PROMPT)
    assert (inputs, outputs) == (11, 13)
    assert draft.binding.instructions_digest == PROMPT and draft.requires_human_review is True and draft.automatic_changes is False
    assert draft.changes[0].baseline_spans[0].quote == "\ufeff甲\r" and draft.changes[0].candidate_spans[0].quote == "😀"
    assert len(draft.changes[0].link_overlaps) == 3 and draft.changes[0].link_overlaps[1].link.current is False


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("bad", [None, True, 13.0, "13", -1, 2000001])
def test_partial_actual_usage_is_kept_and_invalid_counts_never_become_zero(kind, bad):
    value = envelope(kind)
    names = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
    value["usage"] = {names[0]: 0, names[1]: bad}
    rejected(kind, value, (0, None))


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_known_zero_is_real_while_missing_usage_is_unknown(kind):
    value = envelope(kind, '{"changes":[]}')
    names = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
    value["usage"] = {key: 0 for key in names}
    result = p.parse_provider_draft(kind, value, source(), PROMPT)
    assert result[1:] == (0, 0) and not result[0].changes
    value.pop("usage")
    rejected(kind, value, (None, None))


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize(
    "raw",
    [
        '{"changes":[],"changes":[]}',
        '{"changes":NaN}',
        '{"changes":1e999}',
        '```json\n{"changes":[]}\n```',
        '{"changes":',
        "null",
        '{"changes":[],"extra":"PRIVATE_SENTINEL"}',
        '{"changes":[],"x":"\\ud800"}',
    ],
)
def test_untrusted_complete_text_keeps_usage_when_json_or_closed_draft_is_rejected(kind, raw):
    rejected(kind, envelope(kind, raw))


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_false_literal_quote_and_provider_self_binding_are_not_trusted(kind):
    value = change()
    value["baseline_spans"][0]["quote"] = "PRIVATE_SENTINEL"
    rejected(kind, envelope(kind, e.canonical_json({"changes": [value]})))
    rejected(kind, envelope(kind, e.canonical_json({"changes": [], "binding": {"instructions_digest": PROMPT}})))


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("mutation", ["incomplete", "two", "role", "refusal", "action", "outer_action", "invalid_total"])
def test_refused_incomplete_multiple_or_action_output_cannot_become_questions(kind, mutation):
    value = envelope(kind)
    message = value["choices"][0]["message"] if kind == "chat" else value["output"][1]
    if mutation == "incomplete":
        if kind == "chat":
            value["choices"][0]["finish_reason"] = "length"
        else:
            value["status"] = "incomplete"
    elif mutation == "two":
        if kind == "chat":
            value["choices"].append(copy.deepcopy(value["choices"][0]))
        else:
            value["output"].append(copy.deepcopy(message))
    elif mutation == "role":
        message["role"] = "user"
    elif mutation == "refusal":
        message["refusal"] = ""
    elif mutation == "action":
        message["tool_calls"] = []
    elif mutation == "outer_action":
        value["required_action"] = {"url": "PRIVATE_SENTINEL"}
    else:
        value["usage"]["total_tokens"] = 0
    rejected(kind, value)


def test_protocol_imports_remain_pure_without_settings_or_database():
    code = "import sys;import app.ai.document_change_protocol;assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))"
    value = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert value.returncode == 0, value.stderr
