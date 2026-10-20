"""Actual governed originals→full captures→reviewed series, never real inventory."""

import copy
import datetime

import pytest
from fastapi import HTTPException

from app.ai import governance
from app.ai import supply_contract as core
from app.ai import supply_series as series
from app.ai import supply_series_input as inputs
from app.ai import supply_sources as facts
from app.ai.models import AIAuditEvent
from app.ai.supply_series_models import AISupplySeries
from app.ai.supply_snapshot import verify_snapshot
from app.models import Pharmaceutical, User
from tests.test_ai_supply_series_input import declared_request, period_values
from tests.test_ai_supply_sources import NOTE, NOW, create_unit, publish, source_request
from tests.test_ai_supply_sources import supply_case as supply_case


@pytest.fixture
def series_case(supply_case, db_session, monkeypatch):
    from app.ai import supply_collection

    monkeypatch.setattr(inputs, "utcnow", lambda: NOW)
    monkeypatch.setattr(series, "utcnow", lambda: NOW)
    monkeypatch.setattr(supply_collection, "utcnow", lambda: NOW, raising=False)
    case = supply_case
    case["unit"] = create_unit(db_session, case)
    case["rows"] = []
    for target in core.TARGETS:
        row = facts.create_source(db_session, case["pharmacist"], source_request(case, case["unit"], target))
        db_session.commit()
        publish(db_session, case, "daily", row)
        case["rows"].append(row)
    return case


def request_for(db, case):
    period = period_values() | {"item_id": case["drug"].pharmaceutical_id, "timezone": "Asia/Shanghai"}
    preview = inputs.preview_input(db, case["admin"], period)
    c = preview["collection"]
    unit = case["unit"]
    selected = {}
    for group in preview["groups"]:
        eligible = [m for m in group["members"] if m["eligible"] and m["status"] == "published"]
        selected[(group["date"], group["target"])] = eligible[0]["source_record_id"] if len(eligible) == 1 else None
    body = (
        declared_request()
        | period
        | {"unit_definition_id": unit.unit_definition_id, "expected_unit_content_hash": unit.content_hash, "expected_unit_governance_hash": core.hash_content(facts.governance(unit))}
    )
    for day in body["days"]:
        for choice in day["selections"]:
            group = next(g for g in preview["groups"] if (g["date"], g["target"]) == (day["date"], choice["target"]))
            chosen = selected[(day["date"], choice["target"])]
            choice.update(
                source_record_id=chosen,
                absent_reason=None if chosen else "unresolved_conflict" if len([m for m in group["members"] if m["eligible"] and m["status"] == "published"]) > 1 else "missing_selected_original",
                group_digest=group["group_digest"],
            )
    chosen = {v for v in selected.values() if v is not None}
    body["member_reviews"] = [
        {
            "source_record_id": s["source_record_id"],
            "source_kind": s["source_kind"],
            "expected_content_hash": s["content_hash"],
            "expected_governance_hash": s["governance_hash"],
            "selection": "confirmed"
            if (s["source_kind"] == "unit_definition" and s["source_record_id"] == unit.unit_definition_id) or s["source_record_id"] in chosen
            else "excluded"
            if not s["eligible"]
            else "unknown",
            "basis_note": NOTE,
        }
        for r in c["unit_definitions"] + c["source_records"]
        for s in [r["source"]]
    ]
    for declaration in body["target_coverage"]:
        declaration.update(same_scope_confirmed="confirmed", same_definition_confirmed="confirmed", same_method_confirmed="confirmed")
    return {"request": body, "expected_capture_digest": c["collection_digest"]}


def draft(db, case):
    row = series.create_series(db, case["admin"], request_for(db, case))
    db.commit()
    return row


def review_request(row, decision="publish"):
    return {"expected_revision": row.revision, "expected_content_hash": row.content_hash, "basis_note": NOTE, "decision": decision}


