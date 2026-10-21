"""Exact split RCA storage; Source/current purposes precede all Task TEXT.

Opaque locators are technical only and immediately release their independent
RC connection. Normal locks remain Actor -> Event X -> Case/current -> original
purposes -> Run -> Artifact. No helper performs HTTP or commits a transaction.
"""

import datetime as dt
import hashlib
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import inspect, select

from app.ai import rca_evidence_case_contract as k
from app.ai import rca_evidence_cases as cases
from app.ai import rca_evidence_context as context
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_sources as originals
from app.ai import rca_evidence_storage_contract as types
from app.ai import rca_evidence_task_contract as t
from app.ai.models import AIAuditEvent, AIRun
from app.ai.rca_evidence_run_models import ANCHOR_FIELDS, ARTIFACT_SCHEMA, AIRcaEvidenceRunArtifact
from app.ai.rca_evidence_write_guard import current_rows

RUN_TEXT = ("input_json", "result_json", "evidence_json", "context_metadata_json")
RUN_COLUMNS = tuple(column.name for column in AIRun.__table__.columns)
RUN_HEADER = tuple(key for key in RUN_COLUMNS if key not in RUN_TEXT)
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
ART_COLUMNS = tuple(column.name for column in AIRcaEvidenceRunArtifact.__table__.columns)
ART_TEXT = ("source_json", "binding_json")
ART_PHASE = ("create_event_id", "claim_event_id", "claim_lease", "claimed_at", "dispatch_event_id", "dispatched_at", "usage_event_id")
ART_IMMUTABLE = tuple(key for key in ART_COLUMNS if key not in (*ART_TEXT, *ART_PHASE))


@dataclass(frozen=True)
class RcaStoredTask:
    run: AIRun
    artifact: AIRcaEvidenceRunArtifact
    snapshot: types.RcaTaskSnapshot
    metadata: types.RcaTaskMetadata
    binding: t.RcaTaskBinding
    source: c.RcaEvidenceSource
    frozen_case: object
    authorized: grants.AuthorizedEvent
    frozen_audit: bool


def text_hash(raw, maximum=t.MAX_RUN_TEXT_BYTES):
    if type(raw) is not str or not 0 < len(c.utf8(raw)) <= maximum:
        raise ValueError("A complete stored UTF8 object must fit its actual column")
    return hashlib.sha256(c.utf8(raw)).hexdigest()


def canonical_value(raw, maximum=t.MAX_RUN_TEXT_BYTES):
    text_hash(raw, maximum)
    value = c._strict_reply(raw)
    if c.canonical(value) != raw:
        raise ValueError("The exact original canonical JSON bytes must remain unchanged")
    return value


def _narrow_current(db, statement):
    """Only immutable technical columns; no Source/Artifact/Run row lock."""
    with db.no_autoflush:
        rows = set()
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                rows.update(tuple(row) for row in connection.execute(statement))
        rows.update(tuple(row) for row in db.execute(statement))
    if len(rows) > 1:
        raise HTTPException(409, "任务当前技术身份与本事务实际身份互相矛盾")
    return next(iter(rows), None)


def locate_artifact(db, value):
    state = inspect(value, raiseerr=False)
    identifier = value if type(value) is str else state.identity[0] if state is not None and state.identity else getattr(value, "run_id", None)
    if type(identifier) is not str:
        return None
    statement = select(AIRcaEvidenceRunArtifact.run_id, AIRcaEvidenceRunArtifact.case_id, AIRcaEvidenceRunArtifact.requested_by).where(AIRcaEvidenceRunArtifact.run_id == identifier)
    return _narrow_current(db, statement)


def _grant_ids(db, identifier):
    return _narrow_current(
        db, select(AIRcaEvidenceRunArtifact.run_id, AIRcaEvidenceRunArtifact.event_grant_id, AIRcaEvidenceRunArtifact.patient_grant_id).where(AIRcaEvidenceRunArtifact.run_id == identifier)
    )


