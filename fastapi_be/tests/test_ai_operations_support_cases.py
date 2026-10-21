"""Actual complete operations snapshots and current permission before all bodies."""

import json
import re
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, update

from app.ai import operations_support_cases as cases
from app.ai import operations_support_contract as c
from app.ai import operations_support_registry as r
from app.ai import operations_support_releases as releases
from app.ai.operations_support_models import AIOperationsCase, AIOperationsOriginal, AIOperationsRelease
from app.models import User
from tests.test_ai_operations_support_registry import request
from tests.test_ai_operations_support_registry import source as source  # noqa: F401
from tests.test_ai_operations_support_releases import actors as actors
from tests.test_ai_operations_support_releases import draft, proposal, review


@pytest.fixture
def collection(actors):
    db, registrar, creator, reviewer, admin = actors
    original, release = draft(actors)
    releases.review_release(db, reviewer, release["release_id"], review())
    return actors, original, release, cases.create_case(db, admin, {"release_ids": [release["release_id"]]})


def no_body(db, callback, status):
    projections = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("select"):
            projections.append(re.split(r"\sfrom\s", statement.lower(), maxsplit=1)[0])

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        with pytest.raises(HTTPException) as exc:
            callback()
        assert exc.value.status_code == status
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    bodies = [
        "operations_original.identity_json",
        "operations_original.content_text",
        "operations_release.draft_json",
        "operations_release.review_basis",
        "operations_release.published_review_json",
        "operations_case.private_json",
        "operations_case.public_json",
    ]
    assert not any(any(term in statement for term in bodies) for statement in projections), projections


def test_current_admin_can_use_only_complete_reviewed_public_derivatives(collection):
    actors, original, release, created = collection
    db, registrar, creator, reviewer, admin = actors
    public = cases.get_case_part(db, admin, created["case_id"], "source")
    assert public["source_id"] == created["case_id"]
    assert public["counts"] == dict(documents=1, diagnostic_logs=1, runbooks=0, reference_documents=0)
    assert public["action_basis"] == "missing_reviewed_runbook"
    assert public["documents"][0]["text"] == request()["content_text"].replace("secret=合成令牌", c.MASK_TEXT)
    assert public["coverage"] == "explicit_reviewed_derivatives_only_not_live_system_inventory"
    wire = json.dumps(public, ensure_ascii=False)
    assert all(value not in wire for value in ["secret=合成令牌", "origin_note", original["original_id"], "review_basis", "requested_by", "captured_by"])
    no_body(db, lambda: cases.get_case_part(db, admin, created["case_id"], "private"), 403)
    private = cases.get_case_part(db, registrar, created["case_id"], "private")
    assert private["members"][0]["original"]["content_text"] == request()["content_text"]
    assert "metadata" not in public and "metadata" not in private


def test_unknown_case_and_other_current_admin_do_not_expose_frozen_text(collection):
    actors, original, release, created = collection
    db, registrar, creator, reviewer, admin = actors
    other = User(username="opsother" + uuid.uuid4().hex[:8], password=admin.password, user_role="admin")
    db.add(other)
    db.flush()
    no_body(db, lambda: cases.get_case_part(db, other, created["case_id"], "source"), 403)
    no_body(db, lambda: cases.get_case_part(db, admin, str(uuid.uuid4()), "source"), 404)


@pytest.mark.parametrize("withdrawal", ["original", "release", "case", "reviewer_role", "owner_role", "owner_token"])
def test_any_current_withdrawal_or_epoch_loss_denies_before_all_private_body(collection, withdrawal):
    actors, original, release, created = collection
    db, registrar, creator, reviewer, admin = actors
    if withdrawal == "original":
        r.revoke_original(db, registrar, original["original_id"], {"revision": 1, "reason": "原件撤回"})
    elif withdrawal == "release":
        releases.revoke_release(db, registrar, release["release_id"], {"revision": 2, "reason": "发布撤回"})
    elif withdrawal == "case":
        cases.revoke_case(db, registrar, created["case_id"], {"revision": 1, "reason": "快照撤回"})
    elif withdrawal == "reviewer_role":
        reviewer.user_role = "doctor"
        db.flush()
    elif withdrawal == "owner_role":
        db.execute(update(User).where(User.user_id == admin.user_id).values(user_role="doctor").execution_options(synchronize_session=False))
    else:
        assert admin.token_invalid_before is None
        db.execute(update(User).where(User.user_id == admin.user_id).values(token_invalid_before=r.utcnow()).execution_options(synchronize_session=False))
    no_body(db, lambda: cases.get_case_part(db, admin, created["case_id"], "source"), 403)
    if withdrawal in {"original", "release", "case", "reviewer_role"}:
        no_body(db, lambda: cases.get_case_part(db, registrar, created["case_id"], "source"), 403)
        assert cases.describe_case(db, registrar, created["case_id"])["source_accessible"] is False


