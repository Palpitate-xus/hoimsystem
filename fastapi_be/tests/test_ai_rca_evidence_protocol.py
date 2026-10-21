"""Literal provider protocol and independently received token counts only."""

import copy
import json

import pytest

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_protocol as p
from tests.test_ai_rca_evidence_contract import PROMPT, reply, source_dict


def envelope(kind, draft=None):
    raw = json.dumps(reply() if draft is None else draft, ensure_ascii=False)
    if kind == "chat":
        return {"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": raw}}], "usage": {"prompt_tokens": 11, "completion_tokens": 13, "total_tokens": 24}}
    return {
        "status": "completed",
        "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": raw}]}],
        "usage": {"input_tokens": 11, "output_tokens": 13, "total_tokens": 24},
    }


def raw_text(value, kind, raw):
    if kind == "chat":
        value["choices"][0]["message"]["content"] = raw
    else:
        value["output"][0]["content"][0]["text"] = raw


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_one_completed_literal_assistant_retains_real_usage_and_partial_coverage(kind):
    result, inputs, outputs = p.parse_provider_draft(kind, envelope(kind), c.validate_source(source_dict()), PROMPT)
    assert (inputs, outputs) == (11, 13)
    assert result.coverage == c.COVERAGE and result.instructions_digest == PROMPT
    assert len(result.hypotheses) == 1
    zero = envelope(kind, {"hypotheses": [], "clarification_questions": []})
    zero["usage"] = {("prompt_tokens" if kind == "chat" else "input_tokens"): 0, ("completion_tokens" if kind == "chat" else "output_tokens"): 0, "total_tokens": 0}
    result, inputs, outputs = p.parse_provider_draft(kind, zero, c.validate_source(source_dict()), PROMPT)
    assert (inputs, outputs) == (0, 0) and result.hypotheses == []


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("number", [None, False, "0", 0.0, -1, 2000001])
def test_unknown_or_invalid_usage_never_becomes_zero_and_companion_is_retained(kind, number):
    value = envelope(kind)
    value["usage"].pop("total_tokens")
    value["usage"]["prompt_tokens" if kind == "chat" else "input_tokens"] = number
    with pytest.raises(p.RcaEvidenceReplyError) as failure:
        p.parse_provider_draft(kind, value, c.validate_source(source_dict()), PROMPT)
    assert failure.value.input_tokens is None and failure.value.output_tokens == 13


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_absent_usage_retains_none_without_fabricated_counts(kind):
    value = envelope(kind)
    del value["usage"]
    with pytest.raises(p.RcaEvidenceReplyError) as failure:
        p.parse_provider_draft(kind, value, c.validate_source(source_dict()), PROMPT)
    assert failure.value.input_tokens is failure.value.output_tokens is None


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize(
    "raw",
    [
        '{"hypotheses":[],"hypotheses":[],"clarification_questions":[]}',
        '{"hypotheses":[],"clarification_questions":[],"unknown":NaN}',
        '```json\n{"hypotheses":[],"clarification_questions":[]}\n```',
        '{"hypotheses":[],"clarification_questions":[],"clinical_approval":true}',
        '{"hypotheses":[],"clarification_questions":["\\ud800"]}',
        "[]",
    ],
)
def test_bad_literal_body_preserves_actual_received_paid_counts(kind, raw):
    value = envelope(kind)
    raw_text(value, kind, raw)
    with pytest.raises(p.RcaEvidenceReplyError) as failure:
        p.parse_provider_draft(kind, value, c.validate_source(source_dict()), PROMPT)
    assert (failure.value.input_tokens, failure.value.output_tokens) == (11, 13)


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_wrong_quote_timeline_and_extra_hypothesis_status_are_rejected_with_usage(kind):
    for mutate in (
        lambda d: d["hypotheses"][0]["supporting_quotes"][0].update(quote="unbound wrong quote"),
        lambda d: d["hypotheses"][0].update(timeline_entry_ids=["00000000-0000-0000-0000-000000000099"]),
        lambda d: d["hypotheses"][0].update(causal_approval="confirmed"),
    ):
        data = reply()
        mutate(data)
        with pytest.raises(p.RcaEvidenceReplyError) as failure:
            p.parse_provider_draft(kind, envelope(kind, data), c.validate_source(source_dict()), PROMPT)
        assert (failure.value.input_tokens, failure.value.output_tokens) == (11, 13)


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("axis", ["refusal", "action", "multiple", "incomplete", "wrong_role", "wrong_total"])
def test_noncompleted_or_external_action_envelopes_do_not_degrade_to_text(kind, axis):
    value = envelope(kind)
    assistant = value["choices"][0]["message"] if kind == "chat" else value["output"][0]
    if axis == "refusal":
        assistant["refusal"] = "cannot comply"
    elif axis == "action":
        assistant["tool_calls"] = []
    elif axis == "multiple":
        key = "choices" if kind == "chat" else "output"
        value[key].append(copy.deepcopy(value[key][0]))
    elif axis == "incomplete":
        if kind == "chat":
            value["choices"][0]["finish_reason"] = "length"
        else:
            value["status"] = "incomplete"
    elif axis == "wrong_role":
        assistant["role"] = "tool"
    else:
        value["usage"]["total_tokens"] = 0
    with pytest.raises(p.RcaEvidenceReplyError) as failure:
        p.parse_provider_draft(kind, value, c.validate_source(source_dict()), PROMPT)
    assert (failure.value.input_tokens, failure.value.output_tokens) == (11, 13)
