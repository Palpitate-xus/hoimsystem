"""Complete split comparison artifacts and SQL-backed task/Prompt identity.

No helper commits. Current reads acquire actor -> sorted Original X -> targets ->
Scope before locking Artifact. Frozen audit locks only actor -> Scope -> Artifact
and never subsequently waits on live Original/target state.
"""

import hashlib

from fastapi import HTTPException

from app.ai import document_change_contract as c
from app.ai import document_change_sources as sources
from app.ai import document_evidence_sources as originals
from app.ai.context import ContextBundle, context_metadata
from app.ai.document_change_context import change_evidence, public_payload, selection, verify_current_context
from app.ai.document_change_draft import SYSTEM_PROMPT, checked_source
from app.ai.document_change_json import parse_case_json, require_case_json
from app.ai.document_change_models import AIDocumentChangeScope
from app.ai.document_change_run_models import ANCHOR_HASH_FIELDS, ARTIFACT_SCHEMA, AIDocumentChangeRunArtifact
from app.ai.document_change_view_contract import (
    FEATURE_KEY,
    DocumentChangeArtifactRecord,
    DocumentChangeContext,
    binding_for_source,
    private_scope_packet,
    source_packet,
)
from app.ai.document_extraction_view_contract import DocumentFrozenProvider, DocumentFrozenValidation
from app.ai.governance import digest
from app.ai.models import AIAuditEvent
from app.models import User

TEXT_BYTES = 65535
ARTIFACT_CREATED = "document_change.run_artifact_created"


def text_hash(raw):
    if type(raw) is not str or len(c.e.utf8(raw)) > TEXT_BYTES:
        raise ValueError("The complete short Run JSON must fit UTF8 TEXT")
    return hashlib.sha256(c.e.utf8(raw)).hexdigest()


def _json(raw):
    text_hash(raw)
    value = parse_case_json(raw)
    if require_case_json(value) != raw:
        raise ValueError("The original short JSON must be canonical, finite and unique")
    return value


def _evidence_json(raw):
    # The shared evidence TEXT root is a list, whereas the large Case parser
    # deliberately accepts only objects. Wrap it to reuse duplicate/UTF8 rules.
    text_hash(raw)
    value = parse_case_json('{"evidence":' + raw + "}")["evidence"]
    if type(value) is not list or c.e.canonical_json(value) != raw:
        raise ValueError("The original evidence must be a complete canonical list")
    return value


def _task(run):
    snapshot, evidence, metadata = _json(run.input_json), _evidence_json(run.evidence_json), _json(run.context_metadata_json)
    if set(snapshot) != {"catalog_version", "system_prompt", "task_prompt", "payload", "provider_snapshot", "feature_validation"}:
        raise ValueError("The closed frozen task envelope is required")
    if run.feature_key != FEATURE_KEY or run.patient_id is not None or run.encounter_ref is not None or type(run.requested_by) is not int or run.requested_by < 1:
        raise ValueError("A comparison task cannot change feature/actor or acquire patient scope")
    if snapshot["system_prompt"] != SYSTEM_PROMPT or type(snapshot["task_prompt"]) is not str or not snapshot["task_prompt"].strip() or type(snapshot["catalog_version"]) is not str:
        raise ValueError("The actual fixed system and frozen task Prompt are required")
    payload = snapshot["payload"]
    if type(payload) is not dict or set(payload) != {"input", "context", "tools", "evidence"}:
        raise ValueError("The complete short task payload is required")
    context = DocumentChangeContext.model_validate(payload["context"])
    if c.e.canonical_json(context) != c.e.canonical_json(payload["context"]):
        raise ValueError("All original context scalar types must be preserved")
    request = selection(payload["input"])
    bound = context.document_change_binding
    if request.document_change_scope_id != bound.scope.scope_id or payload["tools"] != {} or payload["evidence"] != evidence or evidence != change_evidence(bound):
        raise ValueError("The selected Scope, empty tools and three exact citations differ")
    provider = DocumentFrozenProvider.model_validate(snapshot["provider_snapshot"])
    validation = DocumentFrozenValidation.model_validate(snapshot["feature_validation"])
    if c.e.canonical_json(provider) != c.e.canonical_json(snapshot["provider_snapshot"]) or c.e.canonical_json(validation) != c.e.canonical_json(snapshot["feature_validation"]):
        raise ValueError("Actual frozen provider/validation scalar types differ")
    if (
        type(run.provider_id) is not int
        or run.provider_id != provider.provider_id
        or type(run.provider_revision) is not int
        or run.provider_revision != provider.revision
        or type(run.prompt_version) is not int
        or run.prompt_version < 0
        or type(run.preview) is not int
        or run.preview not in {0, 1}
    ):
        raise ValueError("The actual Run and frozen model/Prompt identity differ")
    instructions = c.e.bytes_hash(SYSTEM_PROMPT + "\n\n" + snapshot["task_prompt"])
    if digest(payload["context"]) != run.context_digest or digest([SYSTEM_PROMPT, snapshot["task_prompt"]]) != run.prompt_hash:
        raise ValueError("The original complete context or Prompt digest differs")
    expected = {
        **context_metadata(ContextBundle(data=context.model_dump(mode="json"), evidence=evidence)),
        "feature_revision": validation.feature_revision,
        "validation_status": validation.status,
        "tool_fingerprint": digest({}),
        "instructions_digest": instructions,
        "model_version": provider.model,
    }
    if c.e.canonical_json(metadata) != c.e.canonical_json(expected):
        raise ValueError("The closed actual frozen metadata differs")
    return snapshot, context, metadata, evidence


