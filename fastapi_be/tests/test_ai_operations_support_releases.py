"""Actual independent release review, immutability and pre-body denial paths."""

import json
import re
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, update

from app.ai import operations_support_contract as c
from app.ai import operations_support_registry as r
from app.ai import operations_support_releases as releases
from app.ai.models import AIAuditEvent
from app.ai.operations_support_models import AIOperationsRelease
from app.models import User
from tests.test_ai_operations_support_registry import request
from tests.test_ai_operations_support_registry import source as source


@pytest.fixture
def actors(source):
    db, registrar, admin = source
    creator = User(username="opsdraft" + uuid.uuid4().hex[:8], password=registrar.password, user_role="super_admin")
    reviewer = User(username="opsreview" + uuid.uuid4().hex[:8], password=registrar.password, user_role="super_admin")
    db.add_all([creator, reviewer])
    db.flush()
    return db, registrar, creator, reviewer, admin


def proposal(created, body, **changes):
    secret = "secret=合成令牌"
    start = body.index(secret)
    return {
        **dict(
            original_id=created["original_id"],
            original_full_sha256=created["content_hash"],
            released_title="独立审核后的标题",
            released_component="演示组件",
            released_version=None,
            redactions=[{"start_codepoint": start, "end_codepoint": start + len(secret), "method": "mask"}],
        ),
        **changes,
    }


def review(**changes):
    return {
        **dict(
            revision=1,
            decision="publish",
            privacy_reviewed=True,
            faithfulness_reviewed=True,
            applicability_reviewed=True,
            model_processing_allowed=False,
            basis="合成材料已按明确三项核查；未声称实际系统版本兼容",
        ),
        **changes,
    }


def draft(actors):
    db, registrar, creator, reviewer, admin = actors
    body = request()["content_text"]
    original = r.register_original(db, registrar, request())
    created = releases.create_release(db, creator, proposal(original, body))
    return original, created


def no_body(db, callback, status):
    seen = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("select"):
            seen.append(re.split(r"\sfrom\s", statement.lower(), maxsplit=1)[0])

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        with pytest.raises(HTTPException) as exc:
            callback()
        assert exc.value.status_code == status
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    private = ["operations_original.identity_json", "operations_original.content_text", "operations_release.draft_json", "operations_release.review_basis", "operations_release.published_review_json"]
    assert not any(any(column in statement for column in private) for statement in seen), seen


def test_real_independent_publication_preserves_complete_reviewed_derivative(actors):
    db, registrar, creator, reviewer, admin = actors
    original, created = draft(actors)
    published = releases.review_release(db, reviewer, created["release_id"], review())
    assert published["status"] == "published" and published["revision"] == 2
    assert published["model_processing_allowed"] == 0
    assert published["review_event_id"] != published["creation_event_id"]
    header = releases.release_header(db, created["release_id"], require_published=True)
    raw, actual = releases.read_published_body(db, header)
    assert actual.reviewed_by == reviewer.user_id
    assert actual.reviewed_at == published["reviewed_at"]
    assert actual.released_text == request()["content_text"].replace("secret=合成令牌", c.MASK_TEXT)
    assert raw.content_text == request()["content_text"]
    assert actual.released_component == "演示组件" and actual.released_version is None
    audit = db.get(AIAuditEvent, published["review_event_id"])
    assert json.loads(audit.detail_json)["published_review_hash"] == c.content_hash(actual)
    assert all(s not in json.dumps(published, ensure_ascii=False) for s in ["secret=", "合成材料已按", "origin_note", "released_text"])


@pytest.mark.parametrize("who", ["registrar", "creator", "admin"])
def test_independent_current_super_required_before_any_review_body(actors, who):
    db, registrar, creator, reviewer, admin = actors
    _, created = draft(actors)
    actor = {"registrar": registrar, "creator": creator, "admin": admin}[who]
    no_body(db, lambda: releases.review_release(db, actor, created["release_id"], review()), 403)


@pytest.mark.parametrize("allow_model", [False, True])
def test_publication_and_model_processing_are_independent_explicit_flags(actors, allow_model):
    db, registrar, creator, reviewer, admin = actors
    _, created = draft(actors)
    releases.review_release(db, reviewer, created["release_id"], review(model_processing_allowed=allow_model))
    if allow_model:
        assert releases.release_header(db, created["release_id"], require_published=True, execution=True)["model_processing_allowed"] == 1
    else:
        no_body(db, lambda: releases.release_header(db, created["release_id"], require_published=True, execution=True), 403)


def test_rejection_never_materializes_published_source_or_transfer_permission(actors):
    db, registrar, creator, reviewer, admin = actors
    _, created = draft(actors)
    result = releases.review_release(db, reviewer, created["release_id"], review(decision="reject", privacy_reviewed=False))
    assert result["status"] == "rejected" and result["published_review_hash"] is None
    assert db.get(AIOperationsRelease, created["release_id"]).published_review_json is None
    no_body(db, lambda: releases.release_header(db, created["release_id"], require_published=True), 403)


