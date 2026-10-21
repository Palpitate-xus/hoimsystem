"""Seed-bound complete leaflet tasks; integrity helpers never grant authority.

All existing-task entries take InventoryGate X, then one deliberate opaque
Artifact locator SHARE (run/source/owner only). A plain RR locator can miss a
new real anchor. No seed or Task TEXT is read at this exception. Sorted actual
Users and Source parents precede Run and complete Artifact locks. Exact audit
PKs replace action/target range scans. Callers own commit and rollback.
"""

import hashlib
import json
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import inspect

from app.ai import document_evidence_contract as d
from app.ai import document_evidence_sources as documents
from app.ai import drug_label_sources as sources
from app.ai.context import ContextBundle, context_metadata
from app.ai.document_evidence_models import AIDocumentOriginal
from app.ai.drug_label_context_contract import checked_context, evidence_for_binding, expand_public_context, selection
from app.ai.drug_label_draft import SYSTEM_PROMPT
from app.ai.drug_label_models import AIDrugLabelProfessionalReview, AIDrugLabelSource
from app.ai.drug_label_projection import project_source
from app.ai.drug_label_result import validate_result
from app.ai.drug_label_run_contract import (
    ACCEPT_ACTION,
    CREATE_ACTION,
    MAX_RESULT_BYTES,
    MAX_TEXT_BYTES,
    USAGE_ACTION,
    DrugLabelFrozenProvider,
    DrugLabelFrozenValidation,
    DrugLabelResultPointer,
    DrugLabelUsageReceipt,
)
from app.ai.drug_label_run_models import ARTIFACT_SCHEMA, AIDrugLabelRunArtifact
from app.ai.inventory_write_guard import current_inventory_rows, lock_inventory_gate
from app.ai.models import AIAuditEvent, AIRun
from app.models import Pharmaceutical, User

FEATURE_KEY = "drug_label_extraction"
STATUSES = {"queued", "running", "succeeded", "failed", "cancelled"}


def text_hash(value, maximum=MAX_TEXT_BYTES):
    if type(value) is not str or not 1 <= len(d.utf8(value)) <= maximum:
        raise ValueError("Complete original UTF8 text is missing or oversized")
    return hashlib.sha256(d.utf8(value)).hexdigest()


def _json(raw, maximum=MAX_TEXT_BYTES):
    text_hash(raw, maximum)
    value = d.parse_json(raw)
    if d.canonical_json(value) != raw:
        raise ValueError("Complete original JSON scalars/bytes must remain canonical")
    return value


def instructions_digest(system, task):
    return hashlib.sha256(d.utf8(system + "\n\n" + task)).hexdigest()


def _opaque_run_id(run):
    """Raw locator only: legacy generic IDs are not subjected to 73 UUID rules."""
    if isinstance(run, str):
        return run
    state = inspect(run, raiseerr=False)
    return (state.identity[0] if state.identity else state.dict.get("run_id")) if state is not None else getattr(run, "run_id", None)


def _run_id(run):
    return sources._key(_opaque_run_id(run))


def _locator(db, identifier):
    # Gate BEFORE this precise current opaque FK lookup, never after it.
    lock_inventory_gate(db)
    return current_inventory_rows(
        db.query(AIDrugLabelRunArtifact.run_id, AIDrugLabelRunArtifact.source_binding_id, AIDrugLabelRunArtifact.requested_by).filter_by(run_id=identifier), shared=True
    ).one_or_none()


def is_drug_label_run(db, run):
    if db is not None:
        with db.no_autoflush:
            # Exact current SQL classification precedes every Task JSON read.
            # A generic/non-UUID locator is still valid input to this lookup.
            if _locator(db, _opaque_run_id(run)) is not None:
                return True
    state = inspect(run, raiseerr=False)
    data = state.dict if state is not None else vars(run) if hasattr(run, "__dict__") else {}
    if data.get("feature_key") == FEATURE_KEY:
        return True
    for field in ("input_json", "evidence_json", "context_metadata_json", "result_json"):
        try:
            value = json.loads(data.get(field, "null"))
        except (ValueError, TypeError, RecursionError):
            continue
        if isinstance(value, dict) and (
            value.get("schema_version") == "drug_label_result_pointer_v1" or {"drug_label_extraction", "drug_label_binding", "drug_label_source_binding_id"} & value.keys()
        ):
            return True
        if field == "input_json" and isinstance(value, dict):
            payload = value.get("payload")
            if isinstance(payload, dict) and any(
                isinstance(payload.get(k), dict) and bool({"drug_label_binding", "drug_label_source", "drug_label_source_binding_id"} & payload[k].keys()) for k in ("input", "context")
            ):
                return True
    return False