def _anchor_values(run):
    return {
        "prompt_hash": run.prompt_hash,
        "context_digest": run.context_digest,
        "input_hash": text_hash(run.input_json),
        "evidence_hash": text_hash(run.evidence_json),
        "metadata_hash": text_hash(run.context_metadata_json),
    }


def _binding_columns(bound):
    return {
        "scope_id": bound.scope.scope_id,
        "scope_content_hash": bound.scope.content_hash,
        "scope_governance_hash": bound.scope.governance_hash,
        "baseline_original_id": bound.baseline_original.original_id,
        "baseline_original_content_hash": bound.baseline_original.content_hash,
        "baseline_original_governance_hash": bound.baseline_original.governance_hash,
        "candidate_original_id": bound.candidate_original.original_id,
        "candidate_original_content_hash": bound.candidate_original.content_hash,
        "candidate_original_governance_hash": bound.candidate_original.governance_hash,
        "inventory_hash": bound.inventory_hash,
        "member_count": bound.member_count,
        "source_digest": bound.source_digest,
    }


def _scope_frozen(db, context):
    bound = context.document_change_binding
    with db.no_autoflush:
        row = db.query(AIDocumentChangeScope).filter_by(scope_id=bound.scope.scope_id).populate_existing().with_for_update(read=True).one_or_none()
    if row is None:
        raise ValueError("The actual immutable Scope is unavailable")
    snapshot = sources.stored(row, "scope")
    if (
        row.content_hash != bound.scope.content_hash
        or snapshot.scope_id != bound.scope.scope_id
        or snapshot.request.baseline_original != bound.baseline_original
        or snapshot.request.candidate_original != bound.candidate_original
        or snapshot.inventory_hash != bound.inventory_hash
        or snapshot.inventory.member_count != bound.member_count
    ):
        raise ValueError("The complete retained private Scope differs from the original task")
    # Current revocation fields remain current. Reconstruct only the actual
    # retained published review, without reporting current eligibility.
    current_governance = sources.governance(row)
    review = current_governance.model_dump(mode="json")
    if review["status"] == "revoked":
        review.update(status="published", revision=2, revoked_by=None, revoked_at=None, revoke_reason="")
    published = c.Governance.model_validate(review)
    if published.status != "published" or c.e.digest(published) != bound.scope.governance_hash:
        raise ValueError("The original actual published Scope signature differs")
    sources.audit_refs(db, row, "scope", current_governance)
    audit_ids = c.AuditReferences(created=row.created_audit_event_id, reviewed=row.review_audit_event_id, revoked=None)
    return snapshot, published, audit_ids


