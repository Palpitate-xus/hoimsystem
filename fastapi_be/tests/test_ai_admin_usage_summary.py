"""Actual nullable accounting, exact Audit FKs and complete source-free reads."""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import admin_usage_summary as stats
from app.ai.admin_usage_receipts import SPECS
from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.models import AIAuditEvent, AIFeedback, AIRun
from app.ai.native_task_routing import _domains
from tests.test_ai_admin_task_directory import PRIVATE, generic, observer
from tests.test_ai_admin_write_authority import change_subject, restore_subject, subject
from tests.test_ai_charge_reconciliation_receipts import terminal
from tests.test_ai_charge_reconciliation_sources import charge_case as charge_case
from tests.test_ai_charge_reconciliation_storage import original_run


@pytest.fixture(autouse=True)
def independent_usage_tasks(db_session):
    # The repository intentionally shares a database within each test module.
    # These aggregate scenarios need independent task populations; preserve
    # every business/Source row and clear only this module's charge/generic work.
    db_session.query(AIFeedback).delete()
    db_session.query(AIChargeRunArtifact).delete()
    db_session.query(AIRun).delete()
    db_session.commit()


def charge_row(case):
    return next(row for row in stats.usage_summary(case["db"], case["super_admin_user"])["data"] if row["feature_key"] == "charge_reconciliation")


def test_every_native_domain_requires_an_explicit_receipt_adapter():
    assert set(SPECS) == {domain for domain, _, _ in _domains()}


def test_legacy_physical_zero_and_positive_are_unverified_and_all_keyset_pages_counted(db_session, seed_data, monkeypatch):
    generic(db_session, seed_data, 7)
    monkeypatch.setattr(stats, "PAGE_SIZE", 3)
    result = stats.usage_summary(db_session, seed_data["super_admin_user"])
    assert result["coverage"] == {"total": 7, "scanned": 7, "complete": True}
    assert PRIVATE not in json.dumps(result)
    row = result["data"][0]
    assert row["count"] == row["unverified_count"] == row["input_tokens_unknown_count"] == row["output_tokens_unknown_count"] == 7
    assert row["input_tokens"] is row["output_tokens"] is None
    assert row["input_tokens_known_sum"] == row["output_tokens_known_sum"] == 0
    assert row["model_call_unknown_count"] == 7


@pytest.mark.parametrize("inputs,outputs,attempted", ((13, 7, True), (13, None, True), (None, 7, True), (None, None, True), (0, 0, False)))
def test_concrete_charge_receipt_preserves_each_independent_unknown_and_actual_zero(charge_case, inputs, outputs, attempted):
    terminal(charge_case, state="cancelled", inputs=inputs, outputs=outputs, attempted=attempted)
    row = charge_row(charge_case)
    assert row["count"] == row["recorded_count"] == 1
    assert row["input_tokens"] == inputs and row["output_tokens"] == outputs
    for key, count in (("input_tokens", inputs), ("output_tokens", outputs)):
        assert row[key + "_known_sum"] == (count if count is not None else 0)
        assert row[key + "_unknown_count"] == int(count is None)
    assert row["model_call_attempted_count"] == int(attempted)
    assert row["model_call_unattempted_count"] == int(not attempted)


def test_unknown_member_keeps_known_sum_without_fabricating_complete_group_total(charge_case):
    terminal(charge_case, state="cancelled", inputs=13, outputs=7)
    terminal(charge_case, state="cancelled", inputs=5, outputs=None)
    row = charge_row(charge_case)
    assert row["count"] == row["recorded_count"] == 2
    assert row["input_tokens"] == 18 and row["input_tokens_unknown_count"] == 0
    assert row["output_tokens"] is None and row["output_tokens_known_sum"] == 7 and row["output_tokens_unknown_count"] == 1


@pytest.mark.parametrize("field,value", (("action", "grant.create"), ("target", "foreign-private-target"), ("actor_id", -1)))
def test_wrong_audit_header_is_invalid_before_any_receipt_body_projection(charge_case, field, value):
    db = charge_case["db"]
    run, _ = terminal(charge_case, state="failed", inputs=13, outputs=None)
    anchor = db.get(AIChargeRunArtifact, run.run_id)
    audit = db.get(AIAuditEvent, anchor.receipt_event_id)
    setattr(audit, field, value)
    audit.detail_json = json.dumps({"schema_version": SPECS["charge"].schema, "private": PRIVATE})
    db.commit()
    queries, seen = observer(db)
    try:
        row = charge_row(charge_case)
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert row["invalid_count"] == 1 and row["input_tokens"] is row["output_tokens"] is None
    assert not any("hoimsystem_ai_audit_event.detail_json \nFROM" in sql for sql in queries)
    assert PRIVATE not in json.dumps(row)


