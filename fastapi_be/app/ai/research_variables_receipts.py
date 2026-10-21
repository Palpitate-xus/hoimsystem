"""Exact76 usage PKs and trusted body-free terminal settlement.

The technical terminal path is an internal worker capability, never a public
Source/read authorization. It reads no Source or Task TEXT and cannot return
any original/draft. Only the original concrete claim and committed dispatch
may settle; an observed pre-dispatch None cannot seize another delivery.
"""

import datetime as dt
from types import SimpleNamespace
from typing import Literal

from fastapi import HTTPException

from app.ai import research_variables_attempts as attempts
from app.ai import research_variables_storage as storage
from app.ai import research_variables_task_reader as reader
from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_contract import SHA, UTC, UUID, Positive, StrictModel
from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_cohort_write_guard import current_research_rows, lock_research_gate
from app.ai.research_variables_run_models import AIResearchVariableRunArtifact, AIResearchVariableRunResult
from app.ai.research_variables_storage_contract import VariableUsageReceipt
from app.ai.research_variables_task_contract import MAX_RUN_TEXT_BYTES, canonical, digest


class VariableReceiptRecord(StrictModel):
    schema_version: Literal["research_variable_usage_event_v1"]
    run_id: UUID
    batch_id: UUID
    requested_by: Positive
    create_event_id: Positive
    claim_event_id: Positive | None
    dispatch_event_id: Positive | None
    claim_lease: UUID | None
    usage_event_id: Positive
    accept_audit_event_id: Positive | None
    source_hash: SHA
    instructions_digest: SHA
    settled_at: UTC
    receipt: VariableUsageReceipt
    final_state_hash: SHA


def state_hash(run):
    return digest({key: storage._clock(getattr(run, key)) for key in storage.RUN_HEADER}, MAX_RUN_TEXT_BYTES)


def usage_record(task, receipt, event_id, clock, accept_event_id=None):
    row = task.artifact
    return VariableReceiptRecord(
        schema_version="research_variable_usage_event_v1",
        run_id=row.run_id,
        batch_id=row.batch_id,
        requested_by=row.requested_by,
        create_event_id=row.create_event_id,
        claim_event_id=row.claim_event_id,
        dispatch_event_id=row.dispatch_event_id,
        claim_lease=row.claim_lease,
        usage_event_id=event_id,
        accept_audit_event_id=accept_event_id,
        source_hash=row.source_hash,
        instructions_digest=row.instructions_digest,
        settled_at=utc_text(clock),
        receipt=receipt,
        final_state_hash=state_hash(task.run),
    )


def verify_receipt(db, task, *, expected=None, accept_event_id=None):
    identifier = task.artifact.usage_event_id
    if type(identifier) is not int:
        raise HTTPException(409, "任务尚无实际用量回执PK；不能以Run物理0冒充已知用量")
    size = current_research_rows(db.query(reader._bytes(db, AIAuditEvent.detail_json)).filter_by(event_id=identifier), shared=True).scalar()
    if type(size) is not int or not 0 < size <= MAX_RUN_TEXT_BYTES:
        raise HTTPException(409, "具体用量回执PK缺失或整件容量异常")
    row = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one_or_none()
    try:
        record = VariableReceiptRecord.model_validate(storage.canonical_value(row.detail_json))
        clock = dt.datetime.strptime(record.settled_at, "%Y-%m-%dT%H:%M:%S.%fZ")
        original = usage_record(task, record.receipt, identifier, clock, accept_event_id)
        if record != original or expected is not None and record.receipt != expected:
            raise ValueError("The actual original claim/dispatch/usage IDs or final Run state differ")
        if (row.actor_id, row.action, row.target, row.create_time) != (task.artifact.requested_by, "research_variable_run.usage", task.artifact.run_id, clock.replace(microsecond=0)):
            raise ValueError("The exact usage Audit actor/action/target/storage clock differ")
        return record
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "本次具体用量回执、原分派或真实未知计数无法核对") from exc


def stage_receipt(db, task, receipt, clock, *, accept_event_id=None):
    """Internal mutation after a proved authentic claim/delivery; no commit."""
    receipt = VariableUsageReceipt.model_validate(receipt)
    if task.artifact.usage_event_id is not None:
        raise HTTPException(409, "实际原分派已结算，未覆盖既有回执")
    event = AIAuditEvent(actor_id=task.artifact.requested_by, action="research_variable_run.usage", target=task.artifact.run_id, detail_json="{}", create_time=clock.replace(microsecond=0))
    db.add(event)
    db.flush()
    task.artifact.usage_event_id = event.event_id
    # Legacy physical nonnullable integers are not receipt authority. Every
    # public/administrative count must use the independently nullable receipt.
    task.run.input_tokens = receipt.input_tokens if receipt.input_tokens is not None else 0
    task.run.output_tokens = receipt.output_tokens if receipt.output_tokens is not None else 0
    event.detail_json = canonical(usage_record(task, receipt, event.event_id, clock, accept_event_id), MAX_RUN_TEXT_BYTES)
    return event


