"""Immutable queued training artifacts; current source precedes all task BODY.

No queue claim, model await or commit occurs here. A failed write/readback rolls
back the complete caller transaction, including after-insert source mutations.
"""

import datetime as dt

from fastapi import HTTPException
from sqlalchemy import func

from app.ai import clinical_training_configuration as cfg
from app.ai import clinical_training_contract as c
from app.ai import clinical_training_learner as learner
from app.ai import clinical_training_practice as practice
from app.ai import clinical_training_references as references
from app.ai import clinical_training_registry as registry
from app.ai.clinical_training_gateway import request
from app.ai.clinical_training_protocol import instructions_for, model_wire
from app.ai.clinical_training_run_models import ARTIFACT_HASHES, ARTIFACT_SCHEMA, FRAME_BYTES, AITrainingRunArtifact
from app.ai.clinical_training_task_contract import TrainingFeedbackSource, TrainingTaskSelection
from app.ai.clinical_training_task_prompt import PROMPT_VERSION, SYSTEM_PROMPT
from app.ai.clinical_training_write_guard import TRAINING_STAFF_ROLES, current_rows

FEATURE = cfg.FEATURE
RAW_FIELDS = ("input_json", "evidence_json", "context_metadata_json")
RUN_TEXT = (*RAW_FIELDS, "result_json")
ARTIFACT_TEXT = ("source_json", "source_binding_json", "prompt_snapshot_json", "execution_snapshot_json")
PHASE_FIELDS = ("created_audit_event_id", "claim_event_id", "claimed_at", "lease_token", "dispatch_event_id", "usage_event_id")
IDENTITY_FIELDS = tuple(column.name for column in AITrainingRunArtifact.__table__.columns if column.name not in (*ARTIFACT_TEXT, *PHASE_FIELDS))
IMMUTABLE_RUN = ("run_id", "feature_key", "provider_id", "provider_revision", "prompt_version", "prompt_hash", "context_digest", "patient_id", "encounter_ref", "requested_by", "preview", "create_time")
CREATION_ACTION = "training.task.artifact.create"


def _clock(value):
    return None if value is None else references.utc_text(value)


def bounded(value, maximum=65535):
    raw = c.canonical_json(value)
    if not 0 < len(raw.encode()) <= maximum:
        raise HTTPException(422, "完整培训任务分件超过明确字节范围，未裁剪保存")
    return raw


def _json(raw, maximum):
    try:
        if type(raw) is not str or not 0 < len(raw.encode()) <= maximum:
            raise ValueError("Entire stored packet required")
        value = c.parse_packet(raw)
        if c.canonical_json(value) != raw:
            raise ValueError("Original canonical bytes differ")
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "培训任务完整JSON或原始字节损坏") from exc


def encoded_header(header):
    return {key: _clock(value) if key in {"create_time", "start_time", "finish_time"} else value for key, value in header.items()}


def run_header(db, run_id, *, shared=True):
    from app.ai.models import AIRun

    columns = [column.name for column in AIRun.__table__.columns if column.name not in RUN_TEXT]
    with db.no_autoflush:
        row = current_rows(db.query(*(getattr(AIRun, key) for key in columns)).filter_by(run_id=registry.identifier(run_id)), shared=shared).one_or_none()
    return None if row is None else dict(row._mapping)


def artifact_header(db, run_id, *, shared=True):
    with db.no_autoflush:
        row = current_rows(db.query(*(getattr(AITrainingRunArtifact, key) for key in (*IDENTITY_FIELDS, *PHASE_FIELDS))).filter_by(run_id=registry.identifier(run_id)), shared=shared).one_or_none()
    return None if row is None else dict(row._mapping)


def _identity(header):
    return {key: _clock(header[key]) if key in {"actor_epoch", "recorded_at"} else header[key] for key in IDENTITY_FIELDS}


def _parts(header):
    short = dict(schema_version="clinical_training_task_ref_v1", clinical_training_submission_id=header["submission_id"], objective=header["objective"], **{key: header[key] for key in ("source_projection_hash", "source_binding_hash", "prompt_snapshot_hash", "execution_snapshot_hash")})
    evidence = [dict(kind="reviewed_actual_training_practice", source_id=header["submission_id"], source_projection_hash=header["source_projection_hash"], source_binding_hash=header["source_binding_hash"], feedback_hash=header["feedback_hash"])]
    metadata = dict(schema_version="clinical_training_task_metadata_v1", clinical_training_submission_id=header["submission_id"], objective=header["objective"], **{key: header[key] for key in ("instructions_digest", "provider_id", "provider_revision")})
    context = {key: header[key] for key in ("source_binding_hash", "instructions_digest", "execution_snapshot_hash", "objective")}
    return dict(zip(RAW_FIELDS, (bounded(short), bounded(evidence), bounded(metadata)), strict=True)), c.content_hash(context)


