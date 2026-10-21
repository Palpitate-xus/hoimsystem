"""Current source dispatch for published knowledge, including exact document spans."""

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.ai.document_evidence_models import AIDocumentKnowledgePublication
from app.ai.document_evidence_sources import bound_source_state, document_binding_exists, is_document_bound_source
from app.ai.models import AIKnowledgeDocument
from app.ai.pathway_knowledge import source_state as pathway_source_state


def is_document_source(db, document):
    """The immutable publication FK remains a marker if URI and kind are removed."""
    return is_document_bound_source(document) or document_binding_exists(db, document)


def source_state(db, document, sources=None):
    if is_document_source(db, document):
        return bound_source_state(db, document)
    return pathway_source_state(db, document, sources)


def source_is_current(db, document, sources=None):
    return source_state(db, document, sources) in {"unlinked", "current"}


def lock_manual_review_target(db, document_id):
    """Current classification must precede a generic knowledge X lock.

    A prior MySQL RR snapshot may not see a newly published document or its
    immutable FK. SHARE NOWAIT reads see current rows without waiting in an
    order opposite to document writers (parents -> publication -> knowledge).
    If a dependency is busy, refuse this alternate writer rather than guessing
    that a missing old-snapshot row is an unbound manual document.
    """
    try:
        current = (
            db.query(AIKnowledgeDocument.document_id, AIKnowledgeDocument.source_kind, AIKnowledgeDocument.source_uri)
            .filter_by(document_id=document_id)
            .with_for_update(read=True, nowait=True)
            .one_or_none()
        )
        if current is None:
            return None
        if is_document_bound_source(current):
            raise HTTPException(409, "原文摘录须在原文证据治理中发布或撤销，请核对完整原件链")
        publication = db.query(AIDocumentKnowledgePublication.publication_id).filter_by(knowledge_document_id=document_id).with_for_update(read=True, nowait=True).first()
        if publication is not None:
            raise HTTPException(409, "原文摘录须在原文证据治理中发布或撤销，请核对完整原件链")
        return db.query(AIKnowledgeDocument).filter_by(document_id=document_id).populate_existing().with_for_update(nowait=True).one()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(409, "知识版本或关联正在变更，请刷新后重新核对") from exc
