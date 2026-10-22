"""Source/purpose-first76 reads and explicit, purpose-authorized frozen audit.

The short current locator is technical, not authority. It immediately returns
its separate MySQL READ COMMITTED connection; SQLite never opens another
StaticPool Session. Parent Source locks always precede Run/Artifact locks.
"""

import datetime as dt
from dataclasses import dataclass

from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy import LargeBinary, cast, func, inspect, select

from app.ai import research_variables_storage as storage
from app.ai import research_variables_storage_contract as types
from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_contract import UUID
from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_cohort_write_guard import current_research_rows, lock_research_write
from app.ai.research_variables_batches import _authorized_row
from app.ai.research_variables_configuration import current_configuration
from app.ai.research_variables_fields import VARIABLE_SOURCE_ROLES
from app.ai.research_variables_run_models import ANCHOR_FIELDS, ARTIFACT_SCHEMA, AIResearchVariableRunArtifact
from app.ai.research_variables_snapshot import project_variable_snapshot
from app.ai.research_variables_task_binding import VariableTaskBinding, evidence_for_binding
from app.ai.research_variables_task_context import authorize_request, prepare_context, wire_parts
from app.ai.research_variables_task_contract import FEATURE_KEY, MAX_BINDING_BYTES, MAX_RUN_TEXT_BYTES, MAX_WIRE_BYTES, canonical, digest, validate_frozen_source


@dataclass(frozen=True)
class VariableStoredTask:
    run: AIRun
    artifact: AIResearchVariableRunArtifact
    snapshot: types.VariableTaskSnapshot
    binding: VariableTaskBinding
    source: object
    private_scope: dict
    authority: object
    frozen_audit: bool


def locate_artifact(db, value):
    """Exactly three opaque columns, never row locks, TEXT or authorization."""
    state = inspect(value, raiseerr=False)
    identifier = value if type(value) is str else state.identity[0] if state is not None and state.identity else getattr(value, "run_id", None)
    try:
        TypeAdapter(UUID).validate_python(identifier, strict=True)
    except (ValueError, TypeError):
        return None
    return _current_opaque_identity(db, identifier)


def _current_opaque_identity(db, identifier):
    """Bound exact PK comparison under the real DB collation, three columns.

    Only technical dispatch may supply a noncanonical alias here. This returns
    actual immutable FK values, never a permission or private-row lock/body.
    """
    statement = select(AIResearchVariableRunArtifact.run_id, AIResearchVariableRunArtifact.batch_id, AIResearchVariableRunArtifact.requested_by).where(
        AIResearchVariableRunArtifact.run_id == identifier
    )
    with db.no_autoflush:
        rows = set()
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                rows.update(tuple(row) for row in connection.execute(statement))
        rows.update(tuple(row) for row in db.execute(statement))
    if len(rows) > 1:
        raise HTTPException(409, "任务当前技术定位与本事务实际身份矛盾，未降级为通用任务")
    return next(iter(rows), None)


def _bytes(db, value):
    return func.octet_length(value) if db.get_bind().dialect.name in {"mysql", "mariadb"} else func.length(cast(value, LargeBinary))


def _technical_authority(db, identity):
    # No Artifact lock before Source. Parent Gate serializes legitimate76
    # writers; this current narrow read cannot itself grant any permission.
    columns = ("run_id", "batch_id", "requested_by", "task_acl_id", "actor_role", "actor_token_invalid_before", "request_authorization_hash")
    statement = (
        select(*[getattr(AIResearchVariableRunArtifact, key) for key in columns], AIRun.preview)
        .join(AIRun, AIRun.run_id == AIResearchVariableRunArtifact.run_id)
        .where(AIResearchVariableRunArtifact.run_id == identity[0])
    )
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                row = connection.execute(statement).one_or_none()
            own = db.execute(statement).one_or_none()
            if own is not None and row is not None and tuple(own) != tuple(row):
                raise HTTPException(409, "原授权技术头在当前事务中不一致")
            row = own if row is None else row
        else:
            row = db.execute(statement).one_or_none()
    if row is None or tuple(row[:3]) != identity:
        raise HTTPException(409, "原任务授权技术头或实际定位缺失")
    return dict(zip((*columns, "preview"), row, strict=True))


def _source_first(db, user, identity, *, frozen_audit):
    actor = lock_research_write(db, user, allowed_roles={"super_admin"} if frozen_audit else VARIABLE_SOURCE_ROLES)
    if identity is None:
        raise HTTPException(404, "明确科研变量任务锚不存在")
    original = _technical_authority(db, identity)
    if not frozen_audit and (actor.user_id, actor.user_role, actor.token_invalid_before) != (identity[2], original["actor_role"], original["actor_token_invalid_before"]):
        raise HTTPException(403, "原请求人、原角色或登录授权已改变；未读取任务或Batch正文")
    authority = authorize_request(
        db,
        actor,
        identity[1],
        expected_authorization_hash=None if frozen_audit else original["request_authorization_hash"],
        expected_acl_id=None if frozen_audit else original["task_acl_id"],
    )
    if frozen_audit:
        # Explicit Super audit still needs its own current project, ALL Scope
        # patient purposes and model-use permission before this first BODY.
        _, batch, proof = _authorized_row(db, authority.actor, identity[1])
        return authority, original, (batch, proof)
    prepared = prepare_context(db, authority.actor, {"research_variable_batch_id": identity[1]})
    return authority, original, prepared


