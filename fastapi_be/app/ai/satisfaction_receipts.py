"""Separate exact-PK usage receipts; full-result acceptance keeps its own audit.

The caller owns current authorization and the Run lock. No helper commits or
calls a model. Nullable actual usage does not inherit legacy Run integer zeroes.
"""

from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from app.ai.models import AIAuditEvent, AIRun
from app.ai.native_acceptance import AUDIT_FIELDS, RUN_FIELDS
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_contract import SHA, UUID, StrictModel
from app.ai.satisfaction_draft import canonical_json, source_hash
from app.ai.satisfaction_storage import _artifact, _canonical_value, expand_result, load_snapshot

WRITE_FIELDS = (*RUN_FIELDS, "input_tokens", "output_tokens", "error_code", "error_message", "latency_ms")
ARTIFACT_FIELDS = tuple(column.name for column in AISatisfactionRunArtifact.__table__.columns)
ACTIONS = {"succeeded": "run.satisfaction.usage.accept", "failed": "run.satisfaction.usage.fail", "cancelled": "run.satisfaction.usage.cancel"}
TokenCount = Annotated[int, Field(strict=True, ge=0, le=2000000)]


class SatisfactionUsage(StrictModel):
    input_tokens: TokenCount | None
    output_tokens: TokenCount | None
    complete: bool
    model_call_attempted: bool | None

    @model_validator(mode="after")
    def actual_receipt(self):
        if self.complete != (self.input_tokens is not None and self.output_tokens is not None):
            raise ValueError("Usage completeness must reflect the actual independent receipt")
        if self.model_call_attempted is False and (self.input_tokens, self.output_tokens) != (0, 0):
            raise ValueError("A known unattempted call has exact zero token use")
        if self.model_call_attempted is None and (self.input_tokens is not None or self.output_tokens is not None):
            raise ValueError("An interrupted unknown call has no invented counts")
        return self


class SatisfactionUsageEvent(StrictModel):
    schema_version: Literal["satisfaction_usage_receipt_v1"]
    run_id: UUID
    lease_token: UUID | None
    source_binding_hash: SHA
    result_hash: SHA | None
    terminal_state_hash: SHA
    status: Literal["succeeded", "failed", "cancelled"]
    error_code: str | None = Field(max_length=64)
    usage: SatisfactionUsage


def usage(inputs=None, outputs=None, attempted=None):
    return SatisfactionUsage(input_tokens=inputs, output_tokens=outputs, complete=inputs is not None and outputs is not None, model_call_attempted=attempted).model_dump(mode="json")


def readback(db, run, expected):
    """Read only this Run, Artifact and specific receipt PK; no audit range locks."""
    with db.no_autoflush:
        actual = db.query(*(getattr(AIRun, key) for key in WRITE_FIELDS)).filter_by(run_id=run.run_id).with_for_update().one_or_none()
        artifact = db.query(*(getattr(AISatisfactionRunArtifact, key) for key in ARTIFACT_FIELDS)).filter_by(run_id=run.run_id).with_for_update().one_or_none()
        receipt = db.query(*(getattr(AIAuditEvent, key) for key in AUDIT_FIELDS)).filter_by(event_id=expected["event"].event_id).with_for_update(read=True).one_or_none()
    if (
        actual is None
        or dict(actual._mapping) != expected["run"]
        or artifact is None
        or dict(artifact._mapping) != expected["artifact"]
        or receipt is None
        or dict(receipt._mapping) != expected["audit"]
    ):
        raise HTTPException(409, "评价任务22字段、完整Artifact或本条具体用量审计写入已变化")


