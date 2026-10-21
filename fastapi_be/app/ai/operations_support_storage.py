"""Staged immutable operations tasks; current source before Run/Artifact TEXT.

No commit, queue claim, HTTP, terminal usage or result acceptance is performed.
The caller must atomically roll back every failed stage/readback.
"""

import datetime as dt

from fastapi import HTTPException
from sqlalchemy import func

from app.ai import operations_support_cases as cases
from app.ai import operations_support_contract as c
from app.ai import operations_support_projection as projection
from app.ai import operations_support_registry as registry
from app.ai.operations_support_configuration import FEATURE, configuration, prepare_context, roles_for
from app.ai.operations_support_gateway import request
from app.ai.operations_support_protocol import instructions_for, model_wire
from app.ai.operations_support_run_models import ARTIFACT_HASHES, ARTIFACT_SCHEMA, FRAME_BYTES, AIOperationsRunArtifact
from app.ai.operations_support_task_contract import OperationsTaskSelection
from app.ai.operations_support_task_prompt import PROMPT_VERSION, SYSTEM_PROMPT
from app.ai.operations_support_write_guard import current_rows, lock_operations_write

RAW_FIELDS = ("input_json", "evidence_json", "context_metadata_json")
RUN_TEXT = (*RAW_FIELDS, "result_json")
CLOCK_FIELDS = ("actor_token_invalid_before", "recorded_at")
IDENTITY_FIELDS = (
    "run_id",
    "schema_version",
    "case_id",
    "case_requested_by",
    "case_private_hash",
    "case_public_hash",
    "case_membership_hash",
    "requested_by",
    "actor_token_invalid_before",
    "recorded_at",
    "objective",
    "source_binding_hash",
    "source_bytes",
    "source_projection_hash",
    "prompt_id",
    "prompt_version",
    "prompt_snapshot_hash",
    "provider_id",
    "provider_revision",
    "config_revision",
    "execution_snapshot_hash",
    "instructions_digest",
    "input_hash",
    "evidence_hash",
    "metadata_hash",
    "run_header_hash",
)
IMMUTABLE_RUN = (
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
CREATION_ACTION = "operations.task.artifact.create"


def _clock(value):
    return None if value is None else registry.utc_text(value)


def _json(raw, maximum):
    try:
        if type(raw) is not str or not 0 < len(raw.encode("utf-8")) <= maximum:
            raise ValueError("Whole stored bytes must fit")
        value = projection._value(raw)
        if c.canonical_json(value) != raw:
            raise ValueError("Stored task JSON must retain its entire original canonical bytes")
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "运维任务完整JSON或原字节损坏") from exc


def encoded_header(header):
    return {key: _clock(value) if key in {"create_time", "start_time", "finish_time"} else value for key, value in header.items()}


def run_header(db, run_id, *, shared=True):
    from app.ai.models import AIRun

    columns = [column.name for column in AIRun.__table__.columns if column.name not in RUN_TEXT]
    with db.no_autoflush:
        row = current_rows(db.query(*(getattr(AIRun, key) for key in columns)).filter_by(run_id=run_id), shared=shared).one_or_none()
    return None if row is None else dict(row._mapping)


def artifact_header(db, run_id, *, shared=True):
    with db.no_autoflush:
        row = current_rows(
            db.query(*(getattr(AIOperationsRunArtifact, key) for key in (*IDENTITY_FIELDS, "created_audit_event_id"))).filter_by(run_id=registry.identifier(run_id)), shared=shared
        ).one_or_none()
    return None if row is None else dict(row._mapping)


def _identity(header):
    return {key: _clock(header[key]) if key in CLOCK_FIELDS else header[key] for key in IDENTITY_FIELDS}


def source_binding(case, objective):
    return {
        "schema_version": "operations_source_binding_v1",
        "case_id": case["case_id"],
        "case_requested_by": case["requested_by"],
        "case_private_hash": case["private_hash"],
        "case_public_hash": case["public_hash"],
        "case_membership_hash": case["member_bindings_hash"],
        "case_creation_event_id": case["creation_event_id"],
        "case_assembled_at": registry.utc_text(case["assembled_at"]),
        "objective": objective,
    }