def _source_locked(db, binding_id, owner_id, user=None, frozen_audit=False):
    hint = db.query(AIDrugLabelSource.pharmaceutical_id, AIDrugLabelSource.original_id).filter_by(source_binding_id=binding_id).one_or_none()
    signer_hint = db.query(AIDrugLabelProfessionalReview.signed_by).filter_by(source_binding_id=binding_id).one_or_none()
    actor_id, epoch = sources._user_hint(user) if user is not None else (owner_id, None)
    ids = {owner_id, actor_id, *(() if signer_hint is None else (signer_hint[0],))}
    actors = {}
    for identifier in sorted(ids):
        value = current_inventory_rows(db.query(User).filter_by(user_id=identifier), shared=True).one_or_none()
        if value is not None:
            actors[identifier] = value
    owner, actor = actors.get(owner_id), actors.get(actor_id)
    if owner is None or actor is None:
        raise HTTPException(403, "当前任务账户不存在")
    if user is not None:
        if actor.user_role not in sources.c.SOURCE_ROLES or epoch is not None and epoch != (actor.user_role, actor.token_invalid_before):
            raise HTTPException(403, "当前说明书任务账户或会话已失效")
        if frozen_audit:
            if actor.user_role != "super_admin":
                raise HTTPException(403, "只有当前超级管理员可明确读取冻结任务")
        elif actor_id != owner_id:
            raise HTTPException(403, "普通说明书任务只允许当前本人读取")
    if hint is None:
        raise HTTPException(409, "任务绑定的完整来源不可用")
    sku = current_inventory_rows(db.query(Pharmaceutical).filter_by(pharmaceutical_id=hint[0]), shared=True).one_or_none()
    original = current_inventory_rows(db.query(AIDocumentOriginal).filter_by(original_id=hint[1]), shared=True).one_or_none()
    row = current_inventory_rows(db.query(AIDrugLabelSource).filter_by(source_binding_id=binding_id), shared=True).one_or_none()
    professional = current_inventory_rows(db.query(AIDrugLabelProfessionalReview).filter_by(source_binding_id=binding_id), shared=True).one_or_none()
    if row is None or (row.pharmaceutical_id, row.original_id) != tuple(hint) or (professional.signed_by if professional else None) != (signer_hint[0] if signer_hint else None):
        raise HTTPException(409, "来源定位与当前完整集合不符")
    snapshot, signature = sources._snapshot(row), sources._professional(professional)
    current_original = documents._original_record(original) if original is not None else None
    record = sources._view(
        row,
        snapshot,
        signature,
        actor,
        sku_current=sku is not None and type(sku.status) is int and sku.status == 0 and d.digest(sources.identity(sku)) == snapshot.identity_hash,
        original_current=current_original is not None
        and current_original.eligible
        and current_original.content_hash == snapshot.original.content_hash
        and current_original.governance_hash == snapshot.original.governance_hash,
        signer_current=professional is not None and actors.get(professional.signed_by) is not None and actors[professional.signed_by].user_role == "pharmacist",
        audit_only=True,
    )
    # This audit-shaped record is an INTERNAL immutable proof, not an assertion
    # that owner/actor holds Super authority. Public reads authorize below.
    return record, actor


