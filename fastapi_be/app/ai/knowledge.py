"""Deterministic paragraph retrieval over reviewed, applicable knowledge versions."""

import datetime
import json
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.ai.catalog import FeatureSpec
from app.ai.document_evidence_contract import SOURCE_KIND as DOCUMENT_SOURCE_KIND
from app.ai.document_evidence_contract import URI_PREFIX as DOCUMENT_URI_PREFIX
from app.ai.governance import digest
from app.ai.knowledge_sources import is_document_source, source_is_current
from app.ai.models import AIKnowledgeDocument, utcnow
from app.ai.pathway_knowledge import eligible_pathway_documents
from app.ai.references import SOURCE_REFERENCE_KEYS
from app.models import ClinicalPathway


def retrieval_query(spec: FeatureSpec, task_input: dict, context: dict, tools: dict | None = None) -> str:
    """Use clinical terms, rather than opaque record IDs, for a contextual one-click request."""
    parts = [spec.name]
    parts.extend(value[:3000] for key, value in task_input.items() if key not in SOURCE_REFERENCE_KEYS and isinstance(value, str) and value.strip())
    parts.extend(context.get("current_confirmed_diagnoses", []))
    for item in context.get("pathway_sources", {}).get("current_templates", []):
        if item.get("explicitly_selected"):
            parts.extend(str(item[field])[:500] for field in ("name", "disease_name", "disease_code") if item.get(field))
    for name, fields in [
        ("outpatient_records", ("symptom", "diagnosis_text")),
        ("structured_records", ("chief_complaint", "diagnosis")),
        ("reviewed_observations", ("display", "code")),
        ("surgery_applications", ("surgery_name", "preop_diagnosis", "surgery_indication")),
        ("perioperative_antibiotics", ("pharmaceutical_name", "indication")),
    ]:
        for item in context.get(name, []):
            if (
                name in {"outpatient_records", "structured_records"}
                and not item.get("current_encounter")
                and item.get("source_id")
                not in {
                    "outpatient:" + str(task_input.get("record_id")),
                    "structured:" + str(task_input.get("structured_record_id")),
                }
            ):
                continue
            if name == "reviewed_observations" and task_input.get("lab_result_id") and item.get("lab_result_id") != task_input["lab_result_id"]:
                continue
            parts.extend(str(item[field])[:500] for field in fields if item.get(field))
    consultations = context.get("consultation_sources", {})
    for item in context.get("adr_sources", {}).get("reports", []):
        if task_input.get("reaction_id") is not None and str(item.get("reaction_id")) == str(task_input["reaction_id"]):
            parts.extend(str(item[field])[:500] for field in ("pharmaceutical_name", "reported_symptom") if item.get(field))
    for name, reference, fields in (("referrals", "referral_id", ("recorded_reason",)), ("mdt_cases", "mdt_id", ("recorded_diagnosis", "recorded_result"))):
        for item in consultations.get(name, []):
            if task_input.get(reference) is not None and str(item.get(reference)) == str(task_input[reference]):
                parts.extend(str(item[field])[:500] for field in fields if item.get(field))
    for prescription in context.get("prescriptions", []):
        if task_input.get("prescription_id") and prescription.get("source_id") != "prescription:" + task_input["prescription_id"]:
            continue
        parts.extend(item["drug_name"] for item in prescription.get("items", []) if item.get("drug_name"))
    navigation = (tools or {}).get("hospital_navigation", {})
    for node in (navigation.get("route") or {}).get("nodes", []):
        parts.extend(str(node[field])[:100] for field in ("name", "department_name", "location") if node.get(field))
    for faq in navigation.get("hospital_faq", []):
        parts.append(faq["question"][:200])
    # Building retrieval terms does not change diagnostic certainty or any clinical record.
    return " ".join(dict.fromkeys(parts))[:8000]


def _terms(value: str) -> set[str]:
    terms = set(re.findall(r"[a-z0-9]+", value.lower()))
    for span in re.findall(r"[\u4e00-\u9fff]+", value):
        terms.update(span[index : index + 2] for index in range(max(0, len(span) - 1)))
    return terms


def _chunks(text: str, size: int = 1000) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size - 150)]


