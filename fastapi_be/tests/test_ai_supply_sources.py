"""Actual SKU/unit/day SQL invariants; no stock, dispense or purchase mutations."""

import copy
import datetime
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.dialects import mysql

from app.ai import supply_sources as s
from app.ai.supply_source_models import AISupplyDailyQuantity
from app.models import Consumable, Pharmaceutical, User
from tests.test_ai_supply_source_input import NOTE, daily

NOW = datetime.datetime(2026, 10, 20, 12, 0, 0, 123456)


@pytest.fixture
def supply_case(seed_data, db_session, monkeypatch):
    monkeypatch.setattr(s, "utcnow", lambda: NOW)
    drug = Pharmaceutical(name="原独立工程药品", barcode="supply-" + uuid.uuid4().hex, stock=37, price="12.34", status=0)
    consumable = Consumable(name="原独立工程耗材", category="手术类", stock=11, unit="套", status=0)
    db_session.add_all([drug, consumable])
    db_session.commit()
    return {
        "drug": drug,
        "consumable": consumable,
        "pharmacist": seed_data["pharmacist_user"],
        "super": seed_data["super_admin_user"],
        "admin": seed_data["admin_user"],
        "director": seed_data["director_user"],
        "nurse": seed_data["nurse_user"],
    }


def attestation(case, confirmed=True):
    return {"status": "confirmed" if confirmed else "unknown", "signer_user_id": case["pharmacist"].user_id if confirmed else None, "basis_note": NOTE if confirmed else None}


def unit_request(case, kind="pharmaceutical", confirmed=True):
    return {
        "item_kind": kind,
        "item_id": case["drug" if kind == "pharmaceutical" else "consumable"].pharmaceutical_id if kind == "pharmaceutical" else case["consumable"].consumable_id,
        "scope": "hospital_inventory",
        "payload": {"original_unit_text": "原明确计数包", "definition_basis_note": NOTE, "professional_attestation": attestation(case, confirmed)},
    }


def publish(db, case, kind, row, decision="publish"):
    rid = getattr(row, s.MODELS[kind][1])
    s.review_source(db, case["super"], kind, rid, {"expected_revision": row.revision, "expected_content_hash": row.content_hash, "decision": decision, "basis_note": NOTE})
    db.commit()
    return row


def create_unit(db, case, kind="pharmaceutical"):
    row = s.create_unit(db, case["pharmacist"], unit_request(case, kind))
    db.commit()
    return publish(db, case, "unit", row)


def source_request(case, unit=None, target="gross_fulfilled_issue_quantity"):
    values = daily()
    values["target"] = target
    if unit:
        values.update(original_unit_text="原明确计数包", unit_review="confirmed", coverage="attested_complete", professional_attestation=attestation(case))
    return {
        "item_kind": "pharmaceutical",
        "item_id": case["drug"].pharmaceutical_id,
        "scope": "hospital_inventory",
        "unit_definition_id": unit.unit_definition_id if unit else None,
        "expected_unit_content_hash": unit.content_hash if unit else None,
        "expected_unit_governance_hash": s.hash_content(s.governance(unit)) if unit else None,
        "payload": values,
    }


@pytest.mark.parametrize("target", ["recorded_request_quantity", "gross_fulfilled_issue_quantity", "confirmed_consumed_quantity"])
def test_actual_three_independent_originals_preserve_zero_clocks_unit_and_professional_confirmation(db_session, supply_case, target):
    case = supply_case
    unit = create_unit(db_session, case)
    request = source_request(case, unit, target)
    row = s.create_source(db_session, case["pharmacist"], request)
    db_session.commit()
    original = s.source_current(db_session, case["pharmacist"], "daily", row.source_record_id)
    assert original["payload"]["quantity"] == {"value": "0.000000", "absent_reason": None} and original["status"] == "draft" and not original["eligible"]
    assert original["payload"]["stock_constraint"] == "full" and original["observed_at"] < original["recorded_at"]
    assert original["signer_user_id"] == case["pharmacist"].user_id and s.verify_original_proof(s.source_proof("daily", row))
    publish(db_session, case, "daily", row)
    current = s.source_current(db_session, case["admin"], "daily", row.source_record_id)
    assert current["eligible"] and current["professional_status"] == "confirmed" and current["reviewed_by"] == case["super"].user_id
    assert case["drug"].stock == 37 and case["consumable"].stock == 11