def _task(run):
    snapshot, evidence, metadata = _json(run.input_json), _json(run.evidence_json), _json(run.context_metadata_json)
    if run.feature_key != FEATURE_KEY or run.patient_id is not None or run.encounter_ref is not None or run.status not in STATUSES or type(run.requested_by) is not int or run.requested_by < 1:
        raise ValueError("Task feature, owner, status and absence of patient scope must remain exact")
    if not isinstance(snapshot, dict) or set(snapshot) != {"catalog_version", "system_prompt", "task_prompt", "payload", "provider_snapshot", "feature_validation"}:
        raise ValueError("A closed complete task is required")
    system, task = snapshot["system_prompt"], snapshot["task_prompt"]
    if system != SYSTEM_PROMPT or type(task) is not str or not task.strip() or type(snapshot["catalog_version"]) is not str or not snapshot["catalog_version"]:
        raise ValueError("The actual fixed system, complete task and catalog must be retained")
    payload = snapshot["payload"]
    if not isinstance(payload, dict) or set(payload) != {"input", "context", "tools", "evidence"} or payload["tools"] != {}:
        raise ValueError("One short leaflet input with no tools is required")
    binding = checked_context(payload["context"])
    request = selection(payload["input"])
    if request.drug_label_source_binding_id != binding.source.source_binding_id or payload["evidence"] != evidence or evidence != evidence_for_binding(binding):
        raise ValueError("Input, complete evidence and context must bind one identical release")
    provider = DrugLabelFrozenProvider.model_validate(snapshot["provider_snapshot"])
    validation = DrugLabelFrozenValidation.model_validate(snapshot["feature_validation"])
    if d.canonical_json(provider) != d.canonical_json(snapshot["provider_snapshot"]) or d.canonical_json(validation) != d.canonical_json(snapshot["feature_validation"]):
        raise ValueError("Frozen model/validation scalar types must remain original")
    if (
        run.provider_id != provider.provider_id
        or run.provider_revision != provider.revision
        or type(run.prompt_version) is not int
        or run.prompt_version < 0
        or d.digest([system, task]) != run.prompt_hash
        or d.digest(payload["context"]) != run.context_digest
    ):
        raise ValueError("Actual Run provider, Prompt and context anchors differ")
    expected = {
        **context_metadata(ContextBundle(data=payload["context"], evidence=evidence)),
        "feature_revision": validation.feature_revision,
        "validation_status": validation.status,
        "tool_fingerprint": d.digest({}),
        "instructions_digest": instructions_digest(system, task),
        "model_version": provider.model,
    }
    if d.canonical_json(metadata) != d.canonical_json(expected):
        raise ValueError("The complete short task metadata differs")
    return snapshot, binding, metadata


def _hashes(run, binding):
    return dict(
        input_hash=text_hash(run.input_json),
        evidence_hash=text_hash(run.evidence_json),
        metadata_hash=text_hash(run.context_metadata_json),
        prompt_hash=run.prompt_hash,
        context_digest=run.context_digest,
        source_binding_hash=d.digest(binding),
    )


def create_audit_detail(run, binding):
    return d.canonical_json(
        {"schema_version": "drug_label_create_audit_v1", "run_id": run.run_id, "source_binding_id": binding.source.source_binding_id, "requested_by": run.requested_by, **_hashes(run, binding)}
    )


def _audit(db, event_id, actor_id, action, target, detail):
    if type(event_id) is not int or event_id < 1:
        raise ValueError("One precise real audit reference is required")
    row = current_inventory_rows(db.query(AIAuditEvent).filter_by(event_id=event_id), shared=True).one_or_none()
    if row is None or (row.actor_id, row.action, row.target, row.detail_json) != (actor_id, action, target, detail):
        raise ValueError("The precise audit PK and complete original fields differ")
    return row


@dataclass
class DrugLabelStoredTask:
    run: AIRun
    artifact: AIDrugLabelRunArtifact
    snapshot: dict
    binding: object
    metadata: dict
    source_record: object
    public_source: object


def _loaded(db, run, artifact, record):
    snapshot, binding, metadata = _task(run)
    expected = _hashes(run, binding)
    if (
        artifact.schema_version != ARTIFACT_SCHEMA
        or artifact.requested_by != run.requested_by
        or artifact.source_binding_id != binding.source.source_binding_id
        or any(getattr(artifact, name) != value for name, value in expected.items())
    ):
        raise ValueError("The durable task anchors differ from complete original bytes")
    if artifact.created_at < d.clock(snapshot["payload"]["context"]["snapshot_time"]):
        raise ValueError("An artifact cannot precede its source/context capture")
    public = project_source(record, secret=artifact.mapping_seed, frozen=True)
    expand_public_context(snapshot["payload"]["context"], public)
    _audit(db, artifact.create_event_id, run.requested_by, CREATE_ACTION, run.run_id, create_audit_detail(run, binding))
    return DrugLabelStoredTask(run, artifact, snapshot, binding, metadata, record, public)


