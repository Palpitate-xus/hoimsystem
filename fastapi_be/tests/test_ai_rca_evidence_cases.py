"""Current finite all-root RCA Cases; synthetic SQLite, not MySQL waits."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.ai import rca_evidence_cases as k
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as g
from app.ai import rca_evidence_sources as s
from app.ai.models import AIAuditEvent
from app.ai.rca_evidence_models import AIRcaEvidenceCase
from app.models import Patient
from tests.test_ai_rca_evidence_grants import both, cas, issue, no_source_text
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_sources import NOTE, TEXT, create, derivative, review, seed_rca


@pytest.fixture(autouse=True)
def isolate_trigger(db_session):
    yield
    db_session.rollback()
    db_session.execute(text("DROP TRIGGER IF EXISTS rca_case_fault"))
    db_session.commit()


def capture(case):
    return k.capture_event(case["db"], case["actor"], case["event_id"])


def create_case(case, **updates):
    current = capture(case)
    record = k.create_case(
        case["db"], case["actor"], {"event_id": case["event_id"], "expected_event_patient_id": case["patient_id"], "expected_collection_hash": current.collection_hash, "basis_note": NOTE, **updates}
    )
    case["db"].commit()
    return record


def publish(case, record, **updates):
    value = k.review_case(
        case["db"],
        case["actor"],
        record.immutable.case_id,
        {**cas(record), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "provenance_review": "confirmed", **updates},
    )
    case["db"].commit()
    return value


def test_actual_all_roots_no_latest_winner_and_only_three_reviewed_derivatives_released(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    rca_ids = [seed_rca(case) for _ in range(8)]  # Former generic source clips at6.
    published = review(case, create(case))
    draft = create(case, text="未审核内容不能外发 private_draft_sentinel")
    rejected = review(case, create(case, text="已拒绝 private_rejected_sentinel"), decision="reject", privacy_review="not_confirmed")
    revoked = review(case, create(case, text="已撤销 private_revoked_sentinel"))
    s.revoke_original(db, case["actor"], revoked.immutable.original_id, cas(revoked))
    db.commit()
    raw_derivative = review(case, create(case, origin_kind="legacy_rca", provenance=derivative(case, "legacy_rca", rca_ids[0]), text="经明确审核的旧记录人工衍生；并未确认原因。"))
    current = capture(case)
    assert [row.rca_id for row in current.rcas] == rca_ids and len(current.originals) == 5
    assert {member.record.governance.status for member in current.originals} == {"draft", "published", "rejected", "revoked"}
    record = publish(case, create_case(case))
    source = k.public_source(db, case["actor"], record.immutable.case_id)
    assert c.validate_source(source) == source and len(source.members) == 1 + 8 + 5
    assert sum(member.kind == "legacy_event" for member in source.members) == 1
    assert {item.text for item in source.items} == {published.immutable.text, raw_derivative.immutable.text}
    wire = c.canonical(k.wire(source))
    for sentinel in (
        "private_draft_sentinel",
        "private_rejected_sentinel",
        "private_revoked_sentinel",
        "旧字段并非认证原因",
        "root_cause",
        "identity_secret",
        "patient_id",
        "created_by",
        "basis_note",
    ):
        assert sentinel not in wire
    assert source.event_state.recorded_severity == 0 and source.event_state.causal_approval == "not_provided"
    assert len({m.member_id for m in source.members}) == len(source.members)
    assert all(item.item_id not in {published.immutable.original_id, raw_derivative.immutable.original_id, draft.immutable.original_id, rejected.immutable.original_id} for item in source.items)
    # Neither frozen grant contents nor the task-free Source changes legacy stock/workflow.
    assert record.immutable.capture.event.status == 0


@pytest.mark.parametrize("change", ["new_rca", "new_draft", "publish_draft", "revoke_published", "legacy_status", "legacy_rca"])
def test_any_same_event_dependency_change_invalidates_whole_case_not_just_selected_winner(grant_case, change):
    case, db = grant_case, grant_case["db"]
    both(case)
    rca_id = seed_rca(case)
    draft = create(case)
    original = review(case, create(case))
    record = publish(case, create_case(case))
    if change == "new_rca":
        seed_rca(case)
    elif change == "new_draft":
        create(case)
    elif change == "publish_draft":
        review(case, draft)
    elif change == "revoke_published":
        s.revoke_original(db, case["actor"], original.immutable.original_id, cas(original))
        db.commit()
    elif change == "legacy_status":
        db.execute(text("UPDATE hoimsystem_adverse_event SET status=2 WHERE event_id=:id"), {"id": case["event_id"]})
        db.commit()
    else:
        db.execute(text("UPDATE hoimsystem_adverse_event_rca SET root_cause='新的矛盾陈述' WHERE rca_id=:id"), {"id": rca_id})
        db.commit()
    changed = k.case_detail(db, case["actor"], record.immutable.case_id)
    assert not changed.eligible and not changed.current_collection_matches and changed.immutable == record.immutable
    with pytest.raises(HTTPException) as error:
        k.public_source(db, case["actor"], record.immutable.case_id)
    assert error.value.status_code == 409


def test_stale_capture_cas_and_new_member_before_case_publication_are_rejected(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    old = capture(case)
    create(case)
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as error:
        create_case(case, expected_collection_hash=old.collection_hash)
    assert error.value.status_code == 409 and db.query(AIAuditEvent).count() == before
    record = create_case(case)
    seed_rca(case)
    with pytest.raises(HTTPException) as error:
        publish(case, record)
    assert error.value.status_code == 409


def test_same_event_old_patient_original_has_only_opaque_root_and_never_its_private_text_or_notes(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    old = review(case, create(case, text="old_patient_text_sentinel"))
    old_case = publish(case, create_case(case))
    new_patient = Patient(name="新的范围", identity="rca-new-case-" + uuid.uuid4().hex, permission="allow")
    db.add(new_patient)
    db.flush()
    new_id = new_patient.patient_id
    db.execute(text("UPDATE hoimsystem_adverse_event SET patient_id=:patient WHERE event_id=:id"), {"patient": new_id, "id": case["event_id"]})
    db.commit()
    case["patient_id"] = new_id
    both(case)
    with pytest.raises(HTTPException) as error:
        no_source_text(db, lambda: k.case_detail(db, case["actor"], old_case.immutable.case_id))
    assert error.value.status_code == 403
    # Observe only Original TEXT: actual current Event/RCA access is separately authorized.
    from sqlalchemy import Select, event

    columns = []

    def observe(state):
        if state.is_select and isinstance(state.statement, Select):
            columns.extend(column.key for column in state.statement.selected_columns if getattr(getattr(column, "table", None), "name", None) == "hoimsystem_ai_rca_evidence_original")

    event.listen(db, "do_orm_execute", observe)
    try:
        current = capture(case)
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert "original_json" not in columns and "review_basis_note" not in columns and "revoke_reason" not in columns
    member = current.originals[0]
    assert member.original_id == old.immutable.original_id and member.visibility == "association_changed_not_disclosed"
    assert "old_patient_text_sentinel" not in c.canonical(current)
    record = publish(case, create_case(case))
    source = k.project_source(record)
    assert len(source.items) == 0 and len(source.members) == 2


def test_patientless_case_requires_only_actual_event_grant_without_fictional_patient(grant_case):
    case, db = grant_case, grant_case["db"]
    db.execute(text("UPDATE hoimsystem_adverse_event SET patient_id=NULL WHERE event_id=:id"), {"id": case["event_id"]})
    db.commit()
    case["patient_id"] = None
    issue(case)
    record = publish(case, create_case(case))
    assert record.immutable.patient_grant is None
    assert k.project_source(record).event_state.patient_association == "not_recorded"


def test_registered_timeline_unchanged_cp_and_human_occurrence_not_inferred_from_legacy_clock(grant_case):
    case = grant_case
    both(case)
    statement = "独立人工记录😀"
    start = TEXT.index(statement)
    entries = [
        {
            "entry_id": str(uuid.uuid4()),
            "statement": statement,
            "occurred_time": {"status": "human_declared_exact", "at": "2026-10-20T01:02:03.000001Z", "basis_hash": c.digest(NOTE)},
            "evidence": [{"start": start, "end": start + len(statement), "quote": statement}],
            "assertion_status": "human_recorded_statement_not_causal_verification",
        }
    ]
    original = review(case, create(case, origin_kind="human_timeline", timeline=entries))
    first = k.project_source(publish(case, create_case(case)))
    second = k.project_source(publish(case, create_case(case)))
    assert first.timeline[0].occurred_time.at == entries[0]["occurred_time"]["at"]
    assert first.timeline[0].occurred_time.basis_hash != entries[0]["occurred_time"]["basis_hash"]
    assert first.timeline[0].evidence[0].quote == statement and first.items[0].text == TEXT
    assert first.timeline[0].recorded_at == original.immutable.recorded_at
    assert first.items[0].item_id != second.items[0].item_id and first.timeline[0].occurred_time.basis_hash != second.timeline[0].occurred_time.basis_hash
    assert first.event_state.causal_approval == "not_provided"


def test_case_revoke_exact_cas_retains_original_signatures_and_blocks_source(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    original = create_case(case)
    record = publish(case, original)
    before = db.query(AIAuditEvent).count()
    revoked = k.revoke_case(db, case["actor"], record.immutable.case_id, cas(record))
    db.commit()
    assert not revoked.eligible and revoked.governance.revision == 3 and revoked.immutable == original.immutable
    assert revoked.governance.reviewed_audit_event_id == record.governance.reviewed_audit_event_id
    assert db.query(AIAuditEvent).count() == before + 1
    with pytest.raises(HTTPException) as error:
        k.revoke_case(db, case["actor"], record.immutable.case_id, cas(record))
    assert error.value.status_code == 409 and db.query(AIAuditEvent).count() == before + 1


@pytest.mark.parametrize("fault", ["audit", "member", "source", "role"])
def test_actual_case_insert_side_effect_rolls_back_whole_case_and_exact_audit(grant_case, fault):
    case, db = grant_case, grant_case["db"]
    both(case)
    original = create(case)
    statements = {
        "audit": "UPDATE hoimsystem_ai_audit_event SET target='changed' WHERE event_id=NEW.created_audit_event_id;",
        "member": "UPDATE hoimsystem_ai_rca_evidence_original SET status='revoked',revision=2,revoked_by=NEW.created_by,revoked_at=NEW.recorded_at,revoke_reason='invalid',revoked_audit_event_id=NEW.created_audit_event_id WHERE original_id='"
        + original.immutable.original_id
        + "';",
        "source": "UPDATE hoimsystem_adverse_event SET status=2 WHERE event_id=NEW.event_id;",
        "role": "UPDATE hoimsystem_users SET user_role='doctor' WHERE user_id=NEW.created_by;",
    }
    db.execute(text("CREATE TRIGGER rca_case_fault AFTER INSERT ON hoimsystem_ai_rca_evidence_case BEGIN " + statements[fault] + " END"))
    db.commit()
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as error:
        create_case(case)
    assert error.value.status_code in {403, 409}
    assert db.query(AIRcaEvidenceCase).filter_by(event_id=case["event_id"]).count() == 0
    assert db.query(AIAuditEvent).count() == before
    assert s.original_detail(db, case["actor"], original.immutable.original_id).governance.status == "draft"


@pytest.mark.parametrize("field", ["body", "governance", "audit"])
def test_self_rehashed_case_or_review_still_requires_independent_exact_audit(grant_case, field):
    case, db = grant_case, grant_case["db"]
    both(case)
    record = publish(case, create_case(case))
    row = db.get(AIRcaEvidenceCase, record.immutable.case_id)
    if field == "body":
        snapshot = record.immutable.model_dump(mode="json")
        snapshot["basis_note"] += "tampered"
        row.case_json = c.canonical(snapshot)
        row.json_bytes = len(row.case_json.encode())
        row.content_hash = c.digest(snapshot)
    elif field == "governance":
        row.review_basis_note += "tampered"
    else:
        db.get(AIAuditEvent, row.created_audit_event_id).detail_json = "{}"
    db.commit()
    with pytest.raises(HTTPException) as error:
        k.case_detail(db, case["actor"], record.immutable.case_id)
    assert error.value.status_code == 409


def test_purpose_revoked_no_case_body_and_current_super_alone_never_restores_it(grant_case):
    case, db = grant_case, grant_case["db"]
    grants = both(case)
    record = publish(case, create_case(case))
    g.revoke_grant(db, case["actor"], grants[1].identity.grant_id, cas(grants[1]))
    db.commit()
    with pytest.raises(HTTPException) as error:
        no_source_text(db, lambda: k.case_detail(db, case["actor"], record.immutable.case_id))
    assert error.value.status_code == 403


def test_stored_case_byte_mismatch_rejects_before_case_json(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    record = create_case(case)
    db.execute(text("UPDATE hoimsystem_ai_rca_evidence_case SET json_bytes=1 WHERE case_id=:id"), {"id": record.immutable.case_id})
    db.commit()
    with pytest.raises(HTTPException) as error:
        no_source_text(db, lambda: k.case_detail(db, case["actor"], record.immutable.case_id))
    assert error.value.status_code == 413


def test_actual_over4096_combined_roots_rejects_without_loading_legacy_rca_text(grant_case):
    from sqlalchemy import Select, event, insert

    from app.models import AdverseEventRca

    case, db = grant_case, grant_case["db"]
    both(case)
    db.execute(
        insert(AdverseEventRca),
        [
            {"event_id": case["event_id"], "event_summary": "actual root", "root_cause": "未核实", "corrective_actions": "无完成证明", "create_time": __import__("datetime").datetime(2026, 10, 21)}
            for _ in range(c.MAX_MEMBERS)
        ],
    )
    db.commit()
    selected = []

    def observe(state):
        if state.is_select and isinstance(state.statement, Select):
            selected.extend(col.key for col in state.statement.selected_columns)

    event.listen(db, "do_orm_execute", observe)
    try:
        with pytest.raises(HTTPException) as error:
            capture(case)
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert error.value.status_code == 413 and "root_cause" not in selected
    assert db.query(AIRcaEvidenceCase).filter_by(event_id=case["event_id"]).count() == 0


def test_full_original_size_does_not_guarantee_combined_case_fits_and_no_text_load_before_reject(grant_case):
    from sqlalchemy import Select, event

    case, db = grant_case, grant_case["db"]
    both(case)
    for _ in range(2):
        create(case, text="😀" * (c.MAX_ORIGINAL_BYTES // 4))
    selected = []

    def observe(state):
        if state.is_select and isinstance(state.statement, Select):
            selected.extend(col.key for col in state.statement.selected_columns)

    event.listen(db, "do_orm_execute", observe)
    before = db.query(AIAuditEvent).count()
    try:
        with pytest.raises(HTTPException) as error:
            capture(case)
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert error.value.status_code == 413 and "original_json" not in selected
    assert db.query(AIAuditEvent).count() == before


@pytest.mark.parametrize("kind", ["original", "case"])
def test_current_actor_role_epoch_is_checked_before_private_source_locator(grant_case, kind):
    from sqlalchemy import Select, event

    case, db = grant_case, grant_case["db"]
    both(case)
    record = create(case) if kind == "original" else create_case(case)
    identifier = record.immutable.original_id if kind == "original" else record.immutable.case_id
    actor = case["actor"]
    _ = actor.user_role, actor.token_invalid_before
    db.execute(text("UPDATE hoimsystem_users SET user_role='doctor' WHERE user_id=:id"), {"id": actor.user_id})
    # Retain the request object's actual loaded epoch for this controlled test.
    db.flush()
    fields = []

    def observe(state):
        if state.is_select and isinstance(state.statement, Select):
            fields.extend(col.key for col in state.statement.selected_columns)

    event.listen(db, "do_orm_execute", observe)
    try:
        with pytest.raises(HTTPException) as error:
            if kind == "original":
                s.original_detail(db, actor, identifier)
            else:
                k.case_detail(db, actor, identifier)
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert error.value.status_code == 403
    assert not {"original_id", "case_id", "original_json", "case_json"}.intersection(fields)
    db.rollback()


@pytest.mark.parametrize("phase", ["create", "publish"])
def test_actual_after_case_sql_trigger_new_legacy_root_cannot_escape_postflush_closure(grant_case, phase):
    case, db = grant_case, grant_case["db"]
    both(case)
    record = create_case(case) if phase == "publish" else None
    operation = "INSERT" if phase == "create" else "UPDATE"
    db.execute(
        text(
            f"CREATE TRIGGER rca_case_fault AFTER {operation} ON hoimsystem_ai_rca_evidence_case BEGIN INSERT INTO hoimsystem_adverse_event_rca(event_id,event_summary,root_cause,corrective_actions,pdca_cycle,create_time) VALUES(NEW.event_id,'trigger new root','unverified','not_completed','P','2026-10-21 12:00:00'); END"
        )
    )
    db.commit()
    before = db.query(AIAuditEvent).count()
    from app.models import AdverseEventRca

    old = db.query(AdverseEventRca).filter_by(event_id=case["event_id"]).count()
    with pytest.raises(HTTPException) as error:
        if phase == "create":
            create_case(case)
        else:
            publish(case, record)
    assert error.value.status_code == 409
    assert db.query(AIAuditEvent).count() == before
    assert db.query(AdverseEventRca).filter_by(event_id=case["event_id"]).count() == old
    if record is not None:
        assert k.case_detail(db, case["actor"], record.immutable.case_id).governance.status == "draft"
