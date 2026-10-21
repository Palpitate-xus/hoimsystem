"""Real immutable FK history filters, never text search or caller-defined scope."""

from fastapi import HTTPException
from sqlalchemy.orm import defer

from app.ai import document_change_sources as sources
from app.ai import document_evidence_sources as originals
from app.ai.document_change_context import selection
from app.ai.document_change_run_models import AIDocumentChangeRunArtifact
from app.ai.document_change_view_contract import FEATURE_KEY
from app.ai.models import AIRun


def filter_history(db, user, query, *, feature_key, scope_id, other_scope, frozen_audit=False):
    actor = originals.current_super(db, user)
    if feature_key != FEATURE_KEY or any(value is not None for value in other_scope):
        raise HTTPException(422, "双原文历史仅接受明确有限范围，不混用患者、住院或其他原件范围")
    if scope_id is not None:
        identifier = selection({"document_change_scope_id": scope_id}).document_change_scope_id
        if not frozen_audit:
            sources.authorize_scope(db, actor, identifier)
        query = query.filter(AIRun.run_id.in_(db.query(AIDocumentChangeRunArtifact.run_id).filter_by(scope_id=identifier)))
    else:
        query = query.filter(AIRun.run_id.in_(db.query(AIDocumentChangeRunArtifact.run_id)))
    return query.options(*(defer(getattr(AIRun, key)) for key in ("input_json", "evidence_json", "context_metadata_json", "result_json")))