@pytest.mark.parametrize("mutation", ("counter", "lease", "missing_fk", "duplicate_key", "wrong_schema", "oversized", "owner"))
def test_invalid_settled_receipts_stay_unknown_and_never_become_pending(charge_case, mutation):
    db = charge_case["db"]
    run, _ = terminal(charge_case, state="cancelled", inputs=13, outputs=None)
    anchor = db.get(AIChargeRunArtifact, run.run_id)
    audit = db.get(AIAuditEvent, anchor.receipt_event_id)
    if mutation == "counter":
        run.input_tokens += 1
    elif mutation == "lease":
        run.lease_token = "00000000-0000-0000-0000-000000000001"
    elif mutation == "missing_fk":
        anchor.receipt_event_id = None
    elif mutation == "duplicate_key":
        audit.detail_json = audit.detail_json[:-1] + ',"usage":{}}'
    elif mutation == "wrong_schema":
        audit.detail_json = audit.detail_json.replace(SPECS["charge"].schema, "other_usage_v1")
    elif mutation == "oversized":
        audit.detail_json = '{"schema_version":"' + SPECS["charge"].schema + '","private":"' + "界" * 24000 + '"}'
    else:
        anchor.requested_by = charge_case["admin_user"].user_id
    db.commit()
    row = charge_row(charge_case)
    assert row["invalid_count"] == 1 and row["pending_count"] == row["recorded_count"] == 0
    assert row["input_tokens"] is row["output_tokens"] is None


def test_queued_native_task_is_pending_and_mutable_feature_does_not_change_domain(charge_case):
    run, *_ = original_run(charge_case)
    run.feature_key = "operations_qa"
    charge_case["db"].commit()
    row = charge_row(charge_case)
    assert row["count"] == row["pending_count"] == 1
    assert row["input_tokens"] is row["output_tokens"] is None


def test_shared_audit_fk_cannot_authorize_another_task_even_with_matching_owner_and_lease(charge_case):
    db = charge_case["db"]
    first, _ = terminal(charge_case, state="cancelled", inputs=13, outputs=7)
    second, _ = terminal(charge_case, state="cancelled", inputs=13, outputs=7)
    second.lease_token = first.lease_token
    db.get(AIChargeRunArtifact, second.run_id).receipt_event_id = db.get(AIChargeRunArtifact, first.run_id).receipt_event_id
    db.commit()
    row = charge_row(charge_case)
    assert row["count"] == 2 and row["recorded_count"] == row["invalid_count"] == 1
    assert row["input_tokens"] is row["output_tokens"] is None
    assert row["input_tokens_known_sum"] == 13 and row["output_tokens_known_sum"] == 7


@pytest.mark.parametrize("mutation", ("queued_lease", "settled_clock", "settled_finish"))
def test_damaged_phase_headers_never_become_pending_or_recorded(charge_case, mutation):
    db = charge_case["db"]
    if mutation == "queued_lease":
        run, *_ = original_run(charge_case)
        run.lease_token = "00000000-0000-0000-0000-000000000001"
    else:
        run, _ = terminal(charge_case, state="cancelled", inputs=0, outputs=0, attempted=False)
        if mutation == "settled_clock":
            run.latency_ms = None
        else:
            run.finish_time = None
    db.commit()
    row = charge_row(charge_case)
    assert row["invalid_count"] == 1 and row["pending_count"] == row["recorded_count"] == 0


@pytest.mark.parametrize("axis", ("role", "epoch", "username"))
def test_stale_super_subject_is_rejected_before_usage_queries(db_session, seed_data, axis):
    generic(db_session, seed_data)
    actor = seed_data["super_admin_user"]
    original = subject(actor)
    change_subject(db_session, original, axis)
    queries, seen = observer(db_session)
    try:
        with pytest.raises(HTTPException) as caught:
            stats.usage_summary(db_session, actor)
        assert caught.value.status_code == 403
        assert len(queries) == 1 and "hoimsystem_users" in queries[0]
    finally:
        event.remove(db_session.bind, "before_cursor_execute", seen)
        restore_subject(db_session, original)


def test_sql_projection_does_not_load_patient_task_source_result_or_error_text(charge_case):
    terminal(charge_case, state="failed", inputs=13, outputs=None)
    db = charge_case["db"]
    queries, seen = observer(db)
    try:
        charge_row(charge_case)
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    for sql in queries:
        assert not any(
            token in sql
            for token in (
                ".input_json",
                ".evidence_json",
                ".context_metadata_json",
                ".source_json",
                ".binding_json",
                ".patient_id",
                ".encounter_ref",
                ".error_message",
                "FOR UPDATE",
                "LOCK IN SHARE MODE",
                "write_gate",
            )
        ), sql
        # The one legacy document FK is extracted by a constant SQL JSON path;
        # no statement selects a whole Run or Artifact result_json column.
        projection = sql.split("FROM")[0]
        assert " result_json" not in projection and ".result_json AS" not in projection, sql


@pytest.mark.parametrize("axis,assignment", (("role", "user_role='pharmacist'"), ("epoch", "token_invalid_before='2099-01-02 03:04:05.123456'"), ("username", "username='usage-read-moved'")))
def test_authority_change_during_usage_snapshot_denies_the_response(db_session, seed_data, axis, assignment):
    generic(db_session, seed_data)
    actor, changed = seed_data["super_admin_user"], []
    original = subject(actor)

    def mutate(conn, cursor, sql, params, context, many):
        if not changed and "FROM hoimsystem_ai_run" in sql:
            changed.append(True)
            db_session.execute(text("UPDATE hoimsystem_users SET " + assignment + " WHERE user_id=:pk"), {"pk": original["user_id"]})

    event.listen(db_session.bind, "after_cursor_execute", mutate)
    try:
        with pytest.raises(HTTPException) as caught:
            stats.usage_summary(db_session, actor)
        assert caught.value.status_code == 403 and changed
    finally:
        event.remove(db_session.bind, "after_cursor_execute", mutate)
        restore_subject(db_session, original)