def _verify_created(db, header, technical_run, *, check_run=True):
    from app.ai.models import AIAuditEvent, AIRun

    with db.no_autoflush:
        event = current_rows(db.query(AIAuditEvent).filter_by(event_id=header["created_audit_event_id"]), shared=True).one_or_none()
    try:
        receipt = _json(event.detail_json, 65535) if event is not None else None
        if type(receipt) is not dict or set(receipt) != {"schema_version", "artifact", "original_run_header"} or receipt["schema_version"] != "clinical_training_artifact_created_v1" or receipt["artifact"] != _identity(header) or header["actor_role"] not in TRAINING_STAFF_ROLES:
            raise ValueError("Original exact technical identity differs")
        original = receipt["original_run_header"]
        if type(original) is not dict or set(original) != {column.name for column in AIRun.__table__.columns} or c.content_hash(original) != header["run_header_hash"]:
            raise ValueError("The complete original25-field Run differs")
        raw, context_hash = _parts(header)
        expected = dict(feature_key=FEATURE, run_id=header["run_id"], provider_id=header["provider_id"], provider_revision=header["provider_revision"], prompt_version=header["prompt_version"], prompt_hash=header["instructions_digest"], context_digest=context_hash, patient_id=None, encounter_ref=None, requested_by=header["requested_by"], status="queued", result_json="{}", error_code=None, error_message=None, input_tokens=0, output_tokens=0, latency_ms=None, start_time=None, lease_token=None, finish_time=None, create_time=_clock(header["recorded_at"].replace(microsecond=0)), **raw)
        if type(original.get("preview")) is not int or original["preview"] not in {0, 1} or any(type(original[key]) is not type(value) or original[key] != value for key, value in expected.items()):
            raise ValueError("The closed initial Run state differs")
        if check_run and (technical_run is None or any(encoded_header(technical_run)[key] != original[key] for key in IMMUTABLE_RUN)):
            raise ValueError("Current immutable Run differs")
        if header["schema_version"] != ARTIFACT_SCHEMA or any(type(header[key]) is not str or len(header[key]) != 64 for key in ARTIFACT_HASHES):
            raise ValueError("Artifact schema or hash fields differ")
        for field, key in zip(RAW_FIELDS, ("input_hash", "evidence_hash", "metadata_hash"), strict=True):
            if registry.raw_sha(raw[field]) != header[key]:
                raise ValueError("Original raw3 differs")
        registry.verify_event(db, header["created_audit_event_id"], header["requested_by"], CREATION_ACTION, header["run_id"], receipt, header["recorded_at"])
        return receipt
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "培训任务原始具体创建回执或Run技术锚损坏；未读取任务正文") from exc


def _before_bodies(db, user, run_id, *, execution):
    if type(execution) is not bool:
        raise HTTPException(422, "培训任务执行标记须为明确布尔值")
    actor = learner.current_learner(db, user)
    h = artifact_header(db, run_id)
    if h is None:
        raise HTTPException(404, "培训任务原生分件不存在")
    if actor.user_id != h["requested_by"] or actor.user_role != h["actor_role"] or actor.token_invalid_before != h["actor_epoch"]:
        raise HTTPException(403, "仅原提交人当前角色与登录epoch可读取本任务正文，超管技术管理不恢复答案")
    submitted = practice.submission_header(db, actor, h["submission_id"])
    review, lesson = practice._current_source(db, actor, submitted)
    if review["model_processing_allowed"] != 1:
        raise HTTPException(403, "原实际练习课程的独立模型处理许可已不可用")
    references._capture_current(db, actor.user_id, lesson["lesson_id"], c.parse_packet(lesson["reference_ids_json"]), expected_state_hash=lesson["reference_state_hash"], metadata_only=True)
    binding = cfg.source_binding(submitted, review, lesson, h["objective"])
    if c.content_hash(binding) != h["source_binding_hash"]:
        raise HTTPException(409, "培训原任务的完整提交、课程或参考版本绑定不同")
    receipt = _verify_created(db, h, None, check_run=False)
    current_config = None
    if execution:
        current_config = cfg.configuration(db, actor, preview=bool(receipt["original_run_header"]["preview"]))
        _, _, prompt, current_execution = current_config
        if (prompt["prompt_id"], prompt["prompt_version"], prompt["instructions_digest"]) != (h["prompt_id"], h["prompt_version"], h["instructions_digest"]) or c.content_hash(current_execution) != h["execution_snapshot_hash"]:
            raise HTTPException(409, "培训当前配置、模型或Prompt与原冻结锚不同；未读取正文")
    technical = run_header(db, run_id)
    _verify_created(db, h, technical)
    return actor, h, submitted, binding, receipt, current_config


