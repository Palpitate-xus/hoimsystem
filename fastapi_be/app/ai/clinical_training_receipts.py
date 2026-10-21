"""Trusted one-delivery terminal accounting without restoring Source authority.

This metadata-only exception cannot dispatch, read private parts or accept
content. Ordinary/public reads must separately authorize the current Source.
"""

from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select

from app.ai import clinical_training_attempts as attempts
from app.ai import clinical_training_contract as c
from app.ai import clinical_training_registry as registry
from app.ai import clinical_training_storage as storage
from app.ai.clinical_training_run_models import AITrainingRunArtifact, AITrainingRunResult
from app.ai.clinical_training_usage_contract import TrainingUsage
from app.ai.models import AIRun

USAGE_ACTION = "training.task.usage"
ErrorCode = Annotated[str, Field(strict=True, min_length=1, max_length=80, pattern=r"^[A-Z][A-Z0-9_]*$")]


class TrainingUsageEvent(c.StrictModel):
    schema_version: Literal["clinical_training_usage_event_v1"]
    run_id: c.Identifier
    submission_id: c.Identifier
    requested_by: c.ActorId
    created_audit_event_id: c.ActorId
    claim_event_id: c.ActorId | None
    dispatch_event_id: c.ActorId | None
    lease_token: c.Identifier | None
    source_projection_hash: c.Digest
    source_binding_hash: c.Digest
    instructions_digest: c.Digest
    usage: TrainingUsage
    status: Literal["succeeded", "failed", "cancelled"]
    error_code: ErrorCode | None
    latency_ms: Annotated[int, Field(strict=True, ge=0, le=2147483647)]
    result_hash: c.Digest | None
    result_reference_hash: c.Digest
    terminal_header_hash: c.Digest
    recorded_at: c.Clock

    @model_validator(mode="after")
    def actual_claim_or_proven_unclaimed_zero(self):
        if (self.claim_event_id is None) != (self.lease_token is None):
            raise ValueError("Actual claim and lease must both exist or both be absent")
        if self.claim_event_id is None and (self.dispatch_event_id is not None or self.status == "succeeded" or self.usage.model_call_attempted is not False):
            raise ValueError("An unclaimed task can only record proven unattempted zero")
        return self


def phase_beginning(attempt):
    if attempt.dispatch is not None:
        return attempts.clock(attempt.dispatch.dispatched_at)
    if attempt.claim is not None:
        return attempts.clock(attempt.claim.claimed_at)
    return attempt.artifact["recorded_at"]


def terminal_hash(header, artifact):
    return c.content_hash(
        {
            "run_header": storage.encoded_header(header),
            "artifact": {
                **storage._identity(artifact),
                "created_audit_event_id": artifact["created_audit_event_id"],
                "claim_event_id": artifact["claim_event_id"],
                "claimed_at": storage._clock(artifact["claimed_at"]),
                "lease_token": artifact["lease_token"],
                "dispatch_event_id": artifact["dispatch_event_id"],
            },
        }
    )


def _no_accepted_result(db, identifier):
    # SQL returns only a boolean and an opaque PK. No result TEXT is selected.
    # Current SHARE reads must not reuse an earlier MySQL RR snapshot.
    with db.no_autoflush:
        empty = db.scalar(select((AIRun.result_json == "{}").label("training_result_is_empty")).where(AIRun.run_id == identifier).with_for_update(read=True))
        found = db.scalar(select(AITrainingRunResult.run_id).where(AITrainingRunResult.run_id == identifier).with_for_update(read=True))
    if empty is not True or found is not None:
        raise HTTPException(409, "失败或取消的培训任务不能保留已接受结果")


def result_reference(header):
    return c.canonical_json(
        {
            "schema_version": "clinical_training_result_ref_v1",
            "run_id": header["run_id"],
            "source_projection_hash": header["source_projection_hash"],
            "instructions_digest": header["instructions_digest"],
            "result_sha256": header["result_hash"],
            "result_bytes": header["result_bytes"],
        }
    )


def acceptance_detail(attempt, header):
    return {
        "schema_version": "clinical_training_result_accepted_v1",
        "run_id": header["run_id"],
        "lease_token": header["lease_token"],
        "created_audit_event_id": attempt.artifact["created_audit_event_id"],
        "claim_event_id": attempt.artifact["claim_event_id"],
        "dispatch_event_id": attempt.artifact["dispatch_event_id"],
        "source_projection_hash": attempt.artifact["source_projection_hash"],
        "source_binding_hash": attempt.artifact["source_binding_hash"],
        "instructions_digest": header["instructions_digest"],
        "result_sha256": header["result_hash"],
        "result_bytes": header["result_bytes"],
        "result_reference_hash": registry.raw_sha(result_reference(header)),
        "accepted_at": registry.references.utc_text(header["accepted_at"]),
    }