def _parts(header):
    short = {
        "schema_version": "operations_support_task_ref_v1",
        "operations_case_id": header["case_id"],
        "objective": header["objective"],
        **{key: header[key] for key in ("source_projection_hash", "source_binding_hash", "prompt_snapshot_hash", "execution_snapshot_hash")},
    }
    evidence = [
        {"kind": "reviewed_operations_documents", "source_id": header["case_id"], "source_projection_hash": header["source_projection_hash"], "source_binding_hash": header["source_binding_hash"]}
    ]
    metadata = {
        "schema_version": "operations_support_task_metadata_v1",
        "operations_case_id": header["case_id"],
        "objective": header["objective"],
        "instructions_digest": header["instructions_digest"],
        "provider_id": header["provider_id"],
        "provider_revision": header["provider_revision"],
    }
    context = {key: header[key] for key in ("source_binding_hash", "instructions_digest", "execution_snapshot_hash", "objective")}
    return dict(zip(RAW_FIELDS, (registry.bounded_json(short, 65535), registry.bounded_json(evidence, 65535), registry.bounded_json(metadata, 65535)), strict=True)), c.content_hash(context)


def _verify_created(db, header, technical_run, *, check_run=True):
    from app.ai.models import AIAuditEvent, AIRun

    with db.no_autoflush:
        event = current_rows(db.query(AIAuditEvent).filter_by(event_id=header["created_audit_event_id"]), shared=True).one_or_none()
    try:
        if event is None:
            raise ValueError("The concrete create receipt is missing")
        receipt = _json(event.detail_json, 65535)
        if (
            type(receipt) is not dict
            or set(receipt) != {"schema_version", "artifact", "requester_role", "original_run_header"}
            or receipt["schema_version"] != "operations_artifact_created_v1"
            or receipt["artifact"] != _identity(header)
            or receipt["requester_role"] not in {"super_admin", "admin"}
        ):
            raise ValueError("The entire immutable technical identity differs")
        original = receipt["original_run_header"]
        if type(original) is not dict or set(original) != {column.name for column in AIRun.__table__.columns} or c.content_hash(original) != header["run_header_hash"]:
            raise ValueError("The complete original Run header differs")
        original_raw, context_hash = _parts(header)
        expected = {
            "feature_key": FEATURE,
            "run_id": header["run_id"],
            "provider_id": header["provider_id"],
            "provider_revision": header["provider_revision"],
            "prompt_version": header["prompt_version"],
            "prompt_hash": header["instructions_digest"],
            "context_digest": context_hash,
            "patient_id": None,
            "encounter_ref": None,
            "requested_by": header["requested_by"],
            "status": "queued",
            "result_json": "{}",
            "error_code": None,
            "error_message": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": None,
            "start_time": None,
            "lease_token": None,
            "finish_time": None,
            "create_time": _clock(header["recorded_at"].replace(microsecond=0)),
            **original_raw,
        }
        if type(original.get("preview")) is not int or original["preview"] not in {0, 1} or any(type(original[key]) is not type(value) or original[key] != value for key, value in expected.items()):
            raise ValueError("The original 25-field Run does not match the closed initial state")
        if check_run and (technical_run is None or any(encoded_header(technical_run)[key] != original[key] for key in IMMUTABLE_RUN)):
            raise ValueError("Actual immutable Run fields differ from the original create receipt")
        if (
            header["schema_version"] != ARTIFACT_SCHEMA
            or header["source_projection_hash"] != header["case_public_hash"]
            or any(type(header[key]) is not str or len(header[key]) != 64 for key in ARTIFACT_HASHES)
        ):
            raise ValueError("Artifact schema or hash identity differs")
        for field, key in zip(RAW_FIELDS, ("input_hash", "evidence_hash", "metadata_hash"), strict=True):
            if registry.raw_sha(original_raw[field]) != header[key]:
                raise ValueError("Original raw3 receipt differs")
        registry.verify_event(db, header["created_audit_event_id"], header["requested_by"], CREATION_ACTION, header["run_id"], receipt, header["recorded_at"])
        return receipt
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "运维任务原始具体创建回执、Run或分件技术锚损坏；未读取任务正文") from exc


