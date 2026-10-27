"""Gate-first native classification; Source authorization precedes Task TEXT.

Only a current opaque Artifact locator is read before Source. Technical terminal
proofs use SQL SHA256/octet scalars for private TEXT after a permission loss;
they never restore clinical bytes to a caller or to an internal fallback.
"""

import hashlib
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import inspect, literal_column
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_input as source_input
from app.ai import infection_cluster_registry as r
from app.ai import infection_cluster_statistics as engine
from app.ai import infection_cluster_statistics_contract as k
from app.ai import infection_cluster_task_context as context
from app.ai import infection_cluster_task_contract as t
from app.ai.infection_cluster_run_models import AIInfectionRunArtifact as Artifact
from app.ai.infection_cluster_write_guard import current, lock_gate
from app.ai.models import AIAuditEvent, AIRun
from app.ai.native_acceptance import RUN_FIELDS

CREATE = "run.infection_cluster.create"
USAGE = "run.infection_cluster.usage"
ACCEPT = "run.infection_cluster.accept"
WRITE_FIELDS = (*RUN_FIELDS, "input_tokens", "output_tokens", "error_code", "error_message", "latency_ms")
CLOCK_FIELDS = ("create_time", "start_time", "finish_time")
TECHNICAL = tuple(col.name for col in Artifact.__table__.columns if col.name not in {"source_json", "result_json"})
IMMUTABLE = tuple(name for name in TECHNICAL if name not in {"usage_event_id", "accept_event_id", "accepted_lease", "accepted_at", "result_hash", "result_bytes", "create_event_id"})


class TextSHA(FunctionElement):
    inherit_cache = True


@compiles(TextSHA, "mysql")
def mysql_sha(element, compiler, **kwargs):
    return "SHA2(CAST(" + compiler.process(list(element.clauses)[0], **kwargs) + " AS BINARY),256)"


@compiles(TextSHA, "sqlite")
def sqlite_sha(element, compiler, **kwargs):
    return "hoim_infection_sha256(" + compiler.process(list(element.clauses)[0], **kwargs) + ")"


def _sql_hash_ready(db):
    if db.get_bind().dialect.name == "sqlite":
        db.connection().connection.driver_connection.create_function(
            "hoim_infection_sha256", 1, lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest() if value is not None else None, deterministic=True
        )


def _state_value(value):
    return r.utc(value) if hasattr(value, "tzinfo") else value


def immutable(row):
    return {name: _state_value(getattr(row, name)) for name in IMMUTABLE}


def _run_id(value):
    if type(value) is str:
        return value
    state = inspect(value, raiseerr=False)
    if state is not None and state.identity:
        return state.identity[0]
    return value.run_id


def locator(db, value):
    """Gate before current opaque lookup, including old RR/own staged anchors.

    Generic non-UUID IDs are not rejected: only a confirmed native Artifact is
    subject to this native contract. No Run/Artifact clinical TEXT is selected.
    """
    lock_gate(db)
    with db.no_autoflush:
        # An unflushed own-session anchor is authoritative for classification;
        # it must not silently fall through a generic Task parser.
        pending = next((row for row in db.new if isinstance(row, Artifact) and row.run_id == _run_id(value)), None)
        if pending is not None:
            return SimpleNamespace(run_id=pending.run_id, scenario_id=pending.scenario_id, requested_by=pending.requested_by)
        return current(db.query(Artifact.run_id, Artifact.scenario_id, Artifact.requested_by).filter_by(run_id=_run_id(value)), shared=True).one_or_none()


def is_infection_run(db, value):
    if db is not None and locator(db, value) is not None:
        return True
    if type(value) is str:
        return False
    loaded = vars(value)
    if loaded.get("feature_key") == t.FEATURE_KEY:
        return True
    return any(
        type(loaded.get(field)) is str and any(mark in loaded[field] for mark in ('"infection_local_frozen_task_v1"', '"infection_statistics_result_pointer_v1"', '"infection_cluster_scenario_id"'))
        for field in t.RAW_FIELDS
    )


def technical(db, rid):
    return current(db.query(*(getattr(Artifact, name) for name in TECHNICAL)).filter_by(run_id=rid), shared=True).one_or_none()


