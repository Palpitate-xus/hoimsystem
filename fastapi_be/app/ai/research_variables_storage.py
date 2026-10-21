"""Source/config-first76 creation with exact SQL bytes and one creation PK.

This first storage layer creates no claim, dispatch, usage or accepted result.
The caller owns the surrounding transaction/commit and actual daily quota.
Private immutable Scope data remains in the original Batch, not this artifact.
"""

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import LargeBinary, cast, func, inspect

from app.ai import research_variables_storage_contract as types
from app.ai.catalog import CATALOG_VERSION
from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_sources import utc_text
from app.ai.research_cohort_write_guard import current_research_rows
from app.ai.research_variables_configuration import current_configuration
from app.ai.research_variables_run_models import ARTIFACT_SCHEMA, AIResearchVariableRunArtifact
from app.ai.research_variables_task_binding import VariableTaskBinding
from app.ai.research_variables_task_context import VariablePreparedContext, prepare_context, wire_parts
from app.ai.research_variables_task_contract import FEATURE_KEY, MAX_BINDING_BYTES, MAX_RUN_TEXT_BYTES, canonical, digest, strict_json

RUN_TEXT = ("input_json", "result_json", "evidence_json", "context_metadata_json")
RUN_HEADER = tuple(str(column.name) for column in AIRun.__table__.columns if column.name not in RUN_TEXT)
RUN_IMMUTABLE = (
    "run_id",
    "feature_key",
    "provider_id",
    "provider_revision",
    "prompt_version",
    "prompt_hash",
    "context_digest",
    "patient_id",
    "encounter_ref",
    "requested_by",
    "preview",
    "create_time",
)
ART_PHASE = ("create_event_id", "claim_event_id", "claim_lease", "claimed_at", "dispatch_event_id", "dispatched_at", "usage_event_id")
ART_TEXT = ("source_json", "binding_json")
ART_IMMUTABLE = tuple(str(column.name) for column in AIResearchVariableRunArtifact.__table__.columns if column.name not in (*ART_PHASE, *ART_TEXT))


@dataclass(frozen=True)
class VariableStagedTask:
    run: AIRun
    artifact: AIResearchVariableRunArtifact
    snapshot: types.VariableTaskSnapshot
    binding: VariableTaskBinding
    prepared: VariablePreparedContext


def text_hash(value, maximum=MAX_RUN_TEXT_BYTES):
    if type(value) is not str or not 0 < len(value.encode("utf-8", errors="strict")) <= maximum:
        raise ValueError("A complete stored UTF8 object must fit its actual column")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_value(raw, maximum=MAX_RUN_TEXT_BYTES):
    text_hash(raw, maximum)
    value = strict_json(raw, maximum)
    if canonical(value, maximum) != raw:
        raise ValueError("Stored canonical original JSON bytes cannot be rewritten")
    return value


def snapshot_for_context(prepared, configured):
    return types.VariableTaskSnapshot(
        schema_version="research_variable_task_snapshot_v1",
        catalog_version=CATALOG_VERSION,
        system_prompt=configured.system_prompt,
        task_prompt=configured.task_prompt,
        prompt_origin=configured.prompt_origin,
        payload={"input": prepared.selection.model_dump(mode="json"), "context": prepared.data, "tools": {}, "evidence": prepared.evidence},
        provider_snapshot=configured.provider_snapshot,
        feature_validation=configured.validation_snapshot,
        batch_publication=prepared.private_scope["proof"]["governance"],
        actor_epoch={"user_role": prepared.binding.request_authorization.actor_role, "token_invalid_before": prepared.binding.request_authorization.actor_token_invalid_before},
        run_clock_basis="legacy_utc_second_storage",
    )


def metadata_for_snapshot(snapshot):
    snapshot = types.VariableTaskSnapshot.model_validate(snapshot)
    context = snapshot.payload.context.model_dump(mode="json")
    return {
        "snapshot_time": context["snapshot_time"],
        "source_count": 1,
        "department_ids": [],
        "context_digest": digest(context),
        "clinical_context_fingerprint": digest({key: value for key, value in context.items() if key != "snapshot_time"}),
        "missing_data": context["missing_data"],
        "feature_revision": snapshot.feature_validation.feature_revision,
        "validation_status": snapshot.feature_validation.status,
        "tool_fingerprint": digest({}),
        "instructions_digest": types.instructions_digest(snapshot),
        "model_version": snapshot.provider_snapshot.model,
        "source_projection_hash": snapshot.payload.context.research_variable_binding.source_projection_hash,
        "request_authorization_hash": snapshot.payload.context.research_variable_binding.request_authorization_hash,
    }


def _clock(value):
    return utc_text(value) if isinstance(value, dt.datetime) else value