def _source_before_task(db, user, identity, *, frozen_audit=False):
    grants.current_actor(db, user, grants.SOURCE_ROLES)
    if identity is None:
        raise HTTPException(404, "RCA原生任务锚不存在")
    identifier, case_id, owner = identity
    auth, row = cases._load(db, user, case_id)
    if not frozen_audit and auth.actor.user_id != owner:
        raise HTTPException(403, "须为原请求人；其它Super需显式冻结审计且具有当前独立用途")
    original_grants = _grant_ids(db, identifier)
    if original_grants is None or original_grants[0] != identifier:
        raise HTTPException(409, "RCA任务原独立用途技术头缺失")
    if not frozen_audit:
        for grant_id, kind in ((original_grants[1], "event_investigation"), (original_grants[2], "associated_patient_processing")):
            if grant_id is None:
                if kind == "event_investigation" or auth.identity.patient_id is not None:
                    raise HTTPException(409, "原任务用途技术头与实际患者归属不一致")
                continue
            context.current_task_grant(db, auth.actor, grant_id, event_id=auth.identity.event_id, patient_id=auth.identity.patient_id, requested_by=owner, permission_kind=kind)
        record = cases._record(db, row, cases._capture(db, auth))
        cases.project_source(record)
        immutable = record.immutable
    else:
        immutable, _current_governance = cases._body(db, row)
    return auth, immutable, original_grants


def _actual_run_header(db, identifier, *, exclusive=False):
    columns = [getattr(AIRun, key) for key in RUN_HEADER]
    columns.extend(originals._bytes_expression(db, getattr(AIRun, key)).label("bytes_" + key) for key in RUN_TEXT)
    row = current_rows(db.query(*columns).filter_by(run_id=identifier), shared=not exclusive).one_or_none()
    if row is None:
        raise HTTPException(404, "RCA任务已不存在")
    value = dict(row._mapping)
    if value["feature_key"] != t.FEATURE_KEY or value["patient_id"] is not None or value["encounter_ref"] is not None:
        raise HTTPException(409, "原生RCA任务不能修改功能或混入通用患者/就诊范围")
    if any(type(value["bytes_" + key]) is not int or not 0 < value["bytes_" + key] <= t.MAX_RUN_TEXT_BYTES for key in RUN_TEXT):
        raise HTTPException(413, "原任务完整TEXT列超限，未读取正文")
    return value


def _artifact_metadata(db, identifier, *, exclusive=False):
    columns = [getattr(AIRcaEvidenceRunArtifact, key) for key in ART_COLUMNS if key not in ART_TEXT]
    columns.extend(originals._bytes_expression(db, getattr(AIRcaEvidenceRunArtifact, key)).label("actual_bytes_" + key) for key in ART_TEXT)
    row = current_rows(db.query(*columns).filter_by(run_id=identifier), shared=not exclusive).one_or_none()
    if row is None:
        raise HTTPException(409, "RCA任务实际Artifact已缺失")
    value = dict(row._mapping)
    for key, shadow, maximum in (("source_json", "source_bytes", c.MAX_WIRE_BYTES), ("binding_json", "binding_bytes", t.MAX_RUN_TEXT_BYTES)):
        if value["actual_bytes_" + key] != value[shadow] or type(value[shadow]) is not int or not 0 < value[shadow] <= maximum:
            raise HTTPException(413, "RCA任务完整Source/Binding字节锚不一致，未加载正文")
    return value


def _clock_value(value):
    return i.utc_text(value) if isinstance(value, dt.datetime) else value


def _run_clock(value):
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None or value.microsecond:
            raise ValueError("Actual legacy Run DATETIME(0) requires explicit naive UTC seconds")
        return value.isoformat(timespec="seconds")
    return value


def _creation_detail(header, artifact):
    immutable_header = {key: _run_clock(header[key]) for key in RUN_IMMUTABLE}
    immutable_header.update({name: artifact[name] for name in ("input_hash", "evidence_hash", "metadata_hash")})
    return {"schema_version": "rca_evidence_creation_anchor_v1", "artifact": {key: _clock_value(artifact[key]) for key in ART_IMMUTABLE}, "run_header_hash": c.digest(immutable_header)}


