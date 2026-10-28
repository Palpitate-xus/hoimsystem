"""Independent actual SQL task proofs; no HTTP, provider call or worker claim."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from app import models
from app.ai import document_evidence_contract as c
from app.ai import document_evidence_sources as sources
from app.ai import document_extraction_storage as storage
from app.ai.catalog import CATALOG_VERSION
from app.ai.context import context_metadata
from app.ai.document_evidence_models import AIDocumentKnowledgePublication, AIDocumentSpanCandidate
from app.ai.document_extraction_context import DocumentExtractionContext, extraction_context, public_payload
from app.ai.document_extraction_contract import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_TASK_PROMPT, parse_extraction_reply
from app.ai.document_extraction_models import ANCHOR_HASH_FIELDS, AIDocumentExtractionRunAnchor
from app.ai.document_extraction_prompt import instructions_digest
from app.ai.document_extraction_result import result_for_draft
from app.ai.models import AIFeatureConfig, AIKnowledgeDocument, AIPromptVersion, AIProvider, AIRun
from app.database import Base
from tests.test_ai_document_evidence_contract import NOTE, NOW
from tests.test_ai_document_evidence_sources import approved_original, cas


@pytest.fixture
def task_factory(monkeypatch):
    """Use actual Source reviews, actual model rows and complete frozen task JSON."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = Session(engine, autoflush=False)
    monkeypatch.setattr(sources, "utcnow", lambda: c.clock(NOW))

    yield lambda **kwargs: create_task(db, **kwargs)
    db.rollback()
    db.close()
    engine.dispose()


def create_task(db, *, kind="chat", original_text=None, stage=True):
    actor = models.User(username="document_storage", user_role="super_admin", password="synthetic-unused")
    db.add(actor)
    db.commit()
    original = approved_original(db, actor, original_text)
    provider = AIProvider(
        max_attempts=1,  # This fixture freezes the legacy single-attempt provider fields.
        name="document storage provider",
        kind=kind,
        api_base="https://synthetic.invalid/v1",
        model="synthetic-complete-text-model",
        enabled=1,
        allows_patient_data=1,
        timeout_seconds=30,
        max_output_tokens=2000,
        temperature=0.2,
        validation_report="本合成模型仅用于工程协议测试，不代表临床验证。",
        created_by=actor.user_id,
    )
    prompt = AIPromptVersion(feature_key=storage.FEATURE_KEY, version=1, task_prompt=EXTRACTION_TASK_PROMPT, change_note=NOTE, created_by=actor.user_id)
    db.add_all([provider, prompt])
    db.flush()
    config = AIFeatureConfig(
        feature_key=storage.FEATURE_KEY,
        enabled=1,
        provider_id=provider.provider_id,
        allowed_roles_json='["super_admin"]',
        validation_status="pilot",
        validation_note="合成工程试点说明，未提供临床与完整覆盖验证。",
        validated_by=actor.user_id,
        validated_at=c.clock(NOW),
        active_prompt_id=prompt.prompt_id,
        updated_by=actor.user_id,
        revision=3,
    )
    db.add(config)
    db.commit()
    values = {"document_original_id": original.snapshot.original_id}
    bundle = extraction_context(db, actor, values)
    snapshot = {
        "catalog_version": CATALOG_VERSION,
        "system_prompt": EXTRACTION_SYSTEM_PROMPT,
        "task_prompt": prompt.task_prompt,
        "payload": {"input": values, "context": bundle.data, "tools": {}, "evidence": bundle.evidence},
        "provider_snapshot": {
            "provider_id": provider.provider_id,
            "revision": provider.revision,
            "name": provider.name,
            "kind": provider.kind,
            "api_base": provider.api_base,
            "model": provider.model,
            "timeout_seconds": provider.timeout_seconds,
            "max_output_tokens": provider.max_output_tokens,
            "validation_report": provider.validation_report,
            "temperature": float(provider.temperature),
            "allows_patient_data": bool(provider.allows_patient_data),
            "effective_output_limit": provider.max_output_tokens,
        },
        "feature_validation": {
            "status": config.validation_status,
            "note": config.validation_note,
            "validated_by": config.validated_by,
            "validated_at": str(config.validated_at),
            "feature_revision": config.revision,
        },
    }
    metadata = {
        **context_metadata(bundle),
        "feature_revision": config.revision,
        "validation_status": config.validation_status,
        "tool_fingerprint": c.digest({}),
        "instructions_digest": instructions_digest(prompt.task_prompt),
        "model_version": provider.model,
    }
    run = AIRun(
        feature_key=storage.FEATURE_KEY,
        requested_by=actor.user_id,
        provider_id=provider.provider_id,
        provider_revision=provider.revision,
        prompt_version=prompt.version,
        prompt_hash=c.digest([EXTRACTION_SYSTEM_PROMPT, prompt.task_prompt]),
        context_digest=c.digest(bundle.data),
        input_json=c.canonical_json(snapshot),
        result_json="{}",
        evidence_json=c.canonical_json(bundle.evidence),
        context_metadata_json=c.canonical_json(metadata),
        status="queued",
        create_time=c.clock(NOW),
    )
    db.add(run)
    db.flush()
    if stage:
        storage.stage_anchor(db, run)
        db.commit()
    return SimpleNamespace(db=db, actor=actor, original=original, provider=provider, config=config, prompt=prompt, run=run, snapshot=snapshot, metadata=metadata, bundle=bundle)


