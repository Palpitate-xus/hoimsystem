"""Pure exact literal/protocol tests using the actual current Context source.

Provider envelopes are protocol fixtures; no inference or SQL is claimed.
"""

import copy
import json
from pathlib import Path

import pytest

from app.ai import research_variables_protocol as protocol
from app.ai import research_variables_task_result as result
from app.ai.research_variables_task_contract import MAX_WIRE_BYTES, VariableTaskSource, canonical, digest

INSTRUCTIONS = "d" * 64


def source():
    values = json.loads((Path(__file__).parent / "fixtures/research_variables_task/actual-current-context.json").read_text())
    return VariableTaskSource.model_validate(values["source"])


def draft(original=None):
    original = original or source()
    row = original.documents[0].model_dump(mode="json")
    literal = row.pop("literal")
    return {
        "schema_version": "research_variable_draft_v1",
        "coverage": "partial_candidates_only",
        "candidates": [{**row, "classification": "value_quote_candidate", "start": 0, "end": len(literal), "quote": literal}],
    }


def envelope(kind, raw, usage=True):
    value = (
        {"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": raw}}]}
        if kind == "chat"
        else {"status": "completed", "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": raw}]}]}
    )
    if usage is True:
        value["usage"] = {"prompt_tokens": 11, "completion_tokens": 13, "total_tokens": 24} if kind == "chat" else {"input_tokens": 11, "output_tokens": 13, "total_tokens": 24}
    elif usage is not False:
        value["usage"] = usage
    return value


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("counts", ["full", "absent", "null", "partial", "null_component", "total_only"])
def test_actual_source_literal_reply_binds_server_anchors_and_keeps_independent_nullable_usage(kind, counts):
    original = source()
    names = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
    usage, expected = {
        "full": (True, (11, 13)),
        "absent": (False, (None, None)),
        "null": (None, (None, None)),
        "partial": ({names[0]: 11}, (11, None)),
        "null_component": ({names[0]: None, names[1]: 13}, (None, 13)),
        "total_only": ({"total_tokens": 24}, (None, None)),
    }[counts]
    bound, inputs, outputs = protocol.parse_provider_draft(kind, envelope(kind, canonical(draft(original)), usage), original, INSTRUCTIONS)
    assert (inputs, outputs) == expected
    assert bound.source_projection_hash == digest(original) and bound.documents_hash == original.documents_hash
    assert bound.instructions_digest == INSTRUCTIONS and bound.source_id == original.source_id
    accepted = result.result_for_draft(bound, original, INSTRUCTIONS)
    assert result.validate_result(accepted.model_dump(mode="json"), original, INSTRUCTIONS) == accepted
    assert accepted.sections[0].source_ids == [original.source_id] and accepted.sections[1].source_ids == []
    quote = accepted.research_variable_extraction.literal_draft.candidates[0].quote
    assert quote.startswith("\ufeff") and "\r\n" in quote and "🧪" in quote
    assert "未核实" in accepted.summary and quote not in accepted.summary


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("damage", ["quote", "duplicate", "float", "fence", "truncated", "refusal", "action", "nonfinite"])
def test_invalid_or_incomplete_provider_reply_retains_actual_received_usage_without_accepting_candidates(kind, damage):
    proposed = draft()
    if damage == "quote":
        proposed["candidates"][0]["quote"] += "原文没有"
    raw = canonical(proposed)
    if damage == "duplicate":
        raw = raw[:-1] + ',"candidates":[]}'
    elif damage == "float":
        raw = raw.replace('"start":0', '"start":0.0')
    elif damage == "fence":
        raw = "```json\n" + raw + "\n```"
    elif damage == "nonfinite":
        raw = raw.replace('"start":0', '"start":NaN')
    value = envelope(kind, raw)
    if damage == "truncated":
        if kind == "chat":
            value["choices"][0]["finish_reason"] = "length"
        else:
            value["status"] = "incomplete"
    elif damage == "refusal":
        value["refusal"] = "explicit refusal"
    elif damage == "action":
        value["actions"] = [{"type": "external_action"}]
    with pytest.raises(protocol.VariableReplyError) as error:
        protocol.parse_provider_draft(kind, value, source(), INSTRUCTIONS)
    assert (error.value.input_tokens, error.value.output_tokens) == (11, 13)


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("invalid", [True, "11", -1, 2000001, 1.0])
def test_invalid_reported_count_is_rejected_but_its_actual_companion_is_retained(kind, invalid):
    names = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
    with pytest.raises(protocol.VariableReplyError) as error:
        protocol.parse_provider_draft(kind, envelope(kind, canonical(draft()), {names[0]: invalid, names[1]: 13}), source(), INSTRUCTIONS)
    assert error.value.input_tokens is None and error.value.output_tokens == 13


