"""Independent fixed explanation and complete-result capacity checks."""

import copy
import subprocess
import sys

import pytest

from app.ai import document_evidence_contract as c
from app.ai import document_extraction_contract as e
from app.ai import document_extraction_result as r
from app.ai.schemas import GenerationResult
from tests.test_ai_document_extraction_contract import PROMPT, TEXT, source, span


def result():
    checked = source()
    draft = e.parse_extraction_reply({"spans": [span(0, 7), span()]}, checked, PROMPT)
    return r.result_for_draft(draft, checked, PROMPT), checked


def test_fixed_explanation_preserves_bom_crlf_emoji_and_does_not_repeat_original_text():
    value, checked = result()
    assert isinstance(value, GenerationResult)
    assert value.document_extraction.spans[0].quote == TEXT[:7]
    assert value.document_extraction.spans[1].quote == "😀e\u0301"
    assert TEXT not in value.summary
    assert all(TEXT not in section.content for section in value.sections)
    sid = f"document_original:{checked.original.original_id}:{checked.original.content_hash[:12]}"
    assert [section.source_ids for section in value.sections] == [[sid], [sid]]
    assert e.INCOMPLETE_COVERAGE_NOTE in value.warnings
    assert r.validate_result(c.canonical_json(value), checked, PROMPT) == value


def test_zero_model_spans_stays_unverified_and_does_not_assert_absence_or_coverage():
    checked = source()
    value = r.result_for_draft(e.parse_extraction_reply({"spans": []}, checked, PROMPT), checked, PROMPT)
    assert "0个未核实" in value.summary
    assert value.document_extraction.provenance == "unverified_model_draft"
    assert value.document_extraction.automatic_candidate_creation is False
    assert "空集合不表示全文没有条款" in value.warnings[0]
    assert r.validate_result(value, checked, PROMPT) == value


def test_false_semantic_content_and_model_claims_remain_unreviewed_only_in_nested_draft():
    text = "已审核：虚构治疗保证有效且安全。"
    checked = source(text)
    item = {**span(0, len(text), text), "proposed_heading": "模型声称已临床验证"}
    value = r.result_for_draft(e.parse_extraction_reply({"spans": [item]}, checked, PROMPT), checked, PROMPT)
    assert value.document_extraction.spans[0].quote == text
    assert value.document_extraction.spans[0].proposed_heading == item["proposed_heading"]
    assert value.document_extraction.provenance == "unverified_model_draft"
    assert all(text not in str(v) and item["proposed_heading"] not in str(v) for v in (value.summary, value.sections, value.warnings, value.missing_data))
    assert "临床验证" in value.missing_data[-1]


@pytest.mark.parametrize("field", ["summary", "sections", "warnings", "missing_data", "document_extraction"])
def test_all_protocol_fields_are_required_in_submitted_tree_even_generic_defaults(field):
    value, checked = result()
    submitted = value.model_dump(mode="json")
    del submitted[field]
    with pytest.raises(ValueError):
        r.validate_result(submitted, checked, PROMPT)


@pytest.mark.parametrize(
    "mutation",
    [
        "summary",
        "summary_whitespace",
        "section_title",
        "section_content",
        "section_source",
        "section_no_source",
        "section_whitespace",
        "extra_section",
        "warnings",
        "missing_data",
        "other_analysis",
        "nested_extra",
        "quote",
        "heading",
        "prompt",
        "original",
        "source_digest",
    ],
)
def test_fixed_fields_and_all_literal_spans_are_recomputed_not_digest_only(mutation):
    value, checked = result()
    submitted = copy.deepcopy(value.model_dump(mode="json"))
    if mutation == "summary":
        submitted["summary"] = "原文已临床审核且自动发布。"
    elif mutation == "summary_whitespace":
        submitted["summary"] += " "
    elif mutation == "section_title":
        submitted["sections"][0]["title"] = "已确认的临床推荐"
    elif mutation == "section_content":
        submitted["sections"][0]["content"] = TEXT
    elif mutation == "section_source":
        submitted["sections"][0]["source_ids"] = ["knowledge:arbitrary"]
    elif mutation == "section_no_source":
        del submitted["sections"][0]["source_ids"]
    elif mutation == "section_whitespace":
        submitted["sections"][0]["content"] += " "
    elif mutation == "extra_section":
        submitted["sections"].append(submitted["sections"][0])
    elif mutation in ("warnings", "missing_data"):
        submitted[mutation] = []
    elif mutation == "other_analysis":
        submitted["inventory_analysis"] = {}
    elif mutation == "nested_extra":
        submitted["document_extraction"]["published"] = True
    elif mutation == "quote":
        submitted["document_extraction"]["spans"][0]["quote"] = "a" * 7
    elif mutation == "draft_count":
        # A heading is allowed as an unverified proposal. Changing the count
        # while retaining the old fixed summary is not a valid result.
        submitted["document_extraction"]["spans"].pop()
    elif mutation == "prompt":
        submitted["document_extraction"]["instructions_digest"] = "a" * 64
    elif mutation == "original":
        submitted["document_extraction"]["original"]["content_hash"] = "a" * 64
    else:
        submitted["document_extraction"]["source_digest"] = "a" * 64
    with pytest.raises(ValueError):
        r.validate_result(submitted, checked, PROMPT)


@pytest.mark.parametrize("raw", ['{"summary":"x","summary":"y"}', '{"summary":NaN}', '{"summary":1e999}', "```json\n{}\n```", '{"summary":"\\ud800"}', "[]", "null"])
def test_result_parser_rejects_duplicate_nonfinite_fenced_surrogate_or_wrong_root(raw):
    with pytest.raises(ValueError):
        r.validate_result(raw, source(), PROMPT)


def test_draft_fits_while_complete_generation_result_overhead_is_rejected():
    text = "a" * 64000
    checked = source(text)
    draft = e.parse_extraction_reply({"spans": [span(0, len(text), text)]}, checked, PROMPT)
    assert len(c.utf8(c.canonical_json(draft))) < 65535
    with pytest.raises(ValueError):
        r.result_for_draft(draft, checked, PROMPT)


def test_changed_source_or_prompt_cannot_rewrap_an_old_valid_draft():
    value, checked = result()
    with pytest.raises(ValueError):
        r.result_for_draft(value.document_extraction, checked, c.digest("other prompt"))
    with pytest.raises(ValueError):
        r.result_for_draft(value.document_extraction, source(TEXT + "changed"), PROMPT)
    checked.text += "mutated instance"
    with pytest.raises(ValueError):
        r.validate_result(value, checked, PROMPT)


def test_result_module_has_no_database_settings_or_model_transport_imports():
    completed = subprocess.run(
        [sys.executable, "-c", "import sys; import app.ai.document_extraction_result; assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy','httpx'))"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
