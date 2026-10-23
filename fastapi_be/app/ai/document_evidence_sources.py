"""Immutable originals, individually reviewed spans and explicit knowledge publication.

Writes stage their SQL audit in the same transaction and never commit. Actor SHARE
locks precede Original -> Candidate -> Publication -> Knowledge locks. The bound
source validator uses current SHARE reads even under a prior repeatable-read view.
"""

import uuid
from functools import wraps

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.ai import document_evidence_contract as c
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.document_evidence_models import AIDocumentKnowledgePublication, AIDocumentOriginal, AIDocumentSpanCandidate
from app.ai.governance import audit
from app.ai.models import AIKnowledgeDocument, utcnow
from app.models import Department, User

REVIEW_FIELDS = ("status", "revision", "privacy_review", "faithfulness_review", "reviewed_by", "reviewed_at", "review_basis_note", "revoked_by", "revoked_at", "revoke_reason")


def _write(function):
    @wraps(function)
    def wrapped(db, *args, **kwargs):
        try:
            return function(db, *args, **kwargs)
        except (SQLAlchemyError, ValidationError, ValueError, UnicodeError) as exc:
            db.rollback()
            raise HTTPException(409, "原文证据或版本发生冲突，整笔操作未接受，请刷新核对") from exc
        except Exception:
            db.rollback()
            raise

    return wrapped


def _epoch(user):
    return user.user_id, user.user_role, user.token_invalid_before


def current_super(db, user, *, expected=None, locking=True):
    request_state = inspect(user, raiseerr=False)
    names = {"username": request_state.dict["username"]} if request_state is not None and "username" in request_state.dict else {}
    expected = _epoch(user) if expected is None else expected
    with db.no_autoflush:
        query = db.query(User).filter_by(user_id=expected[0]).populate_existing()
        if locking:
            query = query.with_for_update(read=True)
        actual = query.one_or_none()
    if (
        actual is None
        or actual.user_role != "super_admin"
        or expected[1] != "super_admin"
        or actual.token_invalid_before != expected[2]
        or any(getattr(actual, key) != value for key, value in names.items())
    ):
        raise HTTPException(403, "当前会话不再具有原文证据超级管理员权限，请重新登录核对")
    return actual


def _row(db, model, key, value, *, writing=False):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError("noncanonical UUID")
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "原文证据标识不规范") from exc
    with db.no_autoflush:
        row = db.query(model).filter(getattr(model, key) == value).populate_existing().with_for_update(read=not writing).one_or_none()
    if row is None:
        raise HTTPException(404, "原文证据不存在")
    return row


def _stored(model, value):
    result = model.model_validate(c.parse_json(value))
    if c.canonical_json(result) != value:
        raise ValueError("Stored original JSON is not the exact canonical object")
    return result


def _governance(row):
    values = {name: getattr(row, name) for name in REVIEW_FIELDS}
    for name in ("reviewed_at", "revoked_at"):
        if values[name] is not None:
            values[name] = c.utc_text(values[name])
    return c.GovernedReview.model_validate(values)


def _publication_governance(row):
    return c.PublicationGovernance(
        status=row.status, revision=row.revision, revoked_by=row.revoked_by, revoked_at=c.utc_text(row.revoked_at) if row.revoked_at else None, revoke_reason=row.revoke_reason
    )


def _initial_review(row):
    row.status, row.revision = "draft", 1
    row.privacy_review = row.faithfulness_review = "unknown"
    row.reviewed_by = row.reviewed_at = row.revoked_by = row.revoked_at = None
    row.review_basis_note = row.revoke_reason = ""


def _cas(row, request, governance):
    if (row.revision, row.content_hash, c.digest(governance)) != (request.expected_revision, request.expected_content_hash, request.expected_governance_hash):
        raise HTTPException(409, "原文证据的内容或治理版本已改变，请重新读取后审核")