def _project_frozen(snapshot, published, audit_ids):
    # Internal reconstruction of the truthful task-time record only. The split
    # public/private DTOs expose no live inventory_current/eligible flag.
    historical = c.ScopeRecord(
        schema_version="document_change_scope_record_v1",
        snapshot=snapshot,
        content_hash=c.e.digest(snapshot),
        governance=published,
        governance_hash=c.e.digest(published),
        inventory_current=True,
        audit_event_ids=audit_ids,
        eligible=True,
        ineligibility_reasons=[],
        hospital_wide_rule_inventory="not_provided",
        automatic_supersession=False,
        clinical_validation="not_provided",
    )
    return checked_source(sources.public_source(historical))


def _created_detail(bound):
    return {"schema_version": "document_change_artifact_created_v1", "scope_id": bound.scope.scope_id, "source_digest": bound.source_digest, "source_binding_hash": c.e.digest(bound)}


def _load_locked(db, run, task):
    snapshot, context, metadata, evidence = task
    bound = context.document_change_binding
    scope_snapshot, published, scope_audits = _scope_frozen(db, context)
    with db.no_autoflush:
        row = db.query(AIDocumentChangeRunArtifact).filter_by(run_id=run.run_id).populate_existing().with_for_update(read=True).one_or_none()
    if (
        row is None
        or row.schema_version != ARTIFACT_SCHEMA
        or row.requested_by != run.requested_by
        or any(getattr(row, key) != value for key, value in {**_binding_columns(bound), **_anchor_values(run)}.items())
    ):
        raise ValueError("The independent concrete SQL Artifact/Run anchors differ")
    if (
        row.recorded_at < c.e.clock(context.snapshot_time)
        or row.scope_governance_json != require_case_json(published)
        or (row.scope_created_audit_event_id, row.scope_review_audit_event_id) != (scope_audits.created, scope_audits.reviewed)
    ):
        raise ValueError("The actual frozen review, audit identities or capture clock differ")
    source = checked_source(parse_case_json(row.source_json))
    if (
        require_case_json(source) != row.source_json
        or row.source_bytes != len(c.e.utf8(row.source_json))
        or c.e.bytes_hash(row.source_json) != row.source_digest
        or source != _project_frozen(scope_snapshot, published, scope_audits)
        or binding_for_source(source) != bound
    ):
        raise ValueError("The complete raw public source or unique private projection differs")
    with db.no_autoflush:
        audit = db.query(AIAuditEvent).filter_by(event_id=row.created_audit_event_id).populate_existing().with_for_update(read=True).one_or_none()
    expected = (run.requested_by, ARTIFACT_CREATED, run.run_id, c.e.canonical_json(_created_detail(bound)), row.recorded_at.replace(microsecond=0))
    if audit is None or tuple(getattr(audit, name) for name in ("actor_id", "action", "target", "detail_json", "create_time")) != expected:
        raise ValueError("The exact task creation audit is unavailable")
    public_payload(snapshot["payload"], source)
    source_packet(run.run_id, bound, source)
    private_scope_packet(run.run_id, bound, scope_snapshot, published, scope_audits)
    return snapshot, metadata, evidence, bound, row, source


def authorize_run(db, user, run, *, current=True):
    try:
        originals.current_super(db, user)
        task = _task(run)
        if current:
            verify_current_context(db, user, task[1].model_dump(mode="json"))
        return _load_locked(db, run, task)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "指南版本任务的完整Scope、原文、Prompt或独立SQL锚不一致") from exc


def load_snapshot(db, run, *, user=None, current=True):
    if user is None:
        with db.no_autoflush:
            user = db.query(User).filter_by(user_id=run.requested_by).populate_existing().with_for_update(read=True).one_or_none()
        if user is None:
            raise HTTPException(403, "当前原任务超级管理员已失效")
    return authorize_run(db, user, run, current=current)