def creation_audit(db, row):
    event = r._actual(db, AIAuditEvent, row.create_event_id)
    if event is None or (event.actor_id, event.action, event.target, event.detail_json) != (
        row.requested_by,
        CREATE,
        row.run_id,
        c.canonical({"schema_version": "infection_local_create_audit_v1", "artifact": immutable(row)}),
    ):
        raise HTTPException(409, "原生本地任务具体创建审计与全部技术锚不一致")
    return event


def _owned_actor(db, user, row):
    actor = r._start(db, user, roles=source_input.SOURCE_ROLES, related_user_ids={row.requested_by})
    if actor.user_id != row.requested_by and actor.user_role != "super_admin":
        raise HTTPException(403, "仅任务本人或当前Super可明确读取此本地任务；临床正文还需逐患者目的许可")
    return actor


def authorize(db, user, rid, *, execution=False, write=False):
    opaque = locator(db, rid)
    if opaque is None:
        raise HTTPException(409, "缺少真实持久化本地任务锚，不回退通用结果")
    row = technical(db, rid)
    if row is None:
        raise HTTPException(409, "当前任务锚尚未完整持久化")
    actor = _owned_actor(db, user, row)
    creation_audit(db, row)
    # Current Source/patient rights and current local profile/config precede
    # every Run private TEXT and Artifact Source/result TEXT query, even Super.
    prepared = context.prepare(db, actor, row.scenario_id, preview=bool(row.preview))
    if (row.snapshot_id, row.profile_id, row.scenario_content_hash, row.scenario_governance_hash, row.profile_content_hash, row.profile_governance_hash, row.configuration_hash, row.source_hash) != (
        prepared[1].payload.source_binding.snapshot_id,
        prepared[3].profile_id,
        prepared[1].content_hash,
        prepared[1].governance_hash,
        prepared[3].content_hash,
        prepared[3].governance_hash,
        prepared[5].config_hash,
        c.digest(prepared[2]),
    ):
        raise HTTPException(409, "当前完整来源/Profile配置与任务技术锚不一致，未读取任务正文")
    if execution and c.digest(context.epoch(actor)) != row.requester_epoch_hash:
        raise HTTPException(409, "请求者角色或令牌时段与原执行请求不同")
    run = current(db.query(AIRun).filter_by(run_id=rid), shared=not write).one_or_none()
    artifact = current(db.query(Artifact).filter_by(run_id=rid), shared=not write).one_or_none()
    if run is None or artifact is None:
        raise HTTPException(409, "本地完整Run/Artifact缺失")
    if (
        run.status not in {"queued", "running", "succeeded", "failed", "cancelled"}
        or run.input_tokens != 0
        or run.output_tokens != 0
        or run.latency_ms is not None
        and (type(run.latency_ms) is not int or run.latency_ms < 0)
    ):
        raise HTTPException(409, "本地任务状态/真实零外部用量不是闭集")
    if run.status in {"queued", "running"} and (
        run.result_json != "{}" or artifact.result_json is not None or artifact.usage_event_id is not None or run.finish_time is not None or run.error_code is not None or run.error_message is not None
    ):
        raise HTTPException(409, "未终态任务混入了结果/回执/错误或完成时钟")
    if run.status == "queued" and (run.lease_token is not None or run.start_time is not None or run.latency_ms is not None):
        raise HTTPException(409, "排队任务不得伪造领取/计算记录")
    if run.status in {"running", "succeeded"} and (run.lease_token is None or run.start_time is None):
        raise HTTPException(409, "实际领取租约/开始时钟缺失")
    if run.status in {"succeeded", "failed", "cancelled"} and run.finish_time is None:
        raise HTTPException(409, "终态真实完成时钟缺失")
    frozen = t.FrozenTask.model_validate_json(run.context_metadata_json)
    selection = {"infection_cluster_scenario_id": frozen.scenario_id}
    if (
        run.feature_key != t.FEATURE_KEY
        or run.provider_id is not None
        or run.provider_revision is not None
        or run.prompt_version != 0
        or run.prompt_hash != t.LOCAL_PROMPT_HASH
        or run.patient_id is not None
        or run.encounter_ref is not None
        or run.requested_by != artifact.requested_by
        or frozen.run_id != rid
        or frozen.requester_epoch.user_id != artifact.requested_by
        or run.input_json != t.task_json(selection)
        or run.evidence_json != "[]"
        or run.context_metadata_json != t.task_json(frozen)
        or (c.text_digest(run.input_json), c.text_digest(run.evidence_json), c.text_digest(run.context_metadata_json)) != (artifact.input_hash, artifact.evidence_hash, artifact.metadata_hash)
        or run.context_digest != artifact.source_binding_hash
        or c.digest(frozen.source_binding) != artifact.source_binding_hash
        or c.digest(frozen.requester_epoch) != artifact.requester_epoch_hash
        or frozen.preview != bool(run.preview)
        or run.preview != artifact.preview
        or artifact.source_json != c.canonical(prepared[2])
        or c.text_digest(artifact.source_json) != artifact.source_hash
        or len(c.utf8(artifact.source_json)) != artifact.source_bytes
    ):
        raise HTTPException(409, "完整本地任务/原始三JSON/Source与实际持久锚不一致")
    if (artifact.created_at, artifact.recipe_hash, artifact.implementation_hash, artifact.scenario_id, artifact.profile_id) != (
        r.clock(frozen.created_at),
        frozen.recipe_hash,
        frozen.implementation_hash,
        frozen.scenario_id,
        frozen.profile_id,
    ):
        raise HTTPException(409, "Task冻结时钟/配方/场景/Profile与持久锚不同")
    context.compare_current(frozen, prepared, execution=execution)
    creation_audit(db, artifact)
    return actor, run, artifact, frozen, prepared[2]


