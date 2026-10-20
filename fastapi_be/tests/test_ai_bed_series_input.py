"""Actual complete bed collections, explicit whole-original selection and frozen projection."""

import copy
import datetime
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from app.ai import bed_contract as core
from app.ai import bed_facts as facts
from app.ai import bed_series_input as series
from app.models import Bed
from tests.test_ai_bed_facts import NOTE, NOW, count, payload
from tests.test_ai_bed_facts import bed_case as bed_case


def period_request(case):
    end = datetime.date(2026, 10, 19)
    return {"ward_id": case["ward"].ward_id, "business_timezone": "Etc/UTC", "date_from": (end - datetime.timedelta(days=111)).isoformat(), "date_to": end.isoformat()}


def original(db, case, kind, day="2026-10-19", *, known=False, values=None, published=True):
    body = payload(kind)
    if kind in {"census", "flow_day"}:
        start, end = facts.day_bounds(day, "Etc/UTC")
        body.update(business_date=day, observed_at=end)
        if kind == "census":
            body["census_at"] = end
            if known:
                body.update(boundary_state_confirmed="confirmed", occupied_beds=count(12))
        else:
            body.update(day_start_at=start, day_end_at=end)
            if known:
                body.update(admission_events=count(3), discharge_events=count(2), transfer_in_events=count(1), transfer_out_events=count(0))
        if known:
            body["coverage"] = "attested_complete"
    if values:
        body.update(values)
    row = facts.create_source(db, case["director"], kind, {"ward_id": case["ward"].ward_id, "payload": body})
    if published:
        facts.review_source(db, case["super"], kind, row.source_record_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": "publish", "review_basis_note": NOTE})
    db.commit()
    return row


@pytest.fixture
def series_case(bed_case, db_session, monkeypatch):
    monkeypatch.setattr(series, "utcnow", lambda: NOW)
    case = bed_case
    case["period"] = period_request(case)
    case["bed"] = Bed(ward_id=case["ward"].ward_id, bed_no="A", status=1)
    db_session.add(case["bed"])
    db_session.commit()
    case["census"] = original(db_session, case, "census")
    case["flow"] = original(db_session, case, "flow_day")
    case["capacity"] = original(db_session, case, "capacity_interval")
    case["draft"] = original(db_session, case, "census", "2026-10-18", published=False)
    end = series.period_bounds(series.SeriesPeriodRequest.model_validate(case["period"]))["future_end_at"]
    case["future"] = original(
        db_session,
        case,
        "capacity_interval",
        values={
            "basis_kind": "reviewed_future_scenario",
            "start_at": "2026-10-20T00:00:00.000000Z",
            "end_at": facts.utc_text(facts.instant(end) + datetime.timedelta(microseconds=1)),
            "observed_at": None,
            "immediate_admittable_slots": count(),
            "immediate_slots_observed_at": None,
        },
    )
    return case


def collection(db, case, *, locking=False):
    return series.current_collection(db, case["director"], case["ward"].ward_id, request=case["period"], locking=locking)


def series_request(db, case, *, chosen=None):
    value = collection(db, case)
    chosen = {case["census"].source_record_id, case["flow"].source_record_id, case["capacity"].source_record_id, case["future"].source_record_id} if chosen is None else set(chosen)
    days = []
    for group in value["day_groups"]:
        item = {"business_date": group["business_date"], "selection_basis_note": NOTE}
        for prefix in ("census", "flow"):
            selected = [candidate["source_record_id"] for candidate in group[prefix + "_candidates"] if candidate["source_record_id"] in chosen and candidate["compatible"]]
            assert len(selected) <= 1
            item.update(
                {
                    prefix + "_source_record_id": selected[0] if selected else None,
                    prefix + "_selection_reason": "confirmed" if selected else "missing",
                    prefix + "_group_digest": group[prefix + "_group_digest"],
                }
            )
        days.append(item)
    reviews = [
        {
            "kind": item["kind"],
            "source_record_id": item["source_record_id"],
            "expected_content_hash": item["content_hash"],
            "expected_governance_hash": item["governance_hash"],
            "selection": "confirmed" if item["source_record_id"] in chosen else "excluded",
            "basis_note": NOTE,
        }
        for item in value["fact_manifest"]
    ]
    coverage = [
        {
            "target": target,
            "definition": "occupied_physical_beds_at_boundary_v1" if target == core.TARGETS[0] else "ward_physical_day_events_v1",
            "same_scope_confirmed": "confirmed",
            "same_definition_confirmed": "confirmed",
            "same_method_confirmed": "confirmed",
            "basis_note": NOTE,
        }
        for target in core.TARGETS
    ]
    return {**case["period"], "days": days, "target_coverage": coverage, "member_reviews": reviews}


def snapshot(db, case, values=None):
    request = series_request(db, case) if values is None else values
    return series.capture_input(db, case["director"], request, str(uuid.uuid4()), expected_collection_digest=collection(db, case)["collection_digest"])


def test_actual_preview_closed_collection_and_full_private_public_projection(db_session, series_case):
    case = series_case
    preview = series.preview_input(db_session, case["director"], case["period"])
    assert "facts" not in preview and len(preview["day_groups"]) == 112 and len(preview["fact_manifest"]) == 5
    value = snapshot(db_session, case)
    assert series.verify_snapshot(value) is value
    public = series.project_source(value, "a" * 64)
    assert core.BedSource.model_validate(public).content_hash == facts.hash_content(value)
    assert public["member_manifest_hash"] == facts.hash_content(public["member_manifest"])
    assert public["member_manifest_hash"] != value["manifest_digest"]
    assert public["source_id"] == f"bed_series:{value['series_id']}:{facts.hash_content(value)[:12]}"
    assert public["census_observations"][0]["occupied_beds"] == count(0)
    assert public["census_observations"][0]["coverage"] == "unknown"
    assert public["flow_observations"][0]["transfer_in_events"] == count()
    assert public["flow_observations"][0]["transfer_out_events"] == count(None, "not_recorded")
    assert public["capacity_intervals"][0]["staff_readiness"] == "unknown"
    assert all("immediate_admittable_slots" not in item for item in public["capacity_intervals"])
    assert NOTE not in facts.canonical_json(public) and "department_id" not in facts.canonical_json(public) and "bed_id" not in facts.canonical_json(public)
    assert public["days"][-1]["flow_source_id"] == next(item["source_id"] for item in value["fact_manifest"] if item["source_record_id"] == case["flow"].source_record_id)
    draft = next(item["source"] for item in value["facts"] if item["source"]["source_record_id"] == case["draft"].source_record_id)
    assert draft["status"] == "draft" and all(draft[key] is None for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))