def load_snapshot(db, run, *, user=None, frozen_audit=False, writing=False):
    """Internal integrity by default; user mode checks role before private rows."""
    try:
        identifier = _run_id(run)
        with db.no_autoflush:
            hint = _locator(db, identifier)
            if hint is None:
                raise ValueError("A real immutable task artifact is required")
            record, _ = _source_locked(db, hint.source_binding_id, hint.requested_by, user=user, frozen_audit=frozen_audit)
            actual = current_inventory_rows(db.query(AIRun).filter_by(run_id=identifier), shared=not writing).one_or_none()
            artifact = current_inventory_rows(db.query(AIDrugLabelRunArtifact).filter_by(run_id=identifier), shared=not writing).one_or_none()
            if actual is None or artifact is None or (artifact.run_id, artifact.source_binding_id, artifact.requested_by) != tuple(hint):
                raise ValueError("The actual task or immutable locator changed")
            return _loaded(db, actual, artifact, record)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "说明书完整任务、私有映射或具体审计锚无法核对；未降级读取") from exc


def stage_artifact(db, run, *, mapping_seed, create_event_id):
    """Caller has created one actual Source-authorized queue transaction."""
    try:
        snapshot, binding, _ = _task(run)
        with db.no_autoflush:
            lock_inventory_gate(db)
            record, actor = _source_locked(db, binding.source.source_binding_id, run.requested_by)
            # Internal proof above never authorizes a new task. Current Source
            # execution is independently mandatory at staging.
            sources.source_current(db, actor, binding.source.source_binding_id, execution=True)
            public = project_source(record, secret=mapping_seed, frozen=True)
            expand_public_context(snapshot["payload"]["context"], public)
            created = sources.utcnow()
            if created < d.clock(snapshot["payload"]["context"]["snapshot_time"]):
                raise ValueError("Server creation clock precedes its actual context")
            artifact = AIDrugLabelRunArtifact(
                run_id=run.run_id,
                source_binding_id=binding.source.source_binding_id,
                requested_by=run.requested_by,
                schema_version=ARTIFACT_SCHEMA,
                created_at=created,
                mapping_seed=mapping_seed,
                create_event_id=create_event_id,
                **_hashes(run, binding),
            )
            db.add(artifact)
            expected = {column.name: getattr(artifact, column.name) for column in artifact.__table__.columns}
            db.flush()
            actual = db.query(*AIDrugLabelRunArtifact.__table__.columns).filter_by(run_id=run.run_id).with_for_update().one_or_none()
            if actual is None or dict(actual._mapping) != expected:
                raise ValueError("The actual inserted artifact differs from all staged fields")
            return load_snapshot(db, run)
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "完整说明书任务未能建立不可变原件、映射和具体创建审计") from exc


def authorize_drug_label_run(db, user, run, *, frozen_audit=False, writing=False):
    if type(frozen_audit) is not bool:
        raise HTTPException(409, "冻结审计必须明确选择")
    stored = load_snapshot(db, run, user=user, frozen_audit=frozen_audit, writing=writing)
    record = sources.source_current(db, user, stored.artifact.source_binding_id, audit_only=frozen_audit, execution=not frozen_audit)
    public = project_source(record, secret=stored.artifact.mapping_seed, frozen=frozen_audit)
    if public != stored.public_source:
        raise HTTPException(409, "当前授权与冻结任务完整投影不一致")
    stored.source_record = record
    return stored


def result_pointer(run_id, result_hash, result_bytes):
    return DrugLabelResultPointer(schema_version="drug_label_result_pointer_v1", run_id=run_id, result_hash=result_hash, result_bytes=result_bytes).model_dump(mode="json")


def accept_audit_detail(stored):
    artifact = stored.artifact
    return d.canonical_json(
        {
            "schema_version": "drug_label_accept_audit_v1",
            "run_id": stored.run.run_id,
            **_hashes(stored.run, stored.binding),
            "result_hash": artifact.result_hash,
            "result_bytes": artifact.result_bytes,
            "accepted_at": d.utc_text(artifact.accepted_at),
            "accepted_lease": artifact.accepted_lease,
            "receipt_event_id": artifact.receipt_event_id,
        }
    )


