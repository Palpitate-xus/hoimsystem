"""Actual claim/dispatch PK proofs; trusted SQL stages, never user capabilities.

The runtime owns commit, current configuration postcheck and closing SQL before
HTTP. Technical readers below deliberately grant no Source/Task body access.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException
from pydantic import model_validator
from sqlalchemy import select

from app.ai import operations_support_contract as c
from app.ai import operations_support_registry as registry
from app.ai import operations_support_storage as storage
from app.ai.models import AIAuditEvent, AIRun
from app.ai.operations_support_models import AIOperationsWriteGate
from app.ai.operations_support_run_models import AIOperationsRunArtifact
from app.ai.operations_support_write_guard import current_rows

CLAIM_ACTION = "operations.task.claim"
DISPATCH_ACTION = "operations.task.dispatch"
PHASE_FIELDS = ("claim_event_id", "dispatch_event_id", "usage_event_id")


class OperationsClaim(c.StrictModel):
    schema_version: Literal["operations_support_claim_v1"]
    run_id: c.Identifier
    case_id: c.Identifier
    requested_by: c.ActorId
    created_audit_event_id: c.ActorId
    claim_event_id: c.ActorId
    lease_token: c.Identifier
    source_projection_hash: c.Digest
    source_binding_hash: c.Digest
    instructions_digest: c.Digest
    claimed_at: c.Clock

    @model_validator(mode="after")
    def actual_distinct_claim(self):
        if self.created_audit_event_id == self.claim_event_id:
            raise ValueError("Creation and claim must be different actual audit PKs")
        return self


class OperationsDispatch(OperationsClaim):
    schema_version: Literal["operations_support_dispatch_v1"]
    dispatch_event_id: c.ActorId
    dispatched_at: c.Clock

    @model_validator(mode="after")
    def actual_distinct_dispatch(self):
        if self.dispatch_event_id in {self.created_audit_event_id, self.claim_event_id} or self.dispatched_at < self.claimed_at:
            raise ValueError("One actual distinct dispatch must follow this exact claim")
        return self


def clock(value):
    c._clock(value)
    return dt.datetime.fromisoformat(value[:-1])


def lock_gate(db):
    """Trusted metadata-only worker settlement; does not authorize any user."""
    with db.no_autoflush:
        gate = current_rows(db.query(AIOperationsWriteGate).filter_by(gate_id=1)).one_or_none()
    if gate is None or gate.revision != 1:
        raise HTTPException(409, "运维任务技术Gate未正确初始化")


def phase_header(db, identifier, *, exclusive=False):
    with db.no_autoflush:
        row = current_rows(
            db.query(*(getattr(AIOperationsRunArtifact, key) for key in (*storage.IDENTITY_FIELDS, "created_audit_event_id", *PHASE_FIELDS))).filter_by(run_id=registry.identifier(identifier)),
            shared=not exclusive,
        ).one_or_none()
    return None if row is None else dict(row._mapping)


def _claim_detail(header, lease, when):
    return {
        "schema_version": "operations_support_claim_audit_v1",
        "run_id": header["run_id"],
        "case_id": header["case_id"],
        "requested_by": header["requested_by"],
        "created_audit_event_id": header["created_audit_event_id"],
        "lease_token": lease,
        **{key: header[key] for key in ("source_projection_hash", "source_binding_hash", "instructions_digest")},
        "claimed_at": registry.utc_text(when),
    }


def _dispatch_detail(claim, when):
    return {**claim.model_dump(mode="json"), "schema_version": "operations_support_dispatch_audit_v1", "dispatched_at": registry.utc_text(when)}


def _event_body(db, identifier):
    with db.no_autoflush:
        row = current_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one_or_none()
    if row is None:
        raise HTTPException(409, "运维任务具体阶段审计PK缺失")
    return storage._json(row.detail_json, 65535)


def claim_from_headers(db, header, run):
    try:
        if header["claim_event_id"] is None or run["lease_token"] is None or run["start_time"] is None:
            raise ValueError("Actual claim event, lease and start clock required")
        body = _event_body(db, header["claim_event_id"])
        when = clock(body["claimed_at"])
        if when < header["recorded_at"] or run["start_time"] != when.replace(microsecond=0):
            raise ValueError("Original UTC6 claim and explicit legacy start seconds differ")
        expected = _claim_detail(header, run["lease_token"], when)
        if body != expected:
            raise ValueError("Complete actual claim body differs")
        proof = OperationsClaim(**{**expected, "schema_version": "operations_support_claim_v1"}, claim_event_id=header["claim_event_id"])
        registry.verify_event(db, proof.claim_event_id, proof.requested_by, CLAIM_ACTION, proof.run_id, expected, when)
        return proof
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "运维任务本次实际claim主键、完整锚、租约或微秒时钟损坏") from exc


def dispatch_from_headers(db, header, run):
    claim = claim_from_headers(db, header, run)
    try:
        if header["dispatch_event_id"] is None:
            raise ValueError("Actual dispatch PK required")
        body = _event_body(db, header["dispatch_event_id"])
        when = clock(body["dispatched_at"])
        expected = _dispatch_detail(claim, when)
        if body != expected:
            raise ValueError("Complete actual dispatch differs")
        proof = OperationsDispatch(
            **{**claim.model_dump(mode="json"), "schema_version": "operations_support_dispatch_v1"}, dispatch_event_id=header["dispatch_event_id"], dispatched_at=registry.utc_text(when)
        )
        registry.verify_event(db, proof.dispatch_event_id, proof.requested_by, DISPATCH_ACTION, proof.run_id, expected, when)
        return proof
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "运维任务本次实际dispatch主键、原claim或微秒时钟损坏") from exc


@dataclass(frozen=True)
class TechnicalAttempt:
    header: dict
    artifact: dict
    claim: OperationsClaim
    dispatch: OperationsDispatch | None


def technical_attempt(db, value, *, exclusive=True):
    """Original trusted worker only; no current Source/Task TEXT is selected."""
    try:
        proof = OperationsClaim.model_validate(value, strict=True)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "原运维任务claim闭集证明无效") from exc
    lock_gate(db)
    artifact = phase_header(db, proof.run_id, exclusive=exclusive)
    run = storage.run_header(db, proof.run_id, shared=not exclusive)
    if artifact is None:
        raise HTTPException(409, "原运维任务分件不存在")
    storage._verify_created(db, artifact, run)
    actual = claim_from_headers(db, artifact, run)
    if actual != proof:
        raise HTTPException(409, "本交付不是原实际claim主键与租约")
    dispatch = dispatch_from_headers(db, artifact, run) if artifact["dispatch_event_id"] is not None else None
    return TechnicalAttempt(run, artifact, actual, dispatch)


def _phase_seen(db, identifier, fields):
    statement = select(*(getattr(AIOperationsRunArtifact, key) for key in fields)).where(AIOperationsRunArtifact.run_id == identifier)
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                row = connection.execute(statement).one_or_none()
            if row is not None and any(value is not None for value in row):
                return True
        # Include this Session's actual uncommitted SQL, not just an external RC
        # snapshot; never use a process-global pending marker.
        own = db.execute(statement).one_or_none()
    return own is not None and any(value is not None for value in own)


def _postcheck(db, user, identifier, expected_run, expected_artifact):
    loaded = storage.load_artifact(db, user, identifier, execution=True)
    run, artifact = loaded[:2]
    if {column.name: getattr(run, column.name) for column in AIRun.__table__.columns} != expected_run or {
        column.name: getattr(artifact, column.name) for column in AIOperationsRunArtifact.__table__.columns
    } != expected_artifact:
        raise HTTPException(409, "本次阶段写入后Run全部字段或完整Artifact真实读回变化")
    return run, artifact


def stage_claim(db, user, identifier):
    """One source-authorized claim; caller owns atomic rollback and commit."""
    if _phase_seen(db, identifier, ("claim_event_id",)):
        return None
    loaded = storage.load_artifact(db, user, identifier, execution=True)
    run, artifact = loaded[:2]
    if run.status != "queued" or artifact.claim_event_id is not None:
        return None
    if (
        run.result_json != "{}"
        or run.input_tokens != 0
        or run.output_tokens != 0
        or any(getattr(run, key) is not None for key in ("lease_token", "start_time", "finish_time", "latency_ms", "error_code", "error_message"))
        or artifact.dispatch_event_id is not None
        or artifact.usage_event_id is not None
    ):
        raise HTTPException(409, "排队运维任务已有执行或终态痕迹，不能重领")
    when, lease = registry.utcnow(), str(uuid.uuid4())
    if when < artifact.recorded_at:
        raise HTTPException(409, "领取时钟早于原任务登记，未改写原钟")
    expected_run = {column.name: getattr(run, column.name) for column in AIRun.__table__.columns}
    expected_artifact = {column.name: getattr(artifact, column.name) for column in AIOperationsRunArtifact.__table__.columns}
    detail = _claim_detail(expected_artifact, lease, when)
    event_id = registry.audit_event(db, run.requested_by, CLAIM_ACTION, identifier, detail, when)
    expected_run.update(status="running", lease_token=lease, start_time=when.replace(microsecond=0))
    expected_artifact["claim_event_id"] = event_id
    changed = (
        db.query(AIRun)
        .filter_by(run_id=identifier, status="queued", lease_token=None, start_time=None, finish_time=None)
        .update({"status": "running", "lease_token": lease, "start_time": when.replace(microsecond=0)}, synchronize_session=False)
    )
    saved = (
        db.query(AIOperationsRunArtifact)
        .filter_by(run_id=identifier, created_audit_event_id=artifact.created_audit_event_id, claim_event_id=None, dispatch_event_id=None, usage_event_id=None)
        .update({"claim_event_id": event_id}, synchronize_session=False)
    )
    if changed != 1 or saved != 1:
        raise HTTPException(409, "原运维任务本次claim CAS失败")
    _postcheck(db, user, identifier, expected_run, expected_artifact)
    return claim_from_headers(db, phase_header(db, identifier), storage.run_header(db, identifier))


def stage_dispatch(db, user, value):
    """One source-authorized reservation; it does not claim HTTP was attempted."""
    try:
        claim = OperationsClaim.model_validate(value, strict=True)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "运维发送须使用原闭集claim证明") from exc
    if _phase_seen(db, claim.run_id, ("dispatch_event_id", "usage_event_id")):
        return None
    # Source/config technical authority is still acquired before the Run lock;
    # the original specific claim must then match before any protected BODY.
    storage._before_bodies(db, user, claim.run_id, execution=True)
    if claim_from_headers(db, phase_header(db, claim.run_id), storage.run_header(db, claim.run_id)) != claim:
        raise HTTPException(409, "本次dispatch并非原实际claim主键和租约；未读取正文")
    loaded = storage.load_artifact(db, user, claim.run_id, execution=True)
    run, artifact = loaded[:2]
    if run.status != "running" or artifact.dispatch_event_id is not None or artifact.usage_event_id is not None:
        return None
    header = phase_header(db, claim.run_id)
    if claim_from_headers(db, header, storage.run_header(db, claim.run_id)) != claim:
        raise HTTPException(409, "运维dispatch不属于原实际claim")
    when = registry.utcnow()
    if when < clock(claim.claimed_at):
        raise HTTPException(409, "发送时钟早于本次领取")
    expected_run = {column.name: getattr(run, column.name) for column in AIRun.__table__.columns}
    expected_artifact = {column.name: getattr(artifact, column.name) for column in AIOperationsRunArtifact.__table__.columns}
    event_id = registry.audit_event(db, run.requested_by, DISPATCH_ACTION, run.run_id, _dispatch_detail(claim, when), when)
    expected_artifact["dispatch_event_id"] = event_id
    changed = (
        db.query(AIOperationsRunArtifact)
        .filter_by(run_id=run.run_id, claim_event_id=claim.claim_event_id, dispatch_event_id=None, usage_event_id=None)
        .update({"dispatch_event_id": event_id}, synchronize_session=False)
    )
    if changed != 1:
        raise HTTPException(409, "运维本次dispatch CAS失败")
    _postcheck(db, user, run.run_id, expected_run, expected_artifact)
    return dispatch_from_headers(db, phase_header(db, run.run_id), storage.run_header(db, run.run_id))