def creation_detail(run, artifact):
    def value(row, key):
        return row[key] if type(row) is dict else getattr(row, key)

    original = {key: _clock(value(run, key)) for key in RUN_IMMUTABLE}
    original.update({key: value(artifact, key) for key in ("input_hash", "evidence_hash", "metadata_hash")})
    return {
        "schema_version": "research_variable_run_creation_v1",
        "artifact": {key: _clock(value(artifact, key)) for key in ART_IMMUTABLE},
        "run_header_hash": digest(original),
        "recorded_at_utc6": utc_text(value(artifact, "recorded_at")),
        "audit_clock_basis": "legacy_utc_second_storage",
    }


def _verify_configuration(snapshot, configured):
    for expected, actual in (
        (snapshot.provider_snapshot, configured.provider_snapshot),
        (snapshot.feature_validation, configured.validation_snapshot),
        (snapshot.prompt_origin, configured.prompt_origin),
    ):
        if canonical(expected) != canonical(actual):
            raise HTTPException(409, "任务原模型、独立验证或Prompt配置已变化")
    if (snapshot.system_prompt, snapshot.task_prompt) != (configured.system_prompt, configured.task_prompt):
        raise HTTPException(409, "任务原完整System/Task Prompt已变化，未采用当前内容替换")


def _readback(db, user, run, expected_run, expected_artifact, snapshot, prepared):
    fresh = prepare_context(db, user, prepared.selection.model_dump(mode="json"))
    if fresh.binding != prepared.binding:
        raise HTTPException(409, "创建后全部当前Source或原请求用途已变化")
    configured = current_configuration(db, fresh.authority.actor, preview=bool(run.preview))
    _verify_configuration(snapshot, configured)
    # Complete Source and config locks precede any Run/Artifact lock or TEXT.
    header = current_research_rows(db.query(*[getattr(AIRun, key) for key in RUN_HEADER]).filter_by(run_id=run.run_id)).one_or_none()
    if header is None or dict(header._mapping) != expected_run:
        raise HTTPException(409, "实际新任务头不存在或混入其他患者、就诊或功能")

    def length(value):
        return func.octet_length(value) if db.get_bind().dialect.name in {"mysql", "mariadb"} else func.length(cast(value, LargeBinary))

    columns = [getattr(AIResearchVariableRunArtifact, key) for key in (*ART_IMMUTABLE, *ART_PHASE)]
    columns += [
        length(AIResearchVariableRunArtifact.source_json).label("actual_source_bytes"),
        length(AIResearchVariableRunArtifact.binding_json).label("actual_binding_bytes"),
    ]
    technical = current_research_rows(db.query(*columns).filter_by(run_id=run.run_id)).one_or_none()
    if technical is None or any(getattr(technical, key) != expected_artifact[key] for key in (*ART_IMMUTABLE, *ART_PHASE)):
        raise HTTPException(409, "实际新Artifact不可变身份、原授权或八个SHA已变化")
    if (technical.actual_source_bytes, technical.actual_binding_bytes) != (technical.source_bytes, technical.binding_bytes):
        raise HTTPException(409, "实际Source/Binding完整字节锚不同，未读取正文")
    event_bytes = current_research_rows(db.query(length(AIAuditEvent.detail_json)).filter_by(event_id=technical.create_event_id), shared=True).scalar()
    if type(event_bytes) is not int or not 0 < event_bytes <= MAX_RUN_TEXT_BYTES:
        raise HTTPException(409, "新任务具体创建审计容量或主键不同，未读取任务正文")
    event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=technical.create_event_id), shared=True).one_or_none()
    if event is None or (event.actor_id, event.action, event.target, event.create_time, event.detail_json) != (
        prepared.binding.request_authorization.requested_by,
        "research_variable_run.create",
        run.run_id,
        technical.recorded_at.replace(microsecond=0),
        canonical(creation_detail(dict(header._mapping), dict(technical._mapping)), MAX_RUN_TEXT_BYTES),
    ):
        raise HTTPException(409, "实际具体创建Audit PK、不可变头或八摘要无法核对")
    actual_run = current_research_rows(db.query(AIRun).filter_by(run_id=run.run_id)).one()
    actual_artifact = current_research_rows(db.query(AIResearchVariableRunArtifact).filter_by(run_id=run.run_id)).one()
    raw_expected = {
        "input_json": canonical(snapshot, MAX_RUN_TEXT_BYTES),
        "result_json": "{}",
        "evidence_json": canonical(prepared.evidence, MAX_RUN_TEXT_BYTES),
        "context_metadata_json": canonical(metadata_for_snapshot(snapshot), MAX_RUN_TEXT_BYTES),
    }
    if any(getattr(actual_run, key) != value for key, value in raw_expected.items()):
        raise HTTPException(409, "实际新Run完整原字节、固定说明或空结果已变化")
    if actual_artifact.source_json != canonical(prepared.source) or actual_artifact.binding_json != canonical(prepared.binding, MAX_BINDING_BYTES):
        raise HTTPException(409, "实际完整Source或独立原授权Binding正文已变化")
    return VariableStagedTask(actual_run, actual_artifact, snapshot, prepared.binding, fresh)