def _original_record(row):
    identity = c.parse_json(row.identity_json)
    if not isinstance(identity, dict) or "text" in identity or c.canonical_json(identity) != row.identity_json:
        raise ValueError("Original identity must be exact canonical metadata, without duplicate text")
    snapshot = c.OriginalImmutable.model_validate({**identity, "text": row.original_text})
    if (snapshot.original_id, snapshot.created_by, snapshot.recorded_at, snapshot.raw_bytes_hash, snapshot.raw_bytes_length, snapshot.codepoint_length) != (
        row.original_id,
        row.created_by,
        c.utc_text(row.recorded_at),
        row.raw_bytes_hash,
        row.raw_bytes_length,
        row.codepoint_length,
    ):
        raise ValueError("Original indexed facts differ from the complete immutable original")
    governance = _governance(row)
    reasons = [] if governance.status == "published" else ["original_not_published"]
    return c.OriginalRecord(
        schema_version="document_original_record_v1",
        source_id=f"document_original:{row.original_id}:{row.content_hash[:12]}",
        snapshot=snapshot,
        content_hash=row.content_hash,
        governance=governance,
        governance_hash=c.digest(governance),
        eligible=not reasons,
        ineligibility_reasons=reasons,
        declaration_status=c.DECLARATION,
        clinical_validation="not_provided",
    )


def _candidate_record(db, row, original):
    snapshot = _stored(c.CandidateImmutable, row.candidate_json)
    proposal = snapshot.proposal
    if (
        snapshot.candidate_id,
        snapshot.created_by,
        snapshot.recorded_at,
        proposal.original.original_id,
        proposal.original.content_hash,
        proposal.original.governance_hash,
        proposal.start,
        proposal.end,
    ) != (row.candidate_id, row.created_by, c.utc_text(row.recorded_at), row.original_id, row.original_content_hash, row.original_governance_hash, row.span_start, row.span_end):
        raise ValueError("Candidate indexed facts differ from the complete immutable proposal")
    if proposal.end > original.snapshot.codepoint_length or original.snapshot.text[proposal.start : proposal.end] != proposal.quote:
        raise ValueError("Candidate quote is not the exact original codepoint span")
    if proposal.original.content_hash != original.content_hash or snapshot.recorded_at < (original.governance.reviewed_at or original.snapshot.recorded_at):
        raise ValueError("Candidate original identity or chronology has changed")
    original_current = original.eligible and proposal.original.governance_hash == original.governance_hash
    governance = _governance(row)
    reasons = ([] if original_current else ["original_not_current"]) + ([] if governance.status == "approved" else ["candidate_not_approved"])
    return c.CandidateRecord(
        schema_version="document_span_candidate_record_v1",
        source_id=f"document_candidate:{row.candidate_id}:{row.content_hash[:12]}",
        snapshot=snapshot,
        content_hash=row.content_hash,
        governance=governance,
        governance_hash=c.digest(governance),
        original_current=original_current,
        eligible=not reasons,
        ineligibility_reasons=reasons,
        clinical_validation="not_provided",
    )


def _candidate_rows(db, candidate_id, *, writing=False):
    # The first lookup only identifies immutable parents. Current SHARE/X reads
    # then follow the same Original -> Candidate lock order as every mutation.
    with db.no_autoflush:
        hint = db.query(AIDocumentSpanCandidate.original_id).filter_by(candidate_id=candidate_id).first()
    if hint is None:
        raise HTTPException(404, "原文条款候选不存在")
    original = _row(db, AIDocumentOriginal, "original_id", hint[0])
    candidate = _row(db, AIDocumentSpanCandidate, "candidate_id", candidate_id, writing=writing)
    if candidate.original_id != original.original_id:
        raise ValueError("Candidate parent changed while acquiring locks")
    return original, candidate


def _finish(db, user, epoch, action, target, detail):
    audit(db, user.user_id, action, target, detail)
    db.flush()
    current_super(db, user, expected=epoch)