def _exact_creation_audit(db, header, artifact):
    identifier = artifact["create_event_id"]
    columns = (AIAuditEvent.event_id, AIAuditEvent.actor_id, AIAuditEvent.action, AIAuditEvent.target, AIAuditEvent.create_time, originals._bytes_expression(db, AIAuditEvent.detail_json))
    metadata = current_rows(db.query(*columns).filter_by(event_id=identifier), shared=True).one_or_none()
    if metadata is None or metadata[-1] is None or not 0 < metadata[-1] <= t.MAX_RUN_TEXT_BYTES:
        raise HTTPException(409, "原RCA任务具体创建审计PK缺失或容量错误")
    expected = {
        **_creation_detail(header, artifact),
        "recorded_at_utc6": i.utc_text(artifact["recorded_at"]),
        "audit_clock_basis": "legacy_utc_second_storage",
    }
    event = current_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one()
    if (event.actor_id, event.action, event.target, event.create_time, event.detail_json) != (
        artifact["requested_by"],
        "rca_run.create",
        artifact["run_id"],
        artifact["recorded_at"].replace(microsecond=0),
        c.canonical(expected),
    ):
        raise HTTPException(409, "原任务具体创建审计与不可变头、登录epoch或八个摘要不一致")


def _check_header_scope(auth, identity, grant_ids, header, artifact, *, frozen_audit):
    if (artifact["run_id"], artifact["case_id"], artifact["requested_by"]) != identity or (header["run_id"], header["requested_by"]) != (identity[0], identity[2]):
        raise HTTPException(409, "原任务、Artifact与技术定位身份不一致")
    if (artifact["run_id"], artifact["event_grant_id"], artifact["patient_grant_id"]) != grant_ids:
        raise HTTPException(409, "实际Artifact原用途外键与授权前技术头不同")
    if (artifact["event_id"], artifact["patient_id_at_capture"]) != (auth.identity.event_id, auth.identity.patient_id):
        raise HTTPException(409, "实际Artifact事件或患者身份与当前原件不同")
    if artifact["schema_version"] != ARTIFACT_SCHEMA or header["create_time"] != artifact["recorded_at"].replace(microsecond=0):
        raise HTTPException(409, "原任务类型或实际双时钟锚不一致")
    if not frozen_audit and (auth.actor.user_role != "super_admin" or auth.actor.token_invalid_before != artifact["actor_token_invalid_before"]):
        raise HTTPException(403, "原任务账户角色或原登录epoch已失效，未读取Task正文")


def _frozen_projection(immutable, snapshot, binding):
    record = k.CaseRecord(
        immutable=immutable,
        content_hash=binding.case_content_hash,
        governance=snapshot.source_case_governance,
        governance_hash=binding.case_governance_hash,
        current_collection_hash=immutable.capture.collection_hash,
        current_collection_matches=True,
        eligible=True,
        evaluated_at=snapshot.payload.context["snapshot_time"],
        public_source_endpoint="separate_typed_8MiB_response",
        causal_verification="not_provided",
    )
    # This is an internal reconstruction of the old publication only. The
    # returned private piece explicitly has execution_current=False.
    return cases.project_source(record), context.frozen_case(immutable, record.governance, record.content_hash, record.governance_hash)


