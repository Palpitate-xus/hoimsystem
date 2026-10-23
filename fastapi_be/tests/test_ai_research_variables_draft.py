"""Exact76 literal proposals; these pure checks grant no Source permission."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai.research_variables_draft import LiteralDocument, parse_draft_json, validate_draft


def document(literal="\ufeff否认胸痛\r\n🧪组合e\u0301，不据此推断未测。", kind="verbatim_text"):
    return dict(member_token="rv_member:" + "a" * 64, record_token="rv_record:" + "b" * 64, field_token="rv_field:" + "c" * 64, variable_key="recorded_symptom", value_kind=kind, literal=literal)


def proposal(doc, start=0, end=None):
    end = len(doc["literal"]) if end is None else end
    return {
        **{key: doc[key] for key in ("member_token", "record_token", "field_token", "variable_key", "value_kind")},
        "classification": "value_quote_candidate",
        "start": start,
        "end": end,
        "quote": doc["literal"][start:end],
    }


def draft(rows):
    return dict(schema_version="research_variable_draft_v1", coverage="partial_candidates_only", candidates=rows)


def test_bom_crlf_emoji_combining_codepoints_and_negative_statement_survive_exactly():
    doc = document()
    raw = draft([proposal(doc)])
    assert validate_draft(raw, [doc]) == raw
    assert parse_draft_json(json.dumps(raw, ensure_ascii=False), [doc]) == raw
    start = doc["literal"].index("🧪")
    assert validate_draft(draft([proposal(doc, start, start + 1)]), [doc])["candidates"][0]["quote"] == "🧪"


@pytest.mark.parametrize(
    "change",
    [
        {"member_token": "rv_member:" + "d" * 64},
        {"record_token": "rv_record:" + "d" * 64},
        {"field_token": "rv_field:" + "d" * 64},
        {"field_token": "rv_record:" + "c" * 64},
        {"variable_key": "other_variable"},
        {"value_kind": "original_integer"},
        {"start": True},
        {"end": 1.0},
        {"start": -1},
        {"end": 8388609},
        {"classification": "clinically_confirmed"},
        {"proposed_value": 0},
        {"quote": "否认胸痛\n🧪组合e\u0301，不据此推断未测。"},
        {"quote": "\ud800"},
    ],
)
def test_foreign_source_identity_unsafe_types_normalization_or_extra_claims_refuse(change):
    doc = document()
    with pytest.raises((ValidationError, ValueError)):
        validate_draft(draft([{**proposal(doc), **change}]), [doc])


@pytest.mark.parametrize(
    "literal,kind",
    [
        ("0", "original_integer"),
        ("-2", "original_integer"),
        ("9223372036854775807", "original_integer"),
        ("2026-10-21", "original_calendar_date"),
        ("2026-10-21T00:00:00.000000", "original_naive_clock"),
        ("2026-10-21T00:00:00.123456", "original_naive_clock"),
    ],
)
def test_original_scalar_date_or_clock_only_accepts_whole_uninterpreted_literal(literal, kind):
    doc = document(literal, kind)
    assert validate_draft(draft([proposal(doc)]), [doc])["candidates"][0]["quote"] == literal
    with pytest.raises(ValueError):
        validate_draft(draft([{**proposal(doc), "classification": "not_measured_quote_candidate"}]), [doc])
    if len(literal) > 1:
        with pytest.raises(ValueError):
            validate_draft(draft([proposal(doc, 1)]), [doc])


@pytest.mark.parametrize(
    "literal,kind",
    [
        ("-0", "original_integer"),
        ("01", "original_integer"),
        ("1.0", "original_integer"),
        ("9223372036854775808", "original_integer"),
        ("True", "original_integer"),
        ("2026-02-30", "original_calendar_date"),
        ("2026-10-21T00:00:00Z", "original_naive_clock"),
        ("2026-10-21T00:00:00.123456+08:00", "original_naive_clock"),
        ("2026-10-21T00:00:00", "original_naive_clock"),
    ],
)
def test_document_types_do_not_normalize_invalid_original_literals(literal, kind):
    with pytest.raises(ValidationError):
        LiteralDocument.model_validate(document(literal, kind))


def test_null_or_no_candidates_never_become_zero_unmeasured_or_inapplicable():
    empty = draft([])
    assert validate_draft(empty, []) == empty
    assert validate_draft(empty, [document(None)]) == empty
    doc = document("0", "original_integer")
    with pytest.raises(ValueError):
        validate_draft(draft([proposal(doc)]), [document(None, "original_integer")])
    for classification in ["not_measured_quote_candidate", "not_applicable_quote_candidate", "conflict_quote_candidate"]:
        text = document("原文记载：本次未测；分类仍待人工复核。")
        row = {**proposal(text), "classification": classification}
        assert validate_draft(draft([row]), [text])["candidates"][0] == row


def test_complete_document_identity_and_duplicate_overlap_budget_fail_closed():
    doc = document()
    with pytest.raises(ValueError):
        validate_draft(draft([]), [doc, copy.deepcopy(doc)])
    for rows in [[proposal(doc), proposal(doc)], [proposal(doc, 0, 5), proposal(doc, 2, 6)]]:
        with pytest.raises(ValueError):
            validate_draft(draft(rows), [doc])
    with pytest.raises(ValueError):
        validate_draft(draft([]), [doc] * 8193)
    with pytest.raises(ValueError):
        validate_draft(draft([]), [document("汉" * (8388608 // 3 + 1))])
    with pytest.raises(ValidationError):
        validate_draft(draft([proposal(doc)] * 129), [doc])


@pytest.mark.parametrize("mutation", ["duplicate_outer", "duplicate_inner", "float", "nan", "trailing", "markdown"])
def test_model_json_is_one_whole_closed_object_with_exact_integer_offsets(mutation):
    doc = document()
    raw = json.dumps(draft([proposal(doc)]), ensure_ascii=False)
    if mutation == "duplicate_outer":
        raw = raw.replace('"coverage":', '"coverage":"partial_candidates_only","coverage":')
    if mutation == "duplicate_inner":
        raw = raw.replace('"start": 0', '"start":0,"start":0')
    if mutation == "float":
        raw = raw.replace('"start": 0', '"start":0.0')
    if mutation == "nan":
        raw = raw.replace('"start": 0', '"start":NaN')
    if mutation == "trailing":
        raw += " extra"
    if mutation == "markdown":
        raw = "```json\n" + raw + "\n```"
    with pytest.raises(ValueError):
        parse_draft_json(raw, [doc])


def test_prompt_literals_can_be_imported_with_stdlib_only_and_no_backend_dependencies():
    root = Path(__file__).parents[1]
    code = "import sys;sys.path.insert(0,sys.argv[1]);from app.ai.research_variables_prompt import SYSTEM_PROMPT,DEFAULT_TASK_PROMPT,VARIABLE_TASK_VERSION;assert SYSTEM_PROMPT and DEFAULT_TASK_PROMPT and VARIABLE_TASK_VERSION;assert not any(n.startswith(('pydantic','sqlalchemy','app.database','app.main','app.models')) for n in sys.modules)"
    result = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(root)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