def usage_receipt(db, stored):
    artifact, run = stored.artifact, stored.run
    if artifact.receipt_event_id is None:
        if run.status in {"queued", "running"} or run.status == "cancelled" and run.lease_token is not None:
            return None
        raise HTTPException(409, "终态任务缺少实际用量审计")
    try:
        row = current_inventory_rows(db.query(AIAuditEvent).filter_by(event_id=artifact.receipt_event_id), shared=True).one_or_none()
        if row is None:
            raise ValueError("The real usage audit is missing")
        receipt = DrugLabelUsageReceipt.model_validate(_json(row.detail_json))
        expected = {
            "run_id": run.run_id,
            "source_binding_hash": artifact.source_binding_hash,
            "input_hash": artifact.input_hash,
            "evidence_hash": artifact.evidence_hash,
            "metadata_hash": artifact.metadata_hash,
            "lease_token": run.lease_token,
            "result_hash": artifact.result_hash,
            "status": run.status,
        }
        if any(getattr(receipt, name) != value for name, value in expected.items()) or (row.actor_id, row.action, row.target) != (run.requested_by, USAGE_ACTION, run.run_id):
            raise ValueError("Usage receipt authority or complete task differs")
        if run.input_tokens != (receipt.input_tokens if receipt.input_tokens is not None else 0) or run.output_tokens != (receipt.output_tokens if receipt.output_tokens is not None else 0):
            raise ValueError("Actual Run counters differ from their independent nullable receipt")
        return receipt
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "实际逐项用量、任务和精确审计无法核对") from exc


def verify_artifact_result(db, stored):
    run, artifact = stored.run, stored.artifact
    try:
        receipt = usage_receipt(db, stored)
        if run.status != "succeeded":
            if run.result_json != "{}" or any(getattr(artifact, name) is not None for name in ("result_json", "result_hash", "result_bytes", "accepted_at", "accepted_lease", "accept_event_id")):
                raise ValueError("An unsuccessful task cannot carry an accepted draft/pointer")
            return None
        pointer = DrugLabelResultPointer.model_validate(_json(run.result_json))
        if (
            pointer.model_dump(mode="json") != result_pointer(run.run_id, artifact.result_hash, artifact.result_bytes)
            or artifact.accepted_at is None
            or artifact.accepted_at < artifact.created_at
            or artifact.accepted_lease != run.lease_token
            or receipt is None
        ):
            raise ValueError("Complete success pointer, real lease or acceptance clock differs")
        if text_hash(artifact.result_json, MAX_RESULT_BYTES) != artifact.result_hash or len(d.utf8(artifact.result_json)) != artifact.result_bytes:
            raise ValueError("Complete accepted result bytes differ")
        result = validate_result(_json(artifact.result_json, MAX_RESULT_BYTES), stored.public_source, stored.metadata["instructions_digest"])
        _audit(db, artifact.accept_event_id, run.requested_by, ACCEPT_ACTION, run.run_id, accept_audit_detail(stored))
        return result.model_dump(mode="json")
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "完整抽取结果、原文、接受时钟或具体审计无法核对") from exc


def load_result(db, user, run, *, frozen_audit=False):
    stored = authorize_drug_label_run(db, user, run, frozen_audit=frozen_audit)
    return verify_artifact_result(db, stored)


def artifact_view(stored):
    """Pure already-authorized technical view; neither seed nor lease is public."""
    artifact = stored.artifact
    return {
        "schema_version": ARTIFACT_SCHEMA,
        "run_id": artifact.run_id,
        "source_binding_id": artifact.source_binding_id,
        "requested_by": artifact.requested_by,
        "created_at": d.utc_text(artifact.created_at),
        **{name: getattr(artifact, name) for name in ("input_hash", "evidence_hash", "metadata_hash", "prompt_hash", "context_digest", "source_binding_hash")},
        "create_event_id": artifact.create_event_id,
        "receipt_event_id": artifact.receipt_event_id,
        "accept_event_id": artifact.accept_event_id,
        "accepted_at": d.utc_text(artifact.accepted_at) if artifact.accepted_at is not None else None,
        "result_hash": artifact.result_hash,
        "result_bytes": artifact.result_bytes,
    }