@_write
def create_original(db, user, values):
    request = values if isinstance(values, c.OriginalCreate) else c.OriginalCreate.model_validate(values)
    epoch = _epoch(user)
    actor = current_super(db, user, expected=epoch)
    text = request.content.text if isinstance(request.content, c.DirectText) else request.content.decoded_text()
    snapshot = c.OriginalImmutable(
        schema_version="document_original_immutable_v1",
        original_id=str(uuid.uuid4()),
        created_by=actor.user_id,
        recorded_at=c.utc_text(utcnow()),
        metadata=request.metadata,
        input_kind=request.content.kind,
        filename=request.content.filename if isinstance(request.content, c.Utf8File) else None,
        raw_bytes_hash=c.bytes_hash(text),
        raw_bytes_length=len(c.utf8(text)),
        codepoint_length=len(text),
        text=text,
    )
    identity = snapshot.model_dump(mode="json", exclude={"text"})
    row = AIDocumentOriginal(
        original_id=snapshot.original_id,
        identity_json=c.canonical_json(identity),
        original_text=text,
        raw_bytes_hash=snapshot.raw_bytes_hash,
        raw_bytes_length=snapshot.raw_bytes_length,
        codepoint_length=snapshot.codepoint_length,
        content_hash=c.digest(snapshot),
        created_by=actor.user_id,
        recorded_at=c.clock(snapshot.recorded_at),
    )
    _initial_review(row)
    db.add(row)
    _finish(db, actor, epoch, "document.original.create", row.original_id, {"content_hash": row.content_hash, "raw_bytes_hash": row.raw_bytes_hash, "raw_bytes_length": row.raw_bytes_length})
    db.refresh(row)
    return _original_record(row)


def original_detail(db, user, original_id):
    current_super(db, user)
    try:
        return _original_record(_row(db, AIDocumentOriginal, "original_id", original_id))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(409, "原文完整性校验失败，不能按已审核原件展示") from exc


def _review(row, request, actor, *, approved_status):
    governance = _governance(row)
    _cas(row, request, governance)
    if row.status != "draft":
        raise HTTPException(409, "只能审核当前草稿；修改原意须登记新的不可变候选或原文")
    now = utcnow()
    if now < row.recorded_at:
        raise HTTPException(409, "当前审核时钟早于原登记钟点")
    row.status = approved_status if request.decision == "approve" else "rejected"
    row.revision = 2
    row.privacy_review, row.faithfulness_review = request.privacy_review, request.faithfulness_review
    row.reviewed_by, row.reviewed_at, row.review_basis_note = actor.user_id, now, request.basis_note


@_write
def review_original(db, user, original_id, values):
    request = values if isinstance(values, c.ReviewRequest) else c.ReviewRequest.model_validate(values)
    epoch = _epoch(user)
    actor = current_super(db, user, expected=epoch)
    row = _row(db, AIDocumentOriginal, "original_id", original_id, writing=True)
    _original_record(row)
    _review(row, request, actor, approved_status="published")
    _finish(db, actor, epoch, "document.original.review", row.original_id, {"content_hash": row.content_hash, "status": row.status, "revision": row.revision})
    db.refresh(row)
    return _original_record(row)


def _revoke(row, request, actor, governance):
    _cas(row, request, governance)
    if row.status == "revoked":
        raise HTTPException(409, "该原文证据已经撤销")
    now = utcnow()
    previous = getattr(row, "reviewed_at", None) or getattr(row, "recorded_at", None) or row.published_at
    if now < previous:
        raise HTTPException(409, "撤销时钟不能早于原记录或审核")
    row.status, row.revision = "revoked", row.revision + 1
    row.revoked_by, row.revoked_at, row.revoke_reason = actor.user_id, now, request.basis_note


