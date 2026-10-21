"""Exact current Super-only original/Run linkage filters, without loading plaintext."""

from fastapi import HTTPException

from app.ai import document_evidence_sources as sources
from app.ai.document_extraction_context import selection
from app.ai.document_extraction_models import AIDocumentExtractionRunAnchor
from app.ai.document_extraction_storage import FEATURE_KEY
from app.ai.models import AIRun


def filter_document_history(db, user, query, *, feature_key, original_id, other_scope):
    sources.current_super(db, user)
    if feature_key != FEATURE_KEY or any(value is not None for value in other_scope):
        raise HTTPException(422, "指南提取历史仅筛选独立原件，不能混入患者、住院或其他运营范围")
    if original_id is not None:
        identifier = selection({"document_original_id": original_id}).document_original_id
        query = query.filter(AIRun.run_id.in_(db.query(AIDocumentExtractionRunAnchor.run_id).filter_by(original_id=identifier)))
    return query