def _headers(db, identity, *, exclusive):
    run_columns = [getattr(AIRun, key) for key in storage.RUN_HEADER]
    run_columns += [_bytes(db, getattr(AIRun, key)).label("bytes_" + key) for key in storage.RUN_TEXT]
    run_row = current_research_rows(db.query(*run_columns).filter_by(run_id=identity[0]), shared=not exclusive).one_or_none()
    if run_row is None:
        raise HTTPException(404, "任务不存在")
    run = dict(run_row._mapping)
    if (run["feature_key"], run["requested_by"], run["patient_id"], run["encounter_ref"]) != (FEATURE_KEY, identity[2], None, None):
        raise HTTPException(409, "原生变量任务功能、请求人或患者/就诊头已改变")
    if any(type(run["bytes_" + key]) is not int or not 0 < run["bytes_" + key] <= MAX_RUN_TEXT_BYTES for key in storage.RUN_TEXT):
        raise HTTPException(413, "完整Run TEXT列超限，未读取正文")
    art_columns = [getattr(AIResearchVariableRunArtifact, key) for key in (*storage.ART_IMMUTABLE, *storage.ART_PHASE)]
    art_columns += [_bytes(db, getattr(AIResearchVariableRunArtifact, key)).label("bytes_" + key) for key in storage.ART_TEXT]
    art_row = current_research_rows(db.query(*art_columns).filter_by(run_id=identity[0]), shared=not exclusive).one_or_none()
    if art_row is None:
        raise HTTPException(409, "实际Artifact不存在")
    artifact = dict(art_row._mapping)
    if (artifact["run_id"], artifact["batch_id"], artifact["requested_by"]) != identity or artifact["schema_version"] != ARTIFACT_SCHEMA:
        raise HTTPException(409, "实际Artifact身份、类型与技术定位不一致")
    for key, maximum in (("source", MAX_WIRE_BYTES), ("binding", MAX_BINDING_BYTES)):
        if type(artifact[key + "_bytes"]) is not int or not 0 < artifact[key + "_bytes"] <= maximum or artifact["bytes_" + key + "_json"] != artifact[key + "_bytes"]:
            raise HTTPException(413, "完整Artifact字节锚不同或超限，未读取正文")
    if run["create_time"] != artifact["recorded_at"].replace(microsecond=0):
        raise HTTPException(409, "实际UTC6与旧Run整秒存储时钟不同")
    return run, artifact


def _creation_audit(db, header, artifact):
    identifier = artifact["create_event_id"]
    columns = (AIAuditEvent.event_id, _bytes(db, AIAuditEvent.detail_json))
    row = current_research_rows(db.query(*columns).filter_by(event_id=identifier), shared=True).one_or_none()
    if row is None or type(row[1]) is not int or not 0 < row[1] <= MAX_RUN_TEXT_BYTES:
        raise HTTPException(409, "原任务具体创建审计PK缺失或容量异常")
    event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one()
    if (event.actor_id, event.action, event.target, event.create_time, event.detail_json) != (
        artifact["requested_by"],
        "research_variable_run.create",
        artifact["run_id"],
        artifact["recorded_at"].replace(microsecond=0),
        canonical(storage.creation_detail(header, artifact), MAX_RUN_TEXT_BYTES),
    ):
        raise HTTPException(409, "原任务具体创建Audit与原授权、不可变头或八个SHA不同")


