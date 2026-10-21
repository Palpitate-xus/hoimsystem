"""Whole same-SKU controlled membership, frozen proof and stable current digests."""

import copy
import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai import inventory_native_collection as c
from app.ai import inventory_native_sources as s
from app.ai import supply_sources as units
from tests.test_ai_inventory_native_source_input import NOTE
from tests.test_ai_inventory_native_sources import NOW, publish, source_request
from tests.test_ai_inventory_native_sources import inventory_case as inventory_case
from tests.test_ai_supply_sources import supply_case as supply_case
from tests.test_ai_supply_sources import unit_request


def period(case):
    return {
        "item_kind": "pharmaceutical",
        "item_id": case["drug"].pharmaceutical_id,
        "scope": "hospital_inventory",
        "timezone": "UTC",
        "date_from": "2026-11-01",
        "date_to": "2026-11-02",
        "as_of": "2026-10-21T12:00:00.123456Z",
    }


def create(db, case, kind="inventory_observation", *, published=True):
    row = s.create_source(db, case["admin"], source_request(case, kind))
    db.commit()
    if published:
        publish(db, case, row)
    return row


def test_current_full_sku_closure_includes_unknown_other_period_and_metadata_only_draft(db_session, inventory_case):
    case = inventory_case
    rows = [create(db_session, case, kind) for kind in ("inventory_observation", "future_quantity_scenario", "purchase_candidate_plan")]
    draft = create(db_session, case, published=False)
    result = c.capture_sources(db_session, case["super"], period(case))
    assert c.verify_capture(result) and len(result["source_records"]) == 4 and len(result["unit_definitions"]) == 1
    byid = {r["source"]["source_record_id"]: r["source"] for r in result["source_records"]}
    assert all(byid[row.source_record_id]["eligible"] and byid[row.source_record_id]["professional_status"] == "unknown" for row in rows)
    assert all(byid[draft.source_record_id][key] is None for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    assert all(not entry["source"][key] for entry in result["source_records"] + result["unit_definitions"] for key in ("audit_only", "can_record", "can_review", "can_revoke"))
    # Different source timezone/date_to remains an explicit review member.
    assert byid[rows[1].source_record_id]["timezone"] == "America/New_York"


def test_new_nonwinner_and_unit_change_full_collection_not_only_selected_records(db_session, inventory_case):
    case = inventory_case
    create(db_session, case)
    a = c.capture_sources(db_session, case["admin"], period(case))
    extra = create(db_session, case, "purchase_candidate_plan", published=False)
    b = c.capture_sources(db_session, case["admin"], period(case))
    assert a["collection_digest"] != b["collection_digest"] and a["current_membership_digest"] != b["current_membership_digest"]
    publish(db_session, case, extra)
    changed = c.capture_sources(db_session, case["admin"], period(case))
    assert changed["collection_digest"] != b["collection_digest"]
    body = unit_request(case, confirmed=False)
    unit = units.create_unit(db_session, case["admin"], body)
    db_session.commit()
    d = c.capture_sources(db_session, case["admin"], period(case))
    assert d["collection_digest"] != changed["collection_digest"] and len(d["unit_definitions"]) == 2
    assert next(e["source"] for e in d["unit_definitions"] if e["source"]["source_record_id"] == unit.unit_definition_id)["payload"] is None


def test_fresh_capture_clock_never_changes_unchanged_membership_or_replaces_original_observation_clock(db_session, inventory_case, monkeypatch):
    case = inventory_case
    row = create(db_session, case)
    a = c.capture_sources(db_session, case["admin"], period(case))
    monkeypatch.setattr(c, "utcnow", lambda: NOW + datetime.timedelta(seconds=2))
    b = c.capture_sources(db_session, case["admin"], period(case))
    assert a["captured_at"] != b["captured_at"] and a["legacy_snapshot"]["captured_at"] != b["legacy_snapshot"]["captured_at"]
    assert all(a[k] == b[k] for k in ("collection_digest", "historical_collection_digest", "current_membership_digest"))
    original = next(e["source"] for e in b["source_records"] if e["source"]["source_record_id"] == row.source_record_id)
    assert original["parent_binding"]["legacy_snapshot"]["captured_at"] == a["legacy_snapshot"]["captured_at"]
    assert c.verify_capture(a) and c.verify_capture(b)


@pytest.mark.parametrize("operation", ["new_original", "new_other_period", "publish", "revoke", "new_unit"])
def test_later_whole_member_never_hides_behind_old_asof_or_leaks_detail(db_session, inventory_case, monkeypatch, operation):
    case = inventory_case
    row = create(db_session, case, published=False)
    late = NOW + datetime.timedelta(microseconds=1)
    monkeypatch.setattr(s, "utcnow", lambda: late)
    monkeypatch.setattr(units, "utcnow", lambda: late)
    monkeypatch.setattr(c, "utcnow", lambda: late)
    if operation in {"new_original", "new_other_period"}:
        body = source_request(case, "purchase_candidate_plan")
        if operation == "new_other_period":
            body["payload"].update(date_from="2026-12-01", date_to="2026-12-02")
        s.create_source(db_session, case["admin"], body)
        db_session.commit()
    elif operation == "new_unit":
        units.create_unit(db_session, case["admin"], unit_request(case, confirmed=False))
        db_session.commit()
    elif operation == "publish":
        publish(db_session, case, row)
    else:
        s.review_source(db_session, case["admin"], row.source_record_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "basis_note": NOTE}, revoke=True)
        db_session.commit()
    seen = []
    conn = db_session.connection()

    def sql(c, cur, statement, p, context, many):
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", sql)
    try:
        with pytest.raises(HTTPException) as e:
            c.capture_sources(db_session, case["super"], period(case))
        assert e.value.status_code == 409 and e.value.detail == "当前完整来源集合已有变化，请刷新真实截止后重新捕获"
    finally:
        event.remove(conn, "before_cursor_execute", sql)
    assert not any("payload_json" in q for q in seen)


