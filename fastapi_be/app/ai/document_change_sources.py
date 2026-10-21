"""Human-declared links and finite comparison scopes, with atomic exact-PK audit.

All methods leave commit to their router. Neither publication nor review mutates
clinical targets, replaces originals, retires rules or invokes a model.
"""

import uuid

from fastapi import HTTPException

from app.ai import document_change_contract as c
from app.ai import document_evidence_sources as originals
from app.ai.document_change_collection import collect_locked, lock_originals, original_ref, preflight_row, target_from_columns
from app.ai.document_change_models import AIDocumentChangeScope, AIDocumentRuleLink
from app.ai.document_change_targets import CaseBudget, sql_octets, target_snapshot
from app.ai.models import AIAuditEvent, utcnow

GOV_FIELDS = (*originals.REVIEW_FIELDS, "dependency_review")
MODELS = {"link": (AIDocumentRuleLink, "link_id", c.LinkImmutable, "link_json"), "scope": (AIDocumentChangeScope, "scope_id", c.ScopeImmutable, "scope_json")}


def governance(row):
    values = {name: getattr(row, name) for name in GOV_FIELDS}
    for name in ("reviewed_at", "revoked_at"):
        if values[name] is not None:
            values[name] = c.e.utc_text(values[name])
    return c.Governance.model_validate(values)


def stored(row, kind):
    _, key, model, field = MODELS[kind]
    snapshot = originals._stored(model, getattr(row, field))
    if (getattr(snapshot, key), snapshot.created_by, snapshot.recorded_at, c.e.digest(snapshot)) != (getattr(row, key), row.created_by, c.e.utc_text(row.recorded_at), row.content_hash):
        raise ValueError("Immutable identity, clock, whole content and indexed facts differ")
    if kind == "link":
        proposal = snapshot.proposal
        ref = target_from_columns(row.target_kind, row.risk_rule_profile_id, row.clinical_pathway_id)
        if (
            proposal.original.original_id,
            proposal.original.content_hash,
            proposal.original.governance_hash,
            proposal.target,
            proposal.expected_target_hash,
            proposal.span.start,
            proposal.span.end,
        ) != (row.original_id, row.original_content_hash, row.original_governance_hash, ref, row.target_snapshot_hash, row.span_start, row.span_end):
            raise ValueError("Link parent, exact span or target indexes changed")
    else:
        request = snapshot.request
        if (
            request.baseline_original.original_id,
            request.baseline_original.content_hash,
            request.baseline_original.governance_hash,
            request.candidate_original.original_id,
            request.candidate_original.content_hash,
            request.candidate_original.governance_hash,
            snapshot.inventory_hash,
            snapshot.inventory.member_count,
        ) != (
            row.baseline_original_id,
            row.baseline_original_content_hash,
            row.baseline_original_governance_hash,
            row.candidate_original_id,
            row.candidate_original_content_hash,
            row.candidate_original_governance_hash,
            row.inventory_hash,
            row.member_count,
        ):
            raise ValueError("Scope parent or complete membership indexes changed")
    return snapshot


def _audit_detail(kind, stage, content_hash, revision):
    return {"schema_version": "document_change_audit_v1", "kind": kind, "stage": stage, "content_hash": content_hash, "revision": revision}


def _audit(db, actor, kind, stage, identifier, content_hash, revision, clock):
    event = AIAuditEvent(
        actor_id=actor.user_id,
        action=f"document_change.{kind}.{stage}",
        target=identifier,
        detail_json=c.e.canonical_json(_audit_detail(kind, stage, content_hash, revision)),
        create_time=clock.replace(microsecond=0),
    )
    db.add(event)
    db.flush([event])
    return event.event_id


