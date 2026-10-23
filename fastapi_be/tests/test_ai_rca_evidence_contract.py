"""Pure synthetic RCA quoting and limits; no actual Source authority claim."""

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_prompt as prompts

H = "a" * 64
PROMPT = hashlib.sha256((prompts.SYSTEM_PROMPT + "\n\n" + prompts.TASK_PROMPT).encode()).hexdigest()
EVENT = "00000000-0000-0000-0000-000000000001"
MANUAL = "00000000-0000-0000-0000-000000000002"
ENTRY = "00000000-0000-0000-0000-000000000003"
CASE = "00000000-0000-0000-0000-000000000004"
TEXT = "\ufeff合成原记录🙂\r\n仅为记录陈述，原因尚未核实。"
TIME = "2026-10-21T12:00:00.123456Z"


def source_dict():
    members = [{"member_id": key, "kind": kind, "content_hash": H, "governance_hash": None, "release_status": "released"} for key, kind in [(EVENT, "legacy_event"), (MANUAL, "human_timeline")]]
    return {
        "schema_version": "rca_evidence_source_v1",
        "case_id": CASE,
        "source_id": f"rca_case:{CASE}:{H[:12]}",
        "content_hash": H,
        "governance_hash": H,
        "snapshot_time": TIME,
        "review_mode": "current_retrospective_investigation_not_historical_prediction",
        "event_state": {
            "recorded_severity": None,
            "recorded_status": 0,
            "report_time": {"text": "2026-10-21T11:00:00.123456", "basis": "stored_naive_no_timezone"},
            "patient_association": "not_recorded",
            "encounter_assignment": "not_recorded",
            "causal_approval": "not_provided",
        },
        "publication": {"status": "published", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "provenance_review": "confirmed", "reviewed_at": TIME},
        "members": members,
        "member_manifest_hash": c.digest(members),
        "items": [
            {
                "item_id": m["member_id"],
                "kind": m["kind"],
                "content_hash": H,
                "governance_hash": None,
                "text": TEXT,
                "text_hash": hashlib.sha256(TEXT.encode()).hexdigest(),
                "available_at": TIME,
                "availability_basis": "server_capture",
            }
            for m in members
        ],
        "timeline": [
            {
                "entry_id": ENTRY,
                "source_item_id": MANUAL,
                "statement": "仅为记录陈述",
                "occurred_time": {"status": "unknown", "basis_hash": H},
                "recorded_at": TIME,
                "evidence": [],
                "assertion_status": "human_recorded_statement_not_causal_verification",
            }
        ],
        "evidence_coverage": "finite_declared_snapshot_not_complete_causality_or_hospital_coverage",
    }


def quote():
    return {"item_id": EVENT, "start": 0, "end": 10, "quote": TEXT[:10]}


def reply():
    return {
        "hypotheses": [
            {
                "hypothesis": "需调查是否存在流程交接问题，目前不能确认。",
                "supporting_quotes": [quote()],
                "conflicting_quotes": [],
                "timeline_entry_ids": [ENTRY],
                "evidence_needed": ["需独立交接原件。"],
                "investigation_questions": ["有哪些相反记录？"],
            }
        ],
        "clarification_questions": [],
    }


def test_exact_unicode_source_and_draft_preserve_unknown_zero_naive_clock_and_declared_scope():
    source = c.validate_source(source_dict())
    draft = c.parse_rca_reply(json.dumps(reply(), ensure_ascii=False), source, PROMPT)
    assert draft.hypotheses[0].supporting_quotes[0].quote == TEXT[:10]
    assert draft.coverage == c.COVERAGE and draft.source_projection_hash == c.digest(source)
    assert source.event_state.recorded_status == 0 and source.event_state.recorded_severity is None
    assert source.timeline[0].occurred_time.status == "unknown"
    assert source.event_state.report_time.text == "2026-10-21T11:00:00.123456"
    assert c.provider_payload(source)["rca_source"]["items"][0]["text"] == TEXT


@pytest.mark.parametrize("field", ["recorded_status", "recorded_severity"])
@pytest.mark.parametrize("value", [False, "0", 0.0])
def test_raw_numeric_states_never_coerce_false_string_or_float(field, value):
    data = source_dict()
    data["event_state"][field] = value
    with pytest.raises(ValueError):
        c.validate_source(data)