def load_task(db, user, value, *, frozen_audit=False, exclusive=False):
    identity = locate_artifact(db, value)
    auth, immutable, grant_ids = _source_before_task(db, user, identity, frozen_audit=frozen_audit)
    header = _actual_run_header(db, identity[0], exclusive=exclusive)
    artifact_header = _artifact_metadata(db, identity[0], exclusive=exclusive)
    # Both checks precede all Run/Artifact TEXT. The exact-PK audit prevents
    # rewriting the original epoch or grant metadata and simply rehashing JSON.
    _exact_creation_audit(db, header, artifact_header)
    _check_header_scope(auth, identity, grant_ids, header, artifact_header, frozen_audit=frozen_audit)
    try:
        run = current_rows(db.query(AIRun).filter_by(run_id=identity[0]), shared=not exclusive).one()
        row = current_rows(db.query(AIRcaEvidenceRunArtifact).filter_by(run_id=identity[0]), shared=not exclusive).one()
        snapshot = types.RcaTaskSnapshot.model_validate(canonical_value(run.input_json))
        metadata = types.RcaTaskMetadata.model_validate(canonical_value(run.context_metadata_json))
        evidence = canonical_value(run.evidence_json)
        binding = t.RcaTaskBinding.model_validate(canonical_value(row.binding_json))
        source = c.validate_source(canonical_value(row.source_json, c.MAX_WIRE_BYTES))
        if t.checked_context(snapshot.payload.context) != binding or canonical_value(run.evidence_json) != t.evidence_for_binding(binding):
            raise ValueError("The exact task context and original evidence differ")
        expected_metadata = types.metadata_for_snapshot(snapshot)
        anchors = {
            "input_hash": text_hash(run.input_json),
            "evidence_hash": text_hash(run.evidence_json),
            "metadata_hash": text_hash(run.context_metadata_json),
            "prompt_hash": c.digest([snapshot.system_prompt, snapshot.task_prompt]),
            "context_digest": c.digest(snapshot.payload.context),
            "instructions_digest": t.instructions_digest(snapshot.system_prompt, snapshot.task_prompt),
            "source_hash": c.digest(source),
            "binding_hash": c.digest(binding),
        }
        if any(getattr(row, name) != anchors[name] for name in ANCHOR_FIELDS) or metadata != expected_metadata or evidence != [item.model_dump(mode="json") for item in snapshot.payload.evidence]:
            raise ValueError("Original Source, input/evidence/metadata bytes and all eight anchors differ")
        if (run.provider_id, run.provider_revision, run.prompt_hash, run.context_digest) != (
            snapshot.provider_snapshot.provider_id,
            snapshot.provider_snapshot.revision,
            anchors["prompt_hash"],
            anchors["context_digest"],
        ):
            raise ValueError("Original provider and immutable Run fields differ from the frozen Task")
        if (binding.case_id, binding.event_id, binding.patient_id_at_capture, binding.requested_by) != (row.case_id, row.event_id, row.patient_id_at_capture, row.requested_by):
            raise ValueError("The short immutable context differs from actual Artifact scope columns")
        if (binding.event_grant.grant_id, binding.patient_grant.grant_id if binding.patient_grant else None) != (row.event_grant_id, row.patient_grant_id):
            raise ValueError("The actual original purposes differ from the immutable context")
        token = c.clock(snapshot.actor_epoch.token_invalid_before).replace(tzinfo=None) if snapshot.actor_epoch.token_invalid_before is not None else None
        if token != row.actor_token_invalid_before:
            raise ValueError("The exact original actor epoch differs from its independent SQL anchor")
        if snapshot.payload.context["snapshot_time"] != i.utc_text(row.recorded_at):
            raise ValueError("Actual UTC6 task registration differs from its stored clock")
        expanded = t.expand_public_context(snapshot.payload.context, source)
        t.public_payload({"input": snapshot.payload.input.model_dump(mode="json"), "context": expanded, "tools": {}, "evidence": evidence})
        projected, frozen = _frozen_projection(immutable, snapshot, binding)
        if c.canonical(projected) != row.source_json:
            raise ValueError("The complete public projection does not mechanically match the original private Case")
        if not frozen_audit:
            context.authorize_binding(db, auth.actor, binding)
        return RcaStoredTask(run, row, snapshot, metadata, binding, source, frozen, auth, frozen_audit)
    except (ValueError, TypeError, UnicodeError, KeyError) as exc:
        raise HTTPException(409, "原RCA任务、完整分件、冻结签署或具体SQL锚无法核对，未降级或截断") from exc