def audit_refs(db, row, kind, gov):
    values = c.AuditReferences(created=row.created_audit_event_id, reviewed=row.review_audit_event_id, revoked=row.revoke_audit_event_id)
    identifier = getattr(row, MODELS[kind][1])
    signatures = (
        ("created", values.created, row.created_by, row.recorded_at, 1),
        ("reviewed", values.reviewed, row.reviewed_by, row.reviewed_at, 2),
        ("revoked", values.revoked, row.revoked_by, row.revoked_at, gov.revision),
    )
    for stage, event_id, actor_id, clock, revision in signatures:
        if event_id is None:
            continue
        with db.no_autoflush:
            event = db.query(AIAuditEvent).filter_by(event_id=event_id).populate_existing().with_for_update(read=True).one_or_none()
        expected = (actor_id, f"document_change.{kind}.{stage}", identifier, c.e.canonical_json(_audit_detail(kind, stage, row.content_hash, revision)), clock.replace(microsecond=0))
        if event is None or tuple(getattr(event, field) for field in ("actor_id", "action", "target", "detail_json", "create_time")) != expected:
            raise ValueError("An exact audit primary key does not match the actual mutation")
    return values


def link_record(db, row, original, target):
    snapshot, gov = stored(row, "link"), governance(row)
    proposal = snapshot.proposal
    if (
        proposal.span.end > original.snapshot.codepoint_length
        or original.snapshot.text[proposal.span.start : proposal.span.end] != proposal.span.quote
        or proposal.original.content_hash != original.content_hash
    ):
        raise ValueError("The actual original and exact Unicode span differ")
    is_original = original.eligible and proposal.original == original_ref(original)
    is_target = target.state == "current" and target == snapshot.target_snapshot
    reasons = ([] if gov.status == "published" else ["link_not_published"]) + ([] if is_original else ["original_changed"]) + ([] if is_target else ["target_changed"])
    return c.LinkRecord(
        schema_version="document_rule_link_record_v1",
        snapshot=snapshot,
        content_hash=row.content_hash,
        governance=gov,
        governance_hash=c.e.digest(gov),
        original_current=is_original,
        target_current=is_target,
        audit_event_ids=audit_refs(db, row, "link", gov),
        eligible=not reasons,
        ineligibility_reasons=reasons,
        declaration_status=c.DECLARATION,
        clinical_validation="not_provided",
    )


def _initial(row):
    originals._initial_review(row)
    row.dependency_review = "unknown"
    row.review_audit_event_id = row.revoke_audit_event_id = None


def _post_actor(db, actor, epoch):
    db.flush()
    originals.current_super(db, actor, expected=epoch)


@originals._write
def create_link(db, user, values):
    request = c.LinkCreate.model_validate(values)
    epoch = originals._epoch(user)
    actor, parents, budget = lock_originals(db, user, [request.original.original_id])
    original = parents[request.original.original_id][1]
    if not original.eligible or request.original != original_ref(original) or original.snapshot.text[request.span.start : request.span.end] != request.span.quote:
        raise HTTPException(409, "原件已变化、未确认发布或引文并非完整逐字范围")
    target = target_snapshot(db, request.target, budget)
    if target.state != "current" or c.e.digest(target) != request.expected_target_hash:
        raise HTTPException(409, "实际目标不是刚审阅的当前完整版本")
    now, identifier = utcnow(), str(uuid.uuid4())
    if c.e.utc_text(now) < original.governance.reviewed_at:
        raise ValueError("Link creation predates original publication")
    snapshot = c.LinkImmutable(schema_version="document_rule_link_immutable_v1", link_id=identifier, created_by=actor.user_id, recorded_at=c.e.utc_text(now), proposal=request, target_snapshot=target)
    event_id = _audit(db, actor, "link", "created", identifier, c.e.digest(snapshot), 1, now)
    row = AIDocumentRuleLink(
        link_id=identifier,
        original_id=request.original.original_id,
        original_content_hash=request.original.content_hash,
        original_governance_hash=request.original.governance_hash,
        target_kind=request.target.kind,
        risk_rule_profile_id=request.target.target_id if request.target.kind == "risk_rule_profile" else None,
        clinical_pathway_id=request.target.target_id if request.target.kind == "clinical_pathway" else None,
        target_snapshot_hash=request.expected_target_hash,
        span_start=request.span.start,
        span_end=request.span.end,
        link_json=c.e.canonical_json(snapshot),
        content_hash=c.e.digest(snapshot),
        created_by=actor.user_id,
        recorded_at=now,
        created_audit_event_id=event_id,
    )
    _initial(row)
    db.add(row)
    _post_actor(db, actor, epoch)
    db.refresh(row)
    result = link_record(
        db,
        row,
        originals._original_record(originals._row(db, type(parents[request.original.original_id][0]), "original_id", request.original.original_id, writing=True)),
        target_snapshot(db, request.target),
    )
    if not result.original_current or not result.target_current:
        raise ValueError("Link parents changed after SQL flush")
    return result


