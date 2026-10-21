"""Actual whole blob/pointer/accept/usage SQL, not HTTP or configured runtime."""

import copy
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text

from app.ai import rca_evidence_cases as cases
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_receipts as receipts
from app.ai import rca_evidence_result as results
from app.ai import rca_evidence_result_storage as storage
from app.ai import rca_evidence_storage as tasks
from app.ai.models import AIAuditEvent, AIRun
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact, AIRcaEvidenceRunResult
from tests import test_ai_rca_evidence_sources as source_helpers
from tests.test_ai_rca_evidence_grants import NOW, cas
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_receipts import dispatched, usage
from tests.test_ai_rca_evidence_storage import denied, task_counts


@pytest.fixture(autouse=True)
def clean_result_trigger(db_session):
    yield
    db_session.rollback()
    db_session.execute(text("DROP TRIGGER IF EXISTS rca_result_fault"))
    db_session.commit()


def candidate(case, proof, *, many=1):
    stored = tasks.load_task(case["db"], case["actor"], proof.run_id)
    item = stored.source.items[0]
    quote = {"item_id": item.item_id, "start": 0, "end": len(item.text), "quote": item.text}
    raw = {
        "hypotheses": [
            {
                "hypothesis": "责任已经确认（模型的这个声称仍是未核实草稿）" if many == 1 else "x" * 4000,
                "supporting_quotes": [quote],
                "conflicting_quotes": [],
                "timeline_entry_ids": [],
                "evidence_needed": ["必须独立调查；引文逐字一致不证明因果"],
                "investigation_questions": [],
            }
            for _ in range(many)
        ],
        "clarification_questions": [],
    }
    draft = c.parse_rca_reply(c.canonical(raw), stored.source, stored.artifact.instructions_digest)
    return results.result_for_draft(draft, stored.source, stored.artifact.instructions_digest)


def accept(case, proof, value=None, **changes):
    dispatch_id = case["db"].query(AIRcaEvidenceRunArtifact.dispatch_event_id).filter_by(run_id=proof.run_id).scalar()
    return storage.stage_result(case["db"], case["actor"], proof, value or candidate(case, proof), **{"dispatch_event_id": dispatch_id, "usage": usage(), "latency_ms": 35, **changes})


def test_actual_large_result_is_split_with_five_different_audit_pks_and_exact_utc6_readback(grant_case):
    case, db = grant_case, grant_case["db"]
    proof, original = dispatched(case)
    value = candidate(case, proof, many=20)
    assert 65535 < len(c.canonical(value).encode()) < c.MAX_WIRE_BYTES
    accepted = accept(case, proof, value)
    db.commit()
    artifact = db.get(AIRcaEvidenceRunArtifact, proof.run_id)
    result = db.get(AIRcaEvidenceRunResult, proof.run_id)
    run = db.get(AIRun, proof.run_id)
    assert len({artifact.create_event_id, artifact.claim_event_id, artifact.dispatch_event_id, artifact.usage_event_id, result.accept_audit_event_id}) == 5
    assert result.accepted_at == NOW and run.finish_time == NOW.replace(microsecond=0)
    assert result.result_bytes == len(result.result_json.encode()) and result.result_hash == tasks.text_hash(result.result_json, c.MAX_WIRE_BYTES)
    assert len(run.result_json.encode()) < 65535 and json.loads(run.result_json)["accept_audit_event_id"] == result.accept_audit_event_id
    assert "rca_evidence_draft" not in run.result_json and storage.read_result(db, case["actor"], proof.run_id) == accepted
    assert storage.result_piece(db, case["actor"], proof.run_id)["data"] == value.model_dump(mode="json")
    receipt = receipts.read_receipt(db, receipts.technical_attempt(db, proof))
    assert receipt.result_hash == result.result_hash and receipt.usage.model_dump(mode="json") == usage()
    assert db.get(AIAuditEvent, result.accept_audit_event_id).action == "rca_run.accept"
    assert db.get(AIAuditEvent, artifact.usage_event_id).action == "rca_run.usage"
    assert tasks.case_piece(db, case["actor"], proof.run_id)["data"]["immutable"]["case_id"] == original.binding.case_id
    before = task_counts(db)
    with pytest.raises(HTTPException) as failure:
        accept(case, proof, value)
    assert failure.value.status_code == 409 and task_counts(db) == before


