"""Actual governed SKU originals, current authority and frozen proof closure."""

import copy
import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect

from app.ai import inventory_native_collection as collection
from app.ai import inventory_native_sources as s
from app.ai import supply_sources as units
from app.ai.inventory_native_source_models import AIInventoryNativeSource
from app.ai.models import AIAuditEvent
from app.models import User
from tests.test_ai_inventory_native_source_input import NOTE, UNIT, candidate, future, observation, request
from tests.test_ai_supply_sources import supply_case as supply_case
from tests.test_ai_supply_sources import unit_request

NOW = datetime.datetime(2026, 10, 21, 12, 0, 0, 123456)


@pytest.fixture
def inventory_case(supply_case, db_session, monkeypatch):
    case = supply_case
    monkeypatch.setattr(s, "utcnow", lambda: NOW)
    monkeypatch.setattr(collection, "utcnow", lambda: NOW)
    monkeypatch.setattr(units, "utcnow", lambda: NOW)
    body = unit_request(case)
    body["payload"]["original_unit_text"] = UNIT
    unit = units.create_unit(db_session, case["pharmacist"], body)
    db_session.commit()
    units.review_source(db_session, case["super"], "unit", unit.unit_definition_id, {"expected_revision": 1, "expected_content_hash": unit.content_hash, "decision": "publish", "basis_note": NOTE})
    db_session.commit()
    return {**case, "unit": unit}


def source_request(case, kind="inventory_observation", *, confirmed=False, with_unit=True):
    builders = {"inventory_observation": observation, "future_quantity_scenario": future, "purchase_candidate_plan": candidate}
    body = request(builders[kind]())
    body["item_id"] = case["drug"].pharmaceutical_id
    unit = case["unit"] if with_unit else None
    body.update(
        unit_definition_id=None if unit is None else unit.unit_definition_id,
        expected_unit_content_hash=None if unit is None else unit.content_hash,
        expected_unit_governance_hash=None if unit is None else units.hash_content(units.governance(unit)),
    )
    if confirmed:
        body["payload"]["professional_attestation"] = {"status": "confirmed", "signer_user_id": case["pharmacist"].user_id, "basis_note": NOTE}

        def confirm(value):
            if isinstance(value, dict):
                if set(value) == {"value", "absent_reason", "original_unit_text", "unit_review"}:
                    value.update(unit_review="confirmed", original_unit_text=UNIT)
                for child in value.values():
                    confirm(child)
            elif isinstance(value, list):
                for child in value:
                    confirm(child)

        confirm(body["payload"])
        if kind == "inventory_observation":
            body["payload"]["legacy_quantity_unit_review"] = "confirmed"
    return body


def publish(db, case, row, *, decision="publish"):
    s.review_source(db, case["super"], row.source_record_id, {"expected_revision": row.revision, "expected_content_hash": row.content_hash, "decision": decision, "basis_note": NOTE})
    db.commit()
    return row


@pytest.mark.parametrize("kind", ["inventory_observation", "future_quantity_scenario", "purchase_candidate_plan"])
def test_three_actual_sources_full_originals_and_technical_publication_do_not_infer_completeness(db_session, inventory_case, kind):
    case = inventory_case
    body = source_request(case, kind, confirmed=True)
    row = s.create_source(db_session, case["pharmacist"], body)
    db_session.commit()
    before = s.source_current(db_session, case["admin"], row.source_record_id)
    assert before["status"] == "draft" and before["parent_current"] and not before["eligible"]
    assert before["professional_status"] == "confirmed" and s.verify_source_wrapper(before)
    original_hash = row.content_hash
    publish(db_session, case, row)
    value = s.source_current(db_session, case["admin"], row.source_record_id)
    assert value["eligible"] and value["content_hash"] == original_hash and value["reviewed_by"] == case["super"].user_id
    assert value["recorded_at"] == "2026-10-21T12:00:00.123456Z" and value["payload"] == body["payload"]
    assert s.verify_original_proof(s.source_proof(row))
    assert case["drug"].stock == 37


@pytest.mark.parametrize("role", ["admin", "director", "super"])
def test_technical_roles_explicit_unknown_are_readable_eligible_but_cannot_professionally_sign(db_session, inventory_case, role):
    case = inventory_case
    row = s.create_source(db_session, case[role], source_request(case, with_unit=False))
    db_session.commit()
    publish(db_session, case, row)
    value = s.source_current(db_session, case[role], row.source_record_id)
    assert value["eligible"] and value["professional_status"] == "unknown" and value["signer_user_id"] is None and value["unit_definition_id"] is None
    with pytest.raises(HTTPException) as failure:
        s.create_source(db_session, case[role], source_request(case, confirmed=True))
    assert failure.value.status_code == 403


def test_current_actual_actor_never_uses_cached_identity_and_read_sql_is_current(db_session, inventory_case):
    case = inventory_case
    row = s.create_source(db_session, case["admin"], source_request(case))
    db_session.commit()
    actor = case["admin"]
    identifier = actor.user_id
    db_session.query(User).filter_by(user_id=identifier).update({"user_role": "patient"}, synchronize_session=False)
    record_id = inspect(row).identity[0]
    seen = []
    connection = db_session.connection()

    def track(c, cursor, sql, args, context, many):
        seen.append(sql)

    event.listen(connection, "before_cursor_execute", track)
    try:
        with pytest.raises(HTTPException) as failure:
            s.source_current(db_session, actor, record_id, audit_only=False)
        assert failure.value.status_code == 403
    finally:
        event.remove(connection, "before_cursor_execute", track)
    assert not any("payload_json" in q for q in seen)