@pytest.mark.parametrize("change", ["short", "long", "future", "timezone", "bool", "datelexeme"])
def test_strict_period_and_current_last_closed_day(db_session, series_case, change):
    values = copy.deepcopy(series_case["period"])
    if change == "short":
        values["date_from"] = "2026-10-01"
    elif change == "long":
        values["date_from"] = "2025-01-01"
    elif change == "future":
        values["date_from"], values["date_to"] = "2026-07-02", "2026-10-20"
    elif change == "timezone":
        values["business_timezone"] = "fake/zone"
    elif change == "bool":
        values["ward_id"] = True
    else:
        values["date_from"] = "2026-7-1"
    with pytest.raises((HTTPException, ValidationError)):
        series.preview_input(db_session, series_case["director"], values)


def test_date_freshness_is_not_own_historical_integrity(db_session, series_case, monkeypatch):
    value = snapshot(db_session, series_case)
    original = facts.canonical_json(value)
    monkeypatch.setattr(series, "utcnow", lambda: NOW + datetime.timedelta(days=30))
    assert series.verify_snapshot(value) is value
    assert series.project_source(value, "a" * 64)["as_of"] == facts.utc_text(NOW)
    assert series.current_collection(db_session, series_case["director"], series_case["ward"].ward_id, request=value["request"])["collection_digest"] == value["collection_digest"]
    with pytest.raises(HTTPException, match="409"):
        series.validate_series_period(value["request"])
    assert facts.canonical_json(value) == original