def test_false_semantic_claim_remains_nested_unreviewed_and_exact_bom_emoji_crlf_quote_is_preserved(grant_case):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    accepted = accept(case, proof)
    db.commit()
    hypothesis = accepted.rca_evidence_draft.hypotheses[0]
    assert hypothesis.supporting_quotes[0].quote == source_helpers.TEXT
    assert "\ufeff" in hypothesis.supporting_quotes[0].quote and "😀\r\n" in hypothesis.supporting_quotes[0].quote
    assert "责任已经确认" in hypothesis.hypothesis and "未核实" in accepted.summary
    assert "责任已经确认" not in accepted.summary and "责任已经确认" not in "".join(section.content for section in accepted.sections)
    assert accepted.rca_evidence_draft.coverage == c.COVERAGE


def test_same_claim_with_another_dispatch_pk_cannot_accept_its_returned_content(grant_case):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    value = candidate(case, proof)
    before = task_counts(db)
    assert accept(case, proof, value, dispatch_event_id=2147483647) is None
    assert task_counts(db) == before and db.query(AIRun.status).filter_by(run_id=proof.run_id).scalar() == "running"


@pytest.mark.parametrize("fault", ["fixed_summary", "quote", "source_hash", "instructions", "foreign_result", "usage_missing", "usage_false"])
def test_full_result_binding_fixed_explanation_literal_quotes_and_actual_usage_are_required(grant_case, fault):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    value = candidate(case, proof).model_dump(mode="json")
    extra = {}
    if fault == "fixed_summary":
        value["summary"] = "模型判断已完成根因确认"
    elif fault == "quote":
        value["rca_evidence_draft"]["hypotheses"][0]["supporting_quotes"][0]["quote"] = "不在原文"
    elif fault == "source_hash":
        value["rca_evidence_draft"]["source_projection_hash"] = "f" * 64
    elif fault == "instructions":
        value["rca_evidence_draft"]["instructions_digest"] = "f" * 64
    elif fault == "foreign_result":
        value["document_extraction"] = {}
    elif fault == "usage_missing":
        extra["usage"] = usage(11, None)
    else:
        extra["usage"] = usage(0, 0, False)
    before = task_counts(db)
    with pytest.raises(HTTPException) as failure:
        accept(case, proof, value, **extra)
    assert failure.value.status_code == 409 and task_counts(db) == before
    assert db.query(AIRun.status).filter_by(run_id=proof.run_id).scalar() == "running"


@pytest.mark.parametrize("fault", ["pointer_whitespace", "pointer_duplicate", "blob_hash", "blob_self_rehash", "accept_pk", "usage_pk", "accepted_clock"])
def test_stored_pointer_blob_clock_and_specific_accept_receipt_are_revalidated_not_merely_echoed(grant_case, fault):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    accepted = accept(case, proof)
    db.commit()
    row = db.get(AIRcaEvidenceRunResult, proof.run_id)
    if fault in {"pointer_whitespace", "pointer_duplicate"}:
        raw = db.query(AIRun.result_json).filter_by(run_id=proof.run_id).scalar()
        raw = " " + raw if fault == "pointer_whitespace" else raw[:-1] + ',"schema_version":"rca_evidence_result_ref_v1"}'
        db.execute(text("UPDATE hoimsystem_ai_run SET result_json=:raw WHERE run_id=:id"), {"raw": raw, "id": proof.run_id})
    elif fault in {"blob_hash", "blob_self_rehash"}:
        value = accepted.model_dump(mode="json")
        value["summary"] = "擅自改为已确认根因"
        raw = c.canonical(value)
        row.result_json, row.result_bytes = raw, len(raw.encode())
        if fault == "blob_self_rehash":
            row.result_hash = tasks.text_hash(raw, c.MAX_WIRE_BYTES)
    elif fault in {"accept_pk", "usage_pk"}:
        wrong = db.query(AIAuditEvent.event_id).filter_by(action="rca_grant.create").first()[0]
        if fault == "accept_pk":
            row.accept_audit_event_id = wrong
        else:
            db.execute(text("UPDATE hoimsystem_ai_rca_evidence_run_artifact SET usage_event_id=:wrong WHERE run_id=:id"), {"wrong": wrong, "id": proof.run_id})
    else:
        db.execute(text("UPDATE hoimsystem_ai_rca_evidence_run_result SET accepted_at='2026-10-21 12:00:00.123455' WHERE run_id=:id"), {"id": proof.run_id})
    db.commit()
    with pytest.raises(HTTPException) as failure:
        storage.read_result(db, case["actor"], proof.run_id)
    assert failure.value.status_code == 409


