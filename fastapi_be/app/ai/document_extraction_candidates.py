"""An explicit ordinal saves one current, unreviewed candidate from a real draft."""

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from app.ai import document_evidence_contract as c
from app.ai import document_evidence_sources as sources
from app.ai.document_evidence_models import AIDocumentOriginal
from app.ai.document_extraction_context import verify_context
from app.ai.document_extraction_contract import DocumentExtractionDraft, candidate_from_draft
from app.ai.document_extraction_runtime import usage_receipt
from app.ai.document_extraction_storage import authorize_document_run, load_result, load_snapshot
from app.ai.governance import audit
from app.ai.models import AIAuditEvent, AIRun
from app.ai.native_acceptance import AUDIT_FIELDS

SAVE_ACTION = "run.document_extraction.candidate"


class SaveDocumentCandidate(c.StrictModel):
    ordinal: int = Field(strict=True, ge=0, le=63)


def save_candidate(db, user, run_id, ordinal):
    actor = sources.current_super(db, user)
    epoch = sources._epoch(actor)
    try:
        run = db.query(AIRun).filter_by(run_id=run_id).one_or_none()
        if run is None:
            raise HTTPException(404, "原文提取任务不存在")
        _, context, _ = load_snapshot(db, run)
        if run.status != "succeeded":
            raise HTTPException(409, "仅能明确选择已成功提取的实际草稿条目")
        # Take the original write lock before reading its review/candidate state.
        # Different completed tasks can share this original; two SHARE→UPDATE
        # upgrades would otherwise deadlock during simultaneous explicit saves.
        sources._row(db, AIDocumentOriginal, "original_id", context.document_binding.original.original_id, writing=True)
        run = db.query(AIRun).filter_by(run_id=run_id).populate_existing().with_for_update().one()
        _, context, metadata = authorize_document_run(db, actor, run, current=True)
        result = load_result(db, run)
        usage_receipt(db, run)
        if result is None:
            raise HTTPException(409, "任务不包含已接收的完整区间草稿")
        draft = DocumentExtractionDraft.model_validate(result["document_extraction"])
        try:
            proposal = candidate_from_draft(draft, context.document_source, metadata["instructions_digest"], ordinal)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, "须明确选择实际草稿中的零起点条目序号") from exc
        previous = db.query(AIAuditEvent).filter_by(action=SAVE_ACTION, target=run_id).populate_existing().with_for_update(read=True).all()
        for event in previous:
            detail = c.parse_json(event.detail_json)
            if not isinstance(detail, dict) or set(detail) != {"run_id", "candidate_id", "ordinal", "source_digest", "proposal_hash", "result_hash"}:
                raise HTTPException(409, "已有逐条保存审计不完整，请在原文治理中核对")
            if detail["ordinal"] == ordinal:
                raise HTTPException(409, "该条草稿已明确保存，请在原文治理中查看现有候选")
        candidate = sources.create_candidate(db, actor, proposal)
        details = {
            "run_id": run_id,
            "candidate_id": candidate.snapshot.candidate_id,
            "ordinal": ordinal,
            "source_digest": context.document_binding.source_digest,
            "proposal_hash": c.digest(proposal),
            "result_hash": c.bytes_hash(run.result_json),
        }
        audit(db, actor.user_id, SAVE_ACTION, run_id, details)
        staged = [event for event in db.new if isinstance(event, AIAuditEvent) and event.action == SAVE_ACTION and event.target == run_id]
        if len(staged) != 1:
            raise HTTPException(409, "本次明确保存须有唯一原任务关联审计")
        event = staged[0]
        expected = {key: getattr(event, key) for key in AUDIT_FIELDS}
        db.flush()
        actual = db.query(*(getattr(AIAuditEvent, key) for key in AUDIT_FIELDS)).filter_by(event_id=event.event_id).with_for_update(read=True).one_or_none()
        if actual is None or dict(actual._mapping) != expected:
            raise HTTPException(409, "本次原任务关联审计实际写入不完整，候选未保存")
        actual_candidate = sources.candidate_detail(db, actor, candidate.snapshot.candidate_id)
        if actual_candidate != candidate or c.digest(actual_candidate.snapshot.proposal) != c.digest(proposal):
            raise HTTPException(409, "候选实际写入与所选完整区间草稿不一致")
        db.refresh(run)
        if load_result(db, run) != result:
            raise HTTPException(409, "保存期间原任务完整草稿发生改变")
        usage_receipt(db, run)
        verify_context(db, actor, context.model_dump(mode="json"), current=True)
        sources.current_super(db, actor, expected=epoch)
        db.commit()
        return actual_candidate
    except HTTPException:
        db.rollback()
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(409, "完整草稿候选及关联审计未能原子保存，请重新核对") from exc