def _open(db, user, kind, identifier, *, writing=False):
    model, key, _, field = MODELS[kind]
    # Immutable technical hint only; never lock a Link/Scope before its parents.
    with db.no_autoflush:
        columns = (model.original_id,) if kind == "link" else (model.baseline_original_id, model.candidate_original_id)
        hint = db.query(*columns).filter(getattr(model, key) == identifier).first()
    if hint is None:
        raise HTTPException(404, "文档关联或有限对比范围不存在")
    actor, parents, budget = lock_originals(db, user, list(hint))
    # Scope writes/reads lock target parents before Scope, and Link before its
    # own row. Full scope collection is built before the final current row read.
    if kind == "link":
        with db.no_autoflush:
            target_hint = db.query(model.target_kind, model.risk_rule_profile_id, model.clinical_pathway_id).filter_by(link_id=identifier).with_for_update(read=True).first()
        if target_hint is None:
            raise ValueError("Link disappeared during parent locking")
        target = target_snapshot(db, target_from_columns(*target_hint), budget)
        current_inventory = target
    else:
        # The immutable Scope request is read only after both parent X locks;
        # all Scope writers use this order. Preflight before loading MEDIUMTEXT.
        with db.no_autoflush:
            size = db.query(sql_octets(getattr(model, field))).filter(getattr(model, key) == identifier).scalar()
            CaseBudget(reserve=0).check_raw(size)
            raw = db.query(getattr(model, field)).filter(getattr(model, key) == identifier).scalar()
        # Immutable-only hint is not locked before targets. Authorized writers
        # never update this JSON; the final current row must match it exactly.
        snapshot = originals._stored(c.ScopeImmutable, raw)
        current_inventory = collect_locked(db, snapshot.request, parents, budget, validate_references=False)
    row = preflight_row(db, model, key, identifier, (field,), CaseBudget(), writing=writing)
    current_snapshot = stored(row, kind)
    if kind == "scope" and current_snapshot != snapshot:
        raise ValueError("Current Scope immutable differs from its technical hint")
    snapshot = current_snapshot
    actual_parents = [snapshot.proposal.original.original_id] if kind == "link" else [snapshot.request.baseline_original.original_id, snapshot.request.candidate_original.original_id]
    if set(actual_parents) != set(parents):
        raise ValueError("Current indexed parents differ from the immutable technical hint")
    return actor, row, parents, current_inventory


def _record(db, row, parents, current, kind):
    if kind == "link":
        return link_record(db, row, parents[row.original_id][1], current)
    snapshot, gov = stored(row, kind), governance(row)
    unchanged = c.e.digest(current) == snapshot.inventory_hash
    reasons = ([] if gov.status == "published" else ["scope_not_published"]) + ([] if unchanged else ["inventory_changed"])
    return c.ScopeRecord(
        schema_version="document_change_scope_record_v1",
        snapshot=snapshot,
        content_hash=row.content_hash,
        governance=gov,
        governance_hash=c.e.digest(gov),
        inventory_current=unchanged,
        audit_event_ids=audit_refs(db, row, kind, gov),
        eligible=not reasons,
        ineligibility_reasons=reasons,
        hospital_wide_rule_inventory="not_provided",
        automatic_supersession=False,
        clinical_validation="not_provided",
    )


@originals._write
def link_detail(db, user, identifier):
    _, row, parents, current = _open(db, user, "link", identifier)
    return _record(db, row, parents, current, "link")


@originals._write
def scope_detail(db, user, identifier):
    _, row, parents, current = _open(db, user, "scope", identifier)
    return _record(db, row, parents, current, "scope")


@originals._write
def capture_scope(db, user, values):
    request = c.ScopeCaptureRequest.model_validate(values)
    epoch = originals._epoch(user)
    actor, parents, budget = lock_originals(db, user, [request.baseline_original.original_id, request.candidate_original.original_id])
    inventory = collect_locked(db, request, parents, budget)
    originals.current_super(db, actor, expected=epoch)
    return {
        "schema_version": "document_change_capture_v1",
        "request": request.model_dump(mode="json"),
        "inventory": inventory.model_dump(mode="json"),
        "inventory_hash": c.e.digest(inventory),
        "member_count": inventory.member_count,
        "hospital_wide_rule_inventory": "not_provided",
        "automatic_supersession": False,
        "clinical_validation": "not_provided",
    }