def assert409(operation):
    with pytest.raises(HTTPException) as rejected:
        operation()
    assert rejected.value.status_code == 409


def write_snapshot(case, snapshot, *, rehash_anchor=False):
    case.run.input_json = c.canonical_json(snapshot)
    if rehash_anchor:
        anchor = case.db.get(AIDocumentExtractionRunAnchor, case.run.run_id)
        anchor.input_hash = hashlib.sha256(case.run.input_json.encode()).hexdigest()
    case.db.commit()


def complete(case, *, empty=False):
    source = DocumentExtractionContext.model_validate(case.bundle.data).document_source
    # The default actual original's [9,12) is emoji + e + combining accent.
    spans = [] if empty else [{"proposed_heading": "未核实标题", "clause_kind": "other", "start": 9, "end": 12, "quote": "😀e\u0301"}]
    draft = parse_extraction_reply({"spans": spans}, source, case.metadata["instructions_digest"])
    result = result_for_draft(draft, source, case.metadata["instructions_digest"]).model_dump(mode="json")
    case.run.result_json = c.canonical_json(result)
    case.run.status = "succeeded"
    case.db.commit()
    return result


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_real_sql_queue_complete_result_and_independent_full_byte_anchors(task_factory, kind):
    case = task_factory(kind=kind)
    assert storage.is_extraction_run(case.db, case.run)
    assert storage.load_result(case.db, case.run) is None
    snapshot, context, metadata = storage.authorize_document_run(case.db, case.actor, case.run, current=True)
    assert context.document_source.text == case.original.snapshot.text and context.snapshot_time == NOW
    raw_digest = hashlib.sha256((EXTRACTION_SYSTEM_PROMPT + "\n\n" + case.prompt.task_prompt).encode()).hexdigest()
    assert metadata["instructions_digest"] == raw_digest != c.digest([EXTRACTION_SYSTEM_PROMPT, case.prompt.task_prompt])
    assert metadata["model_version"] == case.provider.model
    assert set(snapshot["provider_snapshot"]) == {name for name, field in storage.DocumentFrozenProvider.model_fields.items() if field.is_required()}
    anchor = case.db.get(AIDocumentExtractionRunAnchor, case.run.run_id)
    assert anchor.input_hash == hashlib.sha256(case.run.input_json.encode()).hexdigest()
    assert anchor.evidence_hash == hashlib.sha256(case.run.evidence_json.encode()).hexdigest()
    assert anchor.metadata_hash == hashlib.sha256(case.run.context_metadata_json.encode()).hexdigest()
    assert anchor.original_content_hash == case.original.content_hash
    assert anchor.original_governance_hash == case.original.governance_hash
    assert anchor.requested_by == case.actor.user_id and anchor.recorded_at == c.clock(NOW)
    assert storage.load_result(case.db, case.run) is None
    result = complete(case)
    assert storage.load_result(case.db, case.run) == result
    assert result["document_extraction"]["spans"][0]["quote"] == case.original.snapshot.text[9:12]
    assert result["document_extraction"]["automatic_candidate_creation"] is False
    assert result["document_extraction"]["automatic_knowledge_publication"] is False
    assert all(case.db.query(model).count() == 0 for model in (AIDocumentSpanCandidate, AIDocumentKnowledgePublication, AIKnowledgeDocument))
    assert set(public_payload(snapshot["payload"])) == {"document_source", "question"}
    assert "document_review" not in public_payload(snapshot["payload"])


