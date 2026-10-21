"""Complete current comparison inventory under actor -> sorted Original X -> targets.

The technical Link directory is the sole pre-target discovery read, after all
Original X locks. All Link writers take those parents first, preventing phantoms.
These are current locking reads, including directory counts under old MySQL RR.
"""

from fastapi import HTTPException

from app.ai import document_change_contract as c
from app.ai import document_evidence_sources as originals
from app.ai.document_change_models import AIDocumentRuleLink
from app.ai.document_change_targets import CaseBudget, sql_octets, target_snapshot
from app.ai.document_evidence_models import AIDocumentKnowledgePublication, AIDocumentOriginal, AIDocumentSpanCandidate
from app.ai.models import AIKnowledgeDocument


def lock_originals(db, user, identifiers, *, budget=None):
    budget = budget or CaseBudget()
    actor = originals.current_super(db, user)
    rows = {}
    for identifier in sorted(set(identifiers)):
        with db.no_autoflush:
            sizes = db.query(sql_octets(AIDocumentOriginal.original_text), sql_octets(AIDocumentOriginal.identity_json)).filter_by(original_id=identifier).with_for_update().one_or_none()
        if sizes is None:
            raise HTTPException(404, "所选原文不存在")
        budget.check_raw(sum(sizes))
        row = originals._row(db, AIDocumentOriginal, "original_id", identifier, writing=True)
        record = originals._original_record(row)
        budget.add(record, members=1)
        rows[identifier] = (row, record)
    return actor, rows, budget


def preflight_row(db, model, key, identifier, fields, budget, *, writing=False):
    with db.no_autoflush:
        sizes = db.query(*(sql_octets(getattr(model, field)) for field in fields)).filter(getattr(model, key) == identifier).with_for_update(read=not writing).one_or_none()
    if sizes is None:
        raise HTTPException(409, "完整依赖集合的成员已消失")
    budget.check_raw(sum(sizes))
    return originals._row(db, model, key, identifier, writing=writing)


def target_from_columns(kind, profile_id, pathway_id):
    model = c.RiskProfileReference if kind == "risk_rule_profile" else c.PathwayReference if kind == "clinical_pathway" else None
    if model is None:
        raise ValueError("Stored link target kind is not supported")
    return model(kind=kind, target_id=profile_id if kind == "risk_rule_profile" else pathway_id)


def collect_locked(db, request, parents, budget, *, validate_references=True):
    # Parent X locks are already held. Fetch at most cap+1 technical rows before
    # materializing any full dependency; never read an ordinary RR COUNT.
    ids = sorted(parents)
    with db.no_autoflush:
        directory = (
            db.query(AIDocumentRuleLink.link_id, AIDocumentRuleLink.original_id, AIDocumentRuleLink.target_kind, AIDocumentRuleLink.risk_rule_profile_id, AIDocumentRuleLink.clinical_pathway_id)
            .filter(AIDocumentRuleLink.original_id.in_(ids))
            .order_by(AIDocumentRuleLink.link_id)
            .limit(c.MAX_MEMBERS + 1)
            .with_for_update(read=True)
            .all()
        )
    if len(directory) + budget.members > c.MAX_MEMBERS:
        raise ValueError("The whole Link directory exceeds the shared member cap")
    targets = {c.target_key(value): value for value in request.declared_targets}
    for row in directory:
        reference = target_from_columns(row.target_kind, row.risk_rule_profile_id, row.clinical_pathway_id)
        targets[c.target_key(reference)] = reference
    if len(targets) + len(directory) + budget.members > c.MAX_MEMBERS:
        raise ValueError("All target and link dependencies share one member cap")
    frozen_targets = {}
    for key, reference in sorted(targets.items()):
        value = target_snapshot(db, reference, budget)
        budget.add(value, members=1)
        frozen_targets[key] = value
    if validate_references and any(not frozen_targets[c.target_key(value)].exists for value in request.declared_targets):
        raise HTTPException(409, "声明范围内的实际规则或路径已不存在")
    from app.ai.document_change_sources import link_record

    links = []
    for hint in directory:
        row = preflight_row(db, AIDocumentRuleLink, "link_id", hint.link_id, ("link_json",), budget)
        reference = target_from_columns(row.target_kind, row.risk_rule_profile_id, row.clinical_pathway_id)
        if row.original_id != hint.original_id or c.target_key(reference) not in frozen_targets:
            raise ValueError("Technical discovery and full current link differ")
        value = link_record(db, row, parents[row.original_id][1], frozen_targets[c.target_key(reference)])
        budget.add(value, members=1)
        links.append(value)
    with db.no_autoflush:
        publications = (
            db.query(
                AIDocumentKnowledgePublication.publication_id,
                AIDocumentKnowledgePublication.original_id,
                AIDocumentKnowledgePublication.candidate_id,
                AIDocumentKnowledgePublication.knowledge_document_id,
            )
            .filter(AIDocumentKnowledgePublication.original_id.in_(ids))
            .order_by(AIDocumentKnowledgePublication.publication_id)
            .limit(c.MAX_MEMBERS + 1)
            .with_for_update(read=True)
            .all()
        )
    if budget.members + 3 * len(publications) > c.MAX_MEMBERS:
        raise ValueError("All direct publication/candidate/knowledge members share the one cap")
    dependencies = []
    for hint in publications:
        candidate = preflight_row(db, AIDocumentSpanCandidate, "candidate_id", hint.candidate_id, ("candidate_json",), budget)
        publication = preflight_row(db, AIDocumentKnowledgePublication, "publication_id", hint.publication_id, ("publication_json",), budget)
        knowledge = preflight_row(db, AIKnowledgeDocument, "document_id", hint.knowledge_document_id, tuple(c.e.KnowledgeCurrent.model_fields), budget)
        if (publication.original_id, publication.candidate_id, publication.knowledge_document_id, candidate.original_id) != (
            hint.original_id,
            hint.candidate_id,
            hint.knowledge_document_id,
            hint.original_id,
        ):
            raise ValueError("Current publication parents differ from the closed directory")
        original_row, original = parents[hint.original_id]
        value = c.PublicationDependency(candidate=originals._candidate_record(db, candidate, original), publication=originals._publication_record(db, original_row, candidate, publication, knowledge))
        budget.add(value, members=3)
        dependencies.append(value)
    baseline = parents[request.baseline_original.original_id][1]
    candidate = parents[request.candidate_original.original_id][1]
    if validate_references:
        for expected, actual in ((request.baseline_original, baseline), (request.candidate_original, candidate)):
            if not actual.eligible or expected != original_ref(actual):
                raise HTTPException(409, "原件必须当前已发布、双项确认且与显式选择的完整版本相同")
    return c.Inventory(
        schema_version="document_change_inventory_v1",
        baseline_original=baseline,
        candidate_original=candidate,
        targets=list(frozen_targets.values()),
        rule_links=links,
        publications=dependencies,
        member_count=budget.members,
    )


def original_ref(record):
    return c.e.OriginalReference(original_id=record.snapshot.original_id, content_hash=record.content_hash, governance_hash=record.governance_hash)
