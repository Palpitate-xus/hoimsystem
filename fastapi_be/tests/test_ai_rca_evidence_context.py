"""Current actual Source SQL builds split RCA tasks; no Task or model run yet."""

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text

from app.ai import rca_evidence_cases as cases
from app.ai import rca_evidence_context as context
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as g
from app.ai import rca_evidence_task_contract as t
from app.ai import rca_evidence_task_views as views
from app.models import User
from tests.test_ai_rca_evidence_cases import create_case, publish
from tests.test_ai_rca_evidence_grants import NOW, both, cas, issue, no_source_text
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_sources import TEXT, create, review


def prepared(case, question=None):
    both(case)
    original = review(case, create(case))
    record = publish(case, create_case(case))
    value = context.prepare_context(case["db"], case["actor"], {"rca_evidence_case_id": record.immutable.case_id, "question": question})
    return value, original


@pytest.mark.parametrize("question", [None, "", "\u0085\u3000", "原问题🙂\r\n"])
def test_real_published_case_independent_purposes_exact_hmac_public_source_and_split_budgets(grant_case, question):
    case = grant_case
    value, original = prepared(case, question)
    assert value.selection.question == question and value.record.eligible
    assert value.binding.event_id == case["event_id"] and value.binding.patient_id_at_capture == case["patient_id"]
    assert value.binding.event_grant.grant_id != value.binding.patient_grant.grant_id
    assert value.source.items[0].text == TEXT and value.source.items[0].item_id != original.immutable.original_id
    assert value.source == cases.public_source(case["db"], case["actor"], value.binding.case_id)
    assert len(t.text_json(value.data).encode()) < 65535 and len(t.text_json(value.evidence).encode()) < 65535
    assert set(value.data) == {"schema_version", "scope", "source_domain", "selected_sources", "rca_evidence_binding", "scope_note", "missing_data", "snapshot_time"}
    public = t.public_payload({"input": value.selection.model_dump(mode="json"), "context": t.expand_public_context(value.data, value.source), "tools": {}, "evidence": value.evidence})
    assert public == {"rca_source": value.source.model_dump(mode="json"), "question": question}
    assert '"patient_id"' not in c.canonical(public) and '"identity_secret"' not in c.canonical(public)
    assert '"description"' in c.canonical(value.frozen_case)
    assert value.frozen_case.execution_current is False and value.frozen_case.frozen_task_view is True
    assert cases.wire(value.frozen_case)["data"]["governance"]["status"] == "published"
    authorization, immutable = context.authorize_binding(case["db"], case["actor"], value.binding)
    assert immutable == value.record.immutable and authorization.actor.user_id == value.binding.requested_by


@pytest.mark.parametrize(
    "input_value", [{}, {"patient_id": 1}, {"rca_evidence_case_id": None}, {"rca_evidence_case_id": "not-uuid"}, {"rca_evidence_case_id": "00000000-0000-0000-0000-000000000001", "encounter_ref": "x"}]
)
def test_illegal_task_selection_rejects_before_private_source_text(grant_case, input_value):
    def attempt():
        with pytest.raises(HTTPException) as failure:
            context.prepare_context(grant_case["db"], grant_case["actor"], input_value)
        assert failure.value.status_code == 422

    no_source_text(grant_case["db"], attempt)


@pytest.mark.parametrize("change", ["event_permission", "patient_permission", "role", "patient_association", "expiry"])
def test_current_authority_loss_rejects_before_original_or_case_text(grant_case, change, monkeypatch):
    case, db = grant_case, grant_case["db"]
    value, _ = prepared(case)
    if change in {"event_permission", "patient_permission"}:
        anchor = value.binding.event_grant if change == "event_permission" else value.binding.patient_grant
        record = g.grant_detail(db, case["actor"], anchor.grant_id)
        g.revoke_grant(db, case["actor"], anchor.grant_id, cas(record))
        db.commit()
    elif change == "role":
        identifier = inspect(case["actor"]).identity[0]
        db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": identifier})
    elif change == "patient_association":
        db.execute(text("UPDATE hoimsystem_adverse_event SET patient_id=NULL WHERE event_id=:id"), {"id": case["event_id"]})
    else:
        monkeypatch.setattr(g, "utcnow", lambda: NOW + dt.timedelta(days=2))

    def attempt():
        with pytest.raises(HTTPException) as failure:
            context.authorize_binding(db, case["actor"], value.binding)
        assert failure.value.status_code == 403

    no_source_text(db, attempt)
    db.rollback()


