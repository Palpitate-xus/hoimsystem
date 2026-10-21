"""Feature-local nullable usage and concrete terminal audit, never clinical auth.

Only the trusted dedicated worker/cancel service calls this technical primitive.
It never loads Run TEXT or Source bodies and never commits. It can retain actual
paid/unknown use after research permission loss without disclosing that Source.
"""

from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import update

from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact, AIResearchCohortRunResult
from app.ai.research_cohort_contract import SHA, UTC, UUID, StrictModel, canonical_json
from app.ai.research_cohort_draft import digest
from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_cohort_write_guard import current_research_rows, lock_research_gate

Count = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
HEADER_FIELDS = (
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
    "status",
    "preview",
    "error_code",
    "error_message",
    "input_tokens",
    "output_tokens",
    "latency_ms",
    "start_time",
    "lease_token",
    "create_time",
    "finish_time",
)


class ResearchUsage(StrictModel):
    input_tokens: Count | None
    output_tokens: Count | None
    complete: bool
    model_call_attempted: bool | None

    @model_validator(mode="after")
    def faithful_unknown(self):
        if self.complete != (self.input_tokens is not None and self.output_tokens is not None):
            raise ValueError("Complete usage requires both actual counts")
        if self.model_call_attempted is False and (self.input_tokens, self.output_tokens) != (0, 0):
            raise ValueError("A known unattempted request has exact zero use")
        if self.model_call_attempted is None and (self.input_tokens is not None or self.output_tokens is not None):
            raise ValueError("An interrupted attempt cannot manufacture known token counts")
        return self


class ResearchDispatchEvent(StrictModel):
    schema_version: Literal["research_dispatch_reserved_v1"]
    run_id: UUID
    lease_token: UUID
    claim_event_id: Annotated[int, Field(strict=True, ge=1)]
    source_binding_hash: SHA
    instructions_digest: SHA
    execution_snapshot_hash: SHA
    reserved_at: UTC


class ResearchUsageEvent(StrictModel):
    schema_version: Literal["research_usage_event_v1"]
    run_id: UUID
    lease_token: UUID | None
    source_binding_hash: SHA
    usage: ResearchUsage
    dispatch_event_id: Annotated[int, Field(strict=True, ge=1)] | None
    status: Literal["succeeded", "failed", "cancelled"]
    error_code: Annotated[str, Field(strict=True, min_length=1, max_length=80)] | None
    result_hash: SHA | None
    result_reference_hash: SHA
    run_header_hash: SHA
    recorded_at: UTC


def usage(inputs=None, outputs=None, attempted=None):
    return ResearchUsage(input_tokens=inputs, output_tokens=outputs, complete=inputs is not None and outputs is not None, model_call_attempted=attempted).model_dump(mode="json")


def _header(db, run_id, *, shared=False):
    from app.ai.models import AIRun

    row = current_research_rows(db.query(*(getattr(AIRun, key) for key in HEADER_FIELDS)).filter_by(run_id=run_id), shared=shared).one_or_none()
    return dict(row._mapping) if row is not None else None


def _encoded_header(header):
    return {key: utc_text(value) if key in {"start_time", "create_time", "finish_time"} else value for key, value in header.items()}


def _locator(db, run_id, *, shared=False):
    return current_research_rows(
        db.query(
            *(
                getattr(AIResearchCohortRunArtifact, key)
                for key in ("run_id", "requested_by", "source_binding_hash", "instructions_digest", "execution_snapshot_hash", "created_audit_event_id", "usage_event_id", "dispatch_event_id")
            )
        ).filter_by(run_id=run_id),
        shared=shared,
    ).one_or_none()


def _accepted_result_header(db, locator, lease_token, result_hash):
    row = current_research_rows(
        db.query(
            AIResearchCohortRunResult.run_id,
            AIResearchCohortRunResult.lease_token,
            AIResearchCohortRunResult.content_hash,
            AIResearchCohortRunResult.source_binding_hash,
            AIResearchCohortRunResult.accept_audit_event_id,
        ).filter_by(run_id=locator.run_id),
        shared=True,
    ).one_or_none()
    if (
        row is None
        or row.lease_token != lease_token
        or row.content_hash != result_hash
        or row.source_binding_hash != locator.source_binding_hash
        or row.accept_audit_event_id in {locator.created_audit_event_id, locator.usage_event_id, locator.dispatch_event_id}
    ):
        raise HTTPException(409, "研究成功须有独立具体接受回执和原完整结果身份")
    return row