def _original_actor(db, header, receipt):
    from app.models import User

    with db.no_autoflush:
        row = current_rows(db.query(User.user_id, User.user_role, User.token_invalid_before).filter_by(user_id=header["requested_by"]), shared=True).one_or_none()
    if row is None or row.user_role != receipt["requester_role"] or row.token_invalid_before != header["actor_token_invalid_before"]:
        raise HTTPException(403, "原运维任务创建账户角色或登录epoch已变化，未读取任务正文")


def _before_bodies(db, user, run_id, *, execution):
    from app.ai.models import AIFeatureConfig

    if type(execution) is not bool:
        raise HTTPException(422, "运维执行校验标志须为实际布尔值")
    actor = lock_operations_write(db, user)
    h = artifact_header(db, run_id)
    if h is None:
        raise HTTPException(404, "运维任务分件不存在")
    if actor.user_role != "super_admin" and actor.user_id != h["requested_by"]:
        raise HTTPException(403, "不能读取其他账户运维任务")
    case = cases.case_header(db, actor, h["case_id"])
    membership, source_headers = cases.current_members(db, case, execution=True)
    if (h["case_private_hash"], h["case_public_hash"], h["case_membership_hash"], h["case_requested_by"]) != (
        case["private_hash"],
        case["public_hash"],
        case["member_bindings_hash"],
        case["requested_by"],
    ) or h["source_binding_hash"] != c.content_hash(source_binding(case, h["objective"])):
        raise HTTPException(409, "运维任务原完整资料集与当前授权锚不一致")
    # The specific receipt proves the original preview and login epoch before
    # Config or Source/Task BODY. Config still precedes the first Run lock.
    receipt = _verify_created(db, h, None, check_run=False)
    _original_actor(db, h, receipt)
    current_config = None
    if execution:
        current_config = configuration(db, actor, preview=bool(receipt["original_run_header"]["preview"]))
        _, _, current_prompt, current_execution = current_config
        if (current_prompt["prompt_id"], current_prompt["prompt_version"], current_prompt["instructions_digest"]) != (h["prompt_id"], h["prompt_version"], h["instructions_digest"]) or c.content_hash(
            current_execution
        ) != h["execution_snapshot_hash"]:
            raise HTTPException(409, "运维当前配置、Provider或Prompt与原冻结锚不同；未读取来源或任务正文")
    else:
        row = current_rows(db.query(AIFeatureConfig.allowed_roles_json).filter_by(feature_key=FEATURE), shared=True).one_or_none()
        if actor.user_role != "super_admin" and (row is None or actor.user_role not in roles_for(row.allowed_roles_json)):
            raise HTTPException(403, "当前身份不再具备运维任务读取权限")
    actual = run_header(db, run_id)
    _verify_created(db, h, actual)
    return actor, h, case, membership, source_headers, receipt, current_config