def test_pharmacist_role_change_or_unit_revoke_redacts_ordinary_but_keeps_super_original(db_session, inventory_case):
    case = inventory_case
    row = s.create_source(db_session, case["pharmacist"], source_request(case, confirmed=True))
    db_session.commit()
    publish(db_session, case, row)
    db_session.query(User).filter_by(user_id=case["pharmacist"].user_id).update({"user_role": "patient"}, synchronize_session=False)
    db_session.commit()
    value = s.source_current(db_session, case["admin"], row.source_record_id)
    assert not value["eligible"] and "professional_signature_changed" in value["exclusion_reasons"]
    assert all(value[k] is None for k in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    frozen = s.source_current(db_session, case["super"], row.source_record_id, audit_only=True)
    assert frozen["payload"]["professional_attestation"]["status"] == "confirmed" and s.verify_source_wrapper(frozen)


def test_unknown_observation_never_gains_observed_time_from_technical_capture(db_session, inventory_case):
    case = inventory_case
    body = source_request(case)
    body["payload"].update(method="legacy_current_capture", observed_at=None)
    row = s.create_source(db_session, case["admin"], body)
    db_session.commit()
    publish(db_session, case, row)
    value = s.source_current(db_session, case["admin"], row.source_record_id)
    assert value["payload"]["observed_at"] is None and value["parent_binding"]["legacy_snapshot"]["captured_at"] == value["recorded_at"]


def test_any_original_stock_change_invalidates_old_observation_but_not_future_scenario(db_session, inventory_case):
    case = inventory_case
    a = s.create_source(db_session, case["admin"], source_request(case))
    b = s.create_source(db_session, case["admin"], source_request(case, "future_quantity_scenario"))
    db_session.commit()
    publish(db_session, case, a)
    publish(db_session, case, b)
    case["drug"].stock = 4
    db_session.commit()
    old = s.source_current(db_session, case["admin"], a.source_record_id)
    assert not old["eligible"] and "legacy_inventory_changed" in old["exclusion_reasons"] and old["payload"] is None
    assert s.source_current(db_session, case["admin"], b.source_record_id)["eligible"]


def test_governance_cas_author_revoke_reject_and_frozen_audit(db_session, inventory_case):
    case = inventory_case
    row = s.create_source(db_session, case["admin"], source_request(case))
    db_session.commit()
    original_hash = row.content_hash
    rid = row.source_record_id
    with pytest.raises(HTTPException) as e:
        s.review_source(db_session, case["director"], rid, {"expected_revision": 1, "expected_content_hash": original_hash, "decision": "publish", "basis_note": NOTE})
    assert e.value.status_code == 403
    publish(db_session, case, row)
    with pytest.raises(HTTPException) as e:
        s.review_source(db_session, case["super"], rid, {"expected_revision": 1, "expected_content_hash": original_hash, "decision": "publish", "basis_note": NOTE})
    assert e.value.status_code == 409
    s.review_source(db_session, case["admin"], rid, {"expected_revision": 2, "expected_content_hash": original_hash, "basis_note": "😀" * 1000}, revoke=True)
    db_session.commit()
    normal = s.source_current(db_session, case["admin"], rid)
    assert normal["status"] == "revoked" and normal["payload"] is None and not normal["can_revoke"]
    audit = s.source_current(db_session, case["super"], rid, audit_only=True)
    assert audit["revoke_reason"] == "😀" * 1000 and audit["content_hash"] == original_hash
    other = s.create_source(db_session, case["admin"], source_request(case))
    db_session.commit()
    publish(db_session, case, other, decision="reject")
    assert s.source_current(db_session, case["admin"], other.source_record_id)["payload"] is None


@pytest.mark.parametrize("mutation", ["payload", "parent", "header", "governance", "unit", "signer", "clock"])
def test_rehashed_forged_original_relations_fail_closed(db_session, inventory_case, mutation):
    case = inventory_case
    row = s.create_source(db_session, case["pharmacist"], source_request(case, confirmed=True))
    db_session.commit()
    proof = s.source_proof(row)
    bad = copy.deepcopy(proof)
    if mutation == "payload":
        bad["payload"]["unexpected"] = False
    elif mutation == "parent":
        bad["parent_binding"]["unexpected"] = False
    elif mutation == "header":
        bad["date_from"] = "2026-11-01"
    elif mutation == "governance":
        bad["revision"] = 2
    elif mutation == "unit":
        bad["parent_binding"]["unit_definition"] = None
    elif mutation == "signer":
        bad["parent_binding"]["signer"]["user_id"] += 1
    elif mutation == "clock":
        bad["payload"]["observed_at"] = "2026-10-21T12:00:00.123457Z"
    bad["content_hash"] = s.hash_content({**{k: bad[k] for k in s.IDENTITY_FIELDS}, "payload": bad["payload"], "parent_binding": bad["parent_binding"]})
    bad["source_id"] = f"inventory_fact:{bad['source_record_id']}:{bad['content_hash'][:12]}"
    assert not s.verify_original_proof(bad)


def test_audit_failure_rolls_back_original_governance_and_audit_without_committing_stock(db_session, inventory_case, monkeypatch):
    case = inventory_case
    before = db_session.query(AIInventoryNativeSource).count()
    audit_before = db_session.query(AIAuditEvent).count()

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(s.audit, "audit", fail)
    with pytest.raises(RuntimeError):
        s.create_source(db_session, case["admin"], source_request(case))
    assert db_session.query(AIInventoryNativeSource).count() == before and db_session.query(AIAuditEvent).count() == audit_before
    assert case["drug"].stock == 37