@_write
def revoke_original(db, user, original_id, values):
    request = values if isinstance(values, c.RevokeRequest) else c.RevokeRequest.model_validate(values)
    epoch = _epoch(user)
    actor = current_super(db, user, expected=epoch)
    row = _row(db, AIDocumentOriginal, "original_id", original_id, writing=True)
    before = _original_record(row)
    _revoke(row, request, actor, before.governance)
    _finish(db, actor, epoch, "document.original.revoke", row.original_id, {"content_hash": row.content_hash, "revision": row.revision})
    db.refresh(row)
    return _original_record(row)


@_write
def create_candidate(db, user, values):
    request = values if isinstance(values, c.CandidateCreate) else c.CandidateCreate.model_validate(values)
    epoch = _epoch(user)
    actor = current_super(db, user, expected=epoch)
    parent = _row(db, AIDocumentOriginal, "original_id", request.original.original_id)
    original = _original_record(parent)
    if not original.eligible or (original.content_hash, original.governance_hash) != (request.original.content_hash, request.original.governance_hash):
        raise HTTPException(409, "请选择当前已发布且完整绑定的原文版本")
    if request.end > original.snapshot.codepoint_length or original.snapshot.text[request.start : request.end] != request.quote:
        raise HTTPException(422, "候选引文不等于原文Unicode codepoint半开区间，不接受修改或推测")
    snapshot = c.CandidateImmutable(schema_version="document_span_candidate_immutable_v1", candidate_id=str(uuid.uuid4()), created_by=actor.user_id, recorded_at=c.utc_text(utcnow()), proposal=request)
    row = AIDocumentSpanCandidate(
        candidate_id=snapshot.candidate_id,
        original_id=parent.original_id,
        original_content_hash=parent.content_hash,
        original_governance_hash=original.governance_hash,
        span_start=request.start,
        span_end=request.end,
        candidate_json=c.canonical_json(snapshot),
        content_hash=c.digest(snapshot),
        created_by=actor.user_id,
        recorded_at=c.clock(snapshot.recorded_at),
    )
    _initial_review(row)
    db.add(row)
    _finish(db, actor, epoch, "document.candidate.create", row.candidate_id, {"original_id": parent.original_id, "content_hash": row.content_hash, "start": row.span_start, "end": row.span_end})
    db.refresh(row)
    db.refresh(parent)
    return _candidate_record(db, row, _original_record(parent))


def candidate_detail(db, user, candidate_id):
    current_super(db, user)
    try:
        original, row = _candidate_rows(db, candidate_id)
        return _candidate_record(db, row, _original_record(original))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(409, "条款候选或原文完整性校验失败") from exc


@_write
def review_candidate(db, user, candidate_id, values):
    request = values if isinstance(values, c.ReviewRequest) else c.ReviewRequest.model_validate(values)
    epoch = _epoch(user)
    actor = current_super(db, user, expected=epoch)
    parent, row = _candidate_rows(db, candidate_id, writing=True)
    before = _candidate_record(db, row, _original_record(parent))
    if request.decision == "approve" and not before.original_current:
        raise HTTPException(409, "原件已失效，不能批准旧引文")
    _review(row, request, actor, approved_status="approved")
    _finish(db, actor, epoch, "document.candidate.review", row.candidate_id, {"content_hash": row.content_hash, "status": row.status, "revision": row.revision})
    db.refresh(row)
    db.refresh(parent)
    return _candidate_record(db, row, _original_record(parent))


@_write
def revoke_candidate(db, user, candidate_id, values):
    request = values if isinstance(values, c.RevokeRequest) else c.RevokeRequest.model_validate(values)
    epoch = _epoch(user)
    actor = current_super(db, user, expected=epoch)
    parent, row = _candidate_rows(db, candidate_id, writing=True)
    before = _candidate_record(db, row, _original_record(parent))
    _revoke(row, request, actor, before.governance)
    _finish(db, actor, epoch, "document.candidate.revoke", row.candidate_id, {"content_hash": row.content_hash, "revision": row.revision})
    db.refresh(row)
    return _candidate_record(db, row, _original_record(parent))