def usage(db, row, run):
    if row.usage_event_id is None:
        if run.status == "succeeded" or run.status == "failed":
            raise HTTPException(409, "终态本地用量具体审计缺失")
        return None
    event = r._actual(db, AIAuditEvent, row.usage_event_id)
    if event is None or (event.actor_id, event.action, event.target) != (row.requested_by, USAGE, row.run_id):
        raise HTTPException(409, "本地用量具体审计PK不匹配")
    value = t.LocalUsage.model_validate_json(event.detail_json)
    if (
        event.detail_json != c.canonical(value)
        or (value.run_id, value.lease, value.terminal_status) != (row.run_id, run.lease_token, run.status)
        or value.result_hash != row.result_hash
        or run.input_tokens != 0
        or run.output_tokens != 0
    ):
        raise HTTPException(409, "本地用量/原租约/任务状态或结果哈希不匹配")
    return value


def load_result(db, user, rid):
    actor, run, artifact, frozen, value = authorize(db, user, rid)
    usage(db, artifact, run)
    if run.status != "succeeded":
        if run.result_json != "{}" or any(getattr(artifact, field) is not None for field in ("result_json", "result_hash", "result_bytes", "accept_event_id", "accepted_at", "accepted_lease")):
            raise HTTPException(409, "非成功任务不得保存已接受结果或伪造零哈希")
        return None
    result = k.Analysis.model_validate_json(artifact.result_json)
    pointer = t.ResultPointer.model_validate_json(run.result_json)
    if (
        (pointer.run_id, pointer.source_hash, pointer.result_hash, pointer.result_bytes) != (rid, artifact.source_hash, artifact.result_hash, artifact.result_bytes)
        or run.result_json != t.task_json(pointer)
        or artifact.result_json != c.canonical(result)
        or c.digest(result) != artifact.result_hash
        or len(c.utf8(artifact.result_json)) != artifact.result_bytes
        or artifact.accepted_lease != run.lease_token
        or not engine.verify_analysis_binding(value, result)
    ):
        raise HTTPException(409, "实际完整统计结果/精确复算/短pointer/租约无法核对")
    event = r._actual(db, AIAuditEvent, artifact.accept_event_id)
    expected = {
        "schema_version": "infection_local_accept_audit_v1",
        "run_id": rid,
        "lease": artifact.accepted_lease,
        "source_hash": artifact.source_hash,
        "result_hash": artifact.result_hash,
        "result_bytes": artifact.result_bytes,
        "accepted_at": r.utc(artifact.accepted_at),
        "usage_event_id": artifact.usage_event_id,
    }
    if event is None or (event.actor_id, event.action, event.target, event.detail_json) != (artifact.requested_by, ACCEPT, rid, c.canonical(expected)):
        raise HTTPException(409, "完整结果具体接收审计PK无法核对")
    return result


def memory_run_state(run):
    return {name: {"sha256": c.text_digest(getattr(run, name)), "bytes": len(c.utf8(getattr(run, name)))} if name in t.RAW_FIELDS else getattr(run, name) for name in (*WRITE_FIELDS, *CLOCK_FIELDS)}


