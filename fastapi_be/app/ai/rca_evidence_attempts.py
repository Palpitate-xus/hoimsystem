"""One exact claim and one dispatch, each linked to its actual audit PK.

These are transaction-local stages. Runtime owns current configuration checks,
commit, an independent technical delivery precheck, and releasing every SQL
connection before HTTP. A duplicate stage never terminates its original owner.
"""

import uuid
from typing import Literal

from fastapi import HTTPException
from pydantic import model_validator
from sqlalchemy import select

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_storage as storage
from app.ai.models import AIAuditEvent, AIRun
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact
from app.ai.rca_evidence_write_guard import current_rows


class RcaClaimProof(c.StrictModel):
    schema_version: Literal["rca_evidence_claim_v1"]
    run_id: c.OpaqueId
    case_id: c.OpaqueId
    requested_by: i.PositiveId
    create_event_id: i.PositiveId
    claim_event_id: i.PositiveId
    lease_token: c.OpaqueId
    source_hash: c.SHA
    binding_hash: c.SHA
    claimed_at: str

    @model_validator(mode="after")
    def original_claim(self):
        c.clock(self.claimed_at)
        if self.create_event_id == self.claim_event_id:
            raise ValueError("Creation and claim are different actual audit events")
        return self


class RcaDispatchProof(RcaClaimProof):
    schema_version: Literal["rca_evidence_dispatch_v1"]
    dispatch_event_id: i.PositiveId
    dispatched_at: str

    @model_validator(mode="after")
    def original_dispatch(self):
        if self.dispatch_event_id in {self.create_event_id, self.claim_event_id} or c.clock(self.dispatched_at) < c.clock(self.claimed_at):
            raise ValueError("The actual independent dispatch follows this exact claim")
        return self


def _claim_detail(row, lease, when):
    return {
        "schema_version": "rca_evidence_claim_audit_v1",
        "run_id": row.run_id,
        "case_id": row.case_id,
        "requested_by": row.requested_by,
        "create_event_id": row.create_event_id,
        "lease_token": lease,
        "source_hash": row.source_hash,
        "binding_hash": row.binding_hash,
        "claimed_at": i.utc_text(when),
    }


def _dispatch_detail(row, when):
    return {
        "schema_version": "rca_evidence_dispatch_audit_v1",
        "run_id": row.run_id,
        "case_id": row.case_id,
        "requested_by": row.requested_by,
        "create_event_id": row.create_event_id,
        "claim_event_id": row.claim_event_id,
        "lease_token": row.claim_lease,
        "source_hash": row.source_hash,
        "binding_hash": row.binding_hash,
        "dispatched_at": i.utc_text(when),
    }


def _exact_event(db, row, identifier, action, detail, when):
    actual = current_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one_or_none()
    expected = {**detail, "recorded_at_utc6": i.utc_text(when), "audit_clock_basis": "legacy_utc_second_storage"}
    if actual is None or (actual.actor_id, actual.action, actual.target, actual.create_time, actual.detail_json) != (
        row.requested_by,
        action,
        row.run_id,
        when.replace(microsecond=0),
        c.canonical(expected),
    ):
        raise HTTPException(409, "任务本次实际claim/dispatch审计PK、租约或原件摘要不一致")


def claim_proof(db, stored):
    row, run = stored.artifact, stored.run
    if row.claim_event_id is None or row.claim_lease is None or row.claimed_at is None or run.lease_token != row.claim_lease or run.start_time != row.claimed_at.replace(microsecond=0):
        raise HTTPException(409, "原任务未形成完整的实际claim与租约")
    _exact_event(db, row, row.claim_event_id, "rca_run.claim", _claim_detail(row, row.claim_lease, row.claimed_at), row.claimed_at)
    return RcaClaimProof(
        schema_version="rca_evidence_claim_v1",
        run_id=row.run_id,
        case_id=row.case_id,
        requested_by=row.requested_by,
        create_event_id=row.create_event_id,
        claim_event_id=row.claim_event_id,
        lease_token=row.claim_lease,
        source_hash=row.source_hash,
        binding_hash=row.binding_hash,
        claimed_at=i.utc_text(row.claimed_at),
    )