@pytest.mark.parametrize(
    "change", ["omit_review", "duplicate_review", "wrong_hash", "wrong_group", "wrong_kind", "omit_day", "splice_flow", "unreferenced_confirmed", "capacity_unknown", "false_bool"]
)
def test_full_member_and_whole_day_binding_rejects_tampering(db_session, series_case, change):
    case = series_case
    values = series_request(db_session, case)
    if change == "omit_review":
        values["member_reviews"].pop()
    elif change == "duplicate_review":
        values["member_reviews"].append(copy.deepcopy(values["member_reviews"][0]))
    elif change == "wrong_hash":
        values["member_reviews"][0]["expected_content_hash"] = "f" * 64
    elif change == "wrong_group":
        values["days"][-1]["flow_group_digest"] = "f" * 64
    elif change == "wrong_kind":
        values["member_reviews"][0]["kind"] = "flow_day" if values["member_reviews"][0]["kind"] != "flow_day" else "census"
    elif change == "omit_day":
        values["days"].pop()
    elif change == "splice_flow":
        values["days"][-1]["flow_quantities"] = {"admission_events": count(0)}
    elif change == "unreferenced_confirmed":
        values["days"][-1].update(census_source_record_id=None, census_selection_reason="missing")
    elif change == "capacity_unknown":
        next(item for item in values["member_reviews"] if item["kind"] == "capacity_interval")["selection"] = "unknown"
    else:
        values["target_coverage"][0]["same_method_confirmed"] = True
    with pytest.raises((HTTPException, ValidationError)):
        snapshot(db_session, case, values)


def test_duplicate_same_counts_still_changes_full_collection_and_requires_all_reviews(db_session, series_case):
    case = series_case
    before = collection(db_session, case)
    values = series_request(db_session, case)
    duplicate = original(db_session, case, "census")
    after = collection(db_session, case)
    assert before["collection_digest"] != after["collection_digest"] and len(after["fact_manifest"]) == len(before["fact_manifest"]) + 1
    assert len(after["day_groups"][-1]["census_candidates"]) == 2
    with pytest.raises(HTTPException, match="409"):
        series.capture_input(db_session, case["director"], values, str(uuid.uuid4()), expected_collection_digest=before["collection_digest"])
    # Explicitly exclude the new equal-value original; never silently pick latest.
    full = series_request(db_session, case)
    member = next(item for item in full["member_reviews"] if item["source_record_id"] == duplicate.source_record_id)
    assert member["selection"] == "excluded"
    assert len(series.project_source(snapshot(db_session, case, full), "a" * 64)["census_observations"]) == 1


def test_normal_status_type_room_price_and_ward_count_do_not_change_current_binding(db_session, series_case):
    case = series_case
    before = collection(db_session, case)
    case["bed"].status, case["bed"].bed_type, case["bed"].room_no, case["bed"].price_per_day = 2, "单人", "NEW", 123
    case["ward"].status, case["ward"].bed_count = 1, 3000
    db_session.commit()
    after = collection(db_session, case)
    assert after["collection_digest"] == before["collection_digest"]
    assert after["ward_capture_evidence"] != before["ward_capture_evidence"]
    db_session.add(Bed(ward_id=case["ward"].ward_id, bed_no="NEW", status=2))
    db_session.commit()
    member_change = collection(db_session, case)
    assert member_change["current_membership_digest"] != before["current_membership_digest"]
    assert member_change["historical_collection_digest"] == before["historical_collection_digest"]


