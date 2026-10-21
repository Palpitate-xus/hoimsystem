"""Current ordinary Source authority or explicit Super body-free stop.

Stopping a task does not restore its data permissions. Only the original
committed delivery can settle a pending paid call. Source-free Super handling
returns one short cancellation ack and never waits on Source after Run X.
"""

from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from app.ai import research_variables_attempts as attempts
from app.ai import research_variables_receipts as receipts
from app.ai import research_variables_storage as storage
from app.ai import research_variables_task_reader as reader
from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_sources import utcnow
from app.ai.research_cohort_write_guard import current_actor, current_research_rows, lock_research_write
from app.ai.research_variables_fields import VARIABLE_SOURCE_ROLES
from app.ai.research_variables_run_models import AIResearchVariableRunResult
from app.ai.research_variables_storage_contract import VariableUsageReceipt
from app.ai.research_variables_task_contract import canonical, digest


def cancel_variable_run(db, user, identifier):
    try:
        actor = lock_research_write(db, user, allowed_roles=VARIABLE_SOURCE_ROLES)
        technical_super = actor.user_role == "super_admin"
        if not technical_super:
            # This normal path obtains all original project/patient purposes
            # before the first Run X/BODY. Retain these locks until commit.
            reader.load_task(db, actor, identifier, exclusive=True)
        identity = reader.locate_artifact(db, identifier)
        if identity is None:
            raise HTTPException(409, "停止请求缺少实际变量Artifact，不降级通用取消")
        header, artifact = reader._headers(db, identity, exclusive=True)
        reader._creation_audit(db, header, artifact)
        if header["status"] not in {"queued", "running"} or artifact["usage_event_id"] is not None:
            raise HTTPException(409, "任务已停止或结束，未重复取消")
        if not technical_super and actor.user_id != artifact["requested_by"]:
            raise HTTPException(403, "普通来源权限不能取消他人的任务")
        task = SimpleNamespace(run=SimpleNamespace(**header), artifact=SimpleNamespace(**artifact))
        if artifact["claim_event_id"] is None:
            if header["status"] != "queued" or header["lease_token"] is not None or header["start_time"] is not None:
                raise HTTPException(409, "未领取任务不能持执行状态或lease")
            claim = None
        else:
            if header["status"] != "running":
                raise HTTPException(409, "实际领取与排队状态矛盾")
            claim = attempts.verify_claim(db, task)
            if artifact["dispatch_event_id"] is not None:
                attempts.verify_delivery(db, task)
        empty = db.execute(select(AIRun.result_json == "{}").where(AIRun.run_id == identifier)).scalar()
        accepted = current_research_rows(db.query(AIResearchVariableRunResult.run_id).filter_by(run_id=identifier), shared=True).one_or_none()
        if empty is not True or accepted is not None:
            raise HTTPException(409, "未结束任务已有结果痕迹，不能覆盖或伪称未调用")
        clock = utcnow()
        if clock < (artifact["dispatched_at"] or artifact["claimed_at"] or artifact["recorded_at"]):
            raise HTTPException(409, "实际取消时钟早于原阶段，未伪造时钟")
        values = {"status": "cancelled", "finish_time": clock.replace(microsecond=0), "error_code": "TASK_CANCELLED", "error_message": "已停止接收完整结果；已分派调用仍等待原交付结算实际用量。"}
        db.query(AIRun).filter_by(run_id=identifier).update(values, synchronize_session=False)
        detail = {
            "schema_version": "research_variable_cancel_event_v1",
            "run_id": identifier,
            "cancelled_by": actor.user_id,
            "technical_super_stop": technical_super,
            "previous_state_hash": digest({key: storage._clock(value) for key, value in header.items()}),
            "create_event_id": artifact["create_event_id"],
            "claim_event_id": artifact["claim_event_id"],
            "dispatch_event_id": artifact["dispatch_event_id"],
            "source_hash": artifact["source_hash"],
            "binding_hash": artifact["binding_hash"],
        }
        event = AIAuditEvent(actor_id=actor.user_id, action="research_variable_run.cancel", target=identifier, detail_json=canonical(detail), create_time=clock.replace(microsecond=0))
        db.add(event)
        db.flush()
        expected_event = {str(column.name): getattr(event, str(column.name)) for column in AIAuditEvent.__table__.columns}
        after_header, after_artifact = reader._headers(db, identity, exclusive=True)
        if after_header != {**header, **values} or after_artifact != artifact:
            raise HTTPException(409, "取消实际Run头或不可变技术锚在写回后改变")
        if artifact["dispatch_event_id"] is None:
            if claim is None:
                receipts.stage_queued_terminal(
                    db, identifier, expected_create_event_id=artifact["create_event_id"], status="cancelled", error_code="TASK_CANCELLED", error_message=values["error_message"]
                )
            else:
                receipts.stage_terminal(
                    db,
                    claim,
                    delivery=None,
                    receipt=VariableUsageReceipt(input_tokens=0, output_tokens=0, complete=True, model_call_attempted=False),
                    status="cancelled",
                    error_code="TASK_CANCELLED",
                    error_message=values["error_message"],
                    latency_ms=0,
                )
        # The Source-free technical exception must never reacquire Scope/Source
        # under Run X. Current actor/epoch and exact audit/header reads suffice.
        current_actor(db, actor, allowed_roles={"super_admin"} if technical_super else VARIABLE_SOURCE_ROLES)
        if not technical_super:
            reader.load_task(db, actor, identifier, exclusive=True)
        actual_event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=event.event_id), shared=True).one_or_none()
        if actual_event is None or {str(column.name): getattr(actual_event, str(column.name)) for column in AIAuditEvent.__table__.columns} != expected_event:
            raise HTTPException(409, "取消具体审计PK或实际签署已变化")
        actual_header, actual_artifact = reader._headers(db, identity, exclusive=True)
        reader._creation_audit(db, actual_header, actual_artifact)
        if actual_header["status"] != "cancelled" or any(actual_artifact[key] != value for key, value in artifact.items() if key != "usage_event_id"):
            raise HTTPException(409, "实际取消状态或原领取分派已变化")
        if artifact["dispatch_event_id"] is None:
            stopped = SimpleNamespace(run=SimpleNamespace(**actual_header), artifact=SimpleNamespace(**actual_artifact))
            record = receipts.verify_receipt(db, stopped)
            if record.receipt.model_call_attempted is not False:
                raise HTTPException(409, "未分派取消的实际未调用回执不一致")
        elif actual_artifact["usage_event_id"] is not None:
            raise HTTPException(409, "已分派调用不能由取消请求伪造计量终态")
        result = {
            "schema_version": "research_variable_cancel_ack_v1",
            "run_id": identifier,
            "status": "cancelled",
            "cancel_event_id": event.event_id,
            "usage_event_id": actual_artifact["usage_event_id"],
            "receipt_pending": artifact["dispatch_event_id"] is not None,
            "automatic_clinical_write": False,
            "automatic_export": False,
        }
        canonical(result)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
