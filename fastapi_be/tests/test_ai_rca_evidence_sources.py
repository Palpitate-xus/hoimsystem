"""Actual synthetic SQL authority/signatures; not MySQL locking or HTTP."""

import copy
import hashlib
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_sources as s
from app.ai.models import AIAuditEvent
from app.ai.rca_evidence_models import AIRcaEvidenceOriginal
from app.models import AdverseEventRca, Patient
from tests.test_ai_rca_evidence_grants import NOW, both, cas, no_source_text
from tests.test_ai_rca_evidence_grants import grant_case as grant_case

TEXT = "\ufeff独立人工记录😀\r\n时刻未知；原文时间2026-10-21T12:00:00.123456Z不改。"
NOTE = "人工逐字核实隐私、原意与原始来源；不代表临床因果确认。"


@pytest.fixture(autouse=True)
def isolate_actual_trigger(db_session):
    yield
    db_session.rollback()
    db_session.execute(text("DROP TRIGGER IF EXISTS rca_original_fault"))
    db_session.commit()


def body(case, **updates):
    return {
        "event_id": case["event_id"],
        "expected_event_patient_id": case["patient_id"],
        "origin_kind": "manual_evidence",
        "text": TEXT,
        "provenance": {"method": "human_authored_record", "provenance_note": NOTE},
        "timeline": [],
        **updates,
    }


def create(case, **updates):
    record = s.create_original(case["db"], case["actor"], body(case, **updates))
    case["db"].commit()
    return record


def review(case, record, **updates):
    request = {**cas(record), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "provenance_review": "confirmed", **updates}
    value = s.review_original(case["db"], case["actor"], record.immutable.original_id, request)
    case["db"].commit()
    return value


def count(db, model):
    return db.query(model).count()


def seed_rca(case):
    row = AdverseEventRca(
        event_id=case["event_id"],
        event_summary="人工旧记录",
        root_cause="旧字段并非认证原因",
        corrective_actions="无执行证明",
        timeline=None,
        pdca_cycle="A",
        analyst_id=case["actor"].user_id,
        create_time=NOW,
    )
    case["db"].add(row)
    case["db"].flush()
    identifier = row.rca_id
    case["db"].commit()
    return identifier


def derivative(case, kind="legacy_event", identifier=None):
    identifier = case["event_id"] if identifier is None else identifier
    witness = s.legacy_witness(case["db"], case["actor"], case["event_id"], kind, identifier)
    return {"method": "human_declared_derivative", "witness_kind": kind, "witness_id": identifier, "expected_raw_hash": witness["raw_hash"], "provenance_note": NOTE}


