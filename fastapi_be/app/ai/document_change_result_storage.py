"""Lease-bound complete Result/receipt SQL writes; never commits or calls a model.

Successful acceptance locks live Source -> Run -> Artifact. Technical failure or
cancellation receipts lock Run -> Artifact only; they never read live Source or
publish model text after authority has changed. Callers release transactions
before any network await. Public cancel handlers must authorize current Super.
"""

from typing import Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from app.ai import document_change_contract as c
from app.ai import document_change_storage as storage
from app.ai import document_evidence_sources as originals
from app.ai.document_change_context import verify_current_context
from app.ai.document_change_json import parse_case_json, require_case_json
from app.ai.document_change_result import validate_result
from app.ai.document_change_run_models import AIDocumentChangeRunArtifact, AIDocumentChangeRunResult
from app.ai.document_change_view_contract import DocumentChangeResultReference, result_packet
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.ai.native_acceptance import RUN_FIELDS

USAGE = "run.document_change.usage"
ACCEPT = "run.document_change.accept"
WRITE_FIELDS = tuple(dict.fromkeys((*RUN_FIELDS, "input_tokens", "output_tokens", "error_code", "error_message", "latency_ms", "create_time", "start_time", "finish_time")))
IMMUTABLE_FIELDS = tuple(
    name for name in WRITE_FIELDS if name not in {"status", "lease_token", "result_json", "input_tokens", "output_tokens", "error_code", "error_message", "latency_ms", "finish_time"}
)


class Usage(c.e.StrictModel):
    input_tokens: int | None = Field(strict=True, ge=0, le=2000000)
    output_tokens: int | None = Field(strict=True, ge=0, le=2000000)
    complete: bool = Field(strict=True)
    model_call_attempted: bool | None = Field(strict=True)

    @model_validator(mode="after")
    def actual_usage(self):
        if self.complete != (self.input_tokens is not None and self.output_tokens is not None):
            raise ValueError("Completeness follows actual reported counts, never a zero fallback")
        if self.model_call_attempted is None and (self.complete or self.input_tokens is not None or self.output_tokens is not None):
            raise ValueError("An unknown call cannot claim actual provider counts")
        if self.model_call_attempted is False and (not self.complete or (self.input_tokens, self.output_tokens) != (0, 0)):
            raise ValueError("A proven uncalled request has known zero counts")
        return self


class Receipt(c.e.StrictModel):
    schema_version: Literal["document_change_usage_v1"]
    lease_token: c.e.UUID | None
    usage: Usage
    status: Literal["succeeded", "failed", "cancelled"]
    result_hash: c.e.SHA256 | None
    error_code: str | None = Field(max_length=80)


def _locked_run(db, run, lease, *, queued=False):
    with db.no_autoflush:
        row = db.query(*(getattr(AIRun, name) for name in WRITE_FIELDS)).filter_by(run_id=run.run_id).with_for_update().one_or_none()
    if row is None or any(getattr(row, name) != getattr(run, name) for name in IMMUTABLE_FIELDS):
        raise ValueError("The concrete current Run or its original immutable fields differ")
    if queued:
        if (
            lease is not None
            or row.status != "queued"
            or row.lease_token is not None
            or row.start_time is not None
            or row.result_json != "{}"
            or row.input_tokens != 0
            or row.output_tokens != 0
            or row.latency_ms is not None
        ):
            raise ValueError("Only an untouched actual queued task proves that no model call was made")
    else:
        if type(lease) is not str or row.lease_token != lease or run.lease_token != lease or row.status not in {"running", "cancelled"}:
            raise ValueError("The actual current execution lease is no longer valid")
    return row


def _artifact(db, run, context):
    with db.no_autoflush:
        row = db.query(AIDocumentChangeRunArtifact).filter_by(run_id=run.run_id).populate_existing().with_for_update().one_or_none()
    bound = context.document_change_binding
    if (
        row is None
        or row.schema_version != storage.ARTIFACT_SCHEMA
        or row.requested_by != run.requested_by
        or any(getattr(row, key) != value for key, value in {**storage._binding_columns(bound), **storage._anchor_values(run)}.items())
    ):
        raise ValueError("The concrete immutable task Artifact differs")
    if row.usage_event_id is not None:
        raise ValueError("An actual terminal receipt is immutable and cannot be overwritten")
    return row


