"""Synthetic literal-provenance contract checks; no patient access or model calls."""

import copy
import json

import pytest

from app.ai.coding_evidence_contract import OUTPUT_BYTES, CodingEvidenceDraft, parse_draft, structural_counts, text_digest, validate_draft


def example():
    text = "\ufeff原文🙂\r\n排除糖尿病；待进一步核实。"
    source = {
        "source_id": "coding_case:synthetic",
        "documents": [{"source_id": "document:one", "field": "discharge_diagnosis", "text": text, "text_hash": text_digest(text)}],
        "code_bindings": [
            {"binding_token": "binding:one", "kind": "diagnosis", "code_text": "EXAMPLE", "stored_name": "合成名称", "is_primary": 1, "current_dictionary_state": "matches_current_dictionary"}
        ],
    }
    start = text.index("排除")
    reply = {
        "schema_version": "coding_evidence_draft_v1",
        "source_id": source["source_id"],
        "source_projection_hash": "a" * 64,
        "claims": [
            {
                "binding_token": "binding:one",
                "model_assessment": "conflict_claim",
                "review_note": "这是待人工复核的模型主张。",
                "clarification_question": None,
                "citations": [{"document_source_id": "document:one", "text_hash": text_digest(text), "start": start, "end": start + 5, "quote": "排除糖尿病"}],
            }
        ],
    }
    return source, reply


def accept(source, reply):
    draft = parse_draft(json.dumps(reply, ensure_ascii=False))
    return validate_draft(source, draft, "a" * 64)


def test_exact_bom_crlf_emoji_codepoint_quote_and_unreviewed_structure():
    source, reply = example()
    original = copy.deepcopy(source)
    assert accept(source, reply).claims[0].citations[0].quote == "排除糖尿病"
    assert source == original
    counts = structural_counts(source)
    assert counts["observed_primary_diagnosis_binding_count"] == 1
    assert counts["clinical_semantics"] == "unverified"
    assert counts["official_grouping"] == "not_performed"
    assert counts["dictionary_edition"] == counts["historical_group_rule_basis"] == "not_available"


@pytest.mark.parametrize(
    "field,value",
    [("document_source_id", "another:patient"), ("text_hash", "b" * 64), ("start", True), ("start", "6"), ("start", -1), ("end", 99999), ("end", 0), ("quote", "确诊糖尿病"), ("quote", "\ud800")],
)
def test_changed_or_noncanonical_literal_span_rejected(field, value):
    source, reply = example()
    reply["claims"][0]["citations"][0][field] = value
    with pytest.raises((ValueError, UnicodeError)):
        accept(source, reply)


def test_utf16_offset_cannot_replace_codepoint_offset():
    source, reply = example()
    citation = reply["claims"][0]["citations"][0]
    citation["start"] += 1
    citation["end"] += 1
    with pytest.raises(ValueError):
        accept(source, reply)


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "extra", "wrong_binding", "wrong_source", "wrong_projection", "duplicate_citation", "unknown_assessment", "diagnosis_field", "group_field", "amount_field"]
)
def test_closed_member_and_output_contract(mutation):
    source, reply = example()
    claim = reply["claims"][0]
    if mutation == "missing":
        reply["claims"] = []
    elif mutation == "duplicate":
        reply["claims"].append(copy.deepcopy(claim))
    elif mutation == "extra":
        other = copy.deepcopy(claim)
        other["binding_token"] = "not:original"
        reply["claims"].append(other)
    elif mutation == "wrong_binding":
        claim["binding_token"] = "not:original"
    elif mutation == "wrong_source":
        reply["source_id"] = "coding_case:another"
    elif mutation == "wrong_projection":
        reply["source_projection_hash"] = "b" * 64
    elif mutation == "duplicate_citation":
        claim["citations"].append(copy.deepcopy(claim["citations"][0]))
    elif mutation == "unknown_assessment":
        claim["model_assessment"] = "clinically_confirmed"
    else:
        claim[{"diagnosis_field": "new_diagnosis", "group_field": "group_code", "amount_field": "expected_amount"}[mutation]] = "not allowed"
    with pytest.raises(ValueError):
        accept(source, reply)


@pytest.mark.parametrize("assessment", ["support_claim", "conflict_claim"])
def test_support_or_conflict_requires_a_literal_quote(assessment):
    source, reply = example()
    reply["claims"][0].update(model_assessment=assessment, citations=[])
    with pytest.raises(ValueError):
        accept(source, reply)


def test_explicit_insufficient_and_clarification_remain_model_drafts():
    source, reply = example()
    claim = reply["claims"][0]
    claim.update(model_assessment="insufficient_evidence", citations=[])
    assert accept(source, reply).claims[0].model_assessment == "insufficient_evidence"
    claim["model_assessment"] = "clarification_requested"
    with pytest.raises(ValueError):
        accept(source, reply)
    claim["clarification_question"] = "请核对原文是否表达排除诊断。"
    assert accept(source, reply).claims[0].clarification_question
    assert structural_counts(source)["clinical_semantics"] == "unverified"


def test_literal_match_does_not_certify_model_semantics():
    source, reply = example()
    # A literal span validator cannot certify an incorrect medical inference.
    reply["claims"][0]["model_assessment"] = "support_claim"
    assert accept(source, reply).claims[0].model_assessment == "support_claim"
    assert structural_counts(source)["clinical_semantics"] == "unverified"


@pytest.mark.parametrize("field,value", [("kind", "unknown"), ("is_primary", None), ("is_primary", True), ("is_primary", 2)])
def test_original_unknown_kind_and_primary_do_not_become_zero_or_confirmation(field, value):
    source, _ = example()
    source["code_bindings"][0][field] = value
    result = structural_counts(source)
    assert result["observed_primary_diagnosis_binding_count"] == 0
    assert result["unknown_binding_kind_count"] + result["unknown_primary_flag_count"] == 1


def test_duplicate_keys_nonfinite_numbers_and_fenced_json_rejected():
    _, reply = example()
    text = json.dumps(reply)
    for bad in [text.replace('"schema_version":', '"schema_version":"duplicate","schema_version":', 1), text.replace('"start": 6', '"start": NaN'), "```json\n" + text + "\n```"]:
        with pytest.raises(ValueError):
            parse_draft(bad)


def test_complete_utf8_byte_budget_checked_before_parsing():
    _, reply = example()
    text = json.dumps(reply, ensure_ascii=False)
    exact = text + " " * (OUTPUT_BYTES - len(text.encode()))
    assert isinstance(parse_draft(exact), CodingEvidenceDraft)
    with pytest.raises(ValueError):
        parse_draft(exact + " ")


def test_empty_complete_binding_set_does_not_invent_codes():
    source, reply = example()
    source["code_bindings"] = []
    reply["claims"] = []
    assert accept(source, reply).claims == []
    assert structural_counts(source)["binding_count"] == 0