def read_dispatch_event(db, run_id):
    """Current Gate is required; opaque fields and exact two Audit PKs only."""
    from app.ai.models import AIAuditEvent
    from app.ai.research_cohort_storage import _json

    locator = _locator(db, run_id, shared=True)
    header = _header(db, run_id, shared=True)
    if locator is None or header is None or locator.dispatch_event_id is None:
        raise HTTPException(409, "科研模型调用缺少持久dispatch回执FK，不能推定已调用")
    event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=locator.dispatch_event_id), shared=True).one_or_none()
    try:
        value = ResearchDispatchEvent.model_validate(_json(event.detail_json, 65535), strict=True).model_dump(mode="json") if event is not None else None
        if (
            value is None
            or event.action != "research.task.dispatch.reserve"
            or event.target != run_id
            or event.actor_id != locator.requested_by
            or value["run_id"] != run_id
            or value["lease_token"] != header["lease_token"]
            or value["source_binding_hash"] != locator.source_binding_hash
            or value["instructions_digest"] != locator.instructions_digest
            or value["execution_snapshot_hash"] != locator.execution_snapshot_hash
            or locator.dispatch_event_id in {locator.created_audit_event_id, locator.usage_event_id, value["claim_event_id"]}
        ):
            raise ValueError("The durable dispatch reservation differs")
        claim = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=value["claim_event_id"]), shared=True).one_or_none()
        expected = {
            "schema_version": "research_claim_v1",
            "run_id": run_id,
            "lease_token": value["lease_token"],
            "start_time": utc_text(header["start_time"]),
            "source_binding_hash": locator.source_binding_hash,
        }
        if claim is None or claim.action != "research.task.claim" or claim.actor_id != locator.requested_by or claim.target != run_id or claim.detail_json != canonical_json(expected):
            raise ValueError("The original concrete claim receipt differs")
        return value
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(409, "科研原dispatch/claim具体AuditPK证明损坏，不允许重放") from exc


def read_usage_event(db, run_id):
    """Caller has acquired the feature Gate; current opaque columns only."""
    from app.ai.models import AIAuditEvent, AIRun

    locator = _locator(db, run_id, shared=True)
    header = _header(db, run_id, shared=True)
    if locator is None or header is None or locator.usage_event_id is None:
        raise HTTPException(409, "科研终态缺少独立具体usage回执PK")
    row = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=locator.usage_event_id), shared=True).one_or_none()
    try:
        from app.ai.research_cohort_storage import _json

        value = ResearchUsageEvent.model_validate(_json(row.detail_json, 65535), strict=True).model_dump(mode="json") if row is not None else None
        if (
            value is None
            or row.action != "research.task.usage"
            or row.target != run_id
            or row.actor_id != locator.requested_by
            or value["run_id"] != run_id
            or value["source_binding_hash"] != locator.source_binding_hash
            or value["dispatch_event_id"] != locator.dispatch_event_id
            or value["status"] != header["status"]
            or value["lease_token"] != header["lease_token"]
            or value["error_code"] != header["error_code"]
            or value["run_header_hash"] != digest(_encoded_header(header))
            or locator.usage_event_id == locator.created_audit_event_id
        ):
            raise ValueError("The exact independently stored usage receipt changed")
        # Compare SQL boolean, never return an unauthorized result TEXT column.
        expected_reference = {"schema_version": "research_cohort_result_ref_v1", "run_id": run_id, "content_hash": value["result_hash"]} if value["status"] == "succeeded" else {}
        raw = canonical_json(expected_reference)
        if value["result_reference_hash"] != digest(expected_reference) or current_research_rows(db.query(AIRun.result_json == raw).filter_by(run_id=run_id), shared=True).scalar() is not True:
            raise ValueError("The original short result reference differs")
        receipt = value["usage"]
        if locator.dispatch_event_id is not None:
            read_dispatch_event(db, run_id)
        elif receipt["model_call_attempted"] is not False:
            raise ValueError("An attempted or uncertain call needs its durable reservation")
        if header["input_tokens"] != (receipt["input_tokens"] if receipt["input_tokens"] is not None else 0) or header["output_tokens"] != (
            receipt["output_tokens"] if receipt["output_tokens"] is not None else 0
        ):
            raise ValueError("Legacy integer counters must agree with known counts only")
        if value["status"] == "succeeded" and (receipt["model_call_attempted"] is not True or value["result_hash"] is None or value["error_code"] is not None):
            raise ValueError("Success requires an attempted call and complete accepted result identity")
        if value["status"] == "succeeded":
            _accepted_result_header(db, locator, value["lease_token"], value["result_hash"])
        if value["status"] != "succeeded" and value["result_hash"] is not None:
            raise ValueError("A failed or cancelled task cannot retain an accepted clinical result")
        return value
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(409, "科研nullable用量/终态/具体AuditPK回执不完整") from exc