def _execution_epoch(actor, artifact):
    # Artifact is the actual UTC6 capture clock. AIRun.create_time is legacy
    # DATETIME(0); comparing against its floor could reject a newly authorized
    # task created after a same-second token reset.
    if actor.token_invalid_before is not None and actor.token_invalid_before >= artifact.recorded_at:
        raise ValueError("The task predates actual current-session invalidation")


def _current_configuration(db, run, snapshot, metadata):
    """Current model/config/Prompt checks belong only to new acceptance, not audit."""
    from app.ai.catalog import CATALOG_VERSION, FEATURE_BY_KEY
    from app.ai.document_change_draft import TASK_PROMPT
    from app.ai.governance import provider_feature_issues
    from app.ai.runtime import provider_snapshot

    with db.no_autoflush:
        config = db.query(AIFeatureConfig).filter_by(feature_key=storage.FEATURE_KEY).populate_existing().with_for_update(read=True).one_or_none()
        provider = db.query(AIProvider).filter_by(provider_id=run.provider_id).populate_existing().with_for_update(read=True).one_or_none()
        prompt = (
            db.query(AIPromptVersion).filter_by(prompt_id=config.active_prompt_id).populate_existing().with_for_update(read=True).one_or_none()
            if config is not None and config.active_prompt_id
            else None
        )
    if config is None or provider is None or config.provider_id != run.provider_id or provider.enabled != 1 or provider.allows_patient_data != 1:
        raise ValueError("The actual authorized model configuration is unavailable")
    if provider_feature_issues(FEATURE_BY_KEY[storage.FEATURE_KEY], provider):
        raise ValueError("The current provider protocol or data-purpose scope is incompatible")
    validation = {
        "status": config.validation_status,
        "note": config.validation_note,
        "validated_by": config.validated_by,
        "validated_at": str(config.validated_at) if config.validated_at else None,
        "feature_revision": config.revision,
    }
    roles = c.e.parse_json(config.allowed_roles_json)
    if type(roles) is not list or any(type(role) is not str for role in roles):
        raise ValueError("The actual configured roles are invalid")
    if not run.preview and (config.enabled != 1 or config.validation_status != "validated" or "super_admin" not in roles):
        raise ValueError("Non-preview acceptance requires the current enabled validated Super scope")
    if (
        snapshot["catalog_version"] != CATALOG_VERSION
        or snapshot["provider_snapshot"] != provider_snapshot(provider)
        or snapshot["feature_validation"] != validation
        or config.revision != metadata["feature_revision"]
    ):
        raise ValueError("Actual catalog/model/configuration changed after capture")
    if config.active_prompt_id is None:
        if run.prompt_version != 0 or snapshot["task_prompt"] != TASK_PROMPT:
            raise ValueError("The actual packaged baseline Prompt differs")
    elif prompt is None or prompt.feature_key != storage.FEATURE_KEY or prompt.version != run.prompt_version or prompt.task_prompt != snapshot["task_prompt"]:
        raise ValueError("The actual frozen Prompt is no longer the configured Prompt")


def _event(db, actor_id, action, run, detail, now):
    row = AIAuditEvent(actor_id=actor_id, action=action, target=run.run_id, detail_json=require_case_json(detail), create_time=now.replace(microsecond=0))
    db.add(row)
    db.flush()
    return row


def _audit_value(event):
    return {key: getattr(event, key) for key in ("actor_id", "action", "target", "detail_json", "create_time")}


def _post_write(db, run, expected_run, expected_artifact, expected_usage, expected_accept=None):
    with db.no_autoflush:
        actual = db.query(*(getattr(AIRun, name) for name in WRITE_FIELDS)).filter_by(run_id=run.run_id).with_for_update().one_or_none()
        artifact = (
            db.query(*(getattr(AIDocumentChangeRunArtifact, column.name) for column in AIDocumentChangeRunArtifact.__table__.columns))
            .filter_by(run_id=run.run_id)
            .with_for_update(read=True)
            .one_or_none()
        )
    if actual is None or dict(actual._mapping) != expected_run or artifact is None or dict(artifact._mapping) != expected_artifact:
        raise ValueError("The complete actual terminal Run/lease/receipt write differs")
    for event_id, values in (expected_usage, expected_accept) if expected_accept else (expected_usage,):
        with db.no_autoflush:
            row = db.query(AIAuditEvent).filter_by(event_id=event_id).populate_existing().with_for_update(read=True).one_or_none()
        if row is None or _audit_value(row) != values:
            raise ValueError("The exact concrete terminal audit differs after SQL flush")