@pytest.mark.parametrize(
    "mutation",
    [
        "source_id",
        "manifest",
        "text_hash",
        "omitted_item",
        "duplicate_item",
        "missing_event",
        "future_available",
        "future_review",
        "timeline_kind",
        "timeline_statement",
        "added_encounter",
        "old_clock_timezone",
    ],
)
def test_complete_source_closure_rejects_independent_binding_and_clock_errors(mutation):
    data = source_dict()
    if mutation == "source_id":
        data["source_id"] += "x"
    elif mutation == "manifest":
        data["member_manifest_hash"] = "b" * 64
    elif mutation == "text_hash":
        data["items"][0]["text"] += "changed"
    elif mutation == "omitted_item":
        data["items"].pop()
    elif mutation == "duplicate_item":
        data["items"].append(copy.deepcopy(data["items"][0]))
    elif mutation == "missing_event":
        data["members"][0]["kind"] = data["items"][0]["kind"] = "legacy_rca"
        data["member_manifest_hash"] = c.digest(data["members"])
    elif mutation == "future_available":
        data["items"][0]["available_at"] = "2026-10-22T00:00:00.000000Z"
    elif mutation == "future_review":
        data["publication"]["reviewed_at"] = "2026-10-22T00:00:00.000000Z"
    elif mutation == "timeline_kind":
        data["timeline"][0]["source_item_id"] = EVENT
    elif mutation == "timeline_statement":
        data["timeline"][0]["statement"] = "模型补充的时间线"
    elif mutation == "added_encounter":
        data["event_state"]["encounter_assignment"] = "inferred_from_date"
    else:
        data["event_state"]["report_time"]["text"] += "Z"
    with pytest.raises(ValueError):
        c.validate_source(data)


@pytest.mark.parametrize("value", ["2026-02-30T12:00:00.000000Z", "2026-10-21T12:00:00Z", "2026-10-21T12:00:00.000000+00:00", "0000-01-01T00:00:00.000000Z"])
def test_actual_utc6_clocks_do_not_guess_calendar_or_precision(value):
    with pytest.raises(ValueError):
        c.clock(value)


@pytest.mark.parametrize(
    "mutation",
    [
        "bool",
        "float",
        "wrong_quote",
        "unicode_normalization",
        "utf16_index",
        "outside",
        "invented_item",
        "invented_timeline",
        "root_cause_status",
        "model_digest",
        "extra_action",
        "unsupported_without_gap",
    ],
)
def test_model_reply_only_literal_references_and_unverified_closed_fields(mutation):
    data = reply()
    q = data["hypotheses"][0]["supporting_quotes"][0]
    if mutation == "bool":
        q["start"] = False
    elif mutation == "float":
        q["start"] = 0.0
    elif mutation == "wrong_quote":
        q["quote"] = "x" * 10
    elif mutation == "unicode_normalization":
        q["quote"] = q["quote"].replace("\r\n", "\n")
        q["end"] = len(q["quote"])
    elif mutation == "utf16_index":
        q["end"] += 1
    elif mutation == "outside":
        q.update(start=len(TEXT), end=len(TEXT) + 10)
    elif mutation == "invented_item":
        q["item_id"] = CASE
    elif mutation == "invented_timeline":
        data["hypotheses"][0]["timeline_entry_ids"] = [CASE]
    elif mutation == "root_cause_status":
        data["hypotheses"][0]["root_cause_confirmed"] = True
    elif mutation == "model_digest":
        data["source_projection_hash"] = H
    elif mutation == "extra_action":
        data["tool_calls"] = []
    else:
        data["hypotheses"][0]["supporting_quotes"] = []
        data["hypotheses"][0]["evidence_needed"] = []
    with pytest.raises(ValueError):
        c.parse_rca_reply(json.dumps(data), c.validate_source(source_dict()), PROMPT)


@pytest.mark.parametrize(
    "text",
    [
        '{"hypotheses":[],"hypotheses":[],"clarification_questions":[]}',
        '{"hypotheses":NaN,"clarification_questions":[]}',
        '{"hypotheses":Infinity,"clarification_questions":[]}',
        '```json\n{"hypotheses":[],"clarification_questions":[]}\n```',
        "[]",
        '{"hypotheses":[]',
        '{"hypotheses":[],"clarification_questions":["\\ud800"]}',
    ],
)
def test_bad_provider_json_is_rejected_without_sanitizing(text):
    with pytest.raises(ValueError):
        c.parse_rca_reply(text, c.validate_source(source_dict()), PROMPT)