def technical_task(db, claim):
    """Source-loss/paid exception: exact headers/audits only, no data grant."""
    if not isinstance(claim, attempts.VariableClaim):
        raise HTTPException(422, "终态须持可信工作线程本次实际领取对象")
    lock_research_gate(db)
    identity = reader.locate_artifact(db, claim.run_id)
    if identity is None or identity != (claim.run_id, claim.batch_id, claim.requested_by):
        return None
    header, artifact = reader._headers(db, identity, exclusive=True)
    reader._creation_audit(db, header, artifact)
    task = SimpleNamespace(run=SimpleNamespace(**header), artifact=SimpleNamespace(**artifact))
    if artifact["claim_event_id"] != claim.claim_event_id or artifact["claim_lease"] != claim.lease or header["lease_token"] != claim.lease:
        return None
    attempts.verify_claim(db, task, claim)
    return task


def stage_terminal(db, claim, *, delivery, receipt, status, error_code, error_message, latency_ms):
    """Settle only this actual delivery; no Task text or Source reauthorization.

    A caller that never committed a dispatch must pass delivery=None. It can
    only settle when the actual current dispatch PK is still None. If another
    worker already dispatched, this call is inert even when Source was lost.
    """
    try:
        receipt = VariableUsageReceipt.model_validate(receipt)
        if status not in {"failed", "cancelled"} or type(latency_ms) is not int or not 0 <= latency_ms <= 2147483647:
            raise HTTPException(422, "技术终态和实际耗时须明确有界，不能形成成功正文")
        if type(error_code) is not str or not error_code or len(error_code) > 64 or type(error_message) is not str or len(error_message) > 1000:
            raise HTTPException(422, "完整技术错误说明超限，未截断")
        if receipt.model_call_attempted is None and error_code != "WORKER_INTERRUPTED":
            raise HTTPException(422, "仅明确工作线程中断可保留调用是否发生也未知")
        task = technical_task(db, claim)
        if task is None or task.artifact.usage_event_id is not None or task.run.status == "succeeded":
            return None
        if delivery is None:
            if task.artifact.dispatch_event_id is not None:
                return None
            if receipt.model_call_attempted is not False:
                raise HTTPException(409, "未真实分派的本次领取只能报告确定未调用0/0")
        else:
            attempts.verify_delivery(db, task, delivery)
        if current_research_rows(db.query(AIResearchVariableRunResult.run_id).filter_by(run_id=claim.run_id), shared=True).one_or_none() is not None:
            raise HTTPException(409, "存在完整接受件却缺结算锚，未覆盖或重结算")
        clock = utcnow()
        if clock < dt.datetime.strptime(claim.claimed_at, "%Y-%m-%dT%H:%M:%S.%fZ"):
            raise HTTPException(409, "实际结算时钟早于领取")
        # These are UPDATEs, not a full-row ORM SELECT after Source loss.
        final_status = "cancelled" if task.run.status == "cancelled" else status
        # Exact original cancellation remains cancellation after paid settlement.
        db.query(AIRun).filter_by(run_id=claim.run_id).update(
            {"status": final_status, "result_json": "{}", "finish_time": clock.replace(microsecond=0), "error_code": error_code, "error_message": error_message, "latency_ms": latency_ms},
            synchronize_session=False,
        )
        header, artifact = reader._headers(db, (claim.run_id, claim.batch_id, claim.requested_by), exclusive=True)
        task = SimpleNamespace(run=SimpleNamespace(**header), artifact=SimpleNamespace(**artifact))
        # stage_receipt needs real mutable rows, but this exception never loads
        # them wholesale: write all receipt fields by explicit column updates.
        event = AIAuditEvent(actor_id=claim.requested_by, action="research_variable_run.usage", target=claim.run_id, detail_json="{}", create_time=clock.replace(microsecond=0))
        db.add(event)
        db.flush()
        db.query(AIResearchVariableRunArtifact).filter_by(run_id=claim.run_id).update({"usage_event_id": event.event_id}, synchronize_session=False)
        db.query(AIRun).filter_by(run_id=claim.run_id).update(
            {"input_tokens": receipt.input_tokens if receipt.input_tokens is not None else 0, "output_tokens": receipt.output_tokens if receipt.output_tokens is not None else 0},
            synchronize_session=False,
        )
        header, artifact = reader._headers(db, (claim.run_id, claim.batch_id, claim.requested_by), exclusive=True)
        task = SimpleNamespace(run=SimpleNamespace(**header), artifact=SimpleNamespace(**artifact))
        event.detail_json = canonical(usage_record(task, receipt, event.event_id, clock), MAX_RUN_TEXT_BYTES)
        db.flush()
        # Re-read every technical original and exact PK after SQL triggers.
        actual = technical_task(db, claim)
        if (
            actual is None
            or actual.run.status != final_status
            or actual.run.finish_time != clock.replace(microsecond=0)
            or actual.run.error_code != error_code
            or actual.run.error_message != error_message
            or actual.run.latency_ms != latency_ms
        ):
            raise HTTPException(409, "终态实际Run头或原领取已变化，整事务回滚")
        if delivery is not None:
            attempts.verify_delivery(db, actual, delivery)
        return verify_receipt(db, actual, expected=receipt)
    except Exception:
        db.rollback()
        raise


