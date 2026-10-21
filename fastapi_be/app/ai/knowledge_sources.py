"""Current source dispatch for published knowledge, including exact document spans."""

from app.ai.document_evidence_sources import bound_source_state, document_binding_exists, is_document_bound_source
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