def _accepted_header(db, attempt, receipt):
    with db.no_autoflush:
        row = attempts.current_rows(
            db.query(*(getattr(AITrainingRunResult, column.name) for column in AITrainingRunResult.__table__.columns if column.name != "result_json")).filter_by(run_id=receipt.run_id), shared=True
        ).one_or_none()
    if row is None:
        raise HTTPException(409, "成功培训回执缺少实际独立接受结果头")
    header = dict(row._mapping)
    expected = {
        "schema_version": "clinical_training_run_result_v1",
        "lease_token": receipt.lease_token,
        "result_hash": receipt.result_hash,
        "source_projection_hash": receipt.source_projection_hash,
        "instructions_digest": receipt.instructions_digest,
        "accepted_at": attempts.clock(receipt.recorded_at),
    }
    pointer = result_reference(header)
    matches = db.scalar(select((AIRun.result_json == pointer).label("training_result_pointer_matches")).where(AIRun.run_id == receipt.run_id).with_for_update(read=True))
    if (
        any(header[key] != value for key, value in expected.items())
        or receipt.result_hash is None
        or receipt.error_code is not None
        or receipt.usage.model_call_attempted is not True
        or receipt.dispatch_event_id is None
        or matches is not True
        or registry.raw_sha(pointer) != receipt.result_reference_hash
    ):
        raise HTTPException(409, "成功培训回执与原实际接受头、完整pointer或本交付不同")
    registry.verify_event(db, header["accept_audit_event_id"], receipt.requested_by, "training.task.result.accept", receipt.run_id, acceptance_detail(attempt, header), header["accepted_at"])
    return header


def read_receipt(db, attempt):
    """Internal trusted technical reader, after the actual original claim proof."""
    identifier = attempt.artifact["usage_event_id"]
    if identifier is None:
        return None
    try:
        receipt = TrainingUsageEvent.model_validate(attempts._event_body(db, identifier), strict=True)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "实际培训用量审计不是完整闭集回执") from exc
    header, artifact = attempt.header, attempt.artifact
    expected = {
        "run_id": header["run_id"],
        "submission_id": artifact["submission_id"],
        "requested_by": artifact["requested_by"],
        "created_audit_event_id": artifact["created_audit_event_id"],
        "claim_event_id": artifact["claim_event_id"],
        "dispatch_event_id": artifact["dispatch_event_id"],
        "lease_token": header["lease_token"],
        **{key: artifact[key] for key in ("source_projection_hash", "source_binding_hash", "instructions_digest")},
        "status": header["status"],
        "error_code": header["error_code"],
        "latency_ms": header["latency_ms"],
        "terminal_header_hash": terminal_hash(header, artifact),
    }
    if any(getattr(receipt, key) != value for key, value in expected.items()):
        raise HTTPException(409, "培训具体用量回执、原租约或实际终态头不一致")
    when = attempts.clock(receipt.recorded_at)
    if when < phase_beginning(attempt) or header["finish_time"] != when.replace(microsecond=0):
        raise HTTPException(409, "培训实际结束钟与原阶段UTC6不一致")
    if (header["input_tokens"], header["output_tokens"]) != (
        receipt.usage.input_tokens if receipt.usage.input_tokens is not None else 0,
        receipt.usage.output_tokens if receipt.usage.output_tokens is not None else 0,
    ):
        raise HTTPException(409, "旧Run计数与独立nullable回执不一致")
    registry.verify_event(db, identifier, artifact["requested_by"], USAGE_ACTION, header["run_id"], receipt, when)
    if receipt.status != "succeeded":
        if receipt.result_hash is not None or receipt.result_reference_hash != registry.raw_sha("{}"):
            raise HTTPException(409, "失败或取消的回执不能声明接受结果")
        _no_accepted_result(db, header["run_id"])
    else:
        _accepted_header(db, attempt, receipt)
    return receipt


def stage_terminal(db, claim, *, dispatch_event_id, usage, status, error_code, latency_ms):
    """Only this delivery's actual committed dispatch PK may settle its attempt.

    None explicitly means this delivery never reserved a dispatch. If another
    delivery has since reserved one, return None without changing its outcome.
    Unknown interrupted use stays null. A cancelled in-flight owner's actual
    response can still record independently reported paid counts.
    """
    try:
        actual_usage = TrainingUsage.model_validate(usage, strict=True)
        if (
            status not in {"failed", "cancelled"}
            or type(error_code) is not str
            or type(latency_ms) is not int
            or not 0 <= latency_ms <= 2147483647
            or dispatch_event_id is not None
            and (type(dispatch_event_id) is not int or dispatch_event_id < 1)
        ):
            raise ValueError("Explicit failure/cancel, actual latency and delivery dispatch PK required")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "培训技术终态输入无效") from exc
    attempt = attempts.technical_attempt(db, claim, exclusive=True)
    header, artifact = attempt.header, attempt.artifact
    if artifact["dispatch_event_id"] != dispatch_event_id:
        return None
    if artifact["usage_event_id"] is not None or header["status"] not in {"running", "cancelled"}:
        return None
    return _write_terminal(db, attempt, usage=actual_usage, status=status, error_code=error_code, latency_ms=latency_ms)


