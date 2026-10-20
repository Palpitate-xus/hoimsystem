"""Whole real SQL collections, private redaction and pure closed-proof boundaries."""

# ruff: noqa: F811 -- imported pytest fixture is registered at module scope.

import copy
import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai import supply_collection as c
from app.ai import supply_sources as s
from app.ai.supply_contract import day_bounds
from tests.test_ai_supply_sources import NOW, create_unit, publish, source_request, supply_case  # noqa: F401


def period(case, timezone="Asia/Shanghai"):
    end = datetime.date(2026, 10, 19)
    return {
        "item_kind": "pharmaceutical",
        "item_id": case["drug"].pharmaceutical_id,
        "scope": "hospital_inventory",
        "timezone": timezone,
        "date_from": (end - datetime.timedelta(days=111)).isoformat(),
        "date_to": end.isoformat(),
        "as_of": s.utc_text(NOW),
    }


def day_request(case, date, timezone, *, unit=None):
    request = source_request(case, unit)
    start, end = day_bounds(date, timezone)
    request["payload"].update(date=date, timezone=timezone, day_start_at=start, day_end_at=end, observed_at=end)
    return request


def original(db, case, request, *, published=True):
    row = s.create_source(db, case["pharmacist"] if request["payload"]["professional_attestation"]["status"] == "confirmed" else case["admin"], request)
    db.commit()
    return publish(db, case, "daily", row) if published else row