def published(db, case):
    row = draft(db, case)
    series.review_series(db, case["super"], row.series_id, review_request(row))
    db.commit()
    return row


def test_actual_whole_capture_profile_projection_and_independent_missing_targets(db_session, series_case):
    case = series_case
    row = published(db_session, case)
    current = series.series_current(db_session, case["director"], row.series_id)
    assert current["eligible"] and current["snapshot"] and current["public_source"]
    source = core.SupplySource.model_validate(current["public_source"])
    assert len(source.days) == 112 and len(source.observations) == 3 and len(source.member_manifest) == 3
    assert source.profile_content_hash == core.hash_content(current["snapshot"]["profile"]) and source.profile_governance_hash == current["governance_hash"]
    assert source.content_hash == row.content_hash and source.member_manifest_hash == core.hash_content(current["public_source"]["member_manifest"])
    assert len({source.item_token, source.scope_token, source.unit_token}) == 3
    text = core.canonical_json(source.model_dump())
    for raw in (case["drug"].name, "原明确计数包", NOTE, "professional_attestation", "signer_user_id", "sku_binding"):
        assert raw not in text
    assert all(o.quantity.value == "0.000000" and o.stock_constraint == "full" for o in source.observations)
    assert series.authorize_series(db_session, case["pharmacist"], row.series_id, 7)[0].series_id == row.series_id
    assert case["drug"].stock == 37 and case["consumable"].stock == 11


@pytest.mark.parametrize("role", ["pharmacist", "admin", "director"])
def test_ordinary_current_scope_cannot_perform_super_governance(db_session, series_case, role):
    case = series_case
    row = draft(db_session, case)
    with pytest.raises(HTTPException) as e:
        series.review_series(db_session, case[role], row.series_id, review_request(row))
    assert e.value.status_code == 403 and series.series_row(db_session, row.series_id).status == "draft"
    with pytest.raises(HTTPException) as e:
        series.series_current(db_session, case[role], row.series_id, audit_only=True)
    assert e.value.status_code == 403


def test_published_parameters_and_private_or_public_rehash_tampering_are_not_accepted(db_session, series_case):
    case = series_case
    row = published(db_session, case)
    snapshot, source = series.series_proof(row)
    bad = copy.deepcopy(snapshot)
    bad["profile"]["parameters"]["alpha_size"] = {"numerator": "1", "denominator": "5"}
    with pytest.raises(HTTPException):
        verify_snapshot(bad)
    original = row.projection_json
    forged = copy.deepcopy(source)
    forged["observations"][0]["quantity"]["value"] = "999.000000"
    row.projection_json = core.canonical_json(forged)
    row.projection_hash = core.hash_content(forged)
    db_session.flush()
    with pytest.raises(HTTPException) as e:
        series.series_current(db_session, case["super"], row.series_id, audit_only=True)
    assert e.value.status_code == 409
    db_session.rollback()
    assert series.series_row(db_session, row.series_id).projection_json == original


def test_nonwinner_new_same_quantity_root_invalidates_ordinary_but_super_frozen_keeps_own_proof(db_session, series_case):
    case = series_case
    row = published(db_session, case)
    sid = row.series_id
    original = series.series_current(db_session, case["super"], sid, audit_only=True)
    source = facts.create_source(db_session, case["pharmacist"], source_request(case, case["unit"], core.TARGETS[0]))
    db_session.commit()
    publish(db_session, case, "daily", source)
    ordinary = series.series_current(db_session, case["admin"], sid)
    assert not ordinary["eligible"] and not ordinary["source_current"]
    assert all(ordinary[k] is None for k in ("snapshot", "public_source", "local_resolution", "review_basis_note", "revoke_reason"))
    frozen = series.series_current(db_session, case["super"], sid, audit_only=True)
    assert frozen["snapshot"] == original["snapshot"] and frozen["public_source"] == original["public_source"] and not frozen["eligible"]
    with pytest.raises(HTTPException):
        series.authorize_series(db_session, case["super"], sid, 14)