def _write_terminal(db, attempt, *, usage, status, error_code, latency_ms):
    """Trusted locked actual metadata; callers own rollback and final commit."""
    header, artifact = attempt.header, attempt.artifact
    actual_usage = TrainingUsage.model_validate(usage, strict=True)
    dispatch_event_id = artifact["dispatch_event_id"]
    if dispatch_event_id is None and actual_usage.model_call_attempted is not False:
        raise HTTPException(409, "未实际dispatch的任务只能记录已证明未调用的0/0")
    if actual_usage.model_call_attempted is None and (dispatch_event_id is None or error_code != "WORKER_INTERRUPTED"):
        raise HTTPException(409, "未知调用仅用于原实际发送后丢失的worker交付")
    if header["status"] == "cancelled":
        status = "cancelled"
        error_code = "WORKER_INTERRUPTED" if actual_usage.model_call_attempted is None else "TASK_CANCELLED"
    when = registry.utcnow()
    if when < phase_beginning(attempt):
        raise HTTPException(409, "培训终态钟早于原实际领取或发送")
    _no_accepted_result(db, header["run_id"])
    values = {
        "status": status,
        "error_code": error_code,
        "error_message": "本次培训任务未接受草稿；实际用量依独立回执保留，未知不补零。",
        "input_tokens": actual_usage.input_tokens if actual_usage.input_tokens is not None else 0,
        "output_tokens": actual_usage.output_tokens if actual_usage.output_tokens is not None else 0,
        "latency_ms": latency_ms,
        "finish_time": when.replace(microsecond=0),
    }
    planned = {**header, **values}
    try:
        receipt = TrainingUsageEvent(
            schema_version="clinical_training_usage_event_v1",
            run_id=header["run_id"],
            submission_id=artifact["submission_id"],
            requested_by=artifact["requested_by"],
            created_audit_event_id=artifact["created_audit_event_id"],
            claim_event_id=artifact["claim_event_id"],
            dispatch_event_id=artifact["dispatch_event_id"],
            lease_token=header["lease_token"],
            **{key: artifact[key] for key in ("source_projection_hash", "source_binding_hash", "instructions_digest")},
            usage=actual_usage,
            status=status,
            error_code=error_code,
            latency_ms=latency_ms,
            result_hash=None,
            result_reference_hash=registry.raw_sha("{}"),
            terminal_header_hash=terminal_hash(planned, artifact),
            recorded_at=registry.references.utc_text(when),
        )
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "培训终态回执不能组成明确闭集") from exc
    event_id = registry.audit_event(db, artifact["requested_by"], USAGE_ACTION, header["run_id"], receipt, when)
    changed = db.query(AIRun).filter_by(run_id=header["run_id"], status=header["status"], lease_token=header["lease_token"]).update(values, synchronize_session=False)
    saved = (
        db.query(AITrainingRunArtifact)
        .filter_by(run_id=header["run_id"], claim_event_id=artifact["claim_event_id"], dispatch_event_id=dispatch_event_id, usage_event_id=None)
        .update({"usage_event_id": event_id}, synchronize_session=False)
    )
    if changed != 1 or saved != 1:
        raise HTTPException(409, "培训本交付终态CAS失败")
    checked = attempts.technical_header(db, header["run_id"], exclusive=True)
    if checked.header != planned or checked.artifact != {**artifact, "usage_event_id": event_id} or read_receipt(db, checked) != receipt:
        raise HTTPException(409, "实际培训终态、具体回执或完整技术字段读回变化")
    return receipt


def stage_unclaimed_failure(db, identifier, *, error_code):
    """Trusted queue worker: fail an actual unclaimed run without Source TEXT.

    This cannot settle a claimed/in-flight delivery. No ordinary API exposes
    this operation, and no claim/dispatch or model usage is manufactured.
    """
    attempt = attempts.technical_header(db, identifier, exclusive=True)
    header, artifact = attempt.header, attempt.artifact
    if header["status"] != "queued" or artifact["claim_event_id"] is not None or artifact["usage_event_id"] is not None:
        return None
    original = storage._verify_created(db, artifact, header)["original_run_header"]
    if any(value != original[key] for key, value in storage.encoded_header(header).items()):
        raise HTTPException(409, "未领取培训任务已有非原始技术状态，不能补造未调用回执")
    return _write_terminal(db, attempt, usage=TrainingUsage(input_tokens=0, output_tokens=0, complete=True, model_call_attempted=False), status="failed", error_code=error_code, latency_ms=0)