@pytest.mark.parametrize("damage", ["reviewed_actor", "review_pk", "published_hash", "model_permission"])
def test_concrete_review_audit_binds_entire_technical_header_before_body(actors, damage):
    db, registrar, creator, reviewer, admin = actors
    _, created = draft(actors)
    result = releases.review_release(db, reviewer, created["release_id"], review())
    if damage == "reviewed_actor":
        values = {"reviewed_by": admin.user_id}
    elif damage == "review_pk":
        values = {"review_event_id": result["creation_event_id"] + 1000000}
        # Keep FK validity in this actual mismatch test; a different real PK is
        # inserted with a plausible action and wrong whole binding.
        other = AIAuditEvent(actor_id=reviewer.user_id, action="operations_release_review", target=created["release_id"], detail_json="{}", create_time=r.utcnow())
        db.add(other)
        db.flush()
        values = {"review_event_id": other.event_id}
    elif damage == "published_hash":
        values = {"published_review_hash": "0" * 64}
    else:
        values = {"model_processing_allowed": 1}
    db.execute(update(AIOperationsRelease).where(AIOperationsRelease.release_id == created["release_id"]).values(**values).execution_options(synchronize_session=False))
    no_body(db, lambda: releases.get_release(db, registrar, created["release_id"], include_body=True), 409)


def test_original_withdrawal_and_publisher_demotion_both_precede_all_private_text(actors):
    db, registrar, creator, reviewer, admin = actors
    original, created = draft(actors)
    releases.review_release(db, reviewer, created["release_id"], review())
    reviewer.user_role = "admin"
    db.flush()
    no_body(db, lambda: releases.release_header(db, created["release_id"], require_published=True), 403)
    reviewer.user_role = "super_admin"
    db.flush()
    r.revoke_original(db, registrar, original["original_id"], {"revision": 1, "reason": "明确原材料已撤回"})
    no_body(db, lambda: releases.release_header(db, created["release_id"], require_published=True), 403)


@pytest.mark.parametrize("published", [False, True])
def test_draft_or_publication_can_be_revoked_without_reading_private_material(actors, published):
    db, registrar, creator, reviewer, admin = actors
    _, created = draft(actors)
    if published:
        releases.review_release(db, reviewer, created["release_id"], review())
    result = releases.revoke_release(db, registrar, created["release_id"], {"revision": 2 if published else 1, "reason": "明确撤回"})
    assert result["status"] == "revoked" and result["revision"] == (3 if published else 2)
    no_body(db, lambda: releases.get_release(db, registrar, created["release_id"], include_body=True), 403)
    assert releases.get_release(db, registrar, created["release_id"]) == result


def test_no_implicit_empty_or_overlapping_redaction_is_published(actors):
    db, registrar, creator, reviewer, admin = actors
    original = r.register_original(db, registrar, request())
    body = request()["content_text"]
    for spans in [
        [{"start_codepoint": 0, "end_codepoint": len(body), "method": "remove"}],
        [{"start_codepoint": 3, "end_codepoint": 8, "method": "mask"}, {"start_codepoint": 7, "end_codepoint": 10, "method": "remove"}],
    ]:
        with pytest.raises(HTTPException) as exc:
            releases.create_release(db, creator, proposal(original, body, redactions=spans))
        assert exc.value.status_code == 422


def test_old_or_wrong_original_sha_is_rejected_before_body(actors):
    db, registrar, creator, reviewer, admin = actors
    original = r.register_original(db, registrar, request())
    no_body(db, lambda: releases.create_release(db, creator, proposal(original, request()["content_text"], original_full_sha256="0" * 64)), 409)


def test_review_cannot_overwrite_published_version_and_draft_bytes_stay_immutable(actors):
    db, registrar, creator, reviewer, admin = actors
    _, created = draft(actors)
    before = db.get(AIOperationsRelease, created["release_id"]).draft_json
    releases.review_release(db, reviewer, created["release_id"], review())
    no_body(db, lambda: releases.review_release(db, registrar, created["release_id"], review()), 409)
    assert db.get(AIOperationsRelease, created["release_id"]).draft_json == before


def test_private_review_body_tamper_fails_full_reconstruction(actors):
    db, registrar, creator, reviewer, admin = actors
    _, created = draft(actors)
    releases.review_release(db, reviewer, created["release_id"], review())
    db.execute(update(AIOperationsRelease).where(AIOperationsRelease.release_id == created["release_id"]).values(review_basis="无效改写").execution_options(synchronize_session=False))
    header = releases.release_header(db, created["release_id"], require_published=True)
    with pytest.raises(HTTPException) as exc:
        releases.read_published_body(db, header)
    assert exc.value.status_code == 409


def test_publication_receipt_and_column_state_roll_back_together(actors, monkeypatch):
    db, registrar, creator, reviewer, admin = actors
    _, created = draft(actors)
    before = db.query(AIAuditEvent).count()

    def fail(*a, **kw):
        raise HTTPException(409, "synthetic publication readback fault")

    monkeypatch.setattr(releases, "read_published_body", fail)
    with pytest.raises(HTTPException), db.begin_nested():
        releases.review_release(db, reviewer, created["release_id"], review())
    assert db.query(AIAuditEvent).count() == before
    assert releases.release_header(db, created["release_id"])["status"] == "draft"


def test_full_draft_part_has_no_aggregate_original_or_metadata_envelope(actors):
    db, registrar, creator, reviewer, admin = actors
    _, created = draft(actors)
    full = releases.get_release(db, registrar, created["release_id"], include_body=True)
    assert set(full) == {"schema_version", "release_id", "created_by", "recorded_at", "proposal", "released_text"}
    assert full["released_text"] == request()["content_text"].replace("secret=合成令牌", c.MASK_TEXT)
    assert "original" not in full and "metadata" not in full