def test_empty_draft_retains_no_complete_coverage_claim(task_factory):
    case = task_factory()
    result = complete(case, empty=True)
    assert storage.load_result(case.db, case.run) == result
    assert result["document_extraction"]["spans"] == [] and "不表示全文没有条款" in result["document_extraction"]["coverage_note"]


def test_actual_revocation_blocks_current_use_but_preserves_super_frozen_audit(task_factory):
    case = task_factory()
    result = complete(case)
    sources.revoke_original(case.db, case.actor, case.original.snapshot.original_id, {**cas(case.original), "basis_note": NOTE})
    case.db.commit()
    assert409(lambda: storage.authorize_document_run(case.db, case.actor, case.run, current=True))
    _, context, _ = storage.authorize_document_run(case.db, case.actor, case.run, current=False)
    assert context.document_source.text == case.original.snapshot.text
    assert context.document_review.status == "published" and case.original.governance.status == "published"
    assert sources.original_detail(case.db, case.actor, case.original.snapshot.original_id).governance.status == "revoked"
    assert storage.load_result(case.db, case.run) == result


@pytest.mark.parametrize("role", ["doctor", "patient"])
def test_actual_actor_demotion_denies_even_frozen_private_audit(task_factory, role):
    case = task_factory()
    case.db.execute(text("UPDATE hoimsystem_users SET user_role=:role WHERE user_id=:id"), {"role": role, "id": case.actor.user_id})
    case.db.commit()
    for current in (False, True):
        with pytest.raises(HTTPException) as rejected:
            storage.authorize_document_run(case.db, case.actor, case.run, current=current)
        assert rejected.value.status_code == 403


@pytest.mark.parametrize("field", ANCHOR_HASH_FIELDS)
def test_each_actual_retained_anchor_hash_is_required(task_factory, field):
    case = task_factory()
    anchor = case.db.get(AIDocumentExtractionRunAnchor, case.run.run_id)
    setattr(anchor, field, "f" * 64)
    case.db.commit()
    assert409(lambda: storage.load_snapshot(case.db, case.run))


def test_actual_retained_anchor_cannot_be_omitted(task_factory):
    case = task_factory()
    case.db.delete(case.db.get(AIDocumentExtractionRunAnchor, case.run.run_id))
    case.db.commit()
    assert409(lambda: storage.load_snapshot(case.db, case.run))


@pytest.mark.parametrize("field", ["catalog_version", "system_prompt", "task_prompt", "payload", "provider_snapshot", "feature_validation"])
def test_each_frozen_task_section_missing_rejected_even_after_rehash(task_factory, field):
    case = task_factory()
    snapshot = copy.deepcopy(case.snapshot)
    del snapshot[field]
    write_snapshot(case, snapshot, rehash_anchor=True)
    assert409(lambda: storage.load_snapshot(case.db, case.run))


@pytest.mark.parametrize("field", ["input", "context", "tools", "evidence"])
def test_each_complete_payload_section_missing_rejected_even_after_rehash(task_factory, field):
    case = task_factory()
    snapshot = copy.deepcopy(case.snapshot)
    del snapshot["payload"][field]
    write_snapshot(case, snapshot, rehash_anchor=True)
    assert409(lambda: storage.load_snapshot(case.db, case.run))


@pytest.mark.parametrize("field", [name for name, info in storage.DocumentFrozenProvider.model_fields.items() if info.is_required()])
def test_all_twelve_provider_fields_required_despite_self_rehashed_input(task_factory, field):
    case = task_factory()
    snapshot = copy.deepcopy(case.snapshot)
    del snapshot["provider_snapshot"][field]
    write_snapshot(case, snapshot, rehash_anchor=True)
    assert409(lambda: storage.load_snapshot(case.db, case.run))