def _publication_rows(db, publication_id, *, writing=False):
    with db.no_autoflush:
        hint = db.query(AIDocumentKnowledgePublication.original_id, AIDocumentKnowledgePublication.candidate_id).filter_by(publication_id=publication_id).first()
    if hint is None:
        raise HTTPException(404, "知识发布原件不存在")
    original = _row(db, AIDocumentOriginal, "original_id", hint.original_id)
    candidate = _row(db, AIDocumentSpanCandidate, "candidate_id", hint.candidate_id)
    publication = _row(db, AIDocumentKnowledgePublication, "publication_id", publication_id, writing=writing)
    knowledge = _row(db, AIKnowledgeDocument, "document_id", publication.knowledge_document_id, writing=writing)
    if publication.original_id != original.original_id or publication.candidate_id != candidate.candidate_id or candidate.original_id != original.original_id:
        raise ValueError("Publication parent identities changed while acquiring current locks")
    return original, candidate, publication, knowledge


def _publication_record(db, original_row, candidate_row, row, knowledge):
    original = _original_record(original_row)
    candidate = _candidate_record(db, candidate_row, original)
    snapshot = _stored(c.PublicationImmutable, row.publication_json)
    if (
        snapshot.publication_id,
        snapshot.original.original_id,
        snapshot.original.content_hash,
        snapshot.candidate.candidate_id,
        snapshot.candidate.content_hash,
        snapshot.knowledge_document_id,
        snapshot.published_by,
        snapshot.published_at,
    ) != (row.publication_id, row.original_id, row.original_content_hash, row.candidate_id, row.candidate_content_hash, row.knowledge_document_id, row.published_by, c.utc_text(row.published_at)):
        raise ValueError("Publication indexed identities differ from its complete original")
    if snapshot.original.content_hash != original.content_hash or snapshot.candidate.content_hash != candidate.content_hash or snapshot.quote != candidate.snapshot.proposal.quote:
        raise ValueError("Publication quote or complete parent content differs from its frozen anchor")
    if snapshot.published_at < (candidate.governance.reviewed_at or candidate.snapshot.recorded_at):
        raise ValueError("Publication predates the actual candidate review")
    reasons = []
    if not original.eligible or snapshot.original.governance_hash != original.governance_hash:
        reasons.append("original_not_current")
    if not candidate.eligible or snapshot.candidate.governance_hash != candidate.governance_hash:
        reasons.append("candidate_not_approved")
    governance = _publication_governance(row)
    if governance.status != "active":
        reasons.append("publication_revoked")
    if knowledge.status != "published":
        reasons.append("knowledge_not_published")
    km = snapshot.knowledge
    expected = (
        snapshot.knowledge_document_id,
        km.title,
        km.version,
        c.URI_PREFIX + snapshot.publication_id,
        c.SOURCE_KIND,
        None,
        row.content_hash,
        km.category,
        snapshot.quote,
        c.digest(snapshot.quote),
        c.canonical_json(sorted(km.feature_keys)),
        km.department_id,
        c.clock(km.effective_from) if km.effective_from else None,
        c.clock(km.effective_to) if km.effective_to else None,
        snapshot.published_by,
        c.clock(snapshot.knowledge_recorded_at),
        snapshot.published_by,
        c.clock(snapshot.knowledge_recorded_at),
    )
    actual = tuple(
        getattr(knowledge, name)
        for name in (
            "document_id",
            "title",
            "version",
            "source_uri",
            "source_kind",
            "source_reference_id",
            "source_snapshot_hash",
            "category",
            "content",
            "content_hash",
            "feature_keys_json",
            "department_id",
            "effective_from",
            "effective_to",
            "reviewed_by",
            "reviewed_at",
            "created_by",
            "create_time",
        )
    )
    if actual != expected:
        reasons.append("knowledge_changed")
    current = {name: getattr(knowledge, name) for name in c.KnowledgeCurrent.model_fields}
    for name in ("effective_from", "effective_to", "reviewed_at", "create_time"):
        if current[name] is not None:
            current[name] = c.utc_text(current[name])
    return c.PublicationRecord(
        schema_version="document_knowledge_publication_record_v1",
        snapshot=snapshot,
        content_hash=row.content_hash,
        governance=governance,
        governance_hash=c.digest(governance),
        knowledge_current=c.KnowledgeCurrent.model_validate(current),
        eligible=not reasons,
        ineligibility_reasons=reasons,
        clinical_validation="not_provided",
    )


