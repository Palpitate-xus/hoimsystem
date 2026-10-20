"""Deterministic paragraph retrieval over reviewed, applicable knowledge versions."""

import datetime
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.ai.catalog import FeatureSpec
from app.ai.governance import digest
from app.ai.models import AIKnowledgeDocument, utcnow


def _terms(value: str) -> set[str]:
    terms = set(re.findall(r"[a-z0-9]+", value.lower()))
    for span in re.findall(r"[\u4e00-\u9fff]+", value):
        terms.update(span[index : index + 2] for index in range(max(0, len(span) - 1)))
    return terms


def _chunks(text: str, size: int = 1000) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size - 150)]


def retrieve_evidence(db: Session, spec: FeatureSpec, query: str, department_ids: set[int], limit: int = 6) -> list[dict]:
    """Search only current published versions explicitly assigned to this capability."""
    now = utcnow()
    documents = (
        db.query(AIKnowledgeDocument)
        .filter(
            AIKnowledgeDocument.status == "published",
            AIKnowledgeDocument.reviewed_by.isnot(None),
            AIKnowledgeDocument.feature_keys_json.like('%"' + spec.key + '"%'),
            or_(AIKnowledgeDocument.effective_from.is_(None), AIKnowledgeDocument.effective_from <= now),
            or_(AIKnowledgeDocument.effective_to.is_(None), AIKnowledgeDocument.effective_to > now),
            or_(AIKnowledgeDocument.department_id.is_(None), AIKnowledgeDocument.department_id.in_(department_ids)),
        )
        .order_by(AIKnowledgeDocument.reviewed_at.desc())
        .limit(200)
        .all()
    )
    query_terms = _terms(query)
    ranked = []
    for document in documents:
        for index, content in enumerate(_chunks(document.content)):
            terms = _terms(document.title + " " + content)
            overlap = len(query_terms.intersection(terms))
            if not overlap:
                continue
            score = overlap / max(1, len(query_terms))
            evidence = {
                "source_id": f"knowledge:{document.document_id}:{document.content_hash[:12]}:{index}",
                "kind": "knowledge",
                "document_id": document.document_id,
                "title": document.title,
                "version": document.version,
                "source_uri": document.source_uri,
                "content_hash": document.content_hash,
                "chunk_hash": digest(content),
                "reviewed_at": str(document.reviewed_at),
                "content": content,
            }
            ranked.append((score, document.document_id, index, evidence))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [item[3] for item in ranked[:limit]]


def evidence_is_current(db: Session, evidence: list[dict], at: datetime.datetime | None = None) -> bool:
    """Recheck publication after queuing so retired evidence cannot silently be reused."""
    now = at or utcnow()
    for item in evidence:
        if item.get("kind") != "knowledge":
            continue
        document = db.get(AIKnowledgeDocument, item["document_id"])
        if not document or document.status != "published" or document.content_hash != item["content_hash"]:
            return False
        if (document.effective_from and document.effective_from > now) or (document.effective_to and document.effective_to <= now):
            return False
    return True
