"""Atomic full Result acceptance, independently current-authorized split reads.

No helper commits or calls a model. The caller rolls back on every failure.
Source/purpose/per-patient/model permission precedes any private Task/Result TEXT,
including Super reads. Receipt-only failure handling lives in a technical module.
"""

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.research_cohort_artifact_models import RESULT_SCHEMA, AIResearchCohortRunArtifact, AIResearchCohortRunResult
from app.ai.research_cohort_contract import UUID, canonical_json
from app.ai.research_cohort_draft import MAX_BYTES, digest
from app.ai.research_cohort_receipts import ResearchUsage, read_usage_event, stage_terminal_receipt
from app.ai.research_cohort_result import result_for_draft, validate_result
from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_cohort_storage import _json, _sha, load_artifact
from app.ai.research_cohort_write_guard import current_research_rows


def _accept_detail(row, source_hash):
    return {
        "schema_version": "research_result_accepted_v1",
        "run_id": row.run_id,
        "case_id": row.case_id,
        "scope_id": row.scope_id,
        "lease_token": row.lease_token,
        "source_projection_hash": source_hash,
        "source_binding_hash": row.source_binding_hash,
        "instructions_digest": row.instructions_digest,
        "content_hash": row.content_hash,
        "result_bytes": row.result_bytes,
        "accepted_at": utc_text(row.accepted_at),
    }


def load_result(db, user, run_id, *, audit_only=False):
    """Current clinical research permission first, including actual Super audit."""
    from app.ai.models import AIAuditEvent

    run, artifact, case, source = load_artifact(db, user, run_id, audit_only=audit_only)
    row = current_research_rows(db.query(AIResearchCohortRunResult).filter_by(run_id=run_id), shared=True).one_or_none()
    if row is None:
        raise HTTPException(409, "科研完整结果分件不存在，不能从摘要伪造原结果")
    if (
        row.schema_version != RESULT_SCHEMA
        or row.case_id != artifact.case_id
        or row.scope_id != artifact.scope_id
        or row.source_binding_hash != artifact.source_binding_hash
        or row.instructions_digest != artifact.instructions_digest
        or run.status != "succeeded"
        or run.lease_token != row.lease_token
        or run.finish_time is None
        or row.accepted_at.replace(microsecond=0) > run.finish_time
        or row.accept_audit_event_id in {artifact.created_audit_event_id, artifact.usage_event_id}
    ):
        raise HTTPException(409, "科研完整结果与原租约、Source绑定或独立接受回执身份不一致")
    result = validate_result(_json(row.result_json, MAX_BYTES), source)
    if row.result_bytes != len(row.result_json.encode("utf-8")) or row.content_hash != _sha(row.result_json) or row.result_json != canonical_json(result):
        raise HTTPException(409, "科研结果原始UTF8全文、精确字节数或内容SHA被替换")
    reference = {"schema_version": "research_cohort_result_ref_v1", "run_id": run_id, "content_hash": row.content_hash}
    if run.result_json != canonical_json(reference):
        raise HTTPException(409, "科研Run只允许绑定其原完整结果短引用")
    audit = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=row.accept_audit_event_id), shared=True).one_or_none()
    if (
        audit is None
        or audit.actor_id != artifact.requested_by
        or audit.action != "research.task.result.accept"
        or audit.target != run_id
        or audit.detail_json != canonical_json(_accept_detail(row, artifact.source_projection_hash))
    ):
        raise HTTPException(409, "科研结果接受不是原具体AuditPK或回执已变化")
    receipt = read_usage_event(db, run_id)
    if receipt["result_hash"] != row.content_hash or receipt["status"] != "succeeded":
        raise HTTPException(409, "科研结果与nullable实际用量的独立终态回执不一致")
    return row, result


def stage_result(db, user, run_id, lease_token, draft, receipt, *, latency_ms=None):
    """Stage result + usage + accepted audit + terminal Run atomically, no commit."""
    from app.ai.models import AIAuditEvent, AIRun

    try:
        TypeAdapter(UUID).validate_python(lease_token, strict=True)
        checked_usage = ResearchUsage.model_validate(receipt, strict=True).model_dump(mode="json")
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "科研结果接受需要原规范租约与完整nullable用量声明") from exc
    if checked_usage["model_call_attempted"] is not True:
        raise HTTPException(409, "未明确尝试调用的任务不能接受模型结果")
    # This is deliberately before either the Run/result X or private body.
    run, artifact, case, source = load_artifact(db, user, run_id, execution=True)
    run = current_research_rows(db.query(AIRun).filter_by(run_id=run_id)).one()
    artifact = current_research_rows(db.query(AIResearchCohortRunArtifact).filter_by(run_id=run_id)).one()
    if run.status != "running" or run.lease_token != lease_token or artifact.usage_event_id is not None:
        raise HTTPException(409, "只接受当前running原租约的第一次模型结果")
    if current_research_rows(db.query(AIResearchCohortRunResult.run_id).filter_by(run_id=run_id)).one_or_none() is not None:
        raise HTTPException(409, "科研完整结果不能被重复接受或覆盖")
    result = result_for_draft(draft, source)
    raw = canonical_json(result)
    row = AIResearchCohortRunResult(
        run_id=run_id,
        case_id=case["case_id"],
        scope_id=case["scope_id"],
        schema_version=RESULT_SCHEMA,
        lease_token=lease_token,
        accepted_at=utcnow(),
        result_json=raw,
        result_bytes=len(raw.encode("utf-8")),
        content_hash=digest(result),
        source_binding_hash=artifact.source_binding_hash,
        instructions_digest=artifact.instructions_digest,
    )
    audit = AIAuditEvent(actor_id=artifact.requested_by, action="research.task.result.accept", target=run_id, detail_json=canonical_json(_accept_detail(row, artifact.source_projection_hash)))
    db.add(audit)
    db.flush()
    row.accept_audit_event_id = audit.event_id
    db.add(row)
    db.flush()
    expected = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    stage_terminal_receipt(db, run_id, lease_token, checked_usage, status="succeeded", result_hash=row.content_hash, latency_ms=latency_ms)
    # Actual Source, current epoch, complete frames and concrete creation audit
    # are checked again after every write, without committing the transaction.
    load_artifact(db, user, run_id, execution=True)
    actual, checked = load_result(db, user, run_id)
    if {column.name: getattr(actual, column.name) for column in actual.__table__.columns} != expected or canonical_json(checked) != raw:
        raise HTTPException(409, "科研全结果与独立接受/用量回执同事务回读不一致")
    return actual, checked