def retrieve_evidence(db: Session, spec: FeatureSpec, query: str, department_ids: set[int], limit: int = 6, preferred_pathway_ids: set[int] | None = None) -> list[dict]:
    """Search only current published versions explicitly assigned to this capability."""
    now = utcnow()
    documents = (
        db.query(AIKnowledgeDocument)
        .filter(
            AIKnowledgeDocument.status == "published",
            AIKnowledgeDocument.reviewed_by.isnot(None),
            AIKnowledgeDocument.reviewed_at.isnot(None),
            AIKnowledgeDocument.feature_keys_json.like('%"' + spec.key + '"%'),
            or_(AIKnowledgeDocument.effective_from.is_(None), AIKnowledgeDocument.effective_from <= now),
            or_(AIKnowledgeDocument.effective_to.is_(None), AIKnowledgeDocument.effective_to > now),
            or_(AIKnowledgeDocument.department_id.is_(None), AIKnowledgeDocument.department_id.in_(department_ids)),
        )
        .order_by(AIKnowledgeDocument.reviewed_at.desc())
        .limit(200)
        .all()
    )
    preferred = []
    seen_pathways = set()
    if preferred_pathway_ids:
        for document in eligible_pathway_documents(db, preferred_pathway_ids, spec.key, department_ids):
            if document.source_reference_id not in seen_pathways:
                preferred.append(document)
                seen_pathways.add(document.source_reference_id)
    preferred_ids = {document.document_id for document in preferred}
    documents = list({document.document_id: document for document in [*preferred, *documents]}.values())
    source_ids = {document.source_reference_id for document in documents if document.source_kind == "clinical_pathway"}
    sources = {row.pathway_id: row for row in db.query(ClinicalPathway).filter(ClinicalPathway.pathway_id.in_(source_ids)).all()} if source_ids else {}
    query_terms = _terms(query)
    ranked = []
    for document in documents:
        if spec.key not in json.loads(document.feature_keys_json) or not source_is_current(db, document, sources) or digest(document.content) != document.content_hash:
            continue
        is_preferred = document.document_id in preferred_ids
        for index, content in enumerate(_chunks(document.content)):
            terms = _terms(document.title + " " + content)
            overlap = len(query_terms.intersection(terms))
            if not overlap and not is_preferred:
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
            if document.source_kind is not None:
                evidence.update({"source_kind": document.source_kind, "source_reference_id": document.source_reference_id, "source_snapshot_hash": document.source_snapshot_hash})
            ranked.append((0 if is_preferred else 1, 0 if is_preferred else -score, document.document_id, index, evidence))
    ranked.sort(key=lambda item: item[:4])
    return [item[4] for item in ranked[:limit]]


def is_document_evidence(db: Session, item: dict) -> bool:
    """Recognize any retained origin marker, including the real publication FK."""
    if item.get("source_kind") == DOCUMENT_SOURCE_KIND or isinstance(item.get("source_uri"), str) and item["source_uri"].lower().startswith(DOCUMENT_URI_PREFIX):
        return True
    document = db.get(AIKnowledgeDocument, item["document_id"]) if isinstance(item.get("document_id"), str) else None
    return document is not None and is_document_source(db, document)


def evidence_is_current(db: Session, evidence: list[dict], at: datetime.datetime | None = None) -> bool:
    """Recheck publication after queuing so retired evidence cannot silently be reused."""
    now = at or utcnow()
    for item in evidence:
        if item.get("kind") != "knowledge":
            if is_document_evidence(db, item):
                return False
            continue
        document = db.get(AIKnowledgeDocument, item["document_id"])
        # The full original -> candidate -> publication -> knowledge chain uses
        # current SHARE reads. Check it before trusting an identity-map row.
        document_bound = document is not None and is_document_source(db, document)
        if document_bound and not source_is_current(db, document):
            return False
        if not document or document.status != "published" or document.content_hash != item["content_hash"]:
            return False
        if not document.reviewed_by or not document.reviewed_at or not source_is_current(db, document) or digest(document.content) != document.content_hash:
            return False
        if document.source_kind is not None and (
            item.get("source_kind") != document.source_kind or item.get("source_reference_id") != document.source_reference_id or item.get("source_snapshot_hash") != document.source_snapshot_hash
        ):
            return False
        if (document.effective_from and document.effective_from > now) or (document.effective_to and document.effective_to <= now):
            return False
        if document_bound:
            # A valid publication hash does not authenticate arbitrary task
            # prose. Reconstruct the exact published chunk and its metadata.
            matches = [(index, text) for index, text in enumerate(_chunks(document.content)) if item.get("source_id") == f"knowledge:{document.document_id}:{document.content_hash[:12]}:{index}"]
            if len(matches) != 1 or any(
                item.get(key) != value
                for key, value in {
                    "title": document.title,
                    "version": document.version,
                    "source_uri": document.source_uri,
                    "reviewed_at": str(document.reviewed_at),
                    "content": matches[0][1],
                    "chunk_hash": digest(matches[0][1]),
                }.items()
            ):
                return False
    return True