def _frozen_scope(db, current, snapshot, binding, source):
    batch, current_proof = current
    if current_proof["content_hash"] != binding.batch_content_hash:
        raise ValueError("The original immutable Batch changed")
    original = {
        **current_proof,
        "governance": snapshot.batch_publication.model_dump(mode="json"),
        "governance_hash": binding.batch_governance_hash,
        "source": source.model_dump(mode="json"),
        "projection_hash": binding.source_projection_hash,
        "last_event_id": binding.batch_last_event_id,
    }
    if canonical(project_variable_snapshot(original["snapshot"], binding.batch_governance_hash, identity_key=batch.identity_key)) != canonical(source):
        raise ValueError("The whole original private Batch differs from its frozen public projection")
    event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=binding.batch_last_event_id), shared=True).one_or_none()
    expected = {
        "source_kind": "research_variable_batch",
        "content_hash": binding.batch_content_hash,
        "governance_hash": binding.batch_governance_hash,
        "projection_hash": binding.source_projection_hash,
    }
    if event is None or (event.actor_id, event.action, event.target, event.create_time, event.detail_json) != (
        snapshot.batch_publication.reviewed_by,
        "research.variable_batch.review",
        binding.batch_id,
        dt.datetime.strptime(snapshot.batch_publication.reviewed_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(microsecond=0),
        canonical(expected),
    ):
        raise ValueError("The exact original publication audit PK differs")
    return {"snapshot": original["snapshot"], "proof": {key: value for key, value in original.items() if key not in {"snapshot", "source"}}}


def load_task(db, user, value, *, frozen_audit=False, exclusive=False, for_execution=False):
    """Default ordinary reads never silently become a Super frozen audit."""
    if any(type(flag) is not bool for flag in (frozen_audit, exclusive, for_execution)) or frozen_audit and for_execution:
        raise HTTPException(422, "冻结审计与执行须明确分离")
    try:
        identity = locate_artifact(db, value)
        authority, original, current = _source_first(db, user, identity, frozen_audit=frozen_audit)
        if type(original["preview"]) is not int or original["preview"] not in (0, 1):
            raise HTTPException(409, "实际任务技术预览标志无效")
        # This technical nonlocking preview is not authority. Exact creation
        # Audit verification below independently binds it before Task BODY.
        configured = current_configuration(db, authority.actor, preview=bool(original["preview"])) if for_execution else None
        header, artifact = _headers(db, identity, exclusive=exclusive)
        if any(artifact[key] != original[key] for key in original if key != "preview") or header["preview"] != original["preview"]:
            raise HTTPException(409, "实际Artifact原授权与Source前技术头不一致")
        _creation_audit(db, header, artifact)
        if for_execution:
            from app.config import settings

            elapsed = utcnow() - artifact["recorded_at"]
            if elapsed < dt.timedelta(0) or elapsed > dt.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS):
                raise HTTPException(409, "实际变量任务时钟或等待期限已失效，未读取旧Task正文或重放调用")
        # No Task/Artifact BODY has been selected before the independent Source
        # authority, technical headers and exact creation Audit all pass.
        run = current_research_rows(db.query(AIRun).filter_by(run_id=identity[0]), shared=not exclusive).one()
        row = current_research_rows(db.query(AIResearchVariableRunArtifact).filter_by(run_id=identity[0]), shared=not exclusive).one()
        binding = VariableTaskBinding.model_validate(storage.canonical_value(row.binding_json, MAX_BINDING_BYTES))
        snapshot = types.checked_snapshot(storage.canonical_value(run.input_json), binding)
        source = validate_frozen_source(storage.canonical_value(row.source_json, MAX_WIRE_BYTES), binding.source_projection_hash)
        anchors = {
            "input_hash": storage.text_hash(run.input_json),
            "evidence_hash": storage.text_hash(run.evidence_json),
            "metadata_hash": storage.text_hash(run.context_metadata_json),
            "prompt_hash": types.prompt_hash(snapshot),
            "context_digest": digest(snapshot.payload.context),
            "instructions_digest": types.instructions_digest(snapshot),
            "source_hash": digest(source),
            "binding_hash": digest(binding, MAX_BINDING_BYTES),
        }
        if any(getattr(row, key) != anchors[key] for key in ANCHOR_FIELDS):
            raise ValueError("All eight independent original SHA anchors must agree")
        if storage.canonical_value(run.evidence_json) != evidence_for_binding(binding) or storage.canonical_value(run.context_metadata_json) != storage.metadata_for_snapshot(snapshot):
            raise ValueError("The exact original citation and server metadata differ")
        if (run.provider_id, run.provider_revision, run.prompt_version, run.prompt_hash, run.context_digest) != (
            snapshot.provider_snapshot.provider_id,
            snapshot.provider_snapshot.revision,
            snapshot.prompt_origin.prompt_version,
            anchors["prompt_hash"],
            anchors["context_digest"],
        ):
            raise ValueError("The original actual Run provider/Prompt/context differ")
        access = binding.request_authorization
        if (binding.batch_id, access.scope_id, access.requested_by, access.acl_id, access.actor_role, access.actor_token_invalid_before, binding.request_authorization_hash) != (
            row.batch_id,
            row.scope_id,
            row.requested_by,
            row.task_acl_id,
            row.actor_role,
            utc_text(row.actor_token_invalid_before) if row.actor_token_invalid_before is not None else None,
            row.request_authorization_hash,
        ):
            raise ValueError("The explicit original permission manifest differs from its SQL header")
        if (binding.batch_content_hash, access.scope_content_hash, access.scope_governance_hash) != (row.batch_content_hash, row.scope_content_hash, row.scope_governance_hash):
            raise ValueError("The actual original Batch/Scope SHA columns differ")
        if snapshot.payload.context.snapshot_time != utc_text(row.recorded_at):
            raise ValueError("The original UTC6 recording clock differs")
        if frozen_audit:
            private_scope = _frozen_scope(db, current, snapshot, binding, source)
        else:
            if current.binding != binding or canonical(current.source) != row.source_json:
                raise ValueError("The complete current original Source or original request permissions differ")
            private_scope = current.private_scope
        wire_parts(binding, source, private_scope)
        if configured is not None:
            storage._verify_configuration(snapshot, configured)
        return VariableStoredTask(run, row, snapshot, binding, source, private_scope, authority, frozen_audit)
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as exc:
        raise HTTPException(409, "完整变量Task、原授权、八SHA或原件重投影无法核对，未截断或降级") from exc