def test_multiple_published_roots_stay_conflict_and_excluding_unfavorable_root_cannot_select_winner(db_session, series_case):
    case = series_case
    source = facts.create_source(db_session, case["pharmacist"], source_request(case, case["unit"], core.TARGETS[0]))
    db_session.commit()
    publish(db_session, case, "daily", source)
    body = request_for(db_session, case)
    choice = body["request"]["days"][-1]["selections"][0]
    assert choice["source_record_id"] is None and choice["absent_reason"] == "unresolved_conflict"
    row = series.create_series(db_session, case["admin"], body)
    db_session.commit()
    assert row.status == "draft"
    forged = copy.deepcopy(body)
    selected = case["rows"][0].source_record_id
    forged["request"]["days"][-1]["selections"][0].update(source_record_id=selected, absent_reason=None)
    for r in forged["request"]["member_reviews"]:
        if r["source_kind"] == "daily_quantity" and r["source_record_id"] in {selected, source.source_record_id}:
            r["selection"] = "confirmed" if r["source_record_id"] == selected else "excluded"
    before = db_session.query(AISupplySeries).count()
    with pytest.raises(HTTPException) as e:
        series.create_series(db_session, case["admin"], forged)
    assert e.value.status_code == 409 and db_session.query(AISupplySeries).count() == before


def test_unit_and_signer_current_changes_cannot_be_fixed_by_series_attestations(db_session, series_case):
    case = series_case
    row = published(db_session, case)
    db_session.query(User).filter_by(user_id=case["pharmacist"].user_id).update({"user_role": "admin"}, synchronize_session=False)
    db_session.commit()
    ordinary = series.series_current(db_session, case["admin"], row.series_id)
    assert not ordinary["eligible"] and ordinary["snapshot"] is None
    assert series.series_current(db_session, case["super"], row.series_id, audit_only=True)["snapshot"]


def test_stock_and_price_changes_are_not_historical_quantity_changes(db_session, series_case):
    case = series_case
    row = published(db_session, case)
    old = series.series_proof(row)
    db_session.query(Pharmaceutical).filter_by(pharmaceutical_id=case["drug"].pharmaceutical_id).update({"stock": 1, "price": "98.76"}, synchronize_session=False)
    db_session.commit()
    assert series.series_current(db_session, case["admin"], row.series_id)["eligible"]
    assert series.series_proof(row) == old


def test_history_older_date_reads_own_current_source_but_new_execute_rejects(db_session, series_case, monkeypatch):
    case = series_case
    row = published(db_session, case)
    monkeypatch.setattr(inputs, "utcnow", lambda: NOW + datetime.timedelta(days=1))
    assert series.authorize_series(db_session, case["admin"], row.series_id, 7, execution=False)[0].series_id == row.series_id
    old = series.series_current(db_session, case["admin"], row.series_id)
    assert old["source_current"] and old["snapshot"] and not old["eligible"]
    with pytest.raises(HTTPException) as e:
        series.authorize_series(db_session, case["super"], row.series_id, 7)
    assert e.value.status_code == 409


@pytest.mark.parametrize("fault", ["wrong_horizon", "extra_field", "wrong_scope", "bool_horizon"])
def test_closed_full_context_binding_rejects_even_valid_source_with_wrong_context(db_session, series_case, fault):
    case = series_case
    row = published(db_session, case)
    source = series.series_proof(row)[1]
    binding = series.binding_for(row, source) | {"schema_version": "supply_context_binding_v1", "horizon_days": 7}
    assert series.authorize_series(db_session, case["admin"], row.series_id, 7, binding=binding)
    if fault == "wrong_horizon":
        binding["horizon_days"] = 14
    elif fault == "extra_field":
        binding["patient_id"] = 1
    elif fault == "wrong_scope":
        binding["scope"] = "department"
    else:
        binding["horizon_days"] = True
    with pytest.raises(HTTPException) as e:
        series.authorize_series(db_session, case["admin"], row.series_id, 7, binding=binding)
    assert e.value.status_code == 409


