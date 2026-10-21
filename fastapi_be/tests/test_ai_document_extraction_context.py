"""Current SQL authorization and complete unpublished-note isolation for extraction."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.ai import document_evidence_sources as sources
from app.ai.document_evidence_contract import digest
from app.ai.document_extraction_context import extraction_context, public_payload, selection, verify_context
from app.ai.models import AIRun
from tests.test_ai_document_evidence_sources import approved_original, cas, document_case  # noqa: F401 -- pytest fixture


@pytest.fixture
def extraction_case(document_case):  # noqa: F811 -- pytest injects the imported fixture
    db, actor, seed = document_case
    original = approved_original(db, actor, "\ufeff合成原件😀\r\n完整说明与未知适用条件。")
    return db, actor, seed, original


def bundle(case):
    db, actor, _, original = case
    values = {"document_original_id": original.snapshot.original_id}
    return extraction_context(db, actor, values), values


def test_id_only_selection_resolves_complete_original_and_outbound_excludes_private_notes(extraction_case):
    db, actor, _, original = extraction_case
    context, values = bundle(extraction_case)
    before = db.query(AIRun).count()
    assert selection(values).question is None
    assert verify_context(db, actor, context.data).model_dump(mode="json") == context.data
    outbound = public_payload({"input": values, "context": context.data, "tools": {}, "evidence": context.evidence})
    assert set(outbound) == {"document_source", "question"}
    assert outbound["document_source"]["text"] == original.snapshot.text
    assert "document_review" not in outbound and "metadata" not in outbound["document_source"]
    assert original.governance.review_basis_note not in str(outbound)
    assert db.query(AIRun).count() == before


@pytest.mark.parametrize("extra", [{"text": "伪造原文"}, {"home_id": 1}, {"patient_id": 1}, {"document_original_id": None}, {"question": " "}, {"question": 0}])
def test_input_cannot_add_caller_original_or_other_business_scope(extraction_case, extra):
    _, values = bundle(extraction_case)
    with pytest.raises(HTTPException) as rejected:
        selection({**values, **extra})
    assert rejected.value.status_code == 422


def test_revoked_original_is_unusable_but_super_can_verify_old_frozen_review(extraction_case):
    db, actor, _, original = extraction_case
    context, values = bundle(extraction_case)
    sources.revoke_original(db, actor, original.snapshot.original_id, {**cas(original), "basis_note": "本原件现已撤销，保留原审核签署供历史审计。"})
    db.commit()
    for operation in (lambda: extraction_context(db, actor, values), lambda: verify_context(db, actor, context.data)):
        with pytest.raises(HTTPException) as rejected:
            operation()
        assert rejected.value.status_code == 409
    frozen = verify_context(db, actor, context.data, current=False)
    assert frozen.model_dump(mode="json") == context.data
    assert sources.original_detail(db, actor, original.snapshot.original_id).governance.status == "revoked"


def test_self_rehashed_model_source_cannot_replace_actual_original(extraction_case):
    db, actor, _, _ = extraction_case
    context, _ = bundle(extraction_case)
    forged = copy.deepcopy(context.data)
    source = forged["document_source"]
    source["text"] = source["text"].replace("未知", "已知")
    from app.ai.document_evidence_contract import bytes_hash

    source["raw_bytes_hash"] = bytes_hash(source["text"])
    forged["document_binding"]["source_digest"] = digest(source)
    for current in (True, False):
        with pytest.raises(HTTPException) as rejected:
            verify_context(db, actor, forged, current=current)
        assert rejected.value.status_code == 409


def test_review_note_cannot_be_rehashed_into_an_actual_published_signature(extraction_case):
    db, actor, _, _ = extraction_case
    context, _ = bundle(extraction_case)
    forged = copy.deepcopy(context.data)
    forged["document_review"]["review_basis_note"] = "伪造的完整审核说明不得替代数据库原签署。"
    forged["document_source"]["original"]["governance_hash"] = digest(forged["document_review"])
    forged["document_binding"]["original"]["governance_hash"] = digest(forged["document_review"])
    forged["document_binding"]["source_digest"] = digest(forged["document_source"])
    with pytest.raises(HTTPException):
        verify_context(db, actor, forged, current=False)


def test_registration_capacity_does_not_imply_model_task_capacity(document_case):  # noqa: F811 -- imported pytest fixture
    db, actor, _ = document_case
    original = approved_original(db, actor, "汉" * 21846)
    with pytest.raises(HTTPException) as rejected:
        extraction_context(db, actor, {"document_original_id": original.snapshot.original_id})
    assert rejected.value.status_code == 409
    assert sources.original_detail(db, actor, original.snapshot.original_id).snapshot.raw_bytes_length == 65538


def test_demoted_super_cannot_use_even_a_complete_frozen_source(extraction_case):
    db, actor, _, _ = extraction_case
    context, values = bundle(extraction_case)
    db.execute(text("UPDATE hoimsystem_users SET user_role='doctor' WHERE user_id=:pk"), {"pk": actor.user_id})
    assert actor.user_role == "super_admin"
    for operation in (lambda: extraction_context(db, actor, values), lambda: verify_context(db, actor, context.data, current=False)):
        with pytest.raises(HTTPException) as rejected:
            operation()
        assert rejected.value.status_code == 403
    db.rollback()


@pytest.mark.parametrize("field", ["input", "tools", "evidence", "context"])
def test_model_envelope_cannot_mix_unrelated_data(extraction_case, field):
    context, values = bundle(extraction_case)
    payload = {"input": values, "context": context.data, "tools": {}, "evidence": context.evidence}
    payload = copy.deepcopy(payload)
    if field == "context":
        payload[field]["missing_data"] = []
    elif field == "evidence":
        payload[field] = []
    else:
        payload[field]["unrelated"] = "不得发送"
    with pytest.raises((ValueError, HTTPException)):
        public_payload(payload)