def test_false_semantic_classification_is_still_only_an_unreviewed_literal_candidate_and_empty_is_not_completeness():
    original = source()
    values = draft(original)
    values["candidates"][0]["classification"] = "not_measured_quote_candidate"
    bound = result.bind_draft(values, original, INSTRUCTIONS)
    accepted = result.result_for_draft(bound, original, INSTRUCTIONS)
    assert accepted.research_variable_extraction.literal_draft.candidates[0].classification == "not_measured_quote_candidate"
    assert "分类未核实" in accepted.sections[1].content and "不证明" in accepted.warnings[0]
    empty = {"schema_version": "research_variable_draft_v1", "coverage": "partial_candidates_only", "candidates": []}
    accepted = result.result_for_draft(result.bind_draft(empty, original, INSTRUCTIONS), original, INSTRUCTIONS)
    assert accepted.research_variable_extraction.literal_draft.coverage == "partial_candidates_only"
    assert "空候选" in accepted.warnings[1]


@pytest.mark.parametrize("damage", ["summary", "source_id", "instruction", "source_projection", "quote", "missing", "extra"])
def test_full_server_result_cannot_be_rewritten_downgraded_or_rebound(damage):
    original = source()
    accepted = result.result_for_draft(result.bind_draft(draft(original), original, INSTRUCTIONS), original, INSTRUCTIONS).model_dump(mode="json")
    if damage == "summary":
        accepted["summary"] = "已确认未测且完整有效"
    elif damage == "source_id":
        accepted["sections"][0]["source_ids"] = []
    elif damage == "instruction":
        accepted["research_variable_extraction"]["instructions_digest"] = "f" * 64
    elif damage == "source_projection":
        accepted["research_variable_extraction"]["source_projection_hash"] = "f" * 64
    elif damage == "quote":
        accepted["research_variable_extraction"]["literal_draft"]["candidates"][0]["quote"] = "假引文"
    elif damage == "missing":
        del accepted["research_variable_extraction"]
    else:
        accepted["matrix"] = []
    with pytest.raises(ValueError):
        result.validate_result(accepted, original, INSTRUCTIONS)


@pytest.mark.parametrize("damage", ["boolean", "utf16", "overlap", "foreign_key"])
def test_exact_codepoint_spans_and_complete_original_field_membership_are_hard_constraints(damage):
    values = draft()
    row = values["candidates"][0]
    if damage == "boolean":
        row["start"] = False
    elif damage == "utf16":
        row["end"] += 1
    elif damage == "overlap":
        values["candidates"].append(copy.deepcopy(row))
    else:
        row["variable_key"] = "undeclared_variable"
    with pytest.raises(ValueError):
        result.bind_draft(values, source(), INSTRUCTIONS)


def test_full_provider_json_depth_and_utf8_budgets_reject_without_truncating_and_keep_usage():
    for raw in ("[" * 33 + "0" + "]" * 33, "\ud800", "x" * (MAX_WIRE_BYTES + 1)):
        with pytest.raises(protocol.VariableReplyError) as error:
            protocol.parse_provider_draft("chat", envelope("chat", raw), source(), INSTRUCTIONS)
        assert (error.value.input_tokens, error.value.output_tokens) == (11, 13)


def test_all_128_full_4000_codepoint_proposals_are_kept_whole_with_exact_nonoverlap_and_original_types():
    original = source().model_dump(mode="json")
    literal = "🧪" * 4000
    original["documents"][0]["literal"] = literal * 128
    original["documents_hash"] = digest(original["documents"])
    original = VariableTaskSource.model_validate(original)
    values = draft(original)
    base = values["candidates"][0]
    values["candidates"] = [{**base, "start": index * 4000, "end": (index + 1) * 4000, "quote": literal} for index in range(128)]
    accepted = result.result_for_draft(result.bind_draft(values, original, INSTRUCTIONS), original, INSTRUCTIONS)
    raw = canonical(accepted)
    assert len(accepted.research_variable_extraction.literal_draft.candidates) == 128
    assert len(raw.encode()) > 2_000_000 and len(raw.encode()) < MAX_WIRE_BYTES
    assert accepted.research_variable_extraction.literal_draft.candidates[-1].end == 512000
    values["candidates"].append(copy.deepcopy(values["candidates"][-1]))
    with pytest.raises(ValueError):
        result.bind_draft(values, original, INSTRUCTIONS)