def stage_terminal_receipt(db, run_id, lease_token, receipt, *, status, error_code=None, error_message=None, result_hash=None, latency_ms=None):
    """Same-TX header + original nullable usage + specific Audit FK, no commit.

    No research content authorization is conferred. A successful caller must
    first stage its authorized Result and must keep all source locks until its
    own terminal/postwrite checks finish. Failure may preserve actual paid use
    after permission loss using this exclusively technical path.
    """
    from app.ai.models import AIAuditEvent, AIRun

    checked = ResearchUsage.model_validate(receipt, strict=True).model_dump(mode="json")
    if status not in TERMINAL or type(status) is not str:
        raise HTTPException(409, "科研技术回执仅接受明确终态")
    if status == "succeeded" and (checked["model_call_attempted"] is not True or type(result_hash) is not str or error_code is not None or error_message is not None):
        raise HTTPException(409, "研究成功不能伪装未调用或缺少完整结果SHA")
    if status != "succeeded" and result_hash is not None:
        raise HTTPException(409, "失败或取消不接受模型临床结果")
    if error_code is not None and (type(error_code) is not str or not 0 < len(error_code) <= 80):
        raise HTTPException(409, "科研错误代码超出闭集标量预算")
    if error_message is not None and (type(error_message) is not str or len(error_message) > 500):
        raise HTTPException(409, "科研错误消息须为有界技术字符串")
    if latency_ms is not None and (type(latency_ms) is not int or not 0 <= latency_ms <= 2147483647):
        raise HTTPException(409, "科研时延不是明确非负整数")
    lock_research_gate(db)
    locator = _locator(db, run_id)
    header = _header(db, run_id)
    if (
        locator is None
        or header is None
        or header["feature_key"] != "research_cohort"
        or header["requested_by"] != locator.requested_by
        or header["patient_id"] is not None
        or header["encounter_ref"] is not None
    ):
        raise HTTPException(409, "科研技术回执缺少真实Artifact/Run身份")
    if locator.usage_event_id is not None:
        old = read_usage_event(db, run_id)
        if (old["lease_token"], old["usage"], old["status"], old["error_code"], old["result_hash"]) != (lease_token, checked, status, error_code, result_hash):
            raise HTTPException(409, "同一科研任务不能覆盖第一次实际usage回执")
        return locator.usage_event_id
    if locator.dispatch_event_id is not None:
        read_dispatch_event(db, run_id)
    elif checked["model_call_attempted"] is not False:
        raise HTTPException(409, "没有持久dispatch原件不能声称已调用或用量未知")
    if header["lease_token"] != lease_token:
        raise HTTPException(409, "科研worker原租约已变化，不接收旧回执")
    queued_zero = header["status"] == "queued" and lease_token is None and status == "cancelled" and checked == usage(0, 0, False)
    claimed = header["status"] in {"running", "cancelled"} and lease_token is not None
    if not (queued_zero or claimed) or header["status"] == "cancelled" and status != "cancelled":
        raise HTTPException(409, "科研终态不匹配queued取消或原在途租约")
    if status == "succeeded":
        _accepted_result_header(db, locator, lease_token, result_hash)
    reference = {"schema_version": "research_cohort_result_ref_v1", "run_id": run_id, "content_hash": result_hash} if status == "succeeded" else {}
    changes = {
        "status": status,
        "result_json": canonical_json(reference),
        "finish_time": utcnow().replace(microsecond=0),
        "error_code": error_code,
        "error_message": error_message,
        "latency_ms": latency_ms,
        "input_tokens": checked["input_tokens"] if checked["input_tokens"] is not None else 0,
        "output_tokens": checked["output_tokens"] if checked["output_tokens"] is not None else 0,
    }
    expected = {**header, **{key: value for key, value in changes.items() if key != "result_json"}}
    db.execute(update(AIRun).where(AIRun.run_id == run_id, AIRun.status == header["status"], AIRun.lease_token == lease_token).values(**changes).execution_options(synchronize_session=False))
    recorded = utcnow()
    detail = ResearchUsageEvent(
        schema_version="research_usage_event_v1",
        run_id=run_id,
        lease_token=lease_token,
        source_binding_hash=locator.source_binding_hash,
        usage=checked,
        dispatch_event_id=locator.dispatch_event_id,
        status=status,
        error_code=error_code,
        result_hash=result_hash,
        result_reference_hash=digest(reference),
        run_header_hash=digest(_encoded_header(expected)),
        recorded_at=utc_text(recorded),
    ).model_dump(mode="json")
    audit = AIAuditEvent(actor_id=locator.requested_by, action="research.task.usage", target=run_id, detail_json=canonical_json(detail))
    db.add(audit)
    db.flush()
    db.execute(
        update(AIResearchCohortRunArtifact)
        .where(AIResearchCohortRunArtifact.run_id == run_id, AIResearchCohortRunArtifact.usage_event_id.is_(None))
        .values(usage_event_id=audit.event_id)
        .execution_options(synchronize_session=False)
    )
    db.flush()
    if read_usage_event(db, run_id) != detail or _header(db, run_id, shared=True) != expected:
        raise HTTPException(409, "科研终态和独立nullable用量同事务回读不一致")
    return audit.event_id