@pytest.mark.parametrize("role", ["admin", "director", "super"])
def test_technical_roles_can_record_explicit_unknown_not_sign_or_infer_unit(db_session, supply_case, role):
    case = supply_case
    request = source_request(case)
    row = s.create_source(db_session, case[role], request)
    db_session.commit()
    publish(db_session, case, "daily", row)
    value = s.source_current(db_session, case[role], "daily", row.source_record_id)
    assert value["eligible"] and value["professional_status"] == "unknown" and value["signer_user_id"] is None and value["payload"]["unit_review"] == "unknown"
    request["payload"]["professional_attestation"] = attestation(case)
    with pytest.raises(HTTPException) as failure:
        s.create_source(db_session, case[role], request)
    assert failure.value.status_code == 403


def test_nurse_or_deleted_actual_identity_does_not_gain_hospital_inventory_scope(db_session, supply_case):
    case = supply_case
    with pytest.raises(HTTPException) as failure:
        s.create_unit(db_session, case["nurse"], unit_request(case, confirmed=False))
    assert failure.value.status_code == 403
    ghost = User(user_id=2147483600, username="missing", user_role="super_admin")
    with pytest.raises(HTTPException):
        s.current_actor(db_session, ghost)


def test_only_super_reviews_and_only_author_or_super_revokes_real_cas(db_session, supply_case):
    case = supply_case
    row = s.create_source(db_session, case["pharmacist"], source_request(case))
    db_session.commit()
    body = {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": "publish", "basis_note": NOTE}
    with pytest.raises(HTTPException) as failure:
        s.review_source(db_session, case["admin"], "daily", row.source_record_id, body)
    assert failure.value.status_code == 403
    publish(db_session, case, "daily", row)
    with pytest.raises(HTTPException) as stale:
        s.review_source(db_session, case["super"], "daily", row.source_record_id, body)
    assert stale.value.status_code == 409
    revoke = {"expected_revision": 2, "expected_content_hash": row.content_hash, "basis_note": NOTE}
    with pytest.raises(HTTPException) as unauthorized:
        s.review_source(db_session, case["director"], "daily", row.source_record_id, revoke, revoke=True)
    assert unauthorized.value.status_code == 403
    s.review_source(db_session, case["pharmacist"], "daily", row.source_record_id, revoke, revoke=True)
    db_session.commit()
    assert row.status == "revoked" and row.revision == 3
    redacted = s.source_current(db_session, case["pharmacist"], "daily", row.source_record_id)
    assert all(redacted[k] is None for k in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    assert s.source_current(db_session, case["super"], "daily", row.source_record_id, audit_only=True)["payload"]["quantity"]["value"] == "0.000000"


@pytest.mark.parametrize("kind", ["unit", "daily"])
def test_original_signer_role_change_invalidates_new_use_without_erasing_super_frozen_audit(db_session, supply_case, kind):
    case = supply_case
    unit = create_unit(db_session, case)
    row = unit if kind == "unit" else s.create_source(db_session, case["pharmacist"], source_request(case, unit))
    if kind == "daily":
        db_session.commit()
        publish(db_session, case, kind, row)
    rid = getattr(row, s.MODELS[kind][1])
    db_session.query(User).filter_by(user_id=case["pharmacist"].user_id).update({"user_role": "admin"}, synchronize_session=False)
    db_session.commit()
    ordinary = s.source_current(db_session, case["admin"], kind, rid)
    assert not ordinary["eligible"] and ordinary["payload"] is None and "professional_signature_changed" in ordinary["exclusion_reasons"]
    audit = s.source_current(db_session, case["super"], kind, rid, audit_only=True)
    assert audit["payload"]["professional_attestation"]["status"] == "confirmed" and not audit["parent_current"]


def test_mutable_stock_price_do_not_fabricate_history_but_real_sku_identity_changes_do_invalidate(db_session, supply_case):
    case = supply_case
    unit = create_unit(db_session, case)
    row = s.create_source(db_session, case["pharmacist"], source_request(case, unit))
    db_session.commit()
    publish(db_session, case, "daily", row)
    db_session.query(Pharmaceutical).filter_by(pharmaceutical_id=case["drug"].pharmaceutical_id).update({"stock": 2, "price": "99.99"}, synchronize_session=False)
    db_session.commit()
    assert s.source_current(db_session, case["admin"], "daily", row.source_record_id)["eligible"]
    db_session.query(Pharmaceutical).filter_by(pharmaceutical_id=case["drug"].pharmaceutical_id).update({"name": "身份已变"}, synchronize_session=False)
    db_session.commit()
    assert s.source_current(db_session, case["admin"], "daily", row.source_record_id)["payload"] is None


def test_unit_revocation_invalidates_all_dependent_daily_sources_and_new_expected_binding(db_session, supply_case):
    case = supply_case
    unit = create_unit(db_session, case)
    request = source_request(case, unit)
    row = s.create_source(db_session, case["pharmacist"], request)
    db_session.commit()
    publish(db_session, case, "daily", row)
    s.review_source(db_session, case["super"], "unit", unit.unit_definition_id, {"expected_revision": 2, "expected_content_hash": unit.content_hash, "basis_note": NOTE}, revoke=True)
    db_session.commit()
    value = s.source_current(db_session, case["admin"], "daily", row.source_record_id)
    assert not value["eligible"] and "unit_definition_changed" in value["exclusion_reasons"]
    with pytest.raises(HTTPException) as stale:
        s.create_source(db_session, case["pharmacist"], request)
    assert stale.value.status_code == 409


def test_original_unknown_can_be_confirmed_only_by_new_complete_original_not_update(db_session, supply_case):
    case = supply_case
    unknown = s.create_source(db_session, case["admin"], source_request(case))
    db_session.commit()
    publish(db_session, case, "daily", unknown)
    unit = create_unit(db_session, case)
    confirmed = s.create_source(db_session, case["pharmacist"], source_request(case, unit))
    db_session.commit()
    publish(db_session, case, "daily", confirmed)
    assert unknown.source_record_id != confirmed.source_record_id and unknown.content_hash != confirmed.content_hash
    assert s.source_current(db_session, case["admin"], "daily", unknown.source_record_id)["professional_status"] == "unknown"
    assert db_session.query(AISupplyDailyQuantity).filter_by(item_kind="pharmaceutical", item_id=case["drug"].pharmaceutical_id).count() == 2


def test_external_register_key_does_not_prevent_same_day_new_confirmed_or_conflicting_original(db_session, supply_case):
    case = supply_case
    request = source_request(case)
    request["payload"].update(method="external_register", external_record_key="原外部登记-未修改完整key")
    rows = []
    for value in ("0.000000", "8.125000"):
        body = copy.deepcopy(request)
        body["payload"]["quantity"]["value"] = value
        rows.append(s.create_source(db_session, case["admin"], body))
        db_session.commit()
    assert rows[0].source_record_id != rows[1].source_record_id


def test_bad_self_hash_or_rehashed_extra_parent_is_not_a_valid_frozen_original(db_session, supply_case):
    case = supply_case
    row = create_unit(db_session, case)
    proof = s.source_proof("unit", row)
    bad = copy.deepcopy(proof)
    bad["parent_binding"]["unexpected"] = "not trusted"
    body = {k: bad[k] for k in s.IDENTITY_FIELDS}
    bad["content_hash"] = s.hash_content({**body, "payload": bad["payload"], "parent_binding": bad["parent_binding"]})
    bad["source_id"] = s._source_id("unit", bad["source_record_id"], bad["content_hash"])
    assert not s.verify_original_proof(bad)
    row.content_hash = "a" * 64
    db_session.flush()
    with pytest.raises(HTTPException) as corrupt:
        s.source_current(db_session, case["super"], "unit", row.unit_definition_id, audit_only=True)
    assert corrupt.value.status_code == 409


def test_even_fully_rehashed_unit_cannot_claim_another_authors_professional_signature(db_session, supply_case):
    case = supply_case
    row = create_unit(db_session, case)
    proof = s.source_proof("unit", row)
    proof["created_by"] = case["super"].user_id
    proof["content_hash"] = s.hash_content({**{k: proof[k] for k in s.IDENTITY_FIELDS}, "payload": proof["payload"], "parent_binding": proof["parent_binding"]})
    proof["source_id"] = s._source_id("unit", proof["source_record_id"], proof["content_hash"])
    assert not s.verify_original_proof(proof)


def test_optional_legacy_audit_is_closed_projection_not_patient_or_undisclosed_raw_hash(db_session, supply_case):
    from app.models import PharmaceuticalBatch, PharmaceuticalStockLedger

    case = supply_case
    batch = PharmaceuticalBatch(pharmaceutical_id=case["drug"].pharmaceutical_id, batch_no="synthetic-audit", stock=37, create_time=NOW, update_time=NOW)
    db_session.add(batch)
    db_session.flush()
    ledger = PharmaceuticalStockLedger(
        batch_id=batch.batch_id,
        pharmaceutical_id=case["drug"].pharmaceutical_id,
        transaction_type="outbound",
        quantity=-2,
        before_stock=39,
        after_stock=37,
        operator_id=case["pharmacist"].user_id,
        reference_type="private-prescription",
        reference_id="not-public-patient-proof",
        reason="private original note",
        create_time=NOW,
    )
    db_session.add(ledger)
    db_session.commit()
    request = source_request(case)
    request["payload"]["audit_refs"] = [{"kind": "pharmaceutical_ledger", "ledger_id": ledger.ledger_id, "trace_id": None}]
    row = s.create_source(db_session, case["admin"], request)
    db_session.commit()
    proof = s.source_proof("daily", row)
    original = proof["parent_binding"]["audit_originals"][0]
    projection = original["projection"]
    assert projection["quantity"] == -2 and projection["time_basis"] == "legacy_naive_unknown_not_utc_evidence"
    assert not set(projection) & {"patient_id", "operator_id", "reference_id", "reference_type", "reason"}
    assert original["projection_hash"] == s.hash_content(projection) and s.verify_original_proof(proof)
    projection["ledger_id"] += 1
    original["projection_hash"] = s.hash_content(projection)
    proof["content_hash"] = s.hash_content({**{k: proof[k] for k in s.IDENTITY_FIELDS}, "payload": proof["payload"], "parent_binding": proof["parent_binding"]})
    proof["source_id"] = s._source_id("daily", proof["source_record_id"], proof["content_hash"])
    assert not s.verify_original_proof(proof)


def test_new_observation_future_time_and_cross_sku_unit_fail_before_persisted_source(db_session, supply_case):
    case = supply_case
    unit = create_unit(db_session, case, "consumable")
    request = source_request(case, unit)
    with pytest.raises(HTTPException):
        s.create_source(db_session, case["pharmacist"], request)
    request = source_request(case)
    request["payload"]["observed_at"] = "2027-01-01T00:00:00.000000Z"
    with pytest.raises(HTTPException) as future:
        s.create_source(db_session, case["admin"], request)
    assert future.value.status_code == 422 and db_session.query(AISupplyDailyQuantity).filter_by(item_kind="pharmaceutical", item_id=case["drug"].pharmaceutical_id).count() == 0


def test_mysql_uses_shared_actual_user_identity_and_exclusive_real_sku_lock(db_session, supply_case):
    case = supply_case
    item_id = case["drug"].pharmaceutical_id
    queries = []

    def before(connection, clause, multiparams, params, execution_options):
        if clause.__class__.__name__ == "Select":
            queries.append(str(clause.compile(dialect=mysql.dialect())))

    event.listen(db_session.get_bind(), "before_execute", before)
    try:
        s.lock_supply_scope(db_session, case["pharmacist"], "pharmaceutical", item_id)
    finally:
        event.remove(db_session.get_bind(), "before_execute", before)
    assert "LOCK IN SHARE MODE" in queries[0] and "hoimsystem_users" in queries[0]
    assert "FOR UPDATE" in queries[1] and "hoimsystem_pharmaceutical" in queries[1]
    assert case["drug"].stock == 37