def actual_run_state(db, rid):
    _sql_hash_ready(db)
    columns = []
    for name in (*WRITE_FIELDS, *CLOCK_FIELDS):
        col = getattr(AIRun, name)
        if name in t.RAW_FIELDS:
            columns.append(TextSHA(col).label(name + "_sha"))
            # HEX byte length is portable across real SQLite/MySQL and returns
            # only a scalar count, never the clinical string or its hex bytes.
            columns.append(literal_column("length(hex(" + AIRun.__tablename__ + "." + name + "))/2").label(name + "_bytes"))
        else:
            columns.append(col)
    row = current(db.query(*columns).filter(AIRun.run_id == rid)).one_or_none()
    if row is None:
        raise HTTPException(409, "当前Run不存在")
    return {name: {"sha256": row._mapping[name + "_sha"], "bytes": int(row._mapping[name + "_bytes"])} if name in t.RAW_FIELDS else row._mapping[name] for name in (*WRITE_FIELDS, *CLOCK_FIELDS)}


def actual_artifact_state(db, rid):
    """Current technical columns and SQL hashes, without Source/result TEXT."""
    _sql_hash_ready(db)
    row = current(
        db.query(*(getattr(Artifact, name) for name in TECHNICAL), TextSHA(Artifact.source_json).label("actual_source_sha"), TextSHA(Artifact.result_json).label("actual_result_sha")).filter(
            Artifact.run_id == rid
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(409, "实际持久化本地任务锚缺失")
    if row.source_hash != row.actual_source_sha or row.result_hash != row.actual_result_sha:
        raise HTTPException(409, "完整持久件SQL原字节SHA不匹配")
    return {key: row._mapping[key] for key in TECHNICAL}


def verify_technical_run(db, rid):
    """Safe permission-free integrity/terminal path, never an execution grant."""
    if locator(db, rid) is None:
        raise HTTPException(409, "真实本地任务锚缺失")
    artifact = technical(db, rid)
    creation_audit(db, artifact)
    actual_artifact_state(db, rid)
    run = actual_run_state(db, rid)
    if (
        run["feature_key"] != t.FEATURE_KEY
        or run["provider_id"] is not None
        or run["provider_revision"] is not None
        or run["prompt_version"] != 0
        or run["prompt_hash"] != t.LOCAL_PROMPT_HASH
        or run["patient_id"] is not None
        or run["encounter_ref"] is not None
        or run["requested_by"] != artifact.requested_by
        or run["preview"] != artifact.preview
        or run["context_digest"] != artifact.source_binding_hash
        or any(run[name]["sha256"] != getattr(artifact, anchor) for name, anchor in [("input_json", "input_hash"), ("evidence_json", "evidence_hash"), ("context_metadata_json", "metadata_hash")])
        or run["input_tokens"] != 0
        or run["output_tokens"] != 0
        or run["status"] not in {"queued", "running", "succeeded", "failed", "cancelled"}
        or any(run[name]["bytes"] > t.TEXT_BYTES for name in t.RAW_FIELDS)
    ):
        raise HTTPException(409, "本地任务完整技术锚/22字段或原始三JSON字节摘要已改变")
    return artifact, run


def guard_run_id(db, user, rid):
    """Raw current native locator before any generic private Task SELECT."""
    if locator(db, rid) is not None:
        authorize(db, user, rid)
        return True
    # Orphan native markers are checked as scalar SQL booleans only, never by
    # loading the whole old Task TEXT. They cannot establish Source authority.
    from sqlalchemy import func, or_

    markers = ("infection_local_frozen_task_v1", "infection_statistics_result_pointer_v1", "infection_cluster_scenario_id")
    terms = [AIRun.feature_key == t.FEATURE_KEY]
    position = func.strpos if db.get_bind().dialect.name == "postgresql" else func.instr
    terms.extend(position(getattr(AIRun, field), mark) > 0 for field in t.RAW_FIELDS for mark in markers)
    marked = db.query(AIRun.run_id).filter(AIRun.run_id == rid, or_(*terms)).populate_existing().with_for_update(read=True).one_or_none()
    if marked is not None:
        raise HTTPException(409, "旧或损坏78任务缺少真实完整Artifact，不允许通用正文或模型降级")
    return False