@originals._write
def create_scope(db, user, values):
    request = c.ScopeCreate.model_validate(values)
    capture = c.ScopeCaptureRequest.model_validate(request.model_dump(exclude={"expected_inventory_hash"}))
    epoch = originals._epoch(user)
    actor, parents, budget = lock_originals(db, user, [capture.baseline_original.original_id, capture.candidate_original.original_id])
    inventory = collect_locked(db, capture, parents, budget)
    if c.e.digest(inventory) != request.expected_inventory_hash:
        raise HTTPException(409, "完整原件、关联、发布或目标集合已改变，请重看全部范围")
    now, identifier = utcnow(), str(uuid.uuid4())
    if any(c.e.utc_text(now) < value[1].governance.reviewed_at for value in parents.values()):
        raise ValueError("Scope creation predates original publication")
    snapshot = c.ScopeImmutable(
        schema_version="document_change_scope_immutable_v1",
        scope_id=identifier,
        created_by=actor.user_id,
        recorded_at=c.e.utc_text(now),
        request=capture,
        inventory_hash=request.expected_inventory_hash,
        inventory=inventory,
    )
    event_id = _audit(db, actor, "scope", "created", identifier, c.e.digest(snapshot), 1, now)
    row = AIDocumentChangeScope(
        scope_id=identifier,
        baseline_original_id=capture.baseline_original.original_id,
        baseline_original_content_hash=capture.baseline_original.content_hash,
        baseline_original_governance_hash=capture.baseline_original.governance_hash,
        candidate_original_id=capture.candidate_original.original_id,
        candidate_original_content_hash=capture.candidate_original.content_hash,
        candidate_original_governance_hash=capture.candidate_original.governance_hash,
        inventory_hash=request.expected_inventory_hash,
        member_count=inventory.member_count,
        scope_json=c.e.canonical_json(snapshot),
        content_hash=c.e.digest(snapshot),
        created_by=actor.user_id,
        recorded_at=now,
        created_audit_event_id=event_id,
    )
    _initial(row)
    db.add(row)
    _post_actor(db, actor, epoch)
    db.refresh(row)
    fresh = capture_scope(db, actor, capture)
    if fresh["inventory_hash"] != snapshot.inventory_hash:
        raise ValueError("The complete dependency set changed after SQL flush")
    return _record(db, row, parents, inventory, "scope")


@originals._write
def _mutate(db, user, kind, identifier, values, *, revoke=False):
    request = c.e.RevokeRequest.model_validate(values) if revoke else c.ReviewRequest.model_validate(values)
    epoch = originals._epoch(user)
    actor, row, parents, current = _open(db, user, kind, identifier, writing=True)
    before = _record(db, row, parents, current, kind)
    originals._cas(row, request, before.governance)
    now = utcnow()
    if revoke:
        originals._revoke(row, request, actor, before.governance)
        stage, audit_column = "revoked", "revoke_audit_event_id"
    else:
        if row.status != "draft":
            raise HTTPException(409, "仅未审核草稿可显式审核，已审核条目不可覆盖")
        if request.decision == "approve" and (not before.original_current or not before.target_current if kind == "link" else not before.inventory_current):
            raise HTTPException(409, "当前原件或完整依赖已改变，不能发布旧范围")
        if now < row.recorded_at:
            raise ValueError("Review cannot predate registration")
        row.status, row.revision = ("published" if request.decision == "approve" else "rejected"), 2
        row.privacy_review, row.faithfulness_review, row.dependency_review = request.privacy_review, request.faithfulness_review, request.dependency_review
        row.reviewed_by, row.reviewed_at, row.review_basis_note = actor.user_id, now, request.basis_note
        stage, audit_column = "reviewed", "review_audit_event_id"
    # The row's CHECK requires audit FK and signature atomically. Prevent
    # autoflush until the separately inserted audit event has its exact PK.
    with db.no_autoflush:
        event_id = _audit(db, actor, kind, stage, identifier, row.content_hash, row.revision, row.revoked_at if revoke else now)
        setattr(row, audit_column, event_id)
    _post_actor(db, actor, epoch)
    db.refresh(row)
    _, fresh, parents, current = _open(db, actor, kind, identifier, writing=True)
    result = _record(db, fresh, parents, current, kind)
    if not revoke and request.decision == "approve" and not result.eligible:
        raise ValueError("Actual parents or complete dependency set changed after review flush")
    return result