def _stage_usage(db, run, artifact, usage, status, result_hash, error_code, actor_id, now):
    receipt = Receipt(schema_version="document_change_usage_v1", lease_token=run.lease_token, usage=usage, status=status, result_hash=result_hash, error_code=error_code)
    if receipt.usage.model_call_attempted is None:
        raise ValueError("An unknown interrupted call remains pending; it cannot invent a terminal receipt")
    event = _event(db, actor_id, USAGE, run, receipt.model_dump(mode="json"), now)
    artifact.usage_event_id = event.event_id
    run.input_tokens = receipt.usage.input_tokens if receipt.usage.input_tokens is not None else 0
    run.output_tokens = receipt.usage.output_tokens if receipt.usage.output_tokens is not None else 0
    return event


@originals._write
def stage_result(db, user, run, lease, value, usage, *, latency_ms):
    actor = originals.current_super(db, user)
    epoch = originals._epoch(actor)
    task = storage._task(run)
    verify_current_context(db, actor, task[1].model_dump(mode="json"))
    _current_configuration(db, run, task[0], task[2])
    locked = _locked_run(db, run, lease)
    if locked.status != "running" or run.status != "running":
        raise ValueError("A cancelled or otherwise terminal task cannot accept model output")
    if run.requested_by != actor.user_id:
        raise ValueError("Only the actual current task author accepts its execution lease")
    snapshot, metadata, _, bound, _, source = storage._load_locked(db, run, task)
    artifact = _artifact(db, run, task[1])
    _execution_epoch(actor, artifact)
    expected_artifact = {column.name: getattr(artifact, column.name) for column in AIDocumentChangeRunArtifact.__table__.columns}
    checked = validate_result(value, source, metadata["instructions_digest"])
    result_packet(run.run_id, bound, metadata["instructions_digest"], checked)
    usage = Usage.model_validate(usage)
    if not usage.complete or usage.model_call_attempted is not True or type(latency_ms) is not int or not 0 <= latency_ms <= 2147483647:
        raise ValueError("Accepted provider output requires complete actual usage and bounded actual latency")
    raw = require_case_json(checked)
    content_hash, now = c.e.bytes_hash(raw), storage.sources.utcnow()
    if now < artifact.recorded_at:
        raise ValueError("The actual acceptance clock predates task capture")
    if db.query(AIDocumentChangeRunResult.run_id).filter_by(run_id=run.run_id).first() is not None:
        raise ValueError("The complete accepted Result cannot be overwritten")
    receipt = _stage_usage(db, run, artifact, usage, "succeeded", content_hash, None, actor.user_id, now)
    detail = {
        "schema_version": "document_change_accept_v1",
        "scope_id": bound.scope.scope_id,
        "lease_token": lease,
        "source_binding_hash": c.e.digest(bound),
        "result_hash": content_hash,
        "result_bytes": len(c.e.utf8(raw)),
        "usage_event_id": receipt.event_id,
    }
    acceptance = _event(db, actor.user_id, ACCEPT, run, detail, now)
    row = AIDocumentChangeRunResult(
        run_id=run.run_id,
        scope_id=bound.scope.scope_id,
        schema_version="document_change_run_result_v1",
        lease_token=lease,
        content_hash=content_hash,
        result_bytes=len(c.e.utf8(raw)),
        result_json=raw,
        source_binding_hash=c.e.digest(bound),
        accepted_at=now,
        accept_audit_event_id=acceptance.event_id,
    )
    db.add(row)
    reference = DocumentChangeResultReference(
        schema_version="document_change_result_ref_v1",
        run_id=run.run_id,
        scope_id=bound.scope.scope_id,
        lease_token=lease,
        content_hash=content_hash,
        result_bytes=row.result_bytes,
        source_binding_hash=row.source_binding_hash,
        accept_audit_event_id=acceptance.event_id,
    )
    run.status, run.result_json, run.error_code, run.error_message, run.latency_ms, run.finish_time = "succeeded", require_case_json(reference), None, None, latency_ms, now.replace(microsecond=0)
    expected_run = {name: getattr(run, name) for name in WRITE_FIELDS}
    expected_usage, expected_accept = (receipt.event_id, _audit_value(receipt)), (acceptance.event_id, _audit_value(acceptance))
    db.flush()
    expected_artifact["usage_event_id"] = receipt.event_id
    _post_write(db, run, expected_run, expected_artifact, expected_usage, expected_accept)
    originals.current_super(db, actor, expected=epoch)
    verify_current_context(db, actor, task[1].model_dump(mode="json"))
    _current_configuration(db, run, snapshot, metadata)
    if expand_result(db, actor, run, current=True) != checked:
        raise ValueError("The concrete stored complete Result differs after SQL flush")
    return reference


