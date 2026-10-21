"""Current Super -> Run -> Artifact cancellation, returning only a short ack.

This controlled stop exception never authorizes any Source/Task body. A queued
or undispatched task has known zero usage; an already dispatched call remains
pending until its original delivery settles paid/unknown usage independently.
"""

from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select, update

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_receipts as receipts
from app.ai.models import AIRun
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunResult


class RcaCancelAcknowledgement(c.StrictModel):
    schema_version: Literal["rca_evidence_cancel_ack_v1"]
    run_id: c.OpaqueId
    status: Literal["cancelled"]
    cancel_event_id: i.PositiveId
    usage_event_id: i.PositiveId | None
    receipt_pending: bool
    automatic_legacy_write: Literal[False]


@grants._write
def stage_cancel(db, user, identifier):
    actor = grants.current_actor(db, user, grants.SOURCE_ROLES)
    attempt = receipts.technical_header(db, identifier, exclusive=True)
    header, artifact = attempt.header, attempt.artifact
    if header["status"] not in {"queued", "running"} or artifact["usage_event_id"] is not None:
        raise HTTPException(409, "任务已取消或结束，未重复提交停止请求")
    empty = db.scalar(select((AIRun.result_json == "{}").label("cancel_result_is_empty")).where(AIRun.run_id == identifier))
    present = db.scalar(select(AIRcaEvidenceRunResult.run_id).where(AIRcaEvidenceRunResult.run_id == identifier))
    if empty is not True or present is not None:
        raise HTTPException(409, "未结束任务已出现结果痕迹，不能覆盖或伪称未调用")
    when = grants.utcnow()
    if when < (artifact["dispatched_at"] or artifact["claimed_at"] or artifact["recorded_at"]):
        raise HTTPException(409, "真实取消钟点早于实际阶段，未补造时钟")
    values = {
        "status": "cancelled",
        "error_code": "TASK_CANCELLED",
        "error_message": "已停止接收结果；已经分派的请求仍等待独立实际用量回执。",
        "finish_time": when.replace(microsecond=0),
    }
    db.execute(update(AIRun).where(AIRun.run_id == identifier).values(**values), execution_options={"synchronize_session": False})
    detail = {
        "schema_version": "rca_evidence_cancel_audit_v1",
        "run_id": identifier,
        "requested_by": artifact["requested_by"],
        "cancelled_by": actor.user_id,
        "case_id": artifact["case_id"],
        "claim_event_id": artifact["claim_event_id"],
        "dispatch_event_id": artifact["dispatch_event_id"],
        "lease_token": artifact["claim_lease"],
        "source_hash": artifact["source_hash"],
        "binding_hash": artifact["binding_hash"],
        "previous_state_hash": receipts.terminal_state_hash(header, artifact),
    }
    cancel_id, expected_cancel = grants._audit(db, actor, "rca_run.cancel", identifier, detail, when)
    after = receipts.technical_header(db, identifier, exclusive=True)
    if after.header != {**header, **values} or after.artifact != artifact:
        raise HTTPException(409, "实际取消安全头或Artifact技术锚在写回后改变")
    receipt = None
    if artifact["dispatch_event_id"] is None:
        # The task cannot send HTTP without a committed dispatch. This is the
        # only reason to report known0/0; Source loss is irrelevant to stopping.
        receipt = receipts._write_terminal(
            db,
            after,
            usage=receipts.RcaUsageReceipt(input_tokens=0, output_tokens=0, complete=True, model_call_attempted=False),
            status="cancelled",
            error_code="TASK_CANCELLED",
            latency_ms=0,
        )
    grants.current_actor(db, user, grants.SOURCE_ROLES)
    actual = receipts.technical_header(db, identifier, exclusive=True)
    grants._exact_audit(db, cancel_id, expected_cancel)
    if receipt is not None and receipts.read_receipt(db, actual) != receipt:
        raise HTTPException(409, "取消与已知零用量未原子核对")
    return RcaCancelAcknowledgement(
        schema_version="rca_evidence_cancel_ack_v1",
        run_id=identifier,
        status="cancelled",
        cancel_event_id=cancel_id,
        usage_event_id=actual.artifact["usage_event_id"],
        receipt_pending=artifact["dispatch_event_id"] is not None,
        automatic_legacy_write=False,
    )