def test_actual_manual_full_utf8_and_three_signatures_are_bound_to_source_hash(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    before = count(db, AIAuditEvent)
    record = create(case)
    assert record.immutable.text == TEXT and record.immutable.raw_witness is None
    assert record.immutable.text_hash == hashlib.sha256(TEXT.encode()).hexdigest()
    assert not record.eligible and record.governance.status == "draft"
    assert record.immutable.recorded_at == "2026-10-21T12:00:00.123456Z"
    published = review(case, record)
    assert published.eligible and published.governance.reviewed_by == case["actor"].user_id
    assert published.governance.privacy_review == published.governance.faithfulness_review == published.governance.provenance_review == "confirmed"
    assert published.causal_verification == "not_provided"
    audit = db.get(AIAuditEvent, published.governance.reviewed_audit_event_id)
    assert published.content_hash in audit.detail_json and "2026-10-21T12:00:00.123456Z" in audit.detail_json
    assert audit.create_time == NOW.replace(microsecond=0)
    revoked = s.revoke_original(db, case["actor"], record.immutable.original_id, cas(published))
    db.commit()
    assert not revoked.eligible and revoked.immutable == record.immutable
    assert revoked.governance.revision == 3 and revoked.governance.reviewed_at == published.governance.reviewed_at
    assert count(db, AIAuditEvent) == before + 3


def test_missing_purpose_cannot_register_or_read_any_original_text(grant_case):
    case, db = grant_case, grant_case["db"]
    with pytest.raises(HTTPException) as error:
        no_source_text(db, lambda: s.create_original(db, case["actor"], body(case)))
    assert error.value.status_code == 403 and db.query(AIRcaEvidenceOriginal).filter_by(event_id=case["event_id"]).count() == 0
    both(case)
    record = create(case)
    from app.ai import rca_evidence_grants as g

    g.revoke_grant(db, case["actor"], record.immutable.event_grant_id, cas(g.grant_detail(db, case["actor"], record.immutable.event_grant_id)))
    db.commit()
    with pytest.raises(HTTPException) as error:
        no_source_text(db, lambda: s.original_detail(db, case["actor"], record.immutable.original_id))
    assert error.value.status_code == 403


@pytest.mark.parametrize("changed", [None, "new_patient"])
def test_new_current_association_grants_cannot_read_old_patients_private_original(grant_case, changed):
    case, db = grant_case, grant_case["db"]
    both(case)
    record = create(case)
    if changed is not None:
        patient = Patient(name="不同关联主体", identity="rca-original-" + uuid.uuid4().hex, permission="allow")
        db.add(patient)
        db.flush()
        changed = patient.patient_id
    db.execute(text("UPDATE hoimsystem_adverse_event SET patient_id=:patient WHERE event_id=:id"), {"patient": changed, "id": case["event_id"]})
    db.commit()
    case["patient_id"] = changed
    if changed is None:
        from tests.test_ai_rca_evidence_grants import issue

        issue(case)
    else:
        both(case)
    with pytest.raises(HTTPException) as error:
        no_source_text(db, lambda: s.original_detail(db, case["actor"], record.immutable.original_id))
    assert error.value.status_code == 403


@pytest.mark.parametrize("review_name", ["privacy_review", "faithfulness_review", "provenance_review"])
def test_each_explicit_signature_required_and_stale_cas_does_not_append_audit(grant_case, review_name):
    case, db = grant_case, grant_case["db"]
    both(case)
    record = create(case)
    before = count(db, AIAuditEvent)
    with pytest.raises(HTTPException) as error:
        review(case, record, **{review_name: "unknown"})
    assert error.value.status_code == 422 and count(db, AIAuditEvent) == before
    published = review(case, record)
    with pytest.raises(HTTPException) as error:
        review(case, record)
    assert error.value.status_code == 409 and count(db, AIAuditEvent) == before + 1
    assert s.original_detail(db, case["actor"], record.immutable.original_id).governance_hash == published.governance_hash


@pytest.mark.parametrize("kind", ["legacy_event", "legacy_rca"])
def test_derivative_retains_complete_actual_raw_witness_and_naive_clocks(grant_case, kind):
    case, db = grant_case, grant_case["db"]
    both(case)
    identifier = seed_rca(case) if kind == "legacy_rca" else case["event_id"]
    provenance = derivative(case, kind, identifier)
    record = create(case, origin_kind=kind, provenance=provenance)
    raw = record.immutable.raw_witness
    assert c.digest(raw) == provenance["expected_raw_hash"]
    if kind == "legacy_rca":
        assert raw.root_cause == "旧字段并非认证原因" and raw.pdca_cycle == "A"
        assert raw.create_time.text == NOW.isoformat() and raw.create_time.basis == "stored_naive_no_timezone"
    else:
        assert raw.description == "尚未授权时不可读取的合成事件正文" and raw.severity == 0
    published = review(case, record)
    assert published.eligible and published.causal_verification == "not_provided"
    table, key, field = ("hoimsystem_adverse_event_rca", "rca_id", "root_cause") if kind == "legacy_rca" else ("hoimsystem_adverse_event", "event_id", "description")
    db.execute(text(f"UPDATE {table} SET {field}='新且矛盾的原始记录' WHERE {key}=:id"), {"id": identifier})
    db.commit()
    stale = s.original_detail(db, case["actor"], record.immutable.original_id)
    assert not stale.current_raw_witness_matches and not stale.eligible
    assert stale.immutable == record.immutable and stale.governance.status == "published"


def test_stale_derivative_source_cannot_be_newly_signed(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    record = create(case, origin_kind="legacy_event", provenance=derivative(case))
    db.execute(text("UPDATE hoimsystem_adverse_event SET status=2 WHERE event_id=:id"), {"id": case["event_id"]})
    db.commit()
    before = count(db, AIAuditEvent)
    with pytest.raises(HTTPException) as error:
        review(case, record)
    assert error.value.status_code == 409 and count(db, AIAuditEvent) == before


def test_manual_timeline_unknown_and_exact_time_are_own_literal_declarations(grant_case):
    case = grant_case
    both(case)
    statement = "独立人工记录😀"
    start = TEXT.index(statement)
    entries = [
        {
            "entry_id": str(uuid.uuid4()),
            "statement": statement,
            "occurred_time": {"status": "unknown", "basis_hash": c.digest(NOTE)},
            "evidence": [{"start": start, "end": start + len(statement), "quote": statement}],
            "assertion_status": "human_recorded_statement_not_causal_verification",
        }
    ]
    record = create(case, origin_kind="human_timeline", timeline=entries)
    assert record.immutable.timeline[0].model_dump(mode="json") == entries[0]
    assert review(case, record).causal_verification == "not_provided"
    for updated in ({"start": start + 1}, {"end": True}, {"quote": statement.replace("😀", "?")}):
        bad = copy.deepcopy(entries)
        bad[0]["evidence"][0].update(updated)
        with pytest.raises(HTTPException) as error:
            create(case, origin_kind="human_timeline", timeline=bad)
        assert error.value.status_code == 422


@pytest.mark.parametrize("mutation", ["original", "signature", "audit"])
def test_self_rehashed_original_or_governance_does_not_replace_exact_independent_audit(grant_case, mutation):
    case, db = grant_case, grant_case["db"]
    both(case)
    record = review(case, create(case))
    row = db.get(AIRcaEvidenceOriginal, record.immutable.original_id)
    if mutation == "original":
        value = record.immutable.model_dump(mode="json")
        value["text"] += "伪改"
        value["text_hash"] = hashlib.sha256(value["text"].encode()).hexdigest()
        row.original_json = c.canonical(value)
        row.json_bytes, row.content_hash = len(row.original_json.encode()), c.digest(value)
    elif mutation == "signature":
        row.review_basis_note += "伪改"
    else:
        db.get(AIAuditEvent, row.reviewed_audit_event_id).detail_json = "{}"
    db.commit()
    with pytest.raises(HTTPException) as error:
        s.original_detail(db, case["actor"], record.immutable.original_id)
    assert error.value.status_code == 409


@pytest.mark.parametrize("fault", ["audit", "patient", "role", "grant"])
def test_real_after_insert_fault_rolls_back_whole_original_and_exact_audit(grant_case, fault):
    case, db = grant_case, grant_case["db"]
    grants = both(case)
    sql = {
        "audit": "UPDATE hoimsystem_ai_audit_event SET target='changed' WHERE event_id=NEW.created_audit_event_id;",
        "patient": f"UPDATE hoimsystem_adverse_event SET patient_id=NULL WHERE event_id={case['event_id']};",
        "role": f"UPDATE hoimsystem_users SET user_role='doctor' WHERE user_id={case['actor'].user_id};",
        "grant": f"UPDATE hoimsystem_ai_rca_purpose_grant SET valid_until='2026-10-21 11:00:00.000000' WHERE grant_id='{grants[0].identity.grant_id}';",
    }[fault]
    db.execute(text("CREATE TRIGGER rca_original_fault AFTER INSERT ON hoimsystem_ai_rca_evidence_original BEGIN " + sql + " END"))
    db.commit()
    before = count(db, AIAuditEvent)
    with pytest.raises(HTTPException) as error:
        s.create_original(db, case["actor"], body(case))
    assert error.value.status_code in {403, 409}
    assert db.query(AIRcaEvidenceOriginal).filter_by(event_id=case["event_id"]).count() == 0 and count(db, AIAuditEvent) == before
    # Trigger side effects are part of the rolled-back transaction too.
    from app.ai import rca_evidence_grants as g

    assert g.authorize_event(db, case["actor"], case["event_id"])


def test_known_rejection_and_draft_revocation_do_not_publish(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    rejected = review(case, create(case), decision="reject", privacy_review="not_confirmed")
    assert not rejected.eligible and rejected.governance.status == "rejected"
    draft = create(case)
    revoked = s.revoke_original(db, case["actor"], draft.immutable.original_id, cas(draft))
    db.commit()
    assert revoked.governance.revision == 2 and revoked.governance.reviewed_by is None and not revoked.eligible


def test_multibyte_source_boundary_is_utf8_and_all_or_refuse(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    record = create(case, text="😀" * (c.MAX_ORIGINAL_BYTES // 4))
    assert len(record.immutable.text.encode()) == c.MAX_ORIGINAL_BYTES
    before = count(db, AIAuditEvent)
    for value in ("😀" * (c.MAX_ORIGINAL_BYTES // 4) + "a", "\ud800"):
        with pytest.raises(HTTPException) as error:
            create(case, text=value)
        assert error.value.status_code == 422
    assert count(db, AIAuditEvent) == before


def test_entire_stored_json_is_preflighted_before_loading_body(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    record = create(case)
    db.execute(text("UPDATE hoimsystem_ai_rca_evidence_original SET json_bytes=1 WHERE original_id=:id"), {"id": record.immutable.original_id})
    db.commit()
    with pytest.raises(HTTPException) as error:
        no_source_text(db, lambda: s.original_detail(db, case["actor"], record.immutable.original_id))
    assert error.value.status_code == 413


@pytest.mark.parametrize("stage", ["create", "review"])
def test_derivative_legacy_witness_postflush_change_is_atomic_rejection(grant_case, stage):
    case, db = grant_case, grant_case["db"]
    both(case)
    provenance = derivative(case)
    draft = create(case, origin_kind="legacy_event", provenance=provenance) if stage == "review" else None
    event_sql = "INSERT" if stage == "create" else "UPDATE"
    db.execute(
        text(
            f"CREATE TRIGGER rca_original_fault AFTER {event_sql} ON hoimsystem_ai_rca_evidence_original BEGIN UPDATE hoimsystem_adverse_event SET description='flush期间实际原件变更' WHERE event_id=NEW.event_id; END"
        )
    )
    db.commit()
    before = count(db, AIAuditEvent)
    with pytest.raises(HTTPException) as error:
        if stage == "create":
            create(case, origin_kind="legacy_event", provenance=provenance)
        else:
            review(case, draft)
    assert error.value.status_code == 409 and count(db, AIAuditEvent) == before
    if draft is not None:
        current = s.original_detail(db, case["actor"], draft.immutable.original_id)
        assert current.governance.status == "draft" and current.current_raw_witness_matches
