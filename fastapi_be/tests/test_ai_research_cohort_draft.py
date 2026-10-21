"""Actual governed SQLite Case -> pure questions, UTF8 and server result checks.

Model drafts here are explicit synthetic protocol responses, not model calls.
"""

import copy
import subprocess
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.ai.research_cohort_cases import case_current, create_case, preview_input, review_case
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_draft import COVERAGE, citation_catalog, digest, validate_draft
from app.ai.research_cohort_prompt import RESEARCH_SYSTEM_PROMPT, RESEARCH_TASK_PROMPT, instructions_for
from app.ai.research_cohort_protocol import model_input, model_wire, parse_draft_json
from app.ai.research_cohort_result import result_for_draft, validate_result
from tests.test_ai_research_cohort_cases import case_request
from tests.test_ai_research_cohort_collection import clinical_case
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import permitted
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


@pytest.fixture
def public_source(db_session, research_case):
    db, case = db_session, research_case
    case["scope_request"]["external_model_use"] = "recorded_permitted"
    case["scope_request"]["data_families"] = ["medical_records", "patient_demographics", "registrations"]
    scope, _, _ = permitted(db, case)
    _, records = clinical_case(db, case)
    literal = "🧪\ufeff否认胸痛\r\n"
    db.execute(text("UPDATE hoimsystem_medical_record SET symptom=:body WHERE medical_record_id=:id"), {"body": "首" + literal + "末", "id": records[0].medical_record_id})
    db.commit()
    request = case_request(scope)
    request["criteria"]["root"]["literal"] = literal
    preview = preview_input(db, case["admin_user"], request)
    made = create_case(db, case["admin_user"], {"request": request, "expected_collection_digest": preview["expected_collection_digest"], "basis_note": BASIS})
    review_case(db, case["super_admin_user"], made["case_id"], {"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    return case_current(db, case["admin_user"], made["case_id"])["public_source"]


def draft_for(source, *, category="recorded_evidence_question", target_category="recorded_evidence_quote"):
    target = next(row for row in citation_catalog(source)["targets"] if row["category"] == target_category)
    quote = target["text"]
    return {
        "schema_version": "research_cohort_questions_v1",
        "research_source_id": source["source_id"],
        "source_projection_hash": digest(source),
        "coverage": COVERAGE,
        "questions": [
            {
                "category": category,
                "title": "核对原记录否定表述",
                "observation": "原记录中保留明确否定原文，不能据此推断全程临床状态。",
                "clarification_question": "该原文的记录范围和未知条件是否还需要独立人工核对？",
                "citations": [{"target_token": target["target_token"], "text_hash": target["text_hash"], "start": 0, "end": len(quote), "quote": quote}],
            }
        ],
    }


def test_actual_case_quote_cp_bom_crlf_emoji_and_server_deterministic_result_are_separate(public_source):
    source = public_source
    catalog = citation_catalog(source)
    target = next(row for row in catalog["targets"] if row["category"] == "recorded_evidence_quote")
    assert target["text"] == "🧪\ufeff否认胸痛\r\n"
    assert "未知日期完整原文" not in canonical_json(catalog)
    draft = draft_for(source)
    assert parse_draft_json(canonical_json(draft).encode(), source) == draft
    result = result_for_draft(draft, source)
    assert result["deterministic_evaluation"]["counts"] == source["counts"]
    assert result["deterministic_evaluation"]["outcomes"][0]["truth"] == source["outcomes"][0]["truth"]
    assert result["question_draft"] == draft and validate_result(result, source) == result
    assert "identity_secret" not in canonical_json(result) and "patient_id" not in canonical_json(result)


def test_rehashed_wrong_anchor_offsets_normalization_hash_type_and_duplicate_citations_are_rejected(public_source):
    source = public_source
    original = draft_for(source)
    variants = []
    for field, value in (("research_source_id", "research_cohort:foreign"), ("source_projection_hash", "0" * 64), ("coverage", "complete_cohort"), ("sql", "SELECT * FROM patients")):
        wrong = copy.deepcopy(original)
        wrong[field] = value
        variants.append(wrong)
    for key, value in (("start", True), ("end", 999), ("quote", original["questions"][0]["citations"][0]["quote"].replace("\r\n", "\n")), ("text_hash", "0" * 64), ("target_token", "0" * 64)):
        wrong = copy.deepcopy(original)
        wrong["questions"][0]["citations"][0][key] = value
        variants.append(wrong)
    wrong = copy.deepcopy(original)
    wrong["questions"][0]["citations"].append(copy.deepcopy(wrong["questions"][0]["citations"][0]))
    variants.append(wrong)
    for value in variants:
        with pytest.raises(HTTPException):
            validate_draft(value, source)


def test_criteria_and_unknown_reason_cannot_be_mislabeled_clinical_evidence(public_source):
    source = public_source
    standard = draft_for(source, category="standard_question", target_category="criteria_declaration")
    assert validate_draft(standard, source) == standard
    standard["questions"][0]["category"] = "recorded_evidence_question"
    with pytest.raises(HTTPException):
        validate_draft(standard, source)
    unknown = draft_for(source, category="unknown_condition_question", target_category="record_scope_reason")
    assert validate_draft(unknown, source) == unknown


def test_strict_json_rejects_duplicate_nested_keys_nonfinite_trailing_markdown_invalid_utf8(public_source):
    source = public_source
    valid = canonical_json(draft_for(source))
    values = [valid + "{}", "```json\n" + valid + "\n```", valid.replace('"start":0', '"start":0,"start":0'), valid.replace('"start":0', '"start":NaN'), b"\xff", "[]", "null"]
    for raw in values:
        with pytest.raises(HTTPException):
            parse_draft_json(raw, source)


def test_source_model_permission_and_current_versioned_task_are_independent_of_fixed_system(public_source):
    source = public_source
    custom = "这是已授权独立保存的完整Task新版本\ufeff\r\n🧪，保留所有原字面量。"
    value, sha = model_wire(source, "原问题\r\n🧪", custom)
    assert value["instructions"] == RESEARCH_SYSTEM_PROMPT + "\n\n" + custom
    assert len(sha) == 64 and instructions_for(RESEARCH_TASK_PROMPT).startswith(RESEARCH_SYSTEM_PROMPT)
    assert value["input"]["question"] == "原问题\r\n🧪"
    denied = copy.deepcopy(source)
    denied["external_model_use"] = "unknown"
    with pytest.raises(HTTPException) as error:
        model_input(denied)
    assert error.value.status_code == 403
    for question in (True, "🧪" * 2001, "\ud800"):
        with pytest.raises((HTTPException, UnicodeError)):
            model_input(source, question)
    for task in ("\ufeff\r\n ", "🧪" * 16384, None):
        with pytest.raises((ValueError, TypeError)):
            instructions_for(task)


def test_whole_model_wire_not_only_source_and_question_count_caps_are_enforced(public_source, monkeypatch):
    source = public_source
    value = draft_for(source)
    value["questions"] = value["questions"] * 129
    with pytest.raises(HTTPException):
        validate_draft(value, source)
    with pytest.raises(HTTPException) as error:
        parse_draft_json(b" " * (8 * 1024 * 1024 + 1), source)
    assert error.value.status_code == 413
    # Source and catalog each remain complete; their combined actual model
    # message is separately bounded rather than claiming an 8MiB Source fits.
    from app.ai import research_cohort_protocol as protocol

    wire, _ = model_wire(source, None, RESEARCH_TASK_PROMPT)
    limit = len(canonical_json(wire).encode("utf-8")) - 1
    assert len(canonical_json(source).encode("utf-8")) < limit
    monkeypatch.setattr(protocol, "MAX_BYTES", limit)
    with pytest.raises(HTTPException) as error:
        model_wire(source, None, RESEARCH_TASK_PROMPT)
    assert error.value.status_code == 413


def test_model_cannot_replace_server_counts_truth_summary_or_export_restrictions(public_source):
    source = public_source
    result = result_for_draft(draft_for(source), source)
    changes = []
    for key, value in (("summary", "自动认定可入组"), ("no_automatic_export", False), ("no_business_write", 1), ("extra_amount", 100)):
        wrong = copy.deepcopy(result)
        wrong[key] = value
        changes.append(wrong)
    for field in ("counts", "outcomes"):
        wrong = copy.deepcopy(result)
        wrong["deterministic_evaluation"][field] = {} if field == "counts" else []
        changes.append(wrong)
    for wrong in changes:
        with pytest.raises(HTTPException):
            validate_result(wrong, source)
    empty = draft_for(source)
    empty["questions"] = []
    assert result_for_draft(empty, source)["question_draft"]["questions"] == []


def test_pure_modules_import_without_database_settings_or_network():
    code = """
import importlib.abc,sys
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname in {'sqlalchemy','app.database','app.models','pydantic_settings'}:raise RuntimeError(fullname)
sys.meta_path.insert(0,Deny())
from app.ai import research_cohort_draft,research_cohort_prompt,research_cohort_protocol,research_cohort_result
assert 'app.database' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
