"""Actual synthetic current Scope/SQL context; no claims about real MySQL waits."""

import copy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.ai import document_change_context as context
from app.ai import document_change_contract as c
from app.ai import document_change_sources as sources
from app.ai.document_change_json import require_case_json
from app.ai.document_change_run_models import DOCUMENT_CHANGE_RUN_MODELS, AIDocumentChangeRunArtifact
from app.ai.document_change_view_contract import (
    MISSING_DATA,
    DocumentChangeBinding,
    DocumentChangeRequest,
    bounded_wire,
    private_scope_packet,
    source_packet,
)
from tests.test_ai_document_change_sources import change_case as change_case  # noqa: F401
from tests.test_ai_document_change_sources import link_request, published_scope
from tests.test_ai_document_evidence_sources import cas

RUN_ID = "00000000-0000-0000-0000-000000000972"


def prepared(case):
    db, actor, *_ = case
    scope = published_scope(case)
    values = {"document_change_scope_id": scope.snapshot.scope_id, "question": "\ufeff原样问题\r\n😀e\u0301"}
    return scope, values, context.prepare_context(db, actor, values)


def test_actual_complete_scope_short_context_and_public_only_wire(change_case):
    scope, values, (bundle, record, source) = prepared(change_case)
    assert record == scope and source.member_count == scope.snapshot.inventory.member_count
    assert set(bundle.data) == {"scope", "snapshot_time", "document_change_binding", "missing_data"}
    assert bundle.data["missing_data"] == list(MISSING_DATA)
    assert len(c.e.utf8(c.e.canonical_json(bundle.data))) < 65535
    binding = DocumentChangeBinding.model_validate(bundle.data["document_change_binding"])
    assert len(bundle.evidence) == 3 and bundle.evidence == context.change_evidence(binding)
    payload = {"input": values, "context": bundle.data, "tools": {}, "evidence": bundle.evidence}
    public = context.public_payload(payload, source)
    assert set(public) == {"document_change_source", "question"} and public["question"] == values["question"]
    assert public["document_change_source"] == source.model_dump(mode="json")
    assert scope.snapshot.request.declaration_basis_note not in c.e.canonical_json(public)
    assert change_case[4].steps not in c.e.canonical_json(public)
    checked, live, current = context.verify_current_context(change_case[0], change_case[1], bundle.data)
    assert checked.model_dump(mode="json") == bundle.data and live == scope and current == source
    public_packet = source_packet(RUN_ID, binding, source)
    private = private_scope_packet(RUN_ID, binding, scope.snapshot, scope.governance, scope.audit_event_ids)
    assert private.currentness == "not_asserted_by_frozen_packet" and private.frozen_task_view is True
    assert bounded_wire(public_packet)[2] < c.MAX_CASE_BYTES and bounded_wire(private)[2] < c.MAX_CASE_BYTES


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"document_change_scope_id": None},
        {"document_change_scope_id": RUN_ID, "patient_id": 1},
        {"document_change_scope_id": RUN_ID, "question": False},
        {"document_change_scope_id": RUN_ID, "question": "x" * 2001},
        {"document_change_scope_id": RUN_ID, "question": "\ud800"},
    ],
)
def test_request_rejects_foreign_scope_or_unavailable_question(bad):
    with pytest.raises(HTTPException) as error:
        context.selection(bad)
    assert error.value.status_code == 422


def test_actual_optional_question_and_exact_unicode_bounds():
    assert DocumentChangeRequest(document_change_scope_id=RUN_ID).question is None
    value = "😀" * 2000
    assert DocumentChangeRequest(document_change_scope_id=RUN_ID, question=value).question == value


@pytest.mark.parametrize("change", ["tools", "evidence", "missing", "binding", "input", "extra"])
def test_outbound_rejects_mutations_after_both_hash_copies_change(change_case, change):
    _, values, (bundle, _, source) = prepared(change_case)
    payload = {"input": values, "context": bundle.data, "tools": {}, "evidence": bundle.evidence}
    if change == "tools":
        payload["tools"] = {"knowledge": "outside packet"}
    elif change == "evidence":
        payload["evidence"][0]["source_digest"] = "a" * 64
    elif change == "missing":
        payload["context"]["missing_data"] = []
    elif change == "binding":
        payload["context"]["document_change_binding"]["source_digest"] = "b" * 64
        payload["evidence"][0]["source_digest"] = "b" * 64
    elif change == "input":
        payload["input"]["document_change_scope_id"] = RUN_ID
    else:
        payload["context"]["document_change_source"] = source.model_dump(mode="json")
    with pytest.raises((ValueError, ValidationError)):
        context.public_payload(payload, source)