@_write
def publish_candidate(db, user, candidate_id, values):
    request = values if isinstance(values, c.PublishRequest) else c.PublishRequest.model_validate(values)
    epoch = _epoch(user)
    actor = current_super(db, user, expected=epoch)
    parent, row = _candidate_rows(db, candidate_id, writing=True)
    original = _original_record(parent)
    candidate = _candidate_record(db, row, original)
    _cas(row, request, candidate.governance)
    if not candidate.eligible:
        raise HTTPException(409, "只有原件当前有效、隐私与原意逐项批准的候选才能显式发布知识")
    if db.query(AIDocumentKnowledgePublication.publication_id).filter_by(candidate_id=candidate_id).first() is not None:
        raise HTTPException(409, "同一候选只能发布一次；新知识版本须登记新候选并重新审核")
    for key in request.knowledge.feature_keys:
        if key not in FEATURE_BY_KEY:
            raise HTTPException(422, "知识适用功能不存在")
    if request.knowledge.department_id is not None and db.query(Department.department_id).filter_by(department_id=request.knowledge.department_id).with_for_update(read=True).first() is None:
        raise HTTPException(422, "知识适用科室不存在")
    published_at = c.utc_text(utcnow())
    snapshot = c.PublicationImmutable(
        schema_version="document_knowledge_publication_immutable_v1",
        publication_id=str(uuid.uuid4()),
        original=c.OriginalReference(original_id=parent.original_id, content_hash=original.content_hash, governance_hash=original.governance_hash),
        candidate=c.CandidateReference(candidate_id=row.candidate_id, content_hash=candidate.content_hash, governance_hash=candidate.governance_hash),
        published_by=actor.user_id,
        published_at=published_at,
        knowledge_recorded_at=c.utc_text(c.clock(published_at).replace(microsecond=0)),
        knowledge_clock_basis=c.KNOWLEDGE_CLOCK_BASIS,
        publication_basis_note=request.basis_note,
        knowledge_document_id=str(uuid.uuid4()),
        knowledge=request.knowledge,
        quote=candidate.snapshot.proposal.quote,
        quote_bytes_hash=c.bytes_hash(candidate.snapshot.proposal.quote),
    )
    content_hash = c.digest(snapshot)
    km = snapshot.knowledge
    knowledge = AIKnowledgeDocument(
        document_id=snapshot.knowledge_document_id,
        title=km.title,
        version=km.version,
        source_uri=c.URI_PREFIX + snapshot.publication_id,
        source_kind=c.SOURCE_KIND,
        source_reference_id=None,
        source_snapshot_hash=content_hash,
        category=km.category,
        content=snapshot.quote,
        content_hash=c.digest(snapshot.quote),
        feature_keys_json=c.canonical_json(sorted(km.feature_keys)),
        department_id=km.department_id,
        effective_from=c.clock(km.effective_from) if km.effective_from else None,
        effective_to=c.clock(km.effective_to) if km.effective_to else None,
        status="published",
        reviewed_by=actor.user_id,
        reviewed_at=c.clock(snapshot.knowledge_recorded_at),
        created_by=actor.user_id,
        create_time=c.clock(snapshot.knowledge_recorded_at),
    )
    db.add(knowledge)
    db.flush()
    publication = AIDocumentKnowledgePublication(
        publication_id=snapshot.publication_id,
        original_id=parent.original_id,
        original_content_hash=original.content_hash,
        candidate_id=row.candidate_id,
        candidate_content_hash=candidate.content_hash,
        knowledge_document_id=knowledge.document_id,
        publication_json=c.canonical_json(snapshot),
        content_hash=content_hash,
        published_by=actor.user_id,
        published_at=c.clock(published_at),
        status="active",
        revision=1,
        revoked_by=None,
        revoked_at=None,
        revoke_reason="",
    )
    db.add(publication)
    _finish(
        db,
        actor,
        epoch,
        "document.knowledge.publish",
        publication.publication_id,
        {"original_id": parent.original_id, "candidate_id": row.candidate_id, "document_id": knowledge.document_id, "content_hash": content_hash},
    )
    for item in (parent, row, publication, knowledge):
        db.refresh(item)
    result = _publication_record(db, parent, row, publication, knowledge)
    if not result.eligible:
        raise HTTPException(409, "完整知识发布链在接受前已改变，知识与发布记录均未接受")
    return result