@pytest.mark.parametrize("field", list(storage.DocumentFrozenValidation.model_fields))
def test_all_five_validation_fields_required_despite_self_rehashed_input(task_factory, field):
    case = task_factory()
    snapshot = copy.deepcopy(case.snapshot)
    del snapshot["feature_validation"][field]
    write_snapshot(case, snapshot, rehash_anchor=True)
    assert409(lambda: storage.load_snapshot(case.db, case.run))


@pytest.mark.parametrize("field", ["instructions_digest", "model_version", "snapshot_time", "missing_data"])
def test_metadata_cannot_be_omitted_or_replace_actual_prompt_model_source(task_factory, field):
    case = task_factory()
    metadata = copy.deepcopy(case.metadata)
    del metadata[field]
    case.run.context_metadata_json = c.canonical_json(metadata)
    case.db.get(AIDocumentExtractionRunAnchor, case.run.run_id).metadata_hash = hashlib.sha256(case.run.context_metadata_json.encode()).hexdigest()
    case.db.commit()
    assert409(lambda: storage.load_snapshot(case.db, case.run))


@pytest.mark.parametrize("field,value", [("patient_id", 1), ("encounter_ref", "invented-scope"), ("provider_revision", 2), ("prompt_version", -1)])
def test_run_cannot_change_scope_provider_or_prompt_identity(task_factory, field, value):
    case = task_factory()
    if field == "patient_id":
        patient = models.Patient(name="合成不同范围", identity="DOC_STORAGE_001")
        case.db.add(patient)
        case.db.flush()
        value = patient.patient_id
    setattr(case.run, field, value)
    case.db.commit()
    assert409(lambda: storage.load_snapshot(case.db, case.run))


@pytest.mark.parametrize("axis", ["source", "review"])
def test_self_rehashed_full_task_still_cannot_replace_actual_original_or_review(task_factory, axis):
    case = task_factory()
    snapshot = copy.deepcopy(case.snapshot)
    context = snapshot["payload"]["context"]
    if axis == "source":
        source = context["document_source"]
        source["text"] = source["text"].replace("第一行", "假说明")
        source["raw_bytes_hash"] = c.bytes_hash(source["text"])
    else:
        context["document_review"]["review_basis_note"] = "伪造完整原意审核说明，不能替换数据库原签署。"
        context["document_binding"]["original"]["governance_hash"] = context["document_source"]["original"]["governance_hash"] = c.digest(context["document_review"])
    context["document_binding"]["source_digest"] = c.digest(context["document_source"])
    evidence = snapshot["payload"]["evidence"][0]
    evidence.update(
        governance_hash=context["document_binding"]["original"]["governance_hash"],
        source_digest=context["document_binding"]["source_digest"],
        raw_bytes_hash=context["document_source"]["raw_bytes_hash"],
    )
    from app.ai.context import ContextBundle

    metadata = {**case.metadata, **context_metadata(ContextBundle(data=context, evidence=snapshot["payload"]["evidence"]))}
    case.run.input_json = c.canonical_json(snapshot)
    case.run.context_digest = c.digest(context)
    case.run.evidence_json = c.canonical_json(snapshot["payload"]["evidence"])
    case.run.context_metadata_json = c.canonical_json(metadata)
    anchor = case.db.get(AIDocumentExtractionRunAnchor, case.run.run_id)
    anchor.original_governance_hash = context["document_binding"]["original"]["governance_hash"]
    anchor.source_digest = context["document_binding"]["source_digest"]
    anchor.context_digest = case.run.context_digest
    anchor.input_hash = hashlib.sha256(case.run.input_json.encode()).hexdigest()
    anchor.evidence_hash = hashlib.sha256(case.run.evidence_json.encode()).hexdigest()
    anchor.metadata_hash = hashlib.sha256(case.run.context_metadata_json.encode()).hexdigest()
    case.db.commit()
    for current in (False, True):
        assert409(lambda current=current: storage.authorize_document_run(case.db, case.actor, case.run, current=current))