def review_link(db, user, identifier, values):
    return _mutate(db, user, "link", identifier, values)


def revoke_link(db, user, identifier, values):
    return _mutate(db, user, "link", identifier, values, revoke=True)


def review_scope(db, user, identifier, values):
    return _mutate(db, user, "scope", identifier, values)


def revoke_scope(db, user, identifier, values):
    return _mutate(db, user, "scope", identifier, values, revoke=True)


def public_source(record):
    """Mechanical complete projection; free notes and clinical target text stay private."""
    record = c.ScopeRecord.model_validate(record)
    snapshot, inventory = record.snapshot, record.snapshot.inventory
    declared = {c.target_key(value) for value in snapshot.request.declared_targets}

    def original(value):
        return c.DocumentChangeOriginal(
            schema_version="document_change_original_source_v1",
            original=original_ref(value),
            raw_bytes_hash=value.snapshot.raw_bytes_hash,
            raw_bytes_length=value.snapshot.raw_bytes_length,
            codepoint_length=value.snapshot.codepoint_length,
            text=value.snapshot.text,
        )

    return c.DocumentChangeSource(
        schema_version=c.SCHEMA_VERSION,
        scope=c.ScopeReference(scope_id=snapshot.scope_id, content_hash=record.content_hash, governance_hash=record.governance_hash),
        baseline=original(inventory.baseline_original),
        candidate=original(inventory.candidate_original),
        relationship_kind=snapshot.request.relationship.kind,
        same_guideline_family=snapshot.request.relationship.same_guideline_family,
        rule_link_coverage=snapshot.request.rule_link_coverage,
        targets=[c.PublicTarget(target=value.target, snapshot_hash=c.e.digest(value), state=value.state, within_declared_scope=c.target_key(value.target) in declared) for value in inventory.targets],
        rule_links=[
            c.PublicRuleLink(
                link_id=value.snapshot.link_id,
                content_hash=value.content_hash,
                governance_hash=value.governance_hash,
                original=value.snapshot.proposal.original,
                start=value.snapshot.proposal.span.start,
                end=value.snapshot.proposal.span.end,
                quote_bytes_hash=c.e.bytes_hash(value.snapshot.proposal.span.quote),
                target=value.snapshot.proposal.target,
                target_snapshot_hash=value.snapshot.proposal.expected_target_hash,
                dependency_kind=value.snapshot.proposal.dependency_kind,
                current=value.eligible,
                within_declared_scope=c.target_key(value.snapshot.proposal.target) in declared,
            )
            for value in inventory.rule_links
        ],
        publications=[
            c.PublicPublication(
                publication_id=value.publication.snapshot.publication_id,
                content_hash=value.publication.content_hash,
                governance_hash=value.publication.governance_hash,
                original=value.publication.snapshot.original,
                candidate=value.publication.snapshot.candidate,
                knowledge_document_id=value.publication.snapshot.knowledge_document_id,
                knowledge_content_hash=value.publication.knowledge_current.content_hash,
                bound_source_current=value.publication.eligible,
                ineligibility_reasons=value.publication.ineligibility_reasons,
            )
            for value in inventory.publications
        ],
        member_count=inventory.member_count,
        inventory_hash=snapshot.inventory_hash,
        hospital_wide_rule_inventory="not_provided",
        clinical_validation="not_provided",
    )


@originals._write
def authorize_scope(db, user, identifier, *, expected_content_hash=None, expected_governance_hash=None):
    record = scope_detail(db, user, identifier)
    if (
        not record.eligible
        or expected_content_hash is not None
        and record.content_hash != expected_content_hash
        or expected_governance_hash is not None
        and record.governance_hash != expected_governance_hash
    ):
        raise HTTPException(409, "完整有限范围或当前发布治理已改变，不能用于新的影响核对")
    return record, public_source(record)