def _frame_proof(artifact, receipt, case):
    try:
        source = projection.OperationsSupportSource.model_validate(_json(artifact.source_json, c.MAX_WHOLE_BYTES), strict=True)
        prompt = _json(artifact.prompt_snapshot_json, FRAME_BYTES)
        execution = _json(artifact.execution_snapshot_json, FRAME_BYTES)
        if (
            len(artifact.source_json.encode()) != artifact.source_bytes
            or registry.raw_sha(artifact.source_json) != artifact.source_projection_hash
            or c.content_hash(source) != artifact.source_projection_hash
        ):
            raise ValueError("Complete original Source bytes differ")
        if registry.raw_sha(artifact.prompt_snapshot_json) != artifact.prompt_snapshot_hash or registry.raw_sha(artifact.execution_snapshot_json) != artifact.execution_snapshot_hash:
            raise ValueError("Entire frozen frames differ")
        prompt_keys = {"schema_version", "prompt_id", "prompt_version", "origin", "catalog_version", "native_task_version", "system_prompt", "task_prompt", "instructions_digest"}
        execution_keys = {"schema_version", "feature_key", "preview", "requester_epoch", "configuration", "provider_snapshot", "feature_validation"}
        if (
            type(prompt) is not dict
            or set(prompt) != prompt_keys
            or type(execution) is not dict
            or set(execution) != execution_keys
            or prompt["schema_version"] != "operations_prompt_snapshot_v1"
            or execution["schema_version"] != "operations_execution_snapshot_v1"
            or execution["feature_key"] != FEATURE
        ):
            raise ValueError("Closed original frames required")
        if (
            prompt["system_prompt"] != SYSTEM_PROMPT
            or prompt["native_task_version"] != PROMPT_VERSION
            or prompt["prompt_id"] != artifact.prompt_id
            or prompt["prompt_version"] != artifact.prompt_version
            or prompt["instructions_digest"] != registry.raw_sha(instructions_for(prompt["task_prompt"]))
            or prompt["instructions_digest"] != artifact.instructions_digest
        ):
            raise ValueError("Original fixed System and actual versioned Task differ")
        expected_origin = "packaged_task" if artifact.prompt_id is None and artifact.prompt_version == 0 else "database_version"
        if prompt["origin"] != expected_origin or artifact.prompt_id is None and artifact.prompt_version != 0 or artifact.prompt_id is not None and artifact.prompt_version < 1:
            raise ValueError("Actual Prompt FK/version origin differs")
        if (
            execution["requester_epoch"] != {"user_id": artifact.requested_by, "user_role": receipt["requester_role"], "token_invalid_before": _clock(artifact.actor_token_invalid_before)}
            or type(execution["preview"]) is not bool
            or int(execution["preview"]) != receipt["original_run_header"]["preview"]
        ):
            raise ValueError("Original requester epoch or preview differs")
        provider = execution["provider_snapshot"]
        if provider["provider_id"] != artifact.provider_id or provider["revision"] != artifact.provider_revision or execution["configuration"]["revision"] != artifact.config_revision:
            raise ValueError("Provider or configuration revisions differ")
        if c.content_hash(source_binding(case, artifact.objective)) != artifact.source_binding_hash:
            raise ValueError("Original source binding differs")
        selection = OperationsTaskSelection(operations_case_id=artifact.case_id, objective=artifact.objective)
        model_wire(source, selection, prompt["task_prompt"])
        return source, prompt, execution, selection
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "运维任务完整来源、Prompt或执行快照不能重算") from exc


def load_artifact(db, user, run_id, *, execution=False):
    from app.ai.models import AIRun

    actor, h, case, membership, source_headers, receipt, current_config = _before_bodies(db, user, run_id, execution=execution)
    private, current_source = cases.read_case_bodies(db, case, membership, source_headers)
    with db.no_autoflush:
        run = current_rows(db.query(AIRun).filter_by(run_id=run_id), shared=True).one()
        artifact = current_rows(db.query(AIOperationsRunArtifact).filter_by(run_id=run_id), shared=True).one()
    source, prompt, frozen_execution, selection = _frame_proof(artifact, receipt, case)
    if source != current_source:
        raise HTTPException(409, "原任务完整公开投影与当前授权完整资料不一致")
    raw, context_hash = _parts(h)
    if any(getattr(run, key) != value for key, value in raw.items()) or run.context_digest != context_hash:
        raise HTTPException(409, "运维任务raw3原字节或上下文SHA已变化")
    if execution:
        _, _, current_prompt, current_execution = current_config
        # Other feature catalog releases do not change this immutable native Task.
        same_prompt = {key: value for key, value in current_prompt.items() if key != "catalog_version"} == {key: value for key, value in prompt.items() if key != "catalog_version"}
        if not same_prompt or current_execution != frozen_execution:
            raise HTTPException(409, "运维当前Provider、配置、Prompt或原登录epoch与冻结版本不同")
    return run, artifact, source, private, prompt, frozen_execution, selection