def publication_detail(db, user, publication_id):
    current_super(db, user)
    try:
        return _publication_record(db, *_publication_rows(db, publication_id))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(409, "知识发布完整性校验失败，请核对原文证据") from exc


@_write
def revoke_publication(db, user, publication_id, values):
    request = values if isinstance(values, c.RevokeRequest) else c.RevokeRequest.model_validate(values)
    epoch = _epoch(user)
    actor = current_super(db, user, expected=epoch)
    original, candidate, row, knowledge = _publication_rows(db, publication_id, writing=True)
    before = _publication_record(db, original, candidate, row, knowledge)
    _revoke(row, request, actor, before.governance)
    knowledge.status = "retired"
    _finish(db, actor, epoch, "document.knowledge.revoke", row.publication_id, {"document_id": knowledge.document_id, "content_hash": row.content_hash, "revision": row.revision})
    for item in (row, knowledge):
        db.refresh(item)
    return _publication_record(db, original, candidate, row, knowledge)


def is_document_bound_source(document):
    return getattr(document, "source_kind", None) == c.SOURCE_KIND or isinstance(getattr(document, "source_uri", None), str) and document.source_uri.lower().startswith(c.URI_PREFIX)


def document_binding_exists(db, document):
    """The immutable publication FK is also a marker, even if URI/kind are stripped.

    This hint acquires no locks; the validator subsequently re-reads the complete
    dependency chain in the one shared lock order. Knowledge and publication are
    created in the same transaction, so no legitimate older snapshot can contain
    this document without its original publication.
    """
    with db.no_autoflush:
        return db.query(AIDocumentKnowledgePublication.publication_id).filter_by(knowledge_document_id=document.document_id).first() is not None


def bound_source_state(db, document):
    """Return a closed reason; never trust mutable hashes or an old RR snapshot.

    Locking current reads do not prove global serialization against unrelated old
    writers. All new evidence writers follow the shared parent lock order.
    """
    if not is_document_bound_source(document) and not document_binding_exists(db, document):
        return "not_document_evidence"
    try:
        if document.source_kind != c.SOURCE_KIND:
            return "invalid_binding"
        publication_id = c.publication_id_from_uri(document.source_uri)
        original, candidate, publication, knowledge = _publication_rows(db, publication_id)
        if knowledge.document_id != document.document_id:
            return "invalid_binding"
        result = _publication_record(db, original, candidate, publication, knowledge)
        return "current" if result.eligible else result.ineligibility_reasons[0]
    except (HTTPException, ValueError, ValidationError, TypeError, AttributeError, KeyError, UnicodeError):
        return "invalid_binding"


def published_bound_source_is_current(db, document):
    return bound_source_state(db, document) == "current"