@grants._write
def stage_run(db, user, run, prepared, snapshot):
    """Caller owns configured feature/quota checks; this stages real Source SQL.

    The same transaction must perform the caller's current configuration
    postcheck and commit. This helper never enables a feature or calls a model.
    """
    snapshot = types.RcaTaskSnapshot.model_validate(snapshot)
    if t.checked_context(snapshot.payload.context) != prepared.binding:
        raise HTTPException(409, "准备的当前Source与原任务短Binding不同")
    context.authorize_binding(db, user, prepared.binding)
    actor = grants.current_actor(db, user, grants.SOURCE_ROLES)
    token = c.clock(snapshot.actor_epoch.token_invalid_before).replace(tzinfo=None) if snapshot.actor_epoch.token_invalid_before else None
    if actor.token_invalid_before != token:
        raise HTTPException(403, "原入口登录epoch在Source等待后已变化")
    recorded = c.clock(prepared.data["snapshot_time"]).replace(tzinfo=None)
    metadata = types.metadata_for_snapshot(snapshot)
    run.feature_key, run.patient_id, run.encounter_ref = t.FEATURE_KEY, None, None
    run.provider_id, run.provider_revision = snapshot.provider_snapshot.provider_id, snapshot.provider_snapshot.revision
    run.prompt_hash, run.context_digest = c.digest([snapshot.system_prompt, snapshot.task_prompt]), c.digest(prepared.data)
    run.requested_by, run.create_time = actor.user_id, recorded.replace(microsecond=0)
    run.status, run.result_json = "queued", "{}"
    run.input_json, run.evidence_json, run.context_metadata_json = t.text_json(snapshot), t.text_json(prepared.evidence), t.text_json(metadata)
    run.input_tokens = run.output_tokens = 0
    run.error_code = run.error_message = run.latency_ms = run.start_time = run.lease_token = run.finish_time = None
    if type(run.prompt_version) is not int or run.prompt_version < 0 or type(run.preview) is not int or run.preview not in (0, 1):
        raise ValueError("Actual original Prompt version and explicit preview are required")
    db.add(run)
    db.flush()
    source_raw, binding_raw = c.canonical(prepared.source), t.text_json(prepared.binding)
    row = AIRcaEvidenceRunArtifact(
        run_id=run.run_id,
        case_id=prepared.binding.case_id,
        event_id=prepared.binding.event_id,
        patient_id_at_capture=prepared.binding.patient_id_at_capture,
        requested_by=actor.user_id,
        event_grant_id=prepared.binding.event_grant.grant_id,
        patient_grant_id=prepared.binding.patient_grant.grant_id if prepared.binding.patient_grant else None,
        schema_version=ARTIFACT_SCHEMA,
        recorded_at=recorded,
        actor_token_invalid_before=token,
        source_json=source_raw,
        source_bytes=len(c.utf8(source_raw)),
        binding_json=binding_raw,
        binding_bytes=len(c.utf8(binding_raw)),
        input_hash=text_hash(run.input_json),
        evidence_hash=text_hash(run.evidence_json),
        metadata_hash=text_hash(run.context_metadata_json),
        prompt_hash=run.prompt_hash,
        context_digest=run.context_digest,
        instructions_digest=metadata.instructions_digest,
        source_hash=c.digest(prepared.source),
        binding_hash=c.digest(prepared.binding),
        claim_event_id=None,
        claim_lease=None,
        claimed_at=None,
        dispatch_event_id=None,
        dispatched_at=None,
        usage_event_id=None,
    )
    detail = _creation_detail({key: getattr(run, key) for key in RUN_HEADER}, {key: getattr(row, key) for key in ART_IMMUTABLE})
    audit_id, audit_expected = grants._audit(db, actor, "rca_run.create", run.run_id, detail, recorded)
    row.create_event_id = audit_id
    db.add(row)
    expected_run = {key: getattr(run, key) for key in RUN_COLUMNS}
    expected_artifact = {key: getattr(row, key) for key in ART_COLUMNS}
    db.flush()
    stored = load_task(db, user, run.run_id, exclusive=True)
    actual_run = current_rows(db.query(*(getattr(AIRun, key) for key in RUN_COLUMNS)).filter_by(run_id=run.run_id)).one()
    actual_artifact = current_rows(db.query(*(getattr(AIRcaEvidenceRunArtifact, key) for key in ART_COLUMNS)).filter_by(run_id=run.run_id)).one()
    if dict(actual_run._mapping) != expected_run or dict(actual_artifact._mapping) != expected_artifact:
        raise HTTPException(409, "实际Run全部字段、完整Artifact或创建指针在写回后发生变化")
    grants._exact_audit(db, audit_id, audit_expected)
    return stored


def source_piece(db, user, identifier, *, frozen_audit=False):
    return cases.wire(load_task(db, user, identifier, frozen_audit=frozen_audit).source)


def case_piece(db, user, identifier, *, frozen_audit=False):
    return cases.wire(load_task(db, user, identifier, frozen_audit=frozen_audit).frozen_case)