def test_source_governance_late_creation_and_member_transfer_are_current_changes(db_session, series_case):
    case = series_case
    before = collection(db_session, case)
    facts.revoke_source(db_session, case["super"], "census", case["census"].source_record_id, {"expected_revision": 2, "reason": "合成原件已撤销，验证当前清单变化"})
    db_session.commit()
    after = collection(db_session, case)
    assert after["historical_collection_digest"] != before["historical_collection_digest"]
    assert next(item for item in after["fact_manifest"] if item["source_record_id"] == case["census"].source_record_id)["eligible"] is False
    case["bed"].ward_id = case["foreign_ward"].ward_id
    db_session.commit()
    assert collection(db_session, case)["current_membership_digest"] != after["current_membership_digest"]


def test_unrelated_lifetime_sources_do_not_fill_related_cap_or_change_digest(db_session, series_case, monkeypatch):
    case = series_case
    before = collection(db_session, case)
    monkeypatch.setattr(series, "MAX_MEMBERS", len(before["facts"]))
    for _ in range(4):
        original(db_session, case, "census", "2024-01-01")
    after = collection(db_session, case)
    assert after["collection_digest"] == before["collection_digest"]
    with pytest.raises(HTTPException, match="422"):
        original(db_session, case, "census")
        collection(db_session, case)


def test_scan_bound_never_silently_truncates(db_session, series_case, monkeypatch):
    monkeypatch.setattr(series, "MAX_SCANNED", 2)
    with pytest.raises(HTTPException, match="422"):
        collection(db_session, series_case)


def test_even_unrelated_bad_original_body_cannot_be_skipped_by_forged_date(db_session, series_case):
    case = series_case
    row = original(db_session, case, "census", "2024-01-01")
    row.content_hash = "f" * 64
    db_session.commit()
    with pytest.raises(HTTPException, match="409"):
        collection(db_session, case)


def test_timezone_incompatible_related_whole_original_requires_explicit_exclusion(db_session, series_case):
    case = series_case
    start, end = facts.day_bounds("2026-10-19", "Asia/Shanghai")
    row = original(db_session, case, "flow_day", values={"business_timezone": "Asia/Shanghai", "day_start_at": start, "day_end_at": end, "observed_at": end})
    groups = collection(db_session, case)["day_groups"]
    candidate = next(item for item in groups[-1]["flow_candidates"] if item["source_record_id"] == row.source_record_id)
    assert candidate["compatible"] is False and "different_original_business_timezone" in candidate["exclusion_reasons"]
    values = series_request(db_session, case)
    next(item for item in values["member_reviews"] if item["source_record_id"] == row.source_record_id)["selection"] = "unknown"
    with pytest.raises(HTTPException, match="409"):
        snapshot(db_session, case, values)
    assert series.verify_snapshot(snapshot(db_session, case))


def test_last_future_census_endpoint_needs_containing_scenario_not_interval_ending_there(db_session, series_case):
    case = series_case
    period = series.period_bounds(series.SeriesPeriodRequest.model_validate(case["period"]))
    row = original(
        db_session,
        case,
        "capacity_interval",
        values={
            "basis_kind": "reviewed_future_scenario",
            "start_at": period["future_end_at"],
            "end_at": facts.utc_text(facts.instant(period["future_end_at"]) + datetime.timedelta(hours=1)),
            "observed_at": None,
            "immediate_admittable_slots": count(),
            "immediate_slots_observed_at": None,
        },
    )
    value = collection(db_session, case)
    assert row.source_record_id in {item["source_record_id"] for item in value["fact_manifest"]}
    # Genuine capacity just before the history is unrelated even if its parent later changes.
    old = original(db_session, case, "capacity_interval", values={"start_at": "2024-01-01T00:00:00.000000Z", "end_at": "2024-01-02T00:00:00.000000Z", "observed_at": "2024-01-02T00:00:00.000000Z"})
    assert old.source_record_id not in {item["source_record_id"] for item in collection(db_session, case)["fact_manifest"]}