def stage_terminal(db, run, receipt):
    _, binding, _, _ = load_snapshot(db, run)
    row = _artifact(db, run.run_id, exclusive=True)
    checked = SatisfactionUsage.model_validate(receipt)
    if row is None or row.usage_event_id is not None or run.status not in ACTIONS:
        raise HTTPException(409, "评价终态必须有唯一不可覆盖的具体用量回执")
    if checked.model_call_attempted is None and run.error_code != "WORKER_INTERRUPTED":
        raise HTTPException(409, "只有中断任务可保留实际调用状态未知")
    if run.status == "succeeded" and (checked.model_call_attempted is not True or row.result_hash is None):
        raise HTTPException(409, "评价完整成功结果必须有实际调用状态和独立接收审计")
    if run.status != "succeeded" and (run.result_json != "{}" or row.result_hash is not None):
        raise HTTPException(409, "失败或取消任务不能保留已接收结果")
    detail = SatisfactionUsageEvent(
        schema_version="satisfaction_usage_receipt_v1",
        run_id=run.run_id,
        lease_token=run.lease_token,
        source_binding_hash=source_hash(binding),
        result_hash=row.result_hash,
        terminal_state_hash=source_hash({key: getattr(run, key) for key in WRITE_FIELDS}),
        status=run.status,
        error_code=run.error_code,
        usage=checked,
    )
    event = AIAuditEvent(actor_id=run.requested_by, action=ACTIONS[run.status], target=run.run_id, detail_json=canonical_json(detail.model_dump(mode="json")))
    expected = {"run": {key: getattr(run, key) for key in WRITE_FIELDS}, "audit": {key: getattr(event, key) for key in AUDIT_FIELDS}, "event": event}
    db.add(event)
    db.flush()
    row.usage_event_id = event.event_id
    expected["artifact"] = {key: getattr(row, key) for key in ARTIFACT_FIELDS}
    db.flush()
    readback(db, run, expected)
    load_terminal(db, run)
    return expected


def load_terminal(db, run):
    """Caller authorizes before this internal reader touches any result body."""
    try:
        _, binding, _, _ = load_snapshot(db, run)
        row = _artifact(db, run.run_id)
        if row.usage_event_id is None:
            if run.result_json != "{}" or row.result_hash is not None or run.status not in {"queued", "running"} and not (run.status == "cancelled" and run.latency_ms is None):
                raise ValueError("A pending task cannot carry accepted or terminal material")
            return None, usage()
        action = ACTIONS.get(run.status)
        event = db.query(AIAuditEvent).filter_by(event_id=row.usage_event_id).populate_existing().with_for_update(read=True).one_or_none()
        if event is None or action is None or event.action != action or event.actor_id != run.requested_by or event.target != run.run_id:
            raise ValueError("The specific terminal usage audit differs")
        detail = SatisfactionUsageEvent.model_validate(_canonical_value(event.detail_json))
        if (
            canonical_json(detail.model_dump(mode="json")) != event.detail_json
            or detail.run_id != run.run_id
            or detail.lease_token != run.lease_token
            or detail.source_binding_hash != source_hash(binding)
            or detail.status != run.status
            or detail.error_code != run.error_code
            or detail.terminal_state_hash != source_hash({key: getattr(run, key) for key in WRITE_FIELDS})
        ):
            raise ValueError("The actual terminal source, status, lease or receipt differs")
        for key in ("input_tokens", "output_tokens"):
            number = getattr(detail.usage, key)
            if getattr(run, key) != (number if number is not None else 0):
                raise ValueError("Legacy integer fields cannot replace the nullable receipt")
        if detail.usage.model_call_attempted is None and run.error_code != "WORKER_INTERRUPTED":
            raise ValueError("Unknown call state is only retained after process interruption")
        if run.status == "succeeded":
            if detail.usage.model_call_attempted is not True or detail.result_hash != row.result_hash or row.receipt_event_id == row.usage_event_id:
                raise ValueError("Successful usage and independent full-result acceptance differ")
            result = expand_result(db, run)
        else:
            if run.result_json != "{}" or row.result_hash is not None or row.receipt_event_id is not None or detail.result_hash is not None:
                raise ValueError("An unsuccessful task cannot retain a complete accepted result")
            result = None
        return result, detail.usage.model_dump(mode="json")
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "评价终态、具体用量回执或完整结果无效，未降级展示") from exc
