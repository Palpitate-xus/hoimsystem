"""Current Super may stop execution without acquiring any document authority.

An actual committed dispatch stays pending for its original delivery's paid
receipt. A genuinely unclaimed task remains unclaimed, with proven zero use.
The caller owns one atomic commit or rollback of the entire operation.
"""

from typing import Literal

from fastapi import HTTPException

from app.ai import operations_support_attempts as attempts
from app.ai import operations_support_contract as c
from app.ai import operations_support_receipts as receipts
from app.ai import operations_support_registry as registry
from app.ai import operations_support_storage as storage
from app.ai.models import AIRun
from app.ai.operations_support_usage_contract import OperationsUsage
from app.ai.operations_support_write_guard import current_actor, lock_operations_write

CANCEL_ACTION = "operations.task.cancel"


class OperationsCancelAcknowledgement(c.StrictModel):
    schema_version: Literal["operations_support_cancel_ack_v1"]
    run_id: c.Identifier
    status: Literal["cancelled"]
    cancel_event_id: c.ActorId
    usage_event_id: c.ActorId | None
    receipt_pending: bool
    automatic_legacy_write: Literal[False]


def stage_cancel(db, user, identifier):
    actor = lock_operations_write(db, user, governance=True)
    actor_id, actor_epoch = actor.user_id, actor.token_invalid_before
    attempt = attempts.technical_header(db, identifier, exclusive=True)
    header, artifact = attempt.header, attempt.artifact
    if header["status"] not in {"queued", "running"} or artifact["usage_event_id"] is not None:
        raise HTTPException(409, "运维任务已停止或结束，未重复提交取消")
    if any(header[key] is not None for key in ("finish_time", "latency_ms", "error_code", "error_message")) or header["input_tokens"] != 0 or header["output_tokens"] != 0:
        raise HTTPException(409, "未结束运维任务已有终态痕迹，不能覆盖既有用量")
    if header["status"] == "queued":
        original = storage._verify_created(db, artifact, header)["original_run_header"]
        if attempt.claim is not None or any(value != original[key] for key, value in storage.encoded_header(header).items()):
            raise HTTPException(409, "排队运维任务与原始完整技术状态不一致")
    receipts._no_accepted_result(db, identifier)
    when = registry.utcnow()
    if when < receipts.phase_beginning(attempt):
        raise HTTPException(409, "取消钟早于原实际运维阶段，未补造时钟")
    values = {
        "status": "cancelled",
        "error_code": "TASK_CANCELLED",
        "error_message": "已停止接收运维草稿；已发送请求等待原交付的独立实际用量。",
        "finish_time": when.replace(microsecond=0),
    }
    planned = {**header, **values}
    changed = db.query(AIRun).filter_by(run_id=identifier, status=header["status"], lease_token=header["lease_token"]).update(values, synchronize_session=False)
    if changed != 1:
        raise HTTPException(409, "运维取消原状态CAS失败")
    detail = {
        "schema_version": "operations_support_cancel_audit_v1",
        "run_id": identifier,
        "case_id": artifact["case_id"],
        "requested_by": artifact["requested_by"],
        "cancelled_by": actor_id,
        "cancel_actor_token_invalid_before": None if actor_epoch is None else registry.utc_text(actor_epoch),
        "created_audit_event_id": artifact["created_audit_event_id"],
        "claim_event_id": artifact["claim_event_id"],
        "dispatch_event_id": artifact["dispatch_event_id"],
        "lease_token": header["lease_token"],
        "previous_header_hash": receipts.terminal_hash(header, artifact),
        "cancelled_header_hash": receipts.terminal_hash(planned, artifact),
        "cancelled_at": registry.utc_text(when),
    }
    event_id = registry.audit_event(db, actor_id, CANCEL_ACTION, identifier, detail, when)
    checked = attempts.technical_header(db, identifier, exclusive=True)
    if checked.header != planned or checked.artifact != artifact:
        raise HTTPException(409, "运维取消后实际Run或Artifact安全技术头变化")
    receipt = None
    if artifact["dispatch_event_id"] is None:
        receipt = receipts._write_terminal(
            db,
            checked,
            usage=OperationsUsage(input_tokens=0, output_tokens=0, complete=True, model_call_attempted=False),
            status="cancelled",
            error_code="TASK_CANCELLED",
            latency_ms=0,
        )
    current = current_actor(db, user, allowed_roles={"super_admin"})
    if current.user_id != actor_id or current.token_invalid_before != actor_epoch:
        raise HTTPException(403, "本次运维取消管理员的登录授权已变化")
    actual = attempts.technical_header(db, identifier, exclusive=True)
    registry.verify_event(db, event_id, actor_id, CANCEL_ACTION, identifier, detail, when)
    if receipt is not None and receipts.read_receipt(db, actual) != receipt:
        raise HTTPException(409, "运维取消及实际未调用零回执未原子读回")
    if receipt is None and (actual.header != planned or actual.artifact != artifact):
        raise HTTPException(409, "在途运维取消后实际技术字段改变")
    return OperationsCancelAcknowledgement(
        schema_version="operations_support_cancel_ack_v1",
        run_id=identifier,
        status="cancelled",
        cancel_event_id=event_id,
        usage_event_id=actual.artifact["usage_event_id"],
        receipt_pending=artifact["dispatch_event_id"] is not None,
        automatic_legacy_write=False,
    )