def test_another_new_event_grant_does_not_restore_the_original_task_grant(grant_case):
    case, db = grant_case, grant_case["db"]
    value, _ = prepared(case)
    record = g.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
    g.revoke_grant(db, case["actor"], record.identity.grant_id, cas(record))
    db.commit()
    issue(case)
    assert cases.public_source(db, case["actor"], value.binding.case_id) == value.source
    with pytest.raises(HTTPException) as failure:
        context.authorize_binding(db, case["actor"], value.binding)
    assert failure.value.status_code == 403


@pytest.mark.parametrize("change", ["new_draft", "revoke_case"])
def test_current_change_denies_execution_but_explicit_purpose_authorized_frozen_audit_remains(grant_case, change):
    case, db = grant_case, grant_case["db"]
    value, _ = prepared(case)
    if change == "new_draft":
        create(case, text="同事件新增未审核资料也必须完整核对")
    else:
        cases.revoke_case(db, case["actor"], value.binding.case_id, cas(value.record))
        db.commit()
    with pytest.raises(HTTPException) as failure:
        context.authorize_binding(db, case["actor"], value.binding)
    assert failure.value.status_code == 409
    auth, immutable = context.authorize_binding(db, case["actor"], value.binding, frozen_audit=True)
    frozen = context.frozen_case(immutable, value.record.governance, value.record.content_hash, value.record.governance_hash)
    assert frozen == value.frozen_case and auth.actor.user_id == value.binding.requested_by
    assert frozen.execution_current is False


def test_other_super_still_requires_own_purposes_and_explicit_frozen_entry(grant_case):
    case, db = grant_case, grant_case["db"]
    value, _ = prepared(case)
    other = User(username="rca_task_audit_" + uuid.uuid4().hex[:7], password="synthetic-unused", user_role="super_admin")
    db.add(other)
    db.commit()
    with pytest.raises(HTTPException) as failure:
        context.authorize_binding(db, other, value.binding, frozen_audit=True)
    assert failure.value.status_code == 403
    alternate = {**case, "actor": other}
    both(alternate)
    with pytest.raises(HTTPException) as failure:
        context.authorize_binding(db, other, value.binding)
    assert failure.value.status_code == 403
    auth, immutable = context.authorize_binding(db, other, value.binding, frozen_audit=True)
    assert auth.actor.user_id == other.user_id and immutable == value.record.immutable


@pytest.mark.parametrize(
    "input_tokens,output_tokens,attempted,valid",
    [(0, 0, False, True), (None, None, None, True), (11, None, True, True), (None, 13, True, True), (0, 0, True, True), (None, None, False, False), (11, 13, None, False), (False, 13, True, False)],
)
def test_true_nullable_usage_is_separate_from_legacy_run_zero_fields(input_tokens, output_tokens, attempted, valid):
    data = {"input_tokens": input_tokens, "output_tokens": output_tokens, "complete": input_tokens is not None and output_tokens is not None, "model_call_attempted": attempted}
    if valid:
        assert views.RcaUsageReceipt.model_validate(data).model_dump(mode="json") == data
    else:
        with pytest.raises(ValueError):
            views.RcaUsageReceipt.model_validate(data)


def test_damaged_task_grant_does_not_lock_or_read_another_events_grant_body(grant_case, monkeypatch):
    from sqlalchemy import Select, event

    from app.models import AdverseEvent

    case, db = grant_case, grant_case["db"]
    value, _ = prepared(case)
    other_event = AdverseEvent(patient_id=case["patient_id"], reporter_id=case["users"]["doctor_user"].user_id, description="另一个事件的私有正文", severity=0, status=0)
    db.add(other_event)
    db.commit()
    other_id = inspect(other_event).identity[0]
    foreign = issue({**case, "event_id": other_id})
    bound = value.binding.model_dump(mode="json")
    bound["event_grant"]["grant_id"] = foreign.identity.grant_id
    locked, forbidden_body = [], []
    actual_lock = g.lock_event_identity

    def observe_lock(db, identifier):
        locked.append(identifier)
        return actual_lock(db, identifier)

    def observe_sql(state):
        if state.is_select and isinstance(state.statement, Select) and any(col.key == "grant_json" for col in state.statement.selected_columns):
            if foreign.identity.grant_id in state.statement.compile().params.values():
                forbidden_body.append(True)

    monkeypatch.setattr(g, "lock_event_identity", observe_lock)
    event.listen(db, "do_orm_execute", observe_sql)
    try:
        with pytest.raises(HTTPException) as failure:
            context.authorize_binding(db, case["actor"], bound)
        assert failure.value.status_code == 409
    finally:
        event.remove(db, "do_orm_execute", observe_sql)
    assert case["event_id"] in locked and other_id not in locked and not forbidden_body