@pytest.mark.parametrize("mutation", ["losing_link", "target", "scope_revoke", "role"])
def test_current_context_rechecks_actual_complete_closure(change_case, mutation):
    scope, _, (bundle, _, _) = prepared(change_case)
    db, actor, *_ = change_case
    if mutation == "losing_link":
        sources.create_link(db, actor, link_request(change_case))
    elif mutation == "target":
        change_case[4].steps = "actual changed original"
        change_case[4].source_revision += 1
    elif mutation == "scope_revoke":
        sources.revoke_scope(db, actor, scope.snapshot.scope_id, {**cas(scope), "basis_note": "本次明确撤销原完整版本核对范围"})
    else:
        actor.user_role = "admin"
    db.commit()
    with pytest.raises(HTTPException) as error:
        context.verify_current_context(db, actor, bundle.data)
    assert error.value.status_code in {403, 409}


def test_whole_wire_budget_counts_wrapper_and_refuses_without_truncation():
    overhead = len(c.e.utf8(require_case_json({"code": 200, "msg": "success", "data": {"payload": ""}})))
    body = {"payload": "x" * (c.MAX_CASE_BYTES - overhead)}
    assert bounded_wire(body)[2] == c.MAX_CASE_BYTES
    body["payload"] += "x"
    assert len(c.e.utf8(require_case_json(body))) < c.MAX_CASE_BYTES
    with pytest.raises(ValueError):
        bounded_wire(body)
    assert len(body["payload"]) == c.MAX_CASE_BYTES - overhead + 1


def test_private_frozen_packet_does_not_claim_current_eligibility(change_case):
    scope, _, (bundle, _, source) = prepared(change_case)
    binding = DocumentChangeBinding.model_validate(bundle.data["document_change_binding"])
    packet = private_scope_packet(RUN_ID, binding, scope.snapshot, scope.governance, scope.audit_event_ids)
    db, actor, *_ = change_case
    sources.revoke_scope(db, actor, scope.snapshot.scope_id, {**cas(scope), "basis_note": "当前撤销不篡改已捕获原文"})
    db.commit()
    assert packet.published_governance.status == "published" and packet.currentness == "not_asserted_by_frozen_packet"
    with pytest.raises(HTTPException):
        context.verify_current_context(db, actor, bundle.data)
    # This is only pure frozen packet validation; SQL-authorized audit belongs
    # to Storage. No live flag is fabricated for the revoked Source.
    assert source.scope == packet.document_change_binding.scope
    bad = copy.deepcopy(packet.model_dump(mode="json"))
    bad["frozen_task_view"] = 1
    with pytest.raises(ValidationError):
        type(packet).model_validate(bad)


def test_new_model_preserves_nullable_unique_concrete_usage_pk_and_mysql_shapes():
    artifact = AIDocumentChangeRunArtifact.__table__
    assert artifact.c.usage_event_id.nullable
    assert any({column.name for column in item.columns} == {"usage_event_id"} for item in artifact.constraints if item.__class__.__name__ == "UniqueConstraint")
    for model in DOCUMENT_CHANGE_RUN_MODELS:
        ddl = str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
        assert "MEDIUMTEXT" in ddl and "DATETIME(6)" in ddl and "AUTO_INCREMENT" not in ddl
    assert len(artifact.c.usage_event_id.foreign_keys) == 1


def test_mutated_public_model_cannot_self_rehash_changed_raw_bytes(change_case):
    _, values, (bundle, _, source) = prepared(change_case)
    source.baseline.text += "changed"
    payload = {"input": values, "context": bundle.data, "tools": {}, "evidence": bundle.evidence}
    with pytest.raises(ValueError):
        context.public_payload(payload, source)


def test_source_packet_refuses_changed_governance_or_boolean_member_count(change_case):
    _, _, (bundle, _, source) = prepared(change_case)
    bound = copy.deepcopy(bundle.data["document_change_binding"])
    bound["scope"]["governance_hash"] = "a" * 64
    with pytest.raises(ValueError):
        source_packet(RUN_ID, bound, source)
    bound = copy.deepcopy(bundle.data["document_change_binding"])
    bound["member_count"] = True
    with pytest.raises(ValueError):
        source_packet(RUN_ID, bound, source)


@pytest.mark.parametrize("question", ["", " \u0085\u001c\u3000\r\n"])
def test_actual_empty_or_unicode_whitespace_question_preserved(change_case, question):
    db, actor, *_ = change_case
    scope = published_scope(change_case)
    values = {"document_change_scope_id": scope.snapshot.scope_id, "question": question}
    bundle, _, source = context.prepare_context(db, actor, values)
    value = context.public_payload({"input": values, "context": bundle.data, "tools": {}, "evidence": bundle.evidence}, source)
    assert value["question"] == question
    assert c.e.utf8(value["question"]) == c.e.utf8(question)