def dispatch_proof(db, stored):
    claim = claim_proof(db, stored)
    row = stored.artifact
    if row.dispatch_event_id is None or row.dispatched_at is None:
        raise HTTPException(409, "原任务未形成实际dispatch审计")
    _exact_event(db, row, row.dispatch_event_id, "rca_run.dispatch", _dispatch_detail(row, row.dispatched_at), row.dispatched_at)
    return RcaDispatchProof(**{**claim.model_dump(mode="json"), "schema_version": "rca_evidence_dispatch_v1"}, dispatch_event_id=row.dispatch_event_id, dispatched_at=i.utc_text(row.dispatched_at))


def _postcheck(db, user, identifier, expected_run, expected_artifact, audit_id, audit_expected):
    # SQL triggers can change Source or actor. Reauthorize them first, before
    # any actual Run/Artifact TEXT readback; then compare all25 Run columns.
    stored = storage.load_task(db, user, identifier, exclusive=True)
    run = current_rows(db.query(*(getattr(AIRun, key) for key in storage.RUN_COLUMNS)).filter_by(run_id=identifier)).one()
    artifact = current_rows(db.query(*(getattr(AIRcaEvidenceRunArtifact, key) for key in storage.ART_COLUMNS)).filter_by(run_id=identifier)).one()
    if dict(run._mapping) != expected_run or dict(artifact._mapping) != expected_artifact:
        raise HTTPException(409, "实际claim/dispatch写回后的Run全部字段或完整Artifact发生变化")
    grants._exact_audit(db, audit_id, audit_expected)
    return stored


def _already_claimed(db, identifier):
    # A trusted worker may safely skip an existing owner without Source/body
    # access. This boolean never authorizes execution or publishes metadata.
    statement = select(AIRcaEvidenceRunArtifact.claim_event_id).where(AIRcaEvidenceRunArtifact.run_id == identifier)
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                row = connection.execute(statement).one_or_none()
            if row is not None:
                return row[0] is not None
        row = db.execute(statement).one_or_none()
    return row is not None and row[0] is not None


@grants._write
def stage_claim(db, user, identifier):
    """Trusted worker stage only; caller commits and keeps duplicate skips inert."""
    if _already_claimed(db, identifier):
        return None
    stored = storage.load_task(db, user, identifier, exclusive=True)
    run, row = stored.run, stored.artifact
    if run.status != "queued" or row.claim_event_id is not None:
        return None
    if (
        run.result_json != "{}"
        or run.input_tokens != 0
        or run.output_tokens != 0
        or any(getattr(run, key) is not None for key in ("start_time", "lease_token", "finish_time", "latency_ms", "error_code", "error_message"))
    ):
        raise HTTPException(409, "排队任务已有执行或终态痕迹，不能再claim")
    when, lease = grants.utcnow(), str(uuid.uuid4())
    run.status, run.lease_token, run.start_time = "running", lease, when.replace(microsecond=0)
    event_id, expected_event = grants._audit(db, stored.authorized.actor, "rca_run.claim", identifier, _claim_detail(row, lease, when), when)
    row.claim_event_id, row.claim_lease, row.claimed_at = event_id, lease, when
    expected_run = {key: getattr(run, key) for key in storage.RUN_COLUMNS}
    expected_artifact = {key: getattr(row, key) for key in storage.ART_COLUMNS}
    db.flush()
    verified = _postcheck(db, user, identifier, expected_run, expected_artifact, event_id, expected_event)
    return claim_proof(db, verified)


@grants._write
def stage_dispatch(db, user, claim):
    """Current Source is already needed; runtime prechecks delivery before this."""
    claim = RcaClaimProof.model_validate(claim)
    stored = storage.load_task(db, user, claim.run_id, exclusive=True)
    run, row = stored.run, stored.artifact
    if row.dispatch_event_id is not None or row.usage_event_id is not None or run.status != "running":
        return None
    if claim_proof(db, stored) != claim:
        raise HTTPException(409, "本次dispatch不是原claim实际PK与原租约")
    when = grants.utcnow()
    event_id, expected_event = grants._audit(db, stored.authorized.actor, "rca_run.dispatch", run.run_id, _dispatch_detail(row, when), when)
    row.dispatch_event_id, row.dispatched_at = event_id, when
    expected_run = {key: getattr(run, key) for key in storage.RUN_COLUMNS}
    expected_artifact = {key: getattr(row, key) for key in storage.ART_COLUMNS}
    db.flush()
    verified = _postcheck(db, user, run.run_id, expected_run, expected_artifact, event_id, expected_event)
    return dispatch_proof(db, verified)
