"""Atomic76 accepted result, short reference and independently nullable usage.

A full valid literal result can succeed with unknown input/output token counts.
Successful acceptance never replaces clinical records or creates a matrix/CSV.
The caller owns its lease transaction/commit; paid rejection is settled by the
original delivery's separate body-free terminal helper, including acceptedNone.
"""

from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field

from app.ai import research_variables_attempts as attempts
from app.ai import research_variables_receipts as receipts
from app.ai import research_variables_storage as storage
from app.ai import research_variables_task_reader as reader
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_contract import SHA, UTC, UUID, Positive, StrictModel
from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_cohort_write_guard import current_research_rows
from app.ai.research_variables_run_models import RESULT_SCHEMA, AIResearchVariableRunResult
from app.ai.research_variables_storage_contract import VariableUsageReceipt
from app.ai.research_variables_task_binding import binding_reference
from app.ai.research_variables_task_contract import MAX_RUN_TEXT_BYTES, MAX_WIRE_BYTES, canonical
from app.ai.research_variables_task_result import validate_result

RESULT_META = tuple(str(column.name) for column in AIResearchVariableRunResult.__table__.columns if column.name != "result_json")


class VariableResultReference(StrictModel):
    schema_version: Literal["research_variable_result_ref_v1"]
    run_id: UUID
    source_hash: SHA
    instructions_digest: SHA
    accepted_lease: UUID
    accepted_at: UTC
    result_hash: SHA
    result_bytes: Annotated[int, Field(strict=True, ge=1, le=MAX_WIRE_BYTES)]
    accept_audit_event_id: Positive


def reference_for_row(row):
    def get(key):
        return row[key] if type(row) is dict else getattr(row, key)

    return VariableResultReference(
        schema_version="research_variable_result_ref_v1", **{key: utc_text(get(key)) if key == "accepted_at" else get(key) for key in VariableResultReference.model_fields if key != "schema_version"}
    )


def _accept_detail(task, reference):
    return {
        "schema_version": "research_variable_accept_event_v1",
        "reference": reference.model_dump(mode="json"),
        "create_event_id": task.artifact.create_event_id,
        "claim_event_id": task.artifact.claim_event_id,
        "dispatch_event_id": task.artifact.dispatch_event_id,
        "usage_event_id": task.artifact.usage_event_id,
        "final_state_hash": receipts.state_hash(task.run),
    }


def _metadata(db, task):
    columns = [getattr(AIResearchVariableRunResult, key) for key in RESULT_META]
    columns.append(reader._bytes(db, AIResearchVariableRunResult.result_json).label("actual_result_bytes"))
    row = current_research_rows(db.query(*columns).filter_by(run_id=task.run.run_id), shared=True).one_or_none()
    if row is None:
        raise HTTPException(409, "成功原生任务缺少独立完整结果件")
    result = dict(row._mapping)
    if type(result["result_bytes"]) is not int or not 0 < result["result_bytes"] <= MAX_WIRE_BYTES or result["actual_result_bytes"] != result["result_bytes"]:
        raise HTTPException(413, "实际完整结果字节锚不同或超限；未读取结果正文")
    if result["schema_version"] != RESULT_SCHEMA or (result["source_hash"], result["instructions_digest"], result["accepted_lease"]) != (
        task.artifact.source_hash,
        task.artifact.instructions_digest,
        task.artifact.claim_lease,
    ):
        raise HTTPException(409, "实际结果与原完整Source、Prompt或领取lease不同")
    return result


def _accept_audit(db, task, metadata, reference):
    identifier = metadata["accept_audit_event_id"]
    size = current_research_rows(db.query(reader._bytes(db, AIAuditEvent.detail_json)).filter_by(event_id=identifier), shared=True).scalar()
    if type(size) is not int or not 0 < size <= MAX_RUN_TEXT_BYTES:
        raise HTTPException(409, "具体完整接受Audit PK缺失或容量异常")
    row = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one()
    if (row.actor_id, row.action, row.target, row.create_time, row.detail_json) != (
        task.artifact.requested_by,
        "research_variable_run.accept",
        task.run.run_id,
        metadata["accepted_at"].replace(microsecond=0),
        canonical(_accept_detail(task, reference), MAX_RUN_TEXT_BYTES),
    ):
        raise HTTPException(409, "具体接受Audit PK、全量Result引用、原领取/分派或实际状态不同")
    if identifier in {task.artifact.create_event_id, task.artifact.claim_event_id, task.artifact.dispatch_event_id, task.artifact.usage_event_id}:
        raise HTTPException(409, "完整接受与创建、领取、分派、计量回执须为五个实际不同PK")