def test_old_department_candidates_are_metadata_only_without_source_management_scope_bypass(db_session, series_case):
    case = series_case
    case["ward"].department_id = case["foreign"].department_id
    db_session.commit()
    old = facts.create_source(db_session, case["super"], "census", {"ward_id": case["ward"].ward_id, "payload": payload("census")})
    facts.review_source(
        db_session, case["super"], "census", old.source_record_id, {"expected_revision": 1, "expected_content_hash": old.content_hash, "decision": "publish", "review_basis_note": NOTE}
    )
    db_session.commit()
    case["ward"].department_id = case["department"].department_id
    db_session.commit()
    with pytest.raises(HTTPException, match="403"):
        facts.source_current(db_session, case["director"], "census", old.source_record_id)
    record = next(item for item in collection(db_session, case)["facts"] if item["source"]["source_record_id"] == old.source_record_id)
    assert record["source"]["eligible"] is False and record["source"]["payload"] is record["source"]["review_basis_note"] is None
    assert "occupied_beds" not in record["locator"] and "external_record_key" not in record["locator"]
    assert series.verify_snapshot(snapshot(db_session, case))


@pytest.mark.parametrize("change", ["quantity", "manifest", "cohort", "group", "mapping_extra", "recipe", "locator", "redacted_notes"])
def test_frozen_self_proof_rejects_false_or_incomplete_projection_inputs(db_session, series_case, change):
    value = snapshot(db_session, series_case)
    if change == "quantity":
        next(item["source"] for item in value["facts"] if item["source"]["source_kind"] == "census" and item["source"]["eligible"])["payload"]["occupied_beds"] = count(999)
    elif change == "manifest":
        value["fact_manifest"].pop()
    elif change == "cohort":
        value["bed_cohort"] = []
    elif change == "group":
        value["day_groups"][-1]["census_candidates"] = []
    elif change == "mapping_extra":
        value["mapping"] = {}
    elif change == "recipe":
        value["algorithm"]["recipe"]["version"] = "altered-without-own-hash"
    elif change == "locator":
        value["facts"][0]["locator"]["observed_at"] = "2026-10-20T00:00:00.000099Z"
    else:
        next(item["source"] for item in value["facts"] if not item["source"]["eligible"])["review_basis_note"] = NOTE
    with pytest.raises(HTTPException, match="409"):
        series.verify_snapshot(value)


def test_old_frozen_recipe_is_preserved_for_own_audit_but_rejected_for_new_current_math(db_session, series_case):
    value = snapshot(db_session, series_case)
    value["algorithm"]["recipe"]["version"] = "old-compatible-shape"
    value["algorithm"]["recipe_digest"] = facts.hash_content(value["algorithm"]["recipe"])
    assert series.verify_snapshot(value) is value
    old = series.project_source(value, "a" * 64, validate_current_recipe=False)
    assert old["recipe_digest"] == value["algorithm"]["recipe_digest"]
    with pytest.raises(HTTPException, match="409"):
        series.project_source(value, "a" * 64)


def test_capture_late_related_member_locked_recheck_and_real_sql_shapes(db_session, series_case, monkeypatch):
    case = series_case
    values = series_request(db_session, case)
    real = series.current_collection
    calls = []

    def changed(db, user, ward_id, *, request, locking=False):
        calls.append(locking)
        if locking:
            original(db, case, "census")
        return real(db, user, ward_id, request=request, locking=locking)

    monkeypatch.setattr(series, "current_collection", changed)
    with pytest.raises(HTTPException, match="409"):
        series.capture_input(db_session, case["director"], values, str(uuid.uuid4()))
    assert calls == [False, True]
    assert str(facts.current_query(db_session.query(Bed).filter_by(ward_id=case["ward"].ward_id), locking=True).statement.compile(dialect=mysql.dialect())).endswith("FOR UPDATE")