def test_history_does_not_age_only_execution_boundary_checks_new_planning_dates(db_session, inventory_case, monkeypatch):
    case = inventory_case
    create(db_session, case)
    a = c.capture_sources(db_session, case["admin"], period(case))
    monkeypatch.setattr(c, "utcnow", lambda: datetime.datetime(2027, 1, 1))
    b = c.capture_sources(db_session, case["admin"], period(case))
    assert b["collection_digest"] == a["collection_digest"] and c.verify_capture(b)


@pytest.mark.parametrize("mutation", ["extra", "duplicate", "order", "locator", "scope", "unitbody", "body", "flag", "redactedflag", "hash"])
def test_self_rehashed_invalid_closure_never_establishes_hidden_full_proof(db_session, inventory_case, mutation):
    case = inventory_case
    create(db_session, case)
    create(db_session, case, "purchase_candidate_plan", published=False)
    value = c.capture_sources(db_session, case["super"], period(case))
    bad = copy.deepcopy(value)
    if mutation == "extra":
        bad["extra"] = True
    elif mutation == "duplicate":
        bad["source_records"].append(copy.deepcopy(bad["source_records"][0]))
    elif mutation == "order":
        bad["source_records"].reverse()
    elif mutation == "locator":
        bad["source_records"][0]["locator"]["source_record_id"] = bad["unit_definitions"][0]["source"]["source_record_id"]
        bad["source_records"][0]["locator_hash"] = c.hash_content(bad["source_records"][0]["locator"])
    elif mutation == "scope":
        bad["sku_binding"]["item_id"] += 1
    elif mutation == "unitbody":
        bad["unit_definitions"][0]["source"]["payload"]["original_unit_text"] = "伪造已公开名称"
    elif mutation == "body":
        next(e["source"] for e in bad["source_records"] if e["source"]["payload"] is not None)["payload"]["observed_at"] = "2026-10-21T12:00:00.123457Z"
    elif mutation == "flag":
        bad["unit_definitions"][0]["source"]["can_review"] = True
    elif mutation == "redactedflag":
        next(e["source"] for e in bad["source_records"] if e["source"]["payload"] is None)["can_review"] = True
    elif mutation == "hash":
        bad["legacy_snapshot"]["sku"]["original_row_hash"] = "a" * 64
    c._finish(bad)
    assert not c.verify_capture(bad)


def test_max_members_early_reject_and_pk_only_source_pages(db_session, inventory_case, monkeypatch):
    case = inventory_case
    create(db_session, case)
    monkeypatch.setattr(c, "MAX_MEMBERS", 1)
    with pytest.raises(HTTPException) as e:
        c.capture_sources(db_session, case["admin"], period(case))
    assert e.value.status_code == 409
    monkeypatch.setattr(c, "MAX_MEMBERS", 4096)
    seen = []
    conn = db_session.connection()

    def sql(c, cur, statement, p, context, many):
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", sql)
    try:
        assert c.verify_capture(c.capture_sources(db_session, case["admin"], period(case)))
    finally:
        event.remove(conn, "before_cursor_execute", sql)
    pages = [q for q in seen if "hoimsystem_ai_inventory_native_source" in q and "LIMIT" in q.upper()]
    assert pages and all("payload_json" not in q and "parent_binding_json" not in q for q in pages)
