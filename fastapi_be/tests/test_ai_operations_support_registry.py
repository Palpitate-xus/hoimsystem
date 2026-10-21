"""Real SQL originals and authority checks; no HTTP, MySQL or model claim."""

import datetime as dt
import json
import re
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text, update

from app.ai import operations_support_registry as registry
from app.ai.models import AIAuditEvent
from app.ai.operations_support_models import AIOperationsOriginal, AIOperationsWriteGate
from app.ai.operations_support_registry_contract import ReleaseReview
from app.models import User


@pytest.fixture
def source(db_session, seed_data):
    db = db_session
    db.commit()
    prior = db.execute(text("PRAGMA foreign_keys")).scalar_one()
    db.execute(text("PRAGMA foreign_keys=ON"))
    if db.get(AIOperationsWriteGate, 1) is None:
        db.add(AIOperationsWriteGate(gate_id=1, revision=1))
    db.commit()
    actor = db.query(User).filter_by(username="super01").one()
    admin = db.query(User).filter_by(username="admin").one()
    yield db, actor, admin
    db.rollback()
    db.execute(text("PRAGMA foreign_keys=" + str(prior)))
    db.commit()


def request():
    return dict(
        kind="diagnostic_log",
        title="完整合成原始材料",
        origin_note="人工提供，非实际环境读取",
        declared_component=None,
        declared_version="",
        content_text="\ufeff完整 😀\r\n\x00  secret=合成令牌\n尾部  ",
    )


def assert_no_original_body(db, operation, status):
    seen = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("select"):
            seen.append(re.split(r"\sfrom\s", statement.lower(), maxsplit=1)[0])

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        with pytest.raises(HTTPException) as raised:
            operation()
        assert raised.value.status_code == status
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert not any("operations_original.content_text" in s or "operations_original.identity_json" in s for s in seen), seen


def test_exact_original_and_server_identity_are_read_back_without_normalizing(source):
    db, actor, _ = source
    value = request()
    created = registry.register_original(db, actor, value)
    full = registry.get_original(db, actor, created["original_id"], include_body=True)
    assert full["content_text"].encode() == value["content_text"].encode()
    assert full["captured_by"] == actor.user_id
    assert len(full["captured_at"]) == 27 and full["captured_at"].endswith("Z")
    assert full["clock_basis"] == "capture_only_not_verified_incident_occurrence"
    assert full["declared_component"] is None and full["declared_version"] == ""
    assert "content_text" not in created and "origin_note" not in created and "title" not in created
    actual = db.get(AIAuditEvent, created["creation_event_id"])
    assert actual.target == created["original_id"] and actual.action == "operations_original_create"
    assert json.loads(actual.detail_json)["raw_bytes_length"] == len(value["content_text"].encode())


@pytest.mark.parametrize("role", ["admin", "director", "doctor", "nurse", "pharmacist", "patient", "cashier"])
def test_only_actual_current_super_admin_can_register_or_read_raw(source, role):
    db, actor, admin = source
    created = registry.register_original(db, actor, request())
    admin.user_role = role
    db.flush()
    assert_no_original_body(db, lambda: registry.get_original(db, admin, created["original_id"], include_body=True), 403)
    assert_no_original_body(db, lambda: registry.register_original(db, admin, request()), 403)


def test_server_owned_capture_fields_and_unknown_inputs_cannot_be_injected(source):
    db, actor, _ = source
    value = {**request(), "captured_by": actor.user_id, "captured_at": "2026-10-21T00:00:00.000001Z"}
    assert_no_original_body(db, lambda: registry.register_original(db, actor, value), 422)


def test_saved_request_role_and_token_epoch_are_checked_before_body(source):
    db, actor, _ = source
    created = registry.register_original(db, actor, request())
    actor_id = actor.user_id
    assert actor.token_invalid_before is None
    db.execute(update(User).where(User.user_id == actor_id).values(token_invalid_before=dt.datetime(2026, 10, 21, 18)).execution_options(synchronize_session=False))
    assert_no_original_body(db, lambda: registry.get_original(db, actor, created["original_id"], include_body=True), 403)