@pytest.mark.parametrize("change", ["quote", "fixed_summary", "automatic_action", "omitted_warning", "other_result_marker"])
def test_stored_complete_result_cannot_replace_literal_span_or_server_explanation(task_factory, change):
    case = task_factory()
    result = complete(case)
    if change == "quote":
        result["document_extraction"]["spans"][0]["quote"] = "😀eX"
    elif change == "fixed_summary":
        result["summary"] = "所有条款已完成临床验证并已发布知识。"
    elif change == "automatic_action":
        result["document_extraction"]["automatic_knowledge_publication"] = True
    elif change == "omitted_warning":
        result["warnings"] = []
    else:
        result["coding_evidence"] = {"fake": "mixed"}
    case.run.result_json = c.canonical_json(result)
    case.db.commit()
    assert409(lambda: storage.load_result(case.db, case.run))


@pytest.mark.parametrize("status", ["queued", "running", "failed", "cancelled"])
def test_non_successful_complete_task_keeps_empty_result_only(task_factory, status):
    case = task_factory()
    case.run.status = status
    case.db.commit()
    assert storage.load_result(case.db, case.run) is None
    complete(case)
    case.run.status = status
    case.db.commit()
    assert409(lambda: storage.load_result(case.db, case.run))


def test_stripping_all_feature_and_json_markers_cannot_hide_actual_retained_fk(task_factory):
    case = task_factory()
    complete(case)
    case.run.feature_key = "documentation"
    case.run.input_json = "{}"
    case.run.result_json = c.canonical_json({"summary": "generic"})
    case.run.evidence_json = "[]"
    case.run.context_metadata_json = "{}"
    case.db.commit()
    statements = []

    def record_query(state):
        statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(case.db, "do_orm_execute", record_query)
    try:
        assert storage.is_extraction_run(case.db, case.run)
    finally:
        event.remove(case.db, "do_orm_execute", record_query)
    # This observes a real SQLite ORM query and its MySQL lock clause; the
    # separate private-MySQL report proves the actual RR runtime behavior.
    assert any("hoimsystem_ai_document_extraction_run_anchor" in query and ("FOR SHARE" in query or "LOCK IN SHARE MODE" in query) for query in statements)
    assert409(lambda: storage.load_result(case.db, case.run))
    assert409(lambda: storage.authorize_document_run(case.db, case.actor, case.run, current=False))


@pytest.mark.parametrize("input_json,result_json", [(None, None), ("{}", None), (None, "{}"), ("{}", "{}")])
def test_non_document_transient_with_none_json_remains_compatible(input_json, result_json):
    run = AIRun(feature_key="documentation", input_json=input_json, result_json=result_json)
    assert run.run_id is None and not storage.is_extraction_run(None, run)


def test_utf8_limit_is_whole_raw_task_not_character_count_or_nested_source_only(task_factory):
    exact = "🙂" * 16383 + "abc"
    assert len(exact.encode()) == 65535 and storage.text_hash(exact) == hashlib.sha256(exact.encode()).hexdigest()
    with pytest.raises(ValueError):
        storage.text_hash(exact + "x")
    case = task_factory(original_text="汉" * 21000, stage=False)
    assert case.bundle.data["document_source"]["raw_bytes_length"] == 63000
    assert len(case.run.input_json.encode()) > 65535
    with pytest.raises(ValueError):
        storage.stage_anchor(case.db, case.run)
    assert case.db.query(AIDocumentExtractionRunAnchor).count() == 0
    case.db.rollback()
    assert case.db.query(AIRun).count() == 0


def test_json_whitespace_or_duplicate_key_cannot_be_canonicalized_into_old_anchor(task_factory):
    case = task_factory()
    value = json.loads(case.run.input_json)
    case.run.input_json = json.dumps(value, ensure_ascii=False, indent=2)
    case.db.get(AIDocumentExtractionRunAnchor, case.run.run_id).input_hash = hashlib.sha256(case.run.input_json.encode()).hexdigest()
    case.db.commit()
    assert409(lambda: storage.load_snapshot(case.db, case.run))
