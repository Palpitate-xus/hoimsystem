"""Actual synthetic Source lifecycle and current Task authority before TEXT."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, text

from app.ai import research_variables_task_context as context
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_registry import create_registry_original, review_registry_original
from app.ai.research_variables_batches import create_batch, review_batch
from app.ai.research_variables_dictionary import create_dictionary, review_dictionary
from app.ai.research_variables_task_binding import VariableTaskBinding, binding_reference
from app.ai.research_variables_task_contract import MAX_BINDING_BYTES, canonical, digest
from tests.test_ai_research_cohort_collection import clinical_case
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import acl_request, anchors, auth_request, permitted, publish
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401
from tests.test_ai_research_variables_contract import definition
from tests.test_ai_research_variables_dictionary import definition_review, technical_review

PRIVATE = (
    "hoimsystem_ai_research_variable_batch.snapshot_json",
    "hoimsystem_ai_research_variable_batch.projection_json",
    "hoimsystem_ai_research_variable_dictionary.dictionary_json",
    "hoimsystem_ai_research_variable_dictionary.parent_binding_json",
    "hoimsystem_medical_record.symptom",
    "hoimsystem_medical_record.result",
)


@pytest.fixture
def task_factory(db_session, research_case):
    def make(*, model_use="recorded_permitted", two_patients=True):
        db, case = db_session, research_case
        request = case["scope_request"]
        request["external_model_use"] = model_use
        request["permitted_uses"] = ["research_variable_extraction"]
        if two_patients:
            request["patient_ids"] = sorted([case["patient"].patient_id, case["patient2"].patient_id])
        scope, acl, permission = permitted(db, case)
        permissions = [permission]
        for actor in (case["super_admin_user"], case["reviewer"]):
            publish(db, case, "acl", create_registry_original(db, case["super_admin_user"], "acl", {**acl_request(case, scope), "user_id": actor.user_id}))
        if two_patients:
            permissions.append(
                publish(
                    db,
                    case,
                    "authorization",
                    create_registry_original(db, case["super_admin_user"], "authorization", {**auth_request(case, scope), "patient_id": case["patient2"].patient_id}),
                    manual=True,
                )
            )
        dictionary = create_dictionary(db, case["admin_user"], {**anchors(scope), "title": "实际原字段任务字典", "purpose": BASIS, "basis_note": BASIS, "variables": [definition()]})
        review_dictionary(db, case["reviewer"], dictionary["dictionary_id"], definition_review(dictionary), definition=True)
        dictionary = review_dictionary(db, case["super_admin_user"], dictionary["dictionary_id"], technical_review())
        clinical_case(db, case)
        batch = create_batch(
            db,
            case["admin_user"],
            {
                **anchors(scope),
                "variable_dictionary_id": dictionary["dictionary_id"],
                "dictionary_content_hash": dictionary["content_hash"],
                "dictionary_governance_hash": dictionary["governance_hash"],
                "patient_ids": [case["patient"].patient_id],
                "basis_note": BASIS,
            },
        )
        batch = review_batch(db, case["super_admin_user"], batch["batch_id"], technical_review())
        return case, scope, acl, permissions, batch, dictionary

    return make


def observe(db):
    statements = []

    def seen(conn, cursor, sql, params, ctx, many):
        statements.append(sql)

    event.listen(db.bind, "before_cursor_execute", seen)
    return statements, seen


@pytest.mark.parametrize("question", [None, "", "\u3000\t\r\n", "\ufeff明确否定\r\n🧪e\u0301"])
def test_actual_model_permission_context_keeps_every_source_literal_all_scope_permissions_and_optional_question_without_writes(db_session, task_factory, question):
    case, scope, acl, permissions, batch, dictionary = task_factory()
    user = case["admin_user"]
    before = db_session.query(AIAuditEvent).count()
    value = context.prepare_context(db_session, user, {"research_variable_batch_id": batch["batch_id"], "question": question})
    assert db_session.query(AIAuditEvent).count() == before
    assert value.selection.question == question
    assert value.data["question"] == question
    assert value.source.model_dump(mode="json") == batch["original"]["source"]
    assert value.source.external_model_use == "recorded_permitted"
    bound = value.binding
    assert bound.request_authorization.scope_id == scope["scope_id"]
    assert bound.request_authorization.acl_id == acl["source_record_id"]
    assert [p.authorization_id for p in bound.request_authorization.patient_authorizations] == [p["source_record_id"] for p in sorted(permissions, key=lambda p: p["patient_id"])]
    assert len(bound.request_authorization.patient_authorizations) == 2
    assert batch["original"]["snapshot"]["request"]["patient_ids"] == [case["patient"].patient_id]
    assert bound.dictionary_created_event_id == dictionary["original"]["identity"]["created_event_id"]
    assert bound.request_authorization_hash == digest(bound.request_authorization, MAX_BINDING_BYTES)
    assert value.data["research_variable_binding"] == binding_reference(bound)
    assert len(canonical(value.data).encode("utf-8")) < 65535
    parts = context.wire_parts(bound, value.source, value.private_scope)
    assert parts["scope"]["private_scope"]["snapshot"] == batch["original"]["snapshot"]
    assert "source" not in parts["scope"]["private_scope"]["proof"]
    outbound = context.public_payload(value)
    assert set(outbound) == {"research_variable_source", "question"} and outbound["question"] == question
    assert outbound["research_variable_source"] == batch["original"]["source"]
    assert not any(key in canonical(outbound) for key in ("patient_ids", "original_authority_text", "identity_key", "acl_id", "patient_authorizations"))


@pytest.mark.parametrize("model_use", ["unknown", "not_permitted"])
def test_scope_without_explicit_model_use_blocks_before_batch_dictionary_or_clinical_text_even_super(db_session, task_factory, model_use):
    case, _, _, _, batch, _ = task_factory(model_use=model_use)
    statements, seen = observe(db_session)
    try:
        for user in (case["admin_user"], case["super_admin_user"]):
            with pytest.raises(HTTPException) as error:
                context.prepare_context(db_session, user, {"research_variable_batch_id": batch["batch_id"]})
            assert error.value.status_code == 403
    finally:
        event.remove(db_session.bind, "before_cursor_execute", seen)
    assert not any(column in sql for sql in statements for column in PRIVATE)


@pytest.mark.parametrize("which", [0, 1])
def test_any_scope_patient_revocation_including_unselected_member_denies_first_batch_text_even_super(db_session, task_factory, which):
    case, _, _, permissions, batch, _ = task_factory()
    review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[which]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    statements, seen = observe(db_session)
    try:
        for user in (case["admin_user"], case["super_admin_user"]):
            with pytest.raises(HTTPException) as error:
                context.prepare_context(db_session, user, {"research_variable_batch_id": batch["batch_id"]})
            assert error.value.status_code == 403
    finally:
        event.remove(db_session.bind, "before_cursor_execute", seen)
    assert not any(column in sql for sql in statements for column in PRIVATE)


@pytest.mark.parametrize("change", ["role", "epoch"])
def test_loaded_request_epoch_is_saved_before_current_refresh_and_fails_before_body(db_session, task_factory, change):
    case, _, _, _, batch, _ = task_factory()
    user = case["admin_user"]
    identifier, old_role, old_epoch = user.user_id, user.user_role, user.token_invalid_before
    field, value = ("user_role", "director") if change == "role" else ("token_invalid_before", "2099-01-01 00:00:00.000000")
    db_session.execute(text("UPDATE hoimsystem_users SET " + field + "=:value WHERE user_id=:id"), {"value": value, "id": identifier})
    assert user.__dict__["user_role"] == old_role and user.__dict__["token_invalid_before"] == old_epoch
    statements, seen = observe(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            context.prepare_context(db_session, user, {"research_variable_batch_id": batch["batch_id"]})
        assert error.value.status_code == 403
    finally:
        event.remove(db_session.bind, "before_cursor_execute", seen)
        db_session.rollback()
    assert not any(column in sql for sql in statements for column in PRIVATE)


@pytest.mark.parametrize("which", ["acl", "authorization", "epoch"])
def test_original_task_access_hash_cannot_be_replaced_by_a_new_valid_grant_or_epoch_before_body(db_session, task_factory, which):
    case, scope, _, permissions, batch, _ = task_factory()
    user = case["super_admin_user"]
    prepared = context.prepare_context(db_session, user, {"research_variable_batch_id": batch["batch_id"]})
    original = prepared.binding.request_authorization
    if which == "epoch":
        user.token_invalid_before = context.utcnow()
        db_session.commit()
    else:
        identifier = original.acl_id if which == "acl" else permissions[1]["source_record_id"]
        review_registry_original(db_session, user, which, identifier, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
        body = {**acl_request(case, scope), "user_id": inspect(user).identity[0]} if which == "acl" else {**auth_request(case, scope), "patient_id": case["patient2"].patient_id}
        publish(db_session, case, which, create_registry_original(db_session, user, which, body), manual=which == "authorization")
    statements, seen = observe(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            context.authorize_request(db_session, user, batch["batch_id"], expected_authorization_hash=prepared.binding.request_authorization_hash, expected_acl_id=original.acl_id)
        assert error.value.status_code == 403
    finally:
        event.remove(db_session.bind, "before_cursor_execute", seen)
    assert not any(column in sql for sql in statements for column in PRIVATE)


@pytest.mark.parametrize("field", ["patient_id", "encounter_ref", "source", "question_extra"])
def test_foreign_selection_is_rejected_without_any_sql(db_session, task_factory, field):
    _, _, _, _, batch, _ = task_factory()
    statements, seen = observe(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            context.prepare_context(db_session, None, {"research_variable_batch_id": batch["batch_id"], field: None})
        assert error.value.status_code == 422
    finally:
        event.remove(db_session.bind, "before_cursor_execute", seen)
    assert statements == []


def test_binding_keeps_explicit_originals_and_rejects_rehashed_omission_against_independent_task_anchor(db_session, task_factory):
    case, _, _, _, batch, _ = task_factory()
    prepared = context.prepare_context(db_session, case["admin_user"], {"research_variable_batch_id": batch["batch_id"]})
    changed = copy.deepcopy(prepared.binding.model_dump(mode="json"))
    changed["request_authorization"]["patient_authorizations"].pop()
    with pytest.raises(ValueError):
        VariableTaskBinding.model_validate(changed)
    changed["request_authorization_hash"] = digest(changed["request_authorization"], MAX_BINDING_BYTES)
    structured = VariableTaskBinding.model_validate(changed)
    # Structure plus its own new SHA is not original SQL authority. Compare
    # the current complete manifest to the independently stored task anchor.
    with pytest.raises(HTTPException) as error:
        context.authorize_request(db_session, case["admin_user"], batch["batch_id"], expected_authorization_hash=structured.request_authorization_hash)
    assert error.value.status_code == 403


def test_full_http_piece_envelope_is_counted_before_any_run_can_be_queued(db_session, task_factory, monkeypatch):
    case, _, _, _, batch, _ = task_factory()
    actual = context.canonical

    def bounded(value, maximum=context.MAX_RUN_TEXT_BYTES):
        if type(value) is dict and value.get("schema_version") == "research_variable_task_scope_part_v1":
            return actual(value, maximum=100)
        return actual(value, maximum)

    monkeypatch.setattr(context, "canonical", bounded)
    before = db_session.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as error:
        context.prepare_context(db_session, case["admin_user"], {"research_variable_batch_id": batch["batch_id"]})
    assert error.value.status_code == 409 and db_session.query(AIAuditEvent).count() == before


@pytest.mark.parametrize("damage", ["source", "private_scope", "question"])
def test_in_memory_pieces_cannot_be_changed_after_the_independent_current_binding(db_session, task_factory, damage):
    case, _, _, _, batch, _ = task_factory()
    value = context.prepare_context(db_session, case["admin_user"], {"research_variable_batch_id": batch["batch_id"]})
    if damage == "source":
        value.source.governance_hash = "f" * 64
        with pytest.raises(ValueError):
            context.public_payload(value)
    elif damage == "question":
        value.selection.question = "not the original question"
        with pytest.raises(ValueError):
            context.public_payload(value)
    else:
        value.private_scope["snapshot"]["basis_note"] += "changed"
        with pytest.raises(ValueError):
            context.wire_parts(value.binding, value.source, value.private_scope)