def stage_run(db, user, run, prepared, snapshot):
    """Stage one authentic SQL task; never commit, claim or call a provider."""
    try:
        if not inspect(run).transient:
            raise HTTPException(422, "仅可暂存全新任务，不能覆盖已有或已暂存的Run")
        if not isinstance(prepared, VariablePreparedContext):
            raise HTTPException(422, "任务来源必须来自当前完整授权构建")
        snapshot = types.checked_snapshot(snapshot, prepared.binding)
        if snapshot.payload.context.model_dump(mode="json") != prepared.data:
            raise HTTPException(409, "准备的原问题、完整证据或当前上下文不同")
        if type(run.preview) is not int or run.preview not in (0, 1):
            raise HTTPException(422, "新任务须有明确内部预览标志")
        fresh = prepare_context(db, user, prepared.selection.model_dump(mode="json"))
        if fresh.binding != prepared.binding:
            raise HTTPException(409, "任务原完整Source或实际请求许可已变化")
        configured = current_configuration(db, fresh.authority.actor, preview=bool(run.preview))
        _verify_configuration(snapshot, configured)
        wire_parts(prepared.binding, prepared.source, prepared.private_scope)
        recorded = dt.datetime.strptime(prepared.data["snapshot_time"], "%Y-%m-%dT%H:%M:%S.%fZ")
        metadata = metadata_for_snapshot(snapshot)
        run.feature_key, run.patient_id, run.encounter_ref = FEATURE_KEY, None, None
        run.provider_id, run.provider_revision, run.prompt_version = configured.provider.provider_id, configured.provider.revision, snapshot.prompt_origin.prompt_version
        run.prompt_hash, run.context_digest = types.prompt_hash(snapshot), digest(prepared.data)
        run.requested_by, run.create_time, run.status = prepared.binding.request_authorization.requested_by, recorded.replace(microsecond=0), "queued"
        run.input_json, run.result_json, run.evidence_json, run.context_metadata_json = (
            canonical(snapshot, MAX_RUN_TEXT_BYTES),
            "{}",
            canonical(prepared.evidence, MAX_RUN_TEXT_BYTES),
            canonical(metadata, MAX_RUN_TEXT_BYTES),
        )
        run.input_tokens = run.output_tokens = 0  # Legacy physical columns; no usage receipt is invented.
        run.error_code = run.error_message = run.latency_ms = run.start_time = run.lease_token = run.finish_time = None
        if run.run_id is None:
            run.run_id = str(uuid.uuid4())
        expected_run = {key: getattr(run, key) for key in RUN_HEADER}
        db.add(run)
        db.flush()
        source_raw, binding_raw = canonical(prepared.source), canonical(prepared.binding, MAX_BINDING_BYTES)
        event = AIAuditEvent(actor_id=run.requested_by, action="research_variable_run.create", target=run.run_id, detail_json="{}", create_time=recorded.replace(microsecond=0))
        db.add(event)
        db.flush()
        artifact = AIResearchVariableRunArtifact(
            run_id=run.run_id,
            batch_id=prepared.binding.batch_id,
            scope_id=prepared.binding.request_authorization.scope_id,
            requested_by=run.requested_by,
            task_acl_id=prepared.binding.request_authorization.acl_id,
            actor_role=prepared.binding.request_authorization.actor_role,
            actor_token_invalid_before=fresh.authority.actor.token_invalid_before,
            schema_version=ARTIFACT_SCHEMA,
            recorded_at=recorded,
            source_json=source_raw,
            source_bytes=len(source_raw.encode()),
            binding_json=binding_raw,
            binding_bytes=len(binding_raw.encode()),
            batch_content_hash=prepared.binding.batch_content_hash,
            scope_content_hash=prepared.binding.request_authorization.scope_content_hash,
            scope_governance_hash=prepared.binding.request_authorization.scope_governance_hash,
            request_authorization_hash=prepared.binding.request_authorization_hash,
            create_event_id=event.event_id,
            input_hash=text_hash(run.input_json),
            evidence_hash=text_hash(run.evidence_json),
            metadata_hash=text_hash(run.context_metadata_json),
            prompt_hash=run.prompt_hash,
            context_digest=run.context_digest,
            instructions_digest=types.instructions_digest(snapshot),
            source_hash=prepared.binding.source_projection_hash,
            binding_hash=digest(prepared.binding, MAX_BINDING_BYTES),
        )
        expected = {key: getattr(artifact, key) for key in (*ART_IMMUTABLE, *ART_PHASE)}
        event.detail_json = canonical(creation_detail(run, artifact), MAX_RUN_TEXT_BYTES)
        db.add(artifact)
        db.flush()
        return _readback(db, fresh.authority.actor, run, expected_run, expected, snapshot, prepared)
    except Exception:
        db.rollback()
        raise