@originals._write
def stage_artifact(db, user, run):
    actor = originals.current_super(db, user)
    epoch = originals._epoch(actor)
    task = _task(run)
    _, record, source = verify_current_context(db, actor, task[1].model_dump(mode="json"))
    bound = task[1].document_change_binding
    source_packet(run.run_id, bound, source)
    private_scope_packet(run.run_id, bound, record.snapshot, record.governance, record.audit_event_ids)
    raw = require_case_json(source)
    now = sources.utcnow()
    if now < c.e.clock(task[1].snapshot_time) or run.requested_by != actor.user_id:
        raise ValueError("The actual actor or task creation clock differs")
    with db.no_autoflush:
        if db.query(AIDocumentChangeRunArtifact.run_id).filter_by(run_id=run.run_id).with_for_update(read=True).first() is not None:
            raise ValueError("An immutable task Artifact cannot be overwritten")
    audit = AIAuditEvent(actor_id=actor.user_id, action=ARTIFACT_CREATED, target=run.run_id, detail_json=c.e.canonical_json(_created_detail(bound)), create_time=now.replace(microsecond=0))
    db.add(audit)
    db.flush()
    row = AIDocumentChangeRunArtifact(
        run_id=run.run_id,
        requested_by=actor.user_id,
        schema_version=ARTIFACT_SCHEMA,
        recorded_at=now,
        **_binding_columns(bound),
        **_anchor_values(run),
        source_bytes=len(c.e.utf8(raw)),
        source_json=raw,
        scope_governance_json=require_case_json(record.governance),
        scope_created_audit_event_id=record.audit_event_ids.created,
        scope_review_audit_event_id=record.audit_event_ids.reviewed,
        created_audit_event_id=audit.event_id,
        usage_event_id=None,
    )
    db.add(row)
    db.flush()
    originals.current_super(db, actor, expected=epoch)
    load_snapshot(db, run, user=actor, current=True)
    return row


def artifact_record(db, user, run, *, current=True):
    _, _, _, bound, row, _ = authorize_run(db, user, run, current=current)
    return DocumentChangeArtifactRecord(
        schema_version=ARTIFACT_SCHEMA,
        run_id=row.run_id,
        requested_by=row.requested_by,
        recorded_at=c.e.utc_text(row.recorded_at),
        document_change_binding=bound,
        source_bytes=row.source_bytes,
        **{name: getattr(row, name) for name in ANCHOR_HASH_FIELDS},
        scope_created_audit_event_id=row.scope_created_audit_event_id,
        scope_review_audit_event_id=row.scope_review_audit_event_id,
        created_audit_event_id=row.created_audit_event_id,
        usage_event_id=row.usage_event_id,
    )


def expanded_source(db, user, run, *, current=True):
    _, _, _, bound, _, source = authorize_run(db, user, run, current=current)
    return source_packet(run.run_id, bound, source)


def expanded_private_scope(db, user, run, *, current=True):
    _, context, _, _ = _task(run)
    authorize_run(db, user, run, current=current)
    snapshot, published, audits = _scope_frozen(db, context)
    return private_scope_packet(run.run_id, context.document_change_binding, snapshot, published, audits)


def is_document_change_run(db, run):
    """Nonlocking immutable identity dispatch only; never an authorization result.

    Run and Artifact are created atomically. An old RR view may see neither; it
    must fail closed rather than obtain Artifact locks before Original locks.
    """
    from app.ai.models import AIRun

    if run.feature_key == FEATURE_KEY:
        return True
    try:
        snapshot = _json(run.input_json)
        payload = snapshot.get("payload")
        if type(payload) is not dict:
            raise ValueError("The retained task envelope cannot be classified")
        values, context = payload.get("input"), payload.get("context")
        if type(values) is not dict or type(context) is not dict:
            raise ValueError("The retained task references cannot be classified")
        if "document_change_scope_id" in values or {"document_change_binding", "document_change_source", "document_change_private_scope"} & context.keys():
            return True
        result = _json(run.result_json)
        if "document_change" in result or result.get("schema_version") == "document_change_result_ref_v1":
            return True
        with db.no_autoflush:
            identity = (
                db.query(AIRun.feature_key, AIDocumentChangeRunArtifact.run_id)
                .outerjoin(AIDocumentChangeRunArtifact, AIRun.run_id == AIDocumentChangeRunArtifact.run_id)
                .filter(AIRun.run_id == run.run_id)
                .one_or_none()
            )
        if identity is None or identity.feature_key != run.feature_key:
            raise ValueError("The immutable Run/Artifact identity cannot be classified")
        return identity[1] is not None
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "任务原生身份不完整，未降级为通用任务") from exc