def _frame_proof(artifact, receipt, binding):
    try:
        source = TrainingFeedbackSource.model_validate(_json(artifact.source_json, c.WHOLE_BYTES), strict=True)
        frozen_binding = _json(artifact.source_binding_json, FRAME_BYTES)
        prompt = _json(artifact.prompt_snapshot_json, FRAME_BYTES)
        execution = _json(artifact.execution_snapshot_json, FRAME_BYTES)
        if len(artifact.source_json.encode()) != artifact.source_bytes or registry.raw_sha(artifact.source_json) != artifact.source_projection_hash or c.content_hash(source) != artifact.source_projection_hash or frozen_binding != binding or c.content_hash(binding) != artifact.source_binding_hash:
            raise ValueError("Complete Source or binding differs")
        if registry.raw_sha(artifact.prompt_snapshot_json) != artifact.prompt_snapshot_hash or registry.raw_sha(artifact.execution_snapshot_json) != artifact.execution_snapshot_hash:
            raise ValueError("Complete frozen frame hashes differ")
        if type(prompt) is not dict or set(prompt) != {"schema_version", "prompt_id", "prompt_version", "origin", "catalog_version", "native_task_version", "system_prompt", "task_prompt", "instructions_digest"} or type(execution) is not dict or set(execution) != {"schema_version", "feature_key", "preview", "requester_epoch", "configuration", "provider_snapshot", "feature_validation"}:
            raise ValueError("Closed frozen frames required")
        if prompt["schema_version"] != "clinical_training_prompt_snapshot_v1" or execution["schema_version"] != "clinical_training_execution_snapshot_v1" or execution["feature_key"] != FEATURE or prompt["system_prompt"] != SYSTEM_PROMPT or prompt["native_task_version"] != PROMPT_VERSION:
            raise ValueError("Fixed training System/schema differs")
        if (prompt["prompt_id"], prompt["prompt_version"], prompt["instructions_digest"]) != (artifact.prompt_id, artifact.prompt_version, artifact.instructions_digest) or registry.raw_sha(instructions_for(prompt["task_prompt"])) != artifact.instructions_digest:
            raise ValueError("Immutable actual Task differs")
        if prompt["origin"] != ("packaged_task" if artifact.prompt_id is None and artifact.prompt_version == 0 else "database_version"):
            raise ValueError("Prompt version origin differs")
        if execution["requester_epoch"] != dict(user_id=artifact.requested_by, user_role=artifact.actor_role, token_invalid_before=_clock(artifact.actor_epoch)) or type(execution["preview"]) is not bool or int(execution["preview"]) != receipt["original_run_header"]["preview"]:
            raise ValueError("Actual requester or preview differs")
        if execution["provider_snapshot"]["provider_id"] != artifact.provider_id or execution["provider_snapshot"]["revision"] != artifact.provider_revision or execution["configuration"]["revision"] != artifact.config_revision:
            raise ValueError("Actual configuration revisions differ")
        selection = TrainingTaskSelection(clinical_training_submission_id=artifact.submission_id, objective=artifact.objective)
        model_wire(source, selection, prompt["task_prompt"])
        return source, prompt, execution, selection
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "培训任务完整来源、绑定或Prompt执行快照不能重算") from exc


def load_artifact(db, user, run_id, *, execution=False):
    from app.ai.models import AIRun

    actor, header, submitted, binding, receipt, current_config = _before_bodies(db, user, run_id, execution=execution)
    current_source = cfg.read_source(db, actor, submitted)
    with db.no_autoflush:
        run = current_rows(db.query(AIRun).filter_by(run_id=run_id), shared=True).one()
        artifact = current_rows(db.query(AITrainingRunArtifact).filter_by(run_id=run_id), shared=True).one()
    source, prompt, execution_snapshot, selection = _frame_proof(artifact, receipt, binding)
    if source != current_source:
        raise HTTPException(409, "培训任务完整来源与当前原提交、固定评分或参考原文不同")
    raw, context_hash = _parts(header)
    if any(getattr(run, key) != value for key, value in raw.items()) or run.context_digest != context_hash:
        raise HTTPException(409, "培训任务原raw3或上下文摘要改变")
    if execution:
        _, _, current_prompt, current_execution = current_config
        if {key: value for key, value in current_prompt.items() if key != "catalog_version"} != {key: value for key, value in prompt.items() if key != "catalog_version"} or current_execution != execution_snapshot:
            raise HTTPException(409, "培训当前配置与原完整冻结快照不同")
    return run, artifact, source, prompt, execution_snapshot, selection