def test_saved_request_super_role_demotion_precedes_body(source):
    db, actor, _ = source
    created = registry.register_original(db, actor, request())
    actor_id = actor.user_id
    db.execute(update(User).where(User.user_id == actor_id).values(user_role="admin").execution_options(synchronize_session=False))
    assert_no_original_body(db, lambda: registry.get_original(db, actor, created["original_id"], include_body=True), 403)


def test_missing_migration_seed_does_not_lazy_create_authority(source):
    db, actor, _ = source
    db.query(AIOperationsWriteGate).delete()
    db.flush()
    assert_no_original_body(db, lambda: registry.register_original(db, actor, request()), 409)
    assert db.query(AIOperationsWriteGate).count() == 0


def test_withdrawal_preserves_technical_receipts_and_blocks_raw_before_select(source):
    db, actor, _ = source
    created = registry.register_original(db, actor, request())
    revoked = registry.revoke_original(db, actor, created["original_id"], {"revision": 1, "reason": "合成材料撤回😀"})
    assert revoked["status"] == "revoked" and revoked["revision"] == 2 and revoked["revocation_event_id"] != created["creation_event_id"]
    assert_no_original_body(db, lambda: registry.get_original(db, actor, created["original_id"], include_body=True), 403)
    assert registry.get_original(db, actor, created["original_id"]) == revoked
    assert_no_original_body(db, lambda: registry.revoke_original(db, actor, created["original_id"], {"revision": 1, "reason": "重复"}), 403)


@pytest.mark.parametrize("damage", ["digest", "clock", "actual_audit_pk"])
def test_wrong_technical_header_or_actual_audit_is_denied_before_body(source, damage):
    db, actor, _ = source
    created = registry.register_original(db, actor, request())
    values = {"raw_text_sha256": "0" * 64} if damage == "digest" else {"captured_at": dt.datetime(2026, 1, 1)}
    if damage == "actual_audit_pk":
        other = AIAuditEvent(actor_id=actor.user_id, action="operations_original_create", target=str(uuid.uuid4()), detail_json="{}", create_time=registry.utcnow())
        db.add(other)
        db.flush()
        values = {"creation_event_id": other.event_id}
    db.execute(update(AIOperationsOriginal).where(AIOperationsOriginal.original_id == created["original_id"]).values(**values).execution_options(synchronize_session=False))
    assert_no_original_body(db, lambda: registry.get_original(db, actor, created["original_id"], include_body=True), 409)


def test_content_corruption_cannot_be_repaired_by_a_header_digest(source):
    db, actor, _ = source
    created = registry.register_original(db, actor, request())
    db.execute(update(AIOperationsOriginal).where(AIOperationsOriginal.original_id == created["original_id"]).values(content_text="changed").execution_options(synchronize_session=False))
    with pytest.raises(HTTPException) as raised:
        registry.get_original(db, actor, created["original_id"], include_body=True)
    assert raised.value.status_code == 409


def test_actual_create_audit_and_original_rollback_together_on_failed_readback(source, monkeypatch):
    db, actor, _ = source
    before = (db.query(AIOperationsOriginal).count(), db.query(AIAuditEvent).count())

    def fail(*args, **kwargs):
        raise HTTPException(409, "synthetic readback fault")

    monkeypatch.setattr(registry, "read_original_body", fail)
    with pytest.raises(HTTPException), db.begin_nested():
        registry.register_original(db, actor, request())
    assert (db.query(AIOperationsOriginal).count(), db.query(AIAuditEvent).count()) == before


@pytest.mark.parametrize("change", [{"privacy_reviewed": 1}, {"model_processing_allowed": "true"}, {"decision": "reject"}, {"applicability_reviewed": False}])
def test_review_requires_literal_boolean_consistent_decision(change):
    value = dict(revision=1, decision="publish", privacy_reviewed=True, faithfulness_reviewed=True, applicability_reviewed=True, model_processing_allowed=False, basis="明确人工核查范围")
    with pytest.raises(ValueError):
        ReleaseReview.model_validate({**value, **change}, strict=True)


def test_internal_publication_can_explicitly_deny_model_processing():
    value = ReleaseReview(
        revision=1, decision="publish", privacy_reviewed=True, faithfulness_reviewed=True, applicability_reviewed=True, model_processing_allowed=False, basis="明确内部适用性核查，未批准模型处理"
    )
    assert value.model_processing_allowed is False