@originals._write
def stage_terminal(db, run, lease, *, status, usage, latency_ms, error_code=None, error_message=None, queued_no_call=False, actor_id=None):
    """Internal trusted lease worker receipt only; exposes no Source or model text.

    For queued_no_call, the public caller must first current-Super-authorize and
    lock the Run. This helper proves actual untouched SQL queue state as well.
    """
    if status not in {"failed", "cancelled"} or type(latency_ms) is not int or not 0 <= latency_ms <= 2147483647:
        raise ValueError("Only a bounded actual unsuccessful terminal receipt is accepted")
    task = storage._task(run)
    actual = _locked_run(db, run, lease, queued=queued_no_call)
    if queued_no_call and status != "cancelled":
        raise ValueError("Only explicit cancellation can prove an untouched queue did not call a model")
    if actual.status == "cancelled" and status != "cancelled":
        raise ValueError("A cancellation winner cannot be changed to failure")
    artifact = _artifact(db, run, task[1])
    expected_artifact = {column.name: getattr(artifact, column.name) for column in AIDocumentChangeRunArtifact.__table__.columns}
    usage = Usage.model_validate(usage)
    if queued_no_call and usage != Usage(input_tokens=0, output_tokens=0, complete=True, model_call_attempted=False):
        raise ValueError("A never-claimed queue cancellation requires the exact proven zero receipt")
    actor_id = run.requested_by if actor_id is None else actor_id
    if type(actor_id) is not int or actor_id < 1:
        raise ValueError("An actual audit actor is required")
    if error_code is not None and (type(error_code) is not str or len(error_code) > 80) or error_message is not None and (type(error_message) is not str or len(error_message) > 500):
        raise ValueError("The actual bounded error fields are invalid")
    now = storage.sources.utcnow()
    if now < artifact.recorded_at:
        raise ValueError("The actual terminal clock predates task capture")
    receipt = _stage_usage(db, run, artifact, usage, status, None, error_code, actor_id, now)
    run.status, run.result_json, run.error_code, run.error_message, run.latency_ms, run.finish_time = status, "{}", error_code, error_message, latency_ms, now.replace(microsecond=0)
    expected_run = {name: getattr(run, name) for name in WRITE_FIELDS}
    db.flush()
    expected_artifact["usage_event_id"] = receipt.event_id
    _post_write(db, run, expected_run, expected_artifact, (receipt.event_id, _audit_value(receipt)))
    return receipt.event_id