def result_from_task(db, task):
    """Task already carries current ordinary or explicit authorized audit proof."""
    if task.run.status != "succeeded":
        if current_research_rows(db.query(AIResearchVariableRunResult.run_id).filter_by(run_id=task.run.run_id), shared=True).one_or_none() is not None:
            raise HTTPException(409, "非成功状态却持完整接受件，未作为通用结果显示")
        return None
    try:
        reference = VariableResultReference.model_validate(storage.canonical_value(task.run.result_json))
        metadata = _metadata(db, task)
        if reference != reference_for_row(metadata):
            raise ValueError("The short canonical pointer differs from actual result metadata")
        attempts.verify_delivery(db, task)
        receipt = receipts.verify_receipt(db, task, accept_event_id=reference.accept_audit_event_id)
        _accept_audit(db, task, metadata, reference)
        row = current_research_rows(db.query(AIResearchVariableRunResult).filter_by(run_id=task.run.run_id), shared=True).one()
        if storage.text_hash(row.result_json, MAX_WIRE_BYTES) != reference.result_hash:
            raise ValueError("The complete accepted original result bytes differ")
        accepted = validate_result(storage.canonical_value(row.result_json, MAX_WIRE_BYTES), task.source, task.artifact.instructions_digest)
        part = {
            "schema_version": "research_variable_result_part_v1",
            "binding": binding_reference(task.binding),
            "reference": reference.model_dump(mode="json"),
            "result": accepted.model_dump(mode="json"),
            "usage_receipt": receipt.receipt.model_dump(mode="json"),
        }
        canonical(part)
        return part
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "实际短结果引用、独立完整结果、逐字候选或用量无法核对，未降级或截断") from exc


def result_piece(db, user, identifier, *, frozen_audit=False):
    return result_from_task(db, reader.load_task(db, user, identifier, frozen_audit=frozen_audit))


def stage_result(db, user, delivery, value, receipt, *, latency_ms):
    """Caller must settle this delivery even when acceptance returnsNone."""
    try:
        if not isinstance(delivery, attempts.VariableDelivery):
            raise HTTPException(422, "完整接受须持本次真实已提交分派对象")
        receipt = VariableUsageReceipt.model_validate(receipt)
        if receipt.model_call_attempted is not True or type(latency_ms) is not int or not 0 <= latency_ms <= 2147483647:
            raise HTTPException(422, "收到有效完整回复仅证明调用已发生；未知计数保留null")
        task = reader.load_task(db, user, delivery.claim.run_id, exclusive=True, for_execution=True)
        attempts.verify_delivery(db, task, delivery)
        if task.artifact.usage_event_id is not None or task.run.status != "running":
            return None
        accepted = validate_result(value, task.source, task.artifact.instructions_digest)
        raw = canonical(accepted)
        clock = utcnow()
        if clock < task.artifact.dispatched_at:
            raise HTTPException(409, "实际完整接受时钟早于原分派")
        event = AIAuditEvent(actor_id=task.artifact.requested_by, action="research_variable_run.accept", target=task.run.run_id, detail_json="{}", create_time=clock.replace(microsecond=0))
        db.add(event)
        db.flush()
        row = AIResearchVariableRunResult(
            run_id=task.run.run_id,
            schema_version=RESULT_SCHEMA,
            source_hash=task.artifact.source_hash,
            instructions_digest=task.artifact.instructions_digest,
            accepted_lease=delivery.claim.lease,
            accepted_at=clock,
            result_json=raw,
            result_hash=storage.text_hash(raw, MAX_WIRE_BYTES),
            result_bytes=len(raw.encode("utf-8")),
            accept_audit_event_id=event.event_id,
        )
        reference = reference_for_row(row)
        # Count the FULL required response wrapper before storing a succeeded
        # task that cannot subsequently return its whole accepted proof.
        canonical(
            {
                "schema_version": "research_variable_result_part_v1",
                "binding": binding_reference(task.binding),
                "reference": reference.model_dump(mode="json"),
                "result": accepted.model_dump(mode="json"),
                "usage_receipt": receipt.model_dump(mode="json"),
            }
        )
        db.add(row)
        task.run.status, task.run.finish_time, task.run.latency_ms = "succeeded", clock.replace(microsecond=0), latency_ms
        task.run.error_code = task.run.error_message = None
        task.run.result_json = canonical(reference, MAX_RUN_TEXT_BYTES)
        receipts.stage_receipt(db, task, receipt, clock, accept_event_id=event.event_id)
        event.detail_json = canonical(_accept_detail(task, reference), MAX_RUN_TEXT_BYTES)
        db.flush()
        # Reacquire the entire current Source/config BEFORE postflush Task or
        # Result TEXT; failed authority rolls back blob/pointer/status/audits.
        actual = reader.load_task(db, task.authority.actor, task.run.run_id, exclusive=True, for_execution=True)
        if actual.run.status != "succeeded" or actual.run.finish_time != clock.replace(microsecond=0) or actual.run.latency_ms != latency_ms:
            raise HTTPException(409, "接受后实际成功状态或原时钟改变，整事务回滚")
        attempts.verify_delivery(db, actual, delivery)
        part = result_from_task(db, actual)
        if part is None or part["result"] != accepted.model_dump(mode="json") or part["usage_receipt"] != receipt.model_dump(mode="json"):
            raise HTTPException(409, "接受后实际完整结果或原用量不同，整事务回滚")
        return reference
    except Exception:
        db.rollback()
        raise