def test_empty_draft_and_false_causal_prose_are_still_mechanically_unverified():
    source = c.validate_source(source_dict())
    empty = c.parse_rca_reply('{"hypotheses":[],"clarification_questions":[]}', source, PROMPT)
    assert not empty.hypotheses and empty.coverage == c.COVERAGE
    data = reply()
    data["hypotheses"][0]["hypothesis"] = "这段错误的因果声称不能由逐字引用校验来证明。"
    draft = c.parse_rca_reply(json.dumps(data), source, PROMPT)
    assert draft.coverage == c.COVERAGE
    for field in ("case_id", "source_projection_hash", "instructions_digest"):
        altered = draft.model_dump(mode="json")
        altered[field] = CASE if field == "case_id" else "b" * 64
        if field == "case_id":
            altered[field] = EVENT
        with pytest.raises(ValueError):
            c.validate_draft(altered, source, PROMPT)


def test_explicit_occurrence_union_has_no_naive_or_empty_interval_coercion():
    c.OccurrenceExact(status="human_declared_exact", at=TIME, basis_hash=H)
    c.OccurrenceInterval(status="human_declared_interval", start_at=TIME, end_at="2026-10-21T12:00:01.123456Z", basis_hash=H)
    with pytest.raises(ValueError):
        c.OccurrenceExact(status="human_declared_exact", at=TIME[:-1], basis_hash=H)
    with pytest.raises(ValueError):
        c.OccurrenceInterval(status="human_declared_interval", start_at=TIME, end_at=TIME, basis_hash=H)


def test_original_utf8_and_whole_source_wire_cap_are_distinct_all_or_refuse():
    data = source_dict()
    data["timeline"] = []
    text = "🙂" * (c.MAX_ORIGINAL_BYTES // 4)
    for item in data["items"]:
        item["text"] = text
        item["text_hash"] = hashlib.sha256(text.encode()).hexdigest()
    c.ReleasedItem.model_validate(data["items"][0])
    with pytest.raises(ValueError, match="8MiB"):
        c.validate_source(data)
    data["items"][0]["text"] += "🙂"
    data["items"][0]["text_hash"] = hashlib.sha256(data["items"][0]["text"].encode()).hexdigest()
    with pytest.raises(ValueError):
        c.ReleasedItem.model_validate(data["items"][0])


def test_parser_preflights_depth_tokens_and_whole_utf8_before_unbounded_structure():
    for text in ("[" * 33 + "0" + "]" * 33, "[" + ",".join("0" for _ in range(c.MAX_JSON_TOKENS + 1)) + "]", " " * (c.MAX_WIRE_BYTES + 1)):
        with pytest.raises(ValueError, match="budget|8MiB"):
            c._strict_reply(text)


def test_model_hypothesis_count_and_question_whole_utf8_never_truncate():
    data = reply()
    data["hypotheses"] *= 65
    with pytest.raises(ValueError):
        c.parse_rca_reply(json.dumps(data), c.validate_source(source_dict()), PROMPT)
    data = reply()
    data["clarification_questions"] = ["🙂" * 2000 + "x"]
    with pytest.raises(ValueError):
        c.parse_rca_reply(json.dumps(data), c.validate_source(source_dict()), PROMPT)


def test_previously_typed_instances_cannot_bypass_strict_revalidation():
    source = c.validate_source(source_dict())
    source.event_state.recorded_status = False
    with pytest.raises(ValueError):
        c.validate_source(source)
    source = c.validate_source(source_dict())
    draft = c.parse_rca_reply(json.dumps(reply()), source, PROMPT)
    draft.hypotheses[0].supporting_quotes[0].start = False
    with pytest.raises(ValueError):
        c.validate_draft(draft, source, PROMPT)


def test_prompt_metadata_remains_loadable_without_site_or_pydantic():
    script = """
import builtins,runpy
real=builtins.__import__
def blocked(name,*args,**kwargs):
    if name.split('.')[0] in {'pydantic','pydantic_settings','sqlalchemy','dotenv'} or name in {'app.config','app.database','app.models'}:
        raise AssertionError(name)
    return real(name,*args,**kwargs)
builtins.__import__=blocked
value=runpy.run_path('app/ai/rca_evidence_prompt.py')
assert type(value['SYSTEM_PROMPT']) is str and type(value['TASK_PROMPT']) is str
"""
    subprocess.run([sys.executable, "-I", "-S", "-c", script], cwd=Path(__file__).resolve().parents[1], check=True)