def usage_receipt(db, run):
    with db.no_autoflush:
        artifact = db.query(AIDocumentChangeRunArtifact).filter_by(run_id=run.run_id).populate_existing().with_for_update(read=True).one_or_none()
    if artifact is None:
        raise HTTPException(409, "实际指南版本任务用量锚缺失")
    if artifact.usage_event_id is None:
        if run.status in {"queued", "running"} or run.status == "cancelled" and run.latency_ms is None or run.error_code == "WORKER_INTERRUPTED":
            return Usage(input_tokens=None, output_tokens=None, complete=False, model_call_attempted=None)
        raise HTTPException(409, "最终实际用量记录缺失，未伪造零Token")
    with db.no_autoflush:
        row = db.query(AIAuditEvent).filter_by(event_id=artifact.usage_event_id).populate_existing().with_for_update(read=True).one_or_none()
    try:
        if row is None or row.action != USAGE or row.target != run.run_id:
            raise ValueError("The exact actual usage audit PK differs")
        data = storage._json(row.detail_json)
        receipt = Receipt.model_validate(data)
        if require_case_json(receipt) != row.detail_json or receipt.status != run.status or receipt.lease_token != run.lease_token or receipt.error_code != run.error_code:
            raise ValueError("The complete concrete receipt and Run differ")
        for name in ("input_tokens", "output_tokens"):
            value = getattr(receipt.usage, name)
            if getattr(run, name) != (value if value is not None else 0):
                raise ValueError("Legacy counters differ from the actual nullable reported counts")
        reference = DocumentChangeResultReference.model_validate(storage._json(run.result_json)) if run.status == "succeeded" else None
        if (
            receipt.result_hash != (reference.content_hash if reference is not None else None)
            or run.status == "succeeded"
            and (not receipt.usage.complete or receipt.usage.model_call_attempted is not True)
        ):
            raise ValueError("The accepted proof or complete actual usage differs")
        return receipt.usage
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "实际指南版本任务用量或租约审计不一致") from exc


def expand_result(db, user, run, *, current=True):
    _, metadata, _, bound, artifact, source = storage.authorize_run(db, user, run, current=current)
    try:
        if run.status != "succeeded":
            if run.result_json != "{}":
                raise ValueError("An unsuccessful task cannot carry accepted model questions")
            return None
        reference = DocumentChangeResultReference.model_validate(storage._json(run.result_json))
        if (
            require_case_json(reference) != run.result_json
            or reference.run_id != run.run_id
            or reference.scope_id != bound.scope.scope_id
            or reference.lease_token != run.lease_token
            or reference.source_binding_hash != c.e.digest(bound)
        ):
            raise ValueError("The exact canonical result reference differs")
        with db.no_autoflush:
            row = db.query(AIDocumentChangeRunResult).filter_by(run_id=run.run_id).populate_existing().with_for_update(read=True).one_or_none()
            audit = db.query(AIAuditEvent).filter_by(event_id=reference.accept_audit_event_id).populate_existing().with_for_update(read=True).one_or_none()
        if (
            row is None
            or row.schema_version != "document_change_run_result_v1"
            or any(getattr(row, name) != getattr(reference, name) for name in ("run_id", "scope_id", "lease_token", "content_hash", "result_bytes", "source_binding_hash", "accept_audit_event_id"))
        ):
            raise ValueError("The actual complete SQL Result identity differs")
        if c.e.bytes_hash(row.result_json) != reference.content_hash or len(c.e.utf8(row.result_json)) != reference.result_bytes:
            raise ValueError("The complete stored Result UTF8 bytes/hash differ")
        value = validate_result(parse_case_json(row.result_json), source, metadata["instructions_digest"])
        if require_case_json(value) != row.result_json:
            raise ValueError("The actual stored Result is not the complete canonical proof")
        result_packet(run.run_id, bound, metadata["instructions_digest"], value)
        detail = {
            "schema_version": "document_change_accept_v1",
            "scope_id": bound.scope.scope_id,
            "lease_token": run.lease_token,
            "source_binding_hash": c.e.digest(bound),
            "result_hash": reference.content_hash,
            "result_bytes": reference.result_bytes,
            "usage_event_id": artifact.usage_event_id,
        }
        if (
            audit is None
            or _audit_value(audit)
            != {"actor_id": run.requested_by, "action": ACCEPT, "target": run.run_id, "detail_json": require_case_json(detail), "create_time": row.accepted_at.replace(microsecond=0)}
            or artifact.usage_event_id == reference.accept_audit_event_id
        ):
            raise ValueError("The exact complete acceptance and independent usage audit differ")
        usage_receipt(db, run)
        return value
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "完整指南版本结果、租约、Prompt或具体接收审计不一致") from exc


@originals._write
def cancel_unclaimed(db, user, run):
    """Explicit current-Super queue cancellation: actor -> Run -> Artifact only."""
    actor = originals.current_super(db, user)
    epoch = originals._epoch(actor)
    event_id = stage_terminal(
        db,
        run,
        None,
        status="cancelled",
        usage={"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False},
        latency_ms=0,
        queued_no_call=True,
        actor_id=actor.user_id,
    )
    originals.current_super(db, actor, expected=epoch)
    return event_id