def test_actual_all_current_collection_queries_use_populate_and_lock_when_requested(db_session, series_case):
    statements = []

    def capture(conn, cursor, statement, params, context, executemany):
        if statement.startswith("SELECT"):
            compiled = context.compiled.statement
            statements.append((statement, compiled._for_update_arg is not None))

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        value = collection(db_session, series_case, locking=True)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)
    # The first Ward read identifies which Department must be locked; the second
    # Ward read is locked and rechecks that actual binding. SQLite ignores locks.
    for table in ("hoimsystem_users", "hoimsystem_department", "hoimsystem_doctor", "hoimsystem_bed", "hoimsystem_ai_bed_source"):
        matched = [locked for statement, locked in statements if f"FROM {table} " in statement or f"FROM {table}\n" in statement]
        assert matched and all(matched), (table, statements)
    assert value["collection_digest"]
    with Session(db_session.get_bind()) as second:
        second.query(Bed).filter_by(bed_id=series_case["bed"].bed_id).update({"ward_id": series_case["foreign_ward"].ward_id}, synchronize_session=False)
        second.commit()
    assert collection(db_session, series_case, locking=True)["collection_digest"] != value["collection_digest"]


def test_complete_bytes_cap_does_not_truncate_private_or_public(db_session, series_case, monkeypatch):
    value = snapshot(db_session, series_case)
    monkeypatch.setattr(series, "MAX_BYTES", len(facts.canonical_json(value).encode()) - 1)
    with pytest.raises(HTTPException, match="409"):
        series.verify_snapshot(value)
    monkeypatch.setattr(series, "MAX_BYTES", 512)
    with pytest.raises(HTTPException, match="422"):
        collection(db_session, series_case)


def test_actual_224_daily_originals_native_forecast_and_each_unknown_target_independently(db_session, series_case):
    from app.ai.bed_config import runtime_descriptor, runtime_from_descriptor
    from app.ai.bed_model import compute_bed

    case = series_case
    days = series.period_bounds(series.SeriesPeriodRequest.model_validate(case["period"]))["business_dates"]
    originals = {kind: [original(db_session, case, kind, day, known=True) for day in days] for kind in ("census", "flow_day")}
    chosen = {row.source_record_id for rows in originals.values() for row in rows} | {case["capacity"].source_record_id, case["future"].source_record_id}
    base = snapshot(db_session, case, series_request(db_session, case, chosen=chosen))
    source = series.project_source(base, "a" * 64)
    runtime = runtime_from_descriptor(runtime_descriptor())
    analysis = compute_bed(source, 7, "a" * 64, runtime)
    assert [item.status for item in analysis.targets] == ["complete"] * 5
    assert analysis.targets[0].forecast[0].point.numerator == "12"
    assert analysis.targets[0].backtest.forecast_pair_count == 196
    assert analysis.targets[0].backtest.unique_target_dates == 34
    assert len(base["facts"]) == 229 and len(source["census_observations"]) == len(source["flow_observations"]) == 112
    for index, field in enumerate(("occupied_beds", "admission_events", "discharge_events", "transfer_in_events", "transfer_out_events")):
        kind = "census" if index == 0 else "flow_day"
        replacement = original(db_session, case, kind, days[-1], known=True, values={field: count(None, "not_recorded")})
        selected = chosen - {originals[kind][-1].source_record_id} | {replacement.source_record_id}
        captured = snapshot(db_session, case, series_request(db_session, case, chosen=selected))
        public = series.project_source(captured, "a" * 64)
        result = compute_bed(public, 7, "a" * 64, runtime)
        assert [item.status for item in result.targets] == ["input_unknown" if position == index else "complete" for position in range(5)]
        unknown = public["census_observations"] if kind == "census" else public["flow_observations"]
        assert next(item for item in unknown if item["ref"]["source_record_id"] == replacement.source_record_id)[field] == count(None, "not_recorded")
        assert result.targets[index].forecast is None and result.targets[index].observed_sum is None
        assert all(item.forecast is not None for position, item in enumerate(result.targets) if position != index)