def stage_run(db, user, value, *, preview=False):
    """Full current source/config, actual wire preflight, quota, exact Audit/readback."""
    from app.ai.governance import provider_credential
    from app.ai.models import AIRun

    context = prepare_context(db, user, value, preview=preview, exclusive_config=True)
    provider_credential(context.provider)
    request(context.provider, context.source, context.selection, context.prompt["task_prompt"])
    clock = registry.utcnow()
    if clock < context.header["assembled_at"]:
        raise HTTPException(409, "任务登记时钟早于资料集，未改写来源时间")
    day_start = dt.datetime.combine(clock.date(), dt.time.min)
    count_query = db.query(func.count(AIRun.run_id)).filter(AIRun.feature_key == FEATURE, AIRun.requested_by == context.actor.user_id, AIRun.create_time >= day_start)
    used = current_rows(count_query, shared=True).scalar()
    if used >= context.config.daily_limit:
        raise HTTPException(429, "运维功能今日提交额度已用完")
    values = {
        "schema_version": ARTIFACT_SCHEMA,
        "case_id": context.header["case_id"],
        "case_requested_by": context.header["requested_by"],
        "case_private_hash": context.header["private_hash"],
        "case_public_hash": context.header["public_hash"],
        "case_membership_hash": context.header["member_bindings_hash"],
        "requested_by": context.actor.user_id,
        "actor_token_invalid_before": context.actor.token_invalid_before,
        "recorded_at": clock,
        "objective": context.selection.objective,
        "source_binding_hash": c.content_hash(context.binding()),
        "source_json": registry.bounded_json(context.source),
        "source_projection_hash": c.content_hash(context.source),
        "prompt_id": context.prompt["prompt_id"],
        "prompt_version": context.prompt["prompt_version"],
        "prompt_snapshot_json": registry.bounded_json(context.prompt, FRAME_BYTES),
        "prompt_snapshot_hash": c.content_hash(context.prompt),
        "provider_id": context.provider.provider_id,
        "provider_revision": context.provider.revision,
        "config_revision": context.config.revision,
        "execution_snapshot_json": registry.bounded_json(context.execution, FRAME_BYTES),
        "execution_snapshot_hash": c.content_hash(context.execution),
        "instructions_digest": context.prompt["instructions_digest"],
    }
    values["source_bytes"] = len(values["source_json"].encode())
    raw, context_hash = _parts(values)
    run = AIRun(
        feature_key=FEATURE,
        requested_by=context.actor.user_id,
        provider_id=context.provider.provider_id,
        provider_revision=context.provider.revision,
        prompt_version=context.prompt["prompt_version"],
        prompt_hash=context.prompt["instructions_digest"],
        context_digest=context_hash,
        preview=int(preview),
        status="queued",
        create_time=clock.replace(microsecond=0),
        **raw,
        result_json="{}",
        input_tokens=0,
        output_tokens=0,
    )
    db.add(run)
    db.flush()
    identifier = run.run_id
    values["run_id"] = identifier
    for field, key in zip(RAW_FIELDS, ("input_hash", "evidence_hash", "metadata_hash"), strict=True):
        values[key] = registry.raw_sha(raw[field])
    original = encoded_header({column.name: getattr(run, column.name) for column in AIRun.__table__.columns})
    values["run_header_hash"] = c.content_hash(original)
    receipt = {"schema_version": "operations_artifact_created_v1", "artifact": _identity(values), "requester_role": context.actor.user_role, "original_run_header": original}
    values["created_audit_event_id"] = registry.audit_event(db, context.actor.user_id, CREATION_ACTION, identifier, receipt, clock)
    db.add(AIOperationsRunArtifact(**values))
    db.flush()
    # Current actual receipt/header/source/body/config proof after every SQL trigger.
    saved = load_artifact(db, context.actor, identifier, execution=True)
    if encoded_header({column.name: getattr(saved[0], column.name) for column in AIRun.__table__.columns}) != original or current_rows(count_query, shared=True).scalar() != used + 1:
        raise HTTPException(409, "运维任务真实Run、Artifact或同事务当前额度读回不一致")
    return identifier