def test_full_and_hidden_roots_are_all_members_without_fabricating_draft_quantities(db_session, supply_case):
    case = supply_case
    unit = create_unit(db_session, case)
    good = original(db_session, case, source_request(case, unit))
    draft = original(db_session, case, source_request(case), published=False)
    result = c.capture_sources(db_session, case["super"], period(case), locking=True)
    assert c.verify_capture(result) == result
    roots = {r["source"]["source_record_id"]: r["source"] for r in result["source_records"]}
    assert roots[good.source_record_id]["payload"]["quantity"]["value"] == "0.000000"
    assert all(roots[draft.source_record_id][k] is None for k in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    assert len(result["member_manifest"]) == 3 and all(not r[k] for r in roots.values() for k in ("can_record", "can_review", "can_revoke", "audit_only"))


@pytest.mark.parametrize("side", ["before", "after"])
def test_adjacent_logical_dates_with_real_utc_overlap_are_captured_not_silently_lost(db_session, supply_case, side):
    case = supply_case
    req = period(case)
    date = (datetime.date.fromisoformat(req["date_from"]) - datetime.timedelta(days=1)).isoformat() if side == "before" else "2026-10-20"
    timezone = "Pacific/Honolulu" if side == "before" else "Pacific/Kiritimati"
    row = original(db_session, case, day_request(case, date, timezone))
    result = c.capture_sources(db_session, case["admin"], req)
    assert [entry["source"]["source_record_id"] for entry in result["source_records"]] == [row.source_record_id]
    assert c.verify_capture(result) == result


@pytest.mark.parametrize("side", ["before", "after"])
def test_touching_utc_edges_without_positive_overlap_are_not_related(db_session, supply_case, side):
    case = supply_case
    req = period(case)
    date = (datetime.date.fromisoformat(req["date_from"]) - datetime.timedelta(days=1)).isoformat() if side == "before" else "2026-10-20"
    # The second closed day ends after current NOW, so capture a fresh as_of.
    request = day_request(case, date, "Asia/Shanghai")
    if side == "after":
        s_time = s.utc_datetime(request["payload"]["day_end_at"])
        from unittest.mock import patch

        with patch.object(s, "utcnow", lambda: s_time):
            original(db_session, case, request)
    else:
        original(db_session, case, request)
    result = c.capture_sources(db_session, case["admin"], req)
    assert result["source_records"] == [] and c.verify_capture(result) == result


def test_all_originals_cross_keyset_pages_and_bytes_reject_before_next_page(db_session, supply_case, monkeypatch):
    case = supply_case
    for _ in range(c.READ_BATCH + 3):
        original(db_session, case, source_request(case), published=False)
    statements = []

    def sql(statement):
        if statement.is_select and statement.bind_arguments.get("mapper") is not None:
            text = str(statement.statement)
            if "payload_json" in text and "hoimsystem_ai_supply_daily_quantity" in text and "ORDER BY" in text:
                statements.append(statement.statement)

    event.listen(db_session, "do_orm_execute", sql)
    try:
        result = c.capture_sources(db_session, case["admin"], period(case))
    finally:
        event.remove(db_session, "do_orm_execute", sql)
    assert len(result["source_records"]) == c.READ_BATCH + 3 and c.verify_capture(result)
    assert len(statements) == 3 and all(stmt._limit_clause.value == c.READ_BATCH for stmt in statements)
    seen = []
    original_current = s.source_current

    def counted(*args, **kwargs):
        seen.append(args[3])
        return original_current(*args, **kwargs)

    monkeypatch.setattr(s, "source_current", counted)
    monkeypatch.setattr(c, "MAX_BYTES", 100)
    with pytest.raises(HTTPException) as error:
        c.capture_sources(db_session, case["admin"], period(case))
    assert error.value.status_code == 422 and len(seen) == 1


def test_new_nonwinner_late_original_invalidates_cutoff_without_leaking_id_count_or_clock(db_session, supply_case, monkeypatch):
    case = supply_case
    req = period(case)
    before = c.capture_sources(db_session, case["admin"], req)
    monkeypatch.setattr(s, "utcnow", lambda: NOW + datetime.timedelta(microseconds=1))
    row = original(db_session, case, source_request(case), published=False)
    with pytest.raises(HTTPException) as error:
        c.capture_sources(db_session, case["admin"], req, locking=True)
    assert error.value.status_code == 409 and row.source_record_id not in error.value.detail and s.utc_text(NOW) not in error.value.detail
    req["as_of"] = s.utc_text(NOW + datetime.timedelta(microseconds=1))
    after = c.capture_sources(db_session, case["admin"], req)
    assert after["collection_digest"] != before["collection_digest"] and len(after["member_manifest"]) == 1


def test_nonwinner_revocation_and_original_pharmacist_role_are_current_membership_evidence(db_session, supply_case):
    case = supply_case
    unit = create_unit(db_session, case)
    a = original(db_session, case, source_request(case, unit))
    b = original(db_session, case, source_request(case, unit))
    old = c.capture_sources(db_session, case["admin"], period(case), locking=True)
    s.review_source(
        db_session,
        case["super"],
        "daily",
        b.source_record_id,
        {"expected_revision": 2, "expected_content_hash": b.content_hash, "basis_note": "完整逐根库存原件治理依据，工程合成数据不涉及真实业务数量变更。"},
        revoke=True,
    )
    db_session.commit()
    revoked = c.capture_sources(db_session, case["admin"], period(case), locking=True)
    assert revoked["current_membership_digest"] != old["current_membership_digest"]
    case["pharmacist"].user_role = "admin"
    db_session.commit()
    changed = c.capture_sources(db_session, case["admin"], period(case), locking=True)
    assert changed["current_membership_digest"] != revoked["current_membership_digest"] and len(changed["member_manifest"]) == 3
    assert next(r for r in changed["source_records"] if r["source"]["source_record_id"] == a.source_record_id)["source"]["payload"] is None


@pytest.mark.parametrize("attack", ["extra", "quantity", "scope", "locator", "duplicate", "outside"])
def test_rehashing_collection_does_not_legitimize_forged_originals_locators_or_scope(db_session, supply_case, attack):
    case = supply_case
    original(db_session, case, source_request(case))
    value = copy.deepcopy(c.capture_sources(db_session, case["admin"], period(case)))
    entry = value["source_records"][0]
    if attack == "extra":
        entry["source"]["payload"]["extra"] = "untrusted"
    elif attack == "quantity":
        entry["source"]["payload"]["quantity"]["value"] = "999999999999999999.999999"
    elif attack == "scope":
        value["sku_binding"]["identity"]["name"] = "different SKU"
        value["scope_binding"] = c.scope_binding(value["sku_binding"])
    elif attack == "locator":
        entry["locator"]["timezone"] = "UTC"
        entry["locator_hash"] = s.hash_content(entry["locator"])
    elif attack == "duplicate":
        value["source_records"].append(copy.deepcopy(entry))
    else:
        shifted = day_request(case, "2026-06-28", "Asia/Shanghai")
        row = original(db_session, case, shifted)
        full = s.source_current(db_session, case["admin"], "daily", row.source_record_id)
        entry["source"] = c.capture_view(full)
        entry["locator"] = c.locator("daily", s.source_proof("daily", row))
        entry["locator_hash"] = s.hash_content(entry["locator"])
    value["member_manifest"] = sorted((s.source_metadata(e["source"]) for e in value["unit_definitions"] + value["source_records"]), key=lambda r: (r["record_kind"], r["source_record_id"]))
    c._finish(value)
    with pytest.raises(HTTPException) as error:
        c.verify_capture(value)
    assert error.value.status_code == 409