def stage_queued_terminal(db, identifier, *, expected_create_event_id, status, error_code, error_message):
    """Internal known-uncalled stop: no invented claim, dispatch or data grant.

    Public cancellation must obtain its separate current caller authorization
    before invoking this helper. A trusted worker may use it after failed
    Source/config proof, with the original concrete creation PK. An intervening
    real claim makes this observation inert rather than stealing its delivery.
    """
    try:
        if type(expected_create_event_id) is not int or expected_create_event_id <= 0 or status not in {"failed", "cancelled"}:
            raise HTTPException(422, "未领取终态须有实际创建PK和明确终态")
        if type(error_code) is not str or not error_code or len(error_code) > 64 or type(error_message) is not str or len(error_message) > 1000:
            raise HTTPException(422, "完整未领取终态说明超限，未截断")
        lock_research_gate(db)
        identity = reader.locate_artifact(db, identifier)
        if identity is None:
            return None
        header, artifact = reader._headers(db, identity, exclusive=True)
        reader._creation_audit(db, header, artifact)
        if artifact["create_event_id"] != expected_create_event_id:
            raise HTTPException(409, "未领取观察不属于原任务具体创建PK")
        if any(artifact[key] is not None for key in ("claim_event_id", "claim_lease", "claimed_at", "dispatch_event_id", "dispatched_at", "usage_event_id")) or header["status"] not in {
            "queued",
            "cancelled",
        }:
            return None
        if header["lease_token"] is not None or header["start_time"] is not None:
            raise HTTPException(409, "原任务无领取锚却持lease或开始时钟，未伪造未调用")
        if current_research_rows(db.query(AIResearchVariableRunResult.run_id).filter_by(run_id=identifier), shared=True).one_or_none() is not None:
            raise HTTPException(409, "未领取状态与完整接受件矛盾")
        clock = utcnow()
        if clock < artifact["recorded_at"]:
            raise HTTPException(409, "未领取停止时钟早于实际登记")
        final_status = "cancelled" if header["status"] == "cancelled" else status
        db.query(AIRun).filter_by(run_id=identifier).update(
            {
                "status": final_status,
                "result_json": "{}",
                "finish_time": clock.replace(microsecond=0),
                "error_code": error_code,
                "error_message": error_message,
                "latency_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            },
            synchronize_session=False,
        )
        event = AIAuditEvent(actor_id=identity[2], action="research_variable_run.usage", target=identifier, detail_json="{}", create_time=clock.replace(microsecond=0))
        db.add(event)
        db.flush()
        db.query(AIResearchVariableRunArtifact).filter_by(run_id=identifier).update({"usage_event_id": event.event_id}, synchronize_session=False)
        header, artifact = reader._headers(db, identity, exclusive=True)
        task = SimpleNamespace(run=SimpleNamespace(**header), artifact=SimpleNamespace(**artifact))
        uncalled = VariableUsageReceipt(input_tokens=0, output_tokens=0, complete=True, model_call_attempted=False)
        event.detail_json = canonical(usage_record(task, uncalled, event.event_id, clock), MAX_RUN_TEXT_BYTES)
        db.flush()
        actual_header, actual_artifact = reader._headers(db, identity, exclusive=True)
        reader._creation_audit(db, actual_header, actual_artifact)
        if (
            any(actual_artifact[key] is not None for key in ("claim_event_id", "claim_lease", "claimed_at", "dispatch_event_id", "dispatched_at"))
            or actual_artifact["usage_event_id"] != event.event_id
        ):
            raise HTTPException(409, "未领取结算后实际phase发生变化，整事务回滚")
        expected = {
            "status": final_status,
            "finish_time": clock.replace(microsecond=0),
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "lease_token": None,
            "start_time": None,
        }
        if any(actual_header[key] != value for key, value in expected.items()):
            raise HTTPException(409, "未领取结算后实际原任务头不同，整事务回滚")
        return verify_receipt(db, SimpleNamespace(run=SimpleNamespace(**actual_header), artifact=SimpleNamespace(**actual_artifact)), expected=uncalled)
    except Exception:
        db.rollback()
        raise