@pytest.mark.parametrize("fault", ["audit_failure", "role_change_after_audit"])
def test_actual_sql_review_and_audit_postcheck_roll_back_entire_transaction(db_session, series_case, monkeypatch, fault):
    case = series_case
    row = draft(db_session, case)
    before = db_session.query(AIAuditEvent).count()
    sid = row.series_id
    uid = case["super"].user_id
    original = governance.audit

    def change(db, *args, **kwargs):
        original(db, *args, **kwargs)
        if fault == "audit_failure":
            raise RuntimeError("synthetic audit storage failure")
        db.query(User).filter_by(user_id=uid).update({"user_role": "admin"}, synchronize_session=False)

    monkeypatch.setattr(governance, "audit", change)
    with pytest.raises((HTTPException, RuntimeError)):
        series.review_series(db_session, case["super"], sid, review_request(row))
    saved = series.series_row(db_session, sid)
    assert saved.status == "draft" and saved.revision == 1 and saved.projection_json is None
    assert db_session.query(AIAuditEvent).count() == before and db_session.query(User).filter_by(user_id=uid).one().user_role == "super_admin"


def test_true_cas_revocation_and_super_frozen_after_sku_parent_change(db_session, series_case):
    case = series_case
    row = published(db_session, case)
    sid = row.series_id
    old = series.series_proof(row)
    db_session.query(Pharmaceutical).filter_by(pharmaceutical_id=case["drug"].pharmaceutical_id).update({"name": "原SKU身份已改变"}, synchronize_session=False)
    db_session.commit()
    req = {"expected_revision": 2, "expected_content_hash": row.content_hash, "basis_note": NOTE}
    series.revoke_series(db_session, case["super"], sid, req)
    db_session.commit()
    frozen = series.series_current(db_session, case["super"], sid, audit_only=True)
    assert frozen["status"] == "revoked" and frozen["revision"] == 3 and frozen["public_source"] == old[1]
    with pytest.raises(HTTPException) as e:
        series.revoke_series(db_session, case["super"], sid, req)
    assert e.value.status_code == 409


def complete_published(db, case):
    """Actual112×3 complete original declarations, all created/signed/reviewed now.

    The old measured day clocks are explicit synthetic observations; publication
    today is a current retrospective review, never historical availability.
    """
    period = inputs.SeriesPeriodRequest.model_validate(period_values() | {"item_id": case["drug"].pharmaceutical_id, "timezone": "Asia/Shanghai"})
    for index, day in enumerate(inputs.period_days(period)[:-1]):
        for target in core.TARGETS:
            body = source_request(case, case["unit"], target)
            body["payload"].update(
                date=day["date"],
                day_start_at=day["day_start_at"],
                day_end_at=day["day_end_at"],
                observed_at=inputs.utc_text(inputs.instant(day["day_end_at"]) + datetime.timedelta(hours=1)),
                quantity={"value": "4.000000" if index % 7 == 0 else "0.000000", "absent_reason": None},
            )
            row = facts.create_source(db, case["pharmacist"], body)
            db.commit()
            publish(db, case, "daily", row)
    return published(db, case)


def test_actual_full112_by_three_target_sources_project_without_truncation(db_session, series_case):
    row = complete_published(db_session, series_case)
    snapshot, source = series.series_proof(row)
    assert len(source["observations"]) == 112 * 3 and len(source["member_manifest"]) == 112 * 3
    assert len(snapshot["collection"]["unit_definitions"]) == 1 and len(snapshot["collection"]["source_records"]) == 336
    assert all(c["source_id"] is not None for d in source["days"] for c in d["selections"])
    core.SupplySource.model_validate(source)
    assert row.content_hash == core.hash_content(snapshot) and row.projection_hash == core.hash_content(source)