@pytest.mark.parametrize("fault", ["accept_reject", "usage_reject", "accept_tamper", "blob", "pointer", "actor", "new_member", "lease", "run_counter"])
def test_actual_acceptance_sql_fault_rolls_back_full_blob_pointer_two_audits_and_success_together(grant_case, fault):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    value = candidate(case, proof)
    if fault in {"accept_reject", "usage_reject"}:
        action = "accept" if fault == "accept_reject" else "usage"
        sql = f"CREATE TRIGGER rca_result_fault BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_run.{action}' BEGIN SELECT RAISE(ABORT,'synthetic exact audit reject'); END"
    elif fault == "accept_tamper":
        sql = "CREATE TRIGGER rca_result_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_run.accept' BEGIN UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id; END"
    else:
        if fault == "blob":
            action = "UPDATE hoimsystem_ai_rca_evidence_run_result SET result_json='{}',result_bytes=2 WHERE run_id=NEW.run_id;"
        elif fault == "pointer":
            action = "UPDATE hoimsystem_ai_run SET result_json='{}' WHERE run_id=NEW.run_id;"
        elif fault == "actor":
            action = f"UPDATE hoimsystem_users SET user_role='admin' WHERE user_id={inspect(case['actor']).identity[0]};"
        elif fault == "new_member":
            action = f"INSERT INTO hoimsystem_adverse_event_rca(event_id,event_summary,root_cause,corrective_actions,pdca_cycle,create_time) VALUES ({case['event_id']},'actual member','not verified','none','P','2026-10-21 12:00:00.123456');"
        elif fault == "lease":
            action = "UPDATE hoimsystem_ai_run SET lease_token='00000000-0000-0000-0000-000000000099' WHERE run_id=NEW.run_id;"
        else:
            action = "UPDATE hoimsystem_ai_run SET input_tokens=999 WHERE run_id=NEW.run_id;"
        sql = "CREATE TRIGGER rca_result_fault AFTER INSERT ON hoimsystem_ai_rca_evidence_run_result BEGIN " + action + " END"
    before = task_counts(db)
    db.execute(text(sql))
    db.commit()
    with pytest.raises(HTTPException) as failure:
        accept(case, proof, value)
    assert failure.value.status_code in {403, 409} and task_counts(db) == before
    if fault == "new_member":
        assert "仅当前全集仍匹配" in failure.value.detail
    assert db.query(AIRun.status, AIRun.result_json).filter_by(run_id=proof.run_id).one() == ("running", "{}")
    assert db.query(AIRcaEvidenceRunArtifact.usage_event_id).filter_by(run_id=proof.run_id).scalar() is None


def test_source_revoked_result_is_hidden_while_explicit_current_purpose_frozen_audit_recalculates_original(grant_case):
    case, db = grant_case, grant_case["db"]
    proof, value = dispatched(case)
    expected = accept(case, proof)
    db.commit()
    cases.revoke_case(db, case["actor"], value.binding.case_id, cas(value.record))
    db.commit()
    denied(db, lambda: storage.read_result(db, case["actor"], proof.run_id), 409)
    assert storage.read_result(db, case["actor"], proof.run_id, frozen_audit=True) == expected
    record = grants.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
    grants.revoke_grant(db, case["actor"], record.identity.grant_id, cas(record))
    db.commit()
    denied(db, lambda: storage.read_result(db, case["actor"], proof.run_id, frozen_audit=True), 403)


def test_actual_complete_result_wire_overhead_is_rejected_before_acceptance_not_truncated(grant_case, monkeypatch):
    monkeypatch.setattr(source_helpers, "TEXT", "q" * 65535)
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    stored = tasks.load_task(db, case["actor"], proof.run_id)
    base = candidate(case, proof).rca_evidence_draft.hypotheses[0].model_dump(mode="json")
    base["supporting_quotes"] = [copy.deepcopy(base["supporting_quotes"][0]) for _ in range(16)]
    raw = {"hypotheses": [copy.deepcopy(base) for _ in range(8)], "clarification_questions": []}
    last = raw["hypotheses"][-1]["supporting_quotes"][-1]
    last["end"], last["quote"] = 1, "q"
    for _ in range(4):
        draft = c.parse_rca_reply(c.canonical(raw), stored.source, stored.artifact.instructions_digest)
        result = results.result_for_draft(draft, stored.source, stored.artifact.instructions_digest)
        delta = c.MAX_WIRE_BYTES - 10 - len(c.canonical(result).encode())
        if delta == 0:
            break
        last["end"] += delta
        assert 1 <= last["end"] <= 65535
        last["quote"] = "q" * last["end"]
    assert len(c.canonical(result).encode()) == c.MAX_WIRE_BYTES - 10
    before = task_counts(db)
    with pytest.raises(HTTPException) as failure:
        accept(case, proof, result)
    assert failure.value.status_code == 409 and task_counts(db) == before