def test_internal_release_can_be_read_but_not_model_processed(collection):
    actors, original, release, created = collection
    db, registrar, creator, reviewer, admin = actors
    assert cases.get_case_part(db, admin, created["case_id"], "source")["counts"]["documents"] == 1
    no_body(db, lambda: cases.source_current(db, admin, created["case_id"], execution=True), 403)


def test_all_members_must_be_current_before_first_original_is_read(actors):
    db, registrar, creator, reviewer, admin = actors
    original1, release1 = draft(actors)
    original2, release2 = draft(actors)
    for item in (release1, release2):
        releases.review_release(db, reviewer, item["release_id"], review(model_processing_allowed=True))
    created = cases.create_case(db, admin, {"release_ids": [release1["release_id"], release2["release_id"]]})
    public = cases.source_current(db, admin, created["case_id"], execution=True)[4]
    assert public.counts.documents == 2 and public.documents[0].source_id < public.documents[1].source_id
    last = max(release1["release_id"], release2["release_id"])
    releases.revoke_release(db, registrar, last, {"revision": 2, "reason": "排序末件撤回"})
    no_body(db, lambda: cases.source_current(db, admin, created["case_id"]), 403)
    no_body(db, lambda: cases.create_case(db, admin, {"release_ids": [release1["release_id"], release2["release_id"]]}), 403)


def test_two_releases_of_same_original_are_rejected_before_body(actors):
    db, registrar, creator, reviewer, admin = actors
    original, first = draft(actors)
    second = releases.create_release(db, creator, proposal(original, request()["content_text"], released_title="另一明确审核版本"))
    for item in (first, second):
        releases.review_release(db, reviewer, item["release_id"], review())
    no_body(db, lambda: cases.create_case(db, admin, {"release_ids": [first["release_id"], second["release_id"]]}), 422)


@pytest.mark.parametrize("column", ["private_hash", "public_hash", "member_bindings_hash", "requested_by"])
def test_case_specific_audit_binds_all_hashes_and_owner_before_body(collection, column):
    actors, original, release, created = collection
    db, registrar, creator, reviewer, admin = actors
    value = registrar.user_id if column == "requested_by" else "0" * 64
    db.execute(update(AIOperationsCase).where(AIOperationsCase.case_id == created["case_id"]).values(**{column: value}).execution_options(synchronize_session=False))
    no_body(db, lambda: cases.get_case_part(db, registrar, created["case_id"], "source"), 409)


def test_altered_technical_membership_is_not_used_to_read_another_source(collection):
    actors, original, release, created = collection
    db, registrar, creator, reviewer, admin = actors
    db.execute(update(AIOperationsCase).where(AIOperationsCase.case_id == created["case_id"]).values(member_bindings_json="{}").execution_options(synchronize_session=False))
    no_body(db, lambda: cases.get_case_part(db, admin, created["case_id"], "source"), 409)


@pytest.mark.parametrize("damage", ["original", "draft", "review", "case_private", "case_public"])
def test_current_and_frozen_body_damage_is_not_hidden_by_old_matching_headers(collection, damage):
    actors, original, release, created = collection
    db, registrar, creator, reviewer, admin = actors
    if damage == "original":
        db.execute(update(AIOperationsOriginal).where(AIOperationsOriginal.original_id == original["original_id"]).values(content_text="损坏原件").execution_options(synchronize_session=False))
    elif damage == "draft":
        db.execute(update(AIOperationsRelease).where(AIOperationsRelease.release_id == release["release_id"]).values(draft_json="{}").execution_options(synchronize_session=False))
    elif damage == "review":
        db.execute(update(AIOperationsRelease).where(AIOperationsRelease.release_id == release["release_id"]).values(published_review_json="{}").execution_options(synchronize_session=False))
    else:
        db.execute(
            update(AIOperationsCase)
            .where(AIOperationsCase.case_id == created["case_id"])
            .values(**{("private_json" if damage == "case_private" else "public_json"): "{}"})
            .execution_options(synchronize_session=False)
        )
    with pytest.raises(HTTPException) as exc:
        cases.get_case_part(db, admin, created["case_id"], "source")
    assert exc.value.status_code == 409


def test_reviewed_runbook_is_explicit_reference_and_commands_are_only_inert_text(actors):
    db, registrar, creator, reviewer, admin = actors
    value = {**request(), "kind": "runbook", "content_text": "只供人工核对的合成字符串 rm -rf /synthetic-only\r\n"}
    original = r.register_original(db, registrar, value)
    release = releases.create_release(db, creator, proposal(original, request()["content_text"], redactions=[]))
    releases.review_release(db, reviewer, release["release_id"], review())
    created = cases.create_case(db, admin, {"release_ids": [release["release_id"]]})
    public = cases.get_case_part(db, admin, created["case_id"], "source")
    assert public["action_basis"] == "reviewed_runbook_reference_only"
    assert public["documents"][0]["text"] == value["content_text"]
