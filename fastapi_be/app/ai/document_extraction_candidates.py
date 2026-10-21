"""An explicit ordinal saves one current, unreviewed candidate from a real draft."""

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from app.ai import document_evidence_contract as c
from app.ai import document_evidence_sources as sources
from app.ai.document_evidence_models import AIDocumentOriginal
from app.ai.document_extraction_context import verify_context
from app.ai.document_extraction_contract import DocumentExtractionDraft, candidate_from_draft
from app.ai.document_extraction_run_record import encode_record, parse_record
from app.ai.document_extraction_runtime import _verify_write, _write_state, usage_receipt
from app.ai.document_extraction_storage import authorize_document_run, load_result, load_snapshot
from app.ai.governance import audit
from app.ai.models import AIAuditEvent, AIRun

SAVE_ACTION = "run.document_extraction.candidate"


class SaveDocumentCandidate(c.StrictModel):
    ordinal: int = Field(strict=True, ge=0, le=63)


def _saved_candidate(db, actor, run, context, metadata, record, ordinal, reference):
    """Read the exact saved audit/candidate IDs without a missing-key gap lock."""
    event = db.query(AIAuditEvent).filter_by(event_id=reference.audit_event_id).populate_existing().with_for_update(read=True).one_or_none()
    candidate = sources.candidate_detail(db, actor, reference.candidate_id)
    proposal = candidate_from_draft(record.result.document_extraction, context.document_source, metadata["instructions_digest"], ordinal)
    expected = {
        "run_id": run.run_id,
        "candidate_id": reference.candidate_id,
        "ordinal": ordinal,
        "source_digest": context.document_binding.source_digest,
        "proposal_hash": c.digest(proposal),
        "result_hash": c.digest(record.result),
    }
    if (
        event is None
        or event.action != SAVE_ACTION
        or event.target != run.run_id
        or event.actor_id != candidate.snapshot.created_by
        or event.detail_json != c.canonical_json(expected)
        or candidate.snapshot.proposal != proposal
    ):
        raise HTTPException(409, "已保存条目的具体关联审计或完整候选无法核对")
    return candidate


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
        record = parse_record(run.result_json)
        draft = DocumentExtractionDraft.model_validate(result["document_extraction"])
        try:
            proposal = candidate_from_draft(draft, context.document_source, metadata["instructions_digest"], ordinal)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, "须明确选择实际草稿中的零起点条目序号") from exc
        for key, reference in record.saved_candidates.items():
            _saved_candidate(db, actor, run, context, metadata, record, int(key), reference)
        if str(ordinal) in record.saved_candidates:
            raise HTTPException(409, "该条草稿已明确保存，请在原文治理中查看现有候选")
        candidate = sources.create_candidate(db, actor, proposal)
        details = {
            "run_id": run_id,
            "candidate_id": candidate.snapshot.candidate_id,
            "ordinal": ordinal,
            "source_digest": context.document_binding.source_digest,
            "proposal_hash": c.digest(proposal),
            "result_hash": c.digest(result),
        }
        audit(db, actor.user_id, SAVE_ACTION, run_id, details)
        expected = _write_state(db, run, SAVE_ACTION)
        db.flush()
        _verify_write(db, run, expected)
        saved = {key: value.model_dump(mode="json") for key, value in record.saved_candidates.items()}
        saved[str(ordinal)] = {"candidate_id": candidate.snapshot.candidate_id, "audit_event_id": expected["event"].event_id}
        run.result_json = encode_record(result, record.receipt_event_id, saved)
        expected["run"]["result_json"] = run.result_json
        db.flush()
        _verify_write(db, run, expected)
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