def _stage_run(db, user, value, *, preview=False):
    from app.ai.governance import provider_credential
    from app.ai.models import AIRun

    context = cfg.prepare_context(db, user, value, preview=preview, exclusive_config=True)
    provider_credential(context.provider)
    request(context.provider, context.source, context.selection, context.prompt["task_prompt"])
    clock = registry.utcnow()
    if clock < context.submission["submitted_at"]:
        raise HTTPException(409, "培训任务时钟早于实际提交，未改写原来源时刻")
    day_start = dt.datetime.combine(clock.date(), dt.time.min)
    count_query = db.query(func.count(AIRun.run_id)).filter(AIRun.feature_key == FEATURE, AIRun.requested_by == context.actor.user_id, AIRun.create_time >= day_start)
    used = current_rows(count_query, shared=True).scalar()
    if used >= context.config.daily_limit:
        raise HTTPException(429, "培训AI功能今日提交额度已用完")
    binding = context.binding()
    values = dict(schema_version=ARTIFACT_SCHEMA, submission_id=binding["submission_id"], review_id=binding["review_id"], lesson_id=binding["lesson_id"], review_hash=binding["review_hash"], lesson_private_hash=binding["lesson_private_hash"], lesson_public_hash=binding["lesson_public_hash"], lesson_references_hash=binding["lesson_references_hash"], requested_by=context.actor.user_id, actor_role=context.actor.user_role, actor_epoch=context.actor.token_invalid_before, recorded_at=clock, submission_hash=binding["submission_hash"], feedback_hash=binding["feedback_hash"], reference_state_hash=binding["reference_state_hash"], **{key: binding[key] for key in ("lesson_creation_event_id", "review_creation_event_id", "submission_creation_event_id")}, objective=context.selection.objective, source_binding_json=bounded(binding, FRAME_BYTES), source_binding_hash=c.content_hash(binding), source_json=bounded(context.source, c.WHOLE_BYTES), source_projection_hash=c.content_hash(context.source), prompt_id=context.prompt["prompt_id"], prompt_version=context.prompt["prompt_version"], prompt_snapshot_json=bounded(context.prompt, FRAME_BYTES), prompt_snapshot_hash=c.content_hash(context.prompt), provider_id=context.provider.provider_id, provider_revision=context.provider.revision, config_revision=context.config.revision, execution_snapshot_json=bounded(context.execution, FRAME_BYTES), execution_snapshot_hash=c.content_hash(context.execution), instructions_digest=context.prompt["instructions_digest"])
    values["source_bytes"] = len(values["source_json"].encode())
    raw, context_hash = _parts(values)
    run = AIRun(feature_key=FEATURE, requested_by=context.actor.user_id, provider_id=context.provider.provider_id, provider_revision=context.provider.revision, prompt_version=context.prompt["prompt_version"], prompt_hash=context.prompt["instructions_digest"], context_digest=context_hash, preview=int(preview), status="queued", create_time=clock.replace(microsecond=0), **raw, result_json="{}", input_tokens=0, output_tokens=0)
    db.add(run)
    db.flush()
    run_id = values["run_id"] = run.run_id
    for field, key in zip(RAW_FIELDS, ("input_hash", "evidence_hash", "metadata_hash"), strict=True):
        values[key] = registry.raw_sha(raw[field])
    original = encoded_header({column.name: getattr(run, column.name) for column in AIRun.__table__.columns})
    values["run_header_hash"] = c.content_hash(original)
    receipt = dict(schema_version="clinical_training_artifact_created_v1", artifact=_identity(values), original_run_header=original)
    values["created_audit_event_id"] = registry.audit_event(db, context.actor.user_id, CREATION_ACTION, run_id, receipt, clock)
    artifact = AITrainingRunArtifact(**values)
    db.add(artifact)
    db.flush()
    saved = load_artifact(db, context.actor, run_id, execution=True)
    if encoded_header({column.name: getattr(saved[0], column.name) for column in AIRun.__table__.columns}) != original or current_rows(count_query, shared=True).scalar() != used + 1:
        raise HTTPException(409, "培训真实Run、Artifact或当前额度读回不同")
    return run_id


def stage_run(db, user, value, *, preview=False):
    try:
        return _stage_run(db, user, value, preview=preview)
    except Exception:
        db.rollback()
        raise
