"""Pure split-task/proof boundaries, not SQL or provider authorization tests."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_result as r
from app.ai import rca_evidence_task_contract as t
from tests.test_ai_rca_evidence_contract import CASE, PROMPT, TEXT, TIME, H, reply, source_dict


def binding(source=None, **changes):
    source = c.validate_source(source or source_dict())
    grant = t.RcaTaskGrant(
        grant_id="00000000-0000-0000-0000-000000000006",
        event_id=1,
        patient_id_at_grant=None,
        grantee_id=2,
        permission_kind="event_investigation",
        content_hash=H,
        governance_hash=H,
        issued_at="2026-10-21T11:00:00.000000Z",
        valid_until="2026-10-22T12:00:00.000000Z",
    )
    return t.binding_for_source(source, **{"event_id": 1, "patient_id": None, "requested_by": 2, "collection_hash": H, "event_grant": grant, "patient_grant": None, **changes})


def payload(question=None):
    source = c.validate_source(source_dict())
    bound = binding(source)
    short = t.short_context(bound, TIME)
    return {"input": {"rca_evidence_case_id": CASE, "question": question}, "context": t.expand_public_context(short, source), "tools": {}, "evidence": t.evidence_for_binding(bound)}


def draft():
    return c.parse_rca_reply(json.dumps(reply(), ensure_ascii=False), c.validate_source(source_dict()), PROMPT)


@pytest.mark.parametrize("question", [None, "", " \u0085\u3000", "\ufeff原问题🙂\r\n不可执行资料", "🙂" * 2000])
def test_only_complete_public_projection_and_unchanged_optional_question_are_sent(question):
    data = payload(question)
    result = t.public_payload(data)
    assert result == {"rca_source": source_dict(), "question": question}
    assert result["rca_source"]["items"][0]["text"] == TEXT
    assert set(result) == {"rca_source", "question"}
    assert not ({"event_id", "requested_by", "patient_id_at_capture", "event_grant", "rca_evidence_binding"} & set(result))
    assert "identity_secret" not in c.canonical(result)
    assert len(c.utf8(t.text_json(data["evidence"]))) < 65535


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x["input"].update(patient_id=1),
        lambda x: x["input"].update(encounter_ref="admission:1"),
        lambda x: x["input"].update(rca_evidence_case_id=None),
        lambda x: x["input"].update(rca_evidence_case_id="00000000-0000-0000-0000-00000000000A"),
        lambda x: x["input"].update(question="x" * 2001),
        lambda x: x["tools"].update(rca="external action"),
        lambda x: x["context"].update(document_source={}),
        lambda x: x["context"]["selected_sources"].update(rca_evidence_case_id="00000000-0000-0000-0000-000000000009"),
        lambda x: x["evidence"][0].update(content="private sentinel"),
        lambda x: x["context"]["rca_evidence_binding"].update(source_bytes=False),
        lambda x: x["context"]["rca_evidence_binding"].update(source_bytes=1),
        lambda x: x["context"]["rca_evidence_binding"].update(source_projection_hash="b" * 64),
        lambda x: x["context"]["rca_evidence_binding"].update(case_governance_hash="b" * 64),
        lambda x: x["context"]["rca_evidence_binding"]["event_grant"].update(grantee_id=1),
        lambda x: x["context"]["rca_evidence_binding"]["event_grant"].update(valid_until=TIME),
        lambda x: x["context"]["rca_evidence_source"]["event_state"].update(recorded_status=1),
        lambda x: x["context"]["rca_evidence_source"]["items"][0].update(text="另一份原文"),
    ],
)
def test_mixed_or_altered_source_input_evidence_and_purpose_never_pass(change):
    data = payload()
    change(data)
    with pytest.raises((ValueError, TypeError)):
        t.public_payload(data)


def test_associated_patient_requires_two_distinct_exact_actor_purposes():
    source = source_dict()
    source["event_state"]["patient_association"] = "recorded_patient"
    source = c.validate_source(source)
    event = binding().event_grant.model_copy(update={"patient_id_at_grant": 3})
    patient = event.model_copy(update={"grant_id": "00000000-0000-0000-0000-000000000007", "permission_kind": "associated_patient_processing"})
    bound = binding(source, patient_id=3, event_grant=event, patient_grant=patient)
    assert bound.patient_grant.grant_id != bound.event_grant.grant_id
    for changes in ({"patient_grant": None}, {"patient_grant": event}, {"event_grant": event.model_copy(update={"grantee_id": 5})}, {"patient_id": None}):
        with pytest.raises(ValueError):
            binding(source, **{"patient_id": 3, "event_grant": event, "patient_grant": patient, **changes})


@pytest.mark.parametrize("when", ["2026-10-21T11:59:59.123456Z", "2026-10-22T12:00:00.000000Z", "2026-10-21T12:00:00Z", "2026-02-30T12:00:00.000000Z"])
def test_task_publication_and_purpose_clocks_cannot_be_inferred_or_extended(when):
    with pytest.raises(ValueError):
        t.short_context(binding(), when)


def test_prompt_digest_and_canonical_prompt_hash_have_separate_exact_definitions():
    assert t.instructions_digest("System\r\n🙂", "Task\ufeff") != c.digest(["System\r\n🙂", "Task\ufeff"])
    assert t.instructions_digest("a", "b") != t.instructions_digest("a\n", "b")
    for a, b in ((False, "b"), ("a", None)):
        with pytest.raises(ValueError):
            t.instructions_digest(a, b)


def test_fixed_explanation_retains_literal_draft_and_never_promotes_a_model_claim():
    source = c.validate_source(source_dict())
    bad_semantics = draft().model_dump(mode="json")
    bad_semantics["hypotheses"][0]["hypothesis"] = "模型声称已确认原因；软件不能机械验证这句话的因果正确性。"
    result = r.result_for_draft(bad_semantics, source, PROMPT)
    assert result.rca_evidence_draft.coverage == c.COVERAGE
    assert "未核实" in result.summary and "不认证因果" in result.warnings[0]
    assert result.sections[0].source_ids == [source.source_id]
    assert result.rca_evidence_draft.hypotheses[0].supporting_quotes[0].quote == TEXT[:10]
    assert r.validate_result(result.model_dump(mode="json"), source, PROMPT) == result
    assert "approved" not in result.model_dump(mode="json")
    empty = c.parse_rca_reply('{"hypotheses":[],"clarification_questions":[]}', source, PROMPT)
    assert "0项" in r.result_for_draft(empty, source, PROMPT).summary


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(summary="已证实根因且调查完整"),
        lambda x: x.pop("warnings"),
        lambda x: x.update(actions=[]),
        lambda x: x["sections"][0].update(source_ids=[]),
        lambda x: x["sections"][1].update(source_ids=["fake_source"]),
        lambda x: x["rca_evidence_draft"].update(instructions_digest="b" * 64),
        lambda x: x["rca_evidence_draft"]["hypotheses"][0]["supporting_quotes"][0].update(start=False),
        lambda x: x["rca_evidence_draft"]["hypotheses"][0]["supporting_quotes"][0].update(quote="wrongquote"),
    ],
)
def test_result_is_exact_fixed_explanation_and_literal_draft_without_protocol_fallback(change):
    source = c.validate_source(source_dict())
    value = r.result_for_draft(draft(), source, PROMPT).model_dump(mode="json")
    change(value)
    with pytest.raises(ValueError):
        r.validate_result(value, source, PROMPT)


def test_whole_existing_text_limit_is_utf8_not_character_or_partial_prefix():
    with pytest.raises(ValueError, match="65535"):
        t.text_json({"raw": "🙂" * 16384})
    exact = {"raw": "x" * (65535 - len('{"raw":""}'))}
    assert len(t.text_json(exact).encode()) == 65535
    with pytest.raises(ValueError):
        t.RcaTaskSelection(rca_evidence_case_id=CASE, question="\ud800")


def test_whole_result_budget_includes_fixed_explanation_overhead(monkeypatch):
    source = c.validate_source(source_dict())
    item = draft().model_copy(update={"clarification_questions": ["x" * 1000] * 4})
    size = len(c.canonical(r.result_for_draft(item, source, PROMPT)).encode()) - 1
    assert max(len(c.canonical(item).encode()), len(c.canonical(source).encode())) < size
    monkeypatch.setattr(c, "MAX_WIRE_BYTES", size)
    with pytest.raises(ValueError, match="8MiB"):
        r.result_for_draft(item, source, PROMPT)


def test_task_types_and_result_do_not_import_hospital_settings_db_or_network():
    root = Path(__file__).resolve().parents[1]
    code = """
import builtins, socket, sys
sys.path.insert(0, sys.argv[1])
original=builtins.__import__
def guard(name,*args,**kw):
 if name in {'app.config','app.database','app.models','sqlalchemy','pydantic_settings'}: raise RuntimeError(name)
 return original(name,*args,**kw)
builtins.__import__=guard
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('network'))
import app.ai.rca_evidence_task_contract
import app.ai.rca_evidence_result
"""
    value = subprocess.run([sys.executable, "-I", "-c", code, str(root)], capture_output=True, text=True)
    assert value.returncode == 0, value.stderr
