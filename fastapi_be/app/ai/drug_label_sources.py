"""Explicit Super releases and personal pharmacist signatures, no model calls.

Every entry takes InventoryGate first. Opaque locator hints precede sorted User
SHARE locks and are rechecked under SKU -> Original -> Binding -> Review locks.
The caller owns commit; failed acceptance rolls back the full action and audit.
"""

import uuid
from functools import wraps

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.ai import document_evidence_contract as d
from app.ai import document_evidence_sources as documents
from app.ai import drug_label_contract as c
from app.ai.document_evidence_models import AIDocumentOriginal
from app.ai.drug_label_models import AIDrugLabelProfessionalReview, AIDrugLabelSource
from app.ai.inventory_write_guard import current_inventory_rows, lock_inventory_gate
from app.ai.models import AIAuditEvent, utcnow
from app.models import Pharmaceutical, User


def _write(function):
    @wraps(function)
    def operation(db, *args, **kwargs):
        try:
            return function(db, *args, **kwargs)
        except Exception as exc:
            db.rollback()
            if isinstance(exc, HTTPException):
                raise
            if isinstance(exc, (ValueError, ValidationError, SQLAlchemyError, UnicodeError)):
                raise HTTPException(409, "说明书身份、完整原件、签署或审计发生冲突，整笔未接受") from exc
            raise

    return operation


def _key(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise HTTPException(422, "说明书来源标识不规范")
    return value


def _user_hint(user):
    state = inspect(user, raiseerr=False)
    if state is not None:
        identifier = state.identity[0] if state.identity else state.dict.get("user_id")
        epoch = (state.dict.get("user_role"), state.dict.get("token_invalid_before")) if "user_role" in state.dict else None
    else:
        identifier, epoch = getattr(user, "user_id", None), (getattr(user, "user_role", None), getattr(user, "token_invalid_before", None))
    if type(identifier) is not int or identifier < 1:
        raise HTTPException(403, "当前说明书账户无效")
    return identifier, epoch


def _actors(db, user, additional=(), *, roles=c.SOURCE_ROLES):
    identifier, epoch = _user_hint(user)
    actual = {}
    with db.no_autoflush:
        for user_id in sorted({identifier, *additional}):
            row = current_inventory_rows(db.query(User).filter_by(user_id=user_id), shared=True).one_or_none()
            if row is not None:
                actual[user_id] = row
    actor = actual.get(identifier)
    if actor is None or actor.user_role not in roles or epoch is not None and epoch != (actor.user_role, actor.token_invalid_before):
        raise HTTPException(403, "当前账户角色或会话已改变，请重新核对说明书权限")
    return actor, actual, (actor.user_role, actor.token_invalid_before)


def current_actor(db, user, *, allowed_roles=c.SOURCE_ROLES):
    with db.no_autoflush:
        lock_inventory_gate(db)
        return _actors(db, user, roles=allowed_roles)[0]


def identity(row):
    return c.Identity(**{name: getattr(row, name) for name in c.COMPARISON_FIELDS})


def _stored(model, raw):
    value = model.model_validate(d.parse_json(raw))
    if d.canonical_json(value) != raw:
        raise ValueError("Stored snapshot is not exact canonical JSON")
    return value


def _snapshot(row):
    value = _stored(c.SourceSnapshot, row.snapshot_json)
    if (
        value.source_binding_id,
        value.identity.pharmaceutical_id,
        value.created_by,
        d.clock(value.recorded_at),
        value.identity_hash,
        value.original.snapshot.original_id,
        value.original.content_hash,
        value.original.governance_hash,
        d.digest(value),
    ) != (row.source_binding_id, row.pharmaceutical_id, row.created_by, row.recorded_at, row.identity_hash, row.original_id, row.original_content_hash, row.original_governance_hash, row.content_hash):
        raise ValueError("Original source indexed anchors mismatch")
    return value


def _professional(row):
    if row is None:
        return None
    snapshot = _stored(c.ProfessionalSnapshot, row.snapshot_json)
    if (snapshot.professional_review_id, snapshot.source_binding_id, snapshot.source_content_hash, snapshot.signed_by, d.clock(snapshot.signed_at), d.digest(snapshot)) != (
        row.professional_review_id,
        row.source_binding_id,
        row.source_content_hash,
        row.signed_by,
        row.signed_at,
        row.content_hash,
    ):
        raise ValueError("Actual professional signature anchors mismatch")
    governance = c.ProfessionalGovernance(
        status=row.status, revision=row.revision, revoked_by=row.revoked_by, revoked_at=d.utc_text(row.revoked_at) if row.revoked_at else None, revoke_reason=row.revoke_reason
    )
    return c.ProfessionalRecord(schema_version="drug_label_professional_record_v1", snapshot=snapshot, content_hash=row.content_hash, governance=governance, governance_hash=d.digest(governance))


def _governance(row):
    professional = None
    if row.professional_review_id is not None:
        professional = c.ProfessionalReference(professional_review_id=row.professional_review_id, content_hash=row.professional_content_hash, governance_hash=row.professional_governance_hash)
    elif row.professional_content_hash is not None or row.professional_governance_hash is not None:
        raise ValueError("Partial professional publication reference")
    return c.SourceGovernance(
        status=row.status,
        revision=row.revision,
        professional=professional,
        reviewed_by=row.reviewed_by,
        reviewed_at=d.utc_text(row.reviewed_at) if row.reviewed_at else None,
        review_basis_note=row.review_basis_note,
        revoked_by=row.revoked_by,
        revoked_at=d.utc_text(row.revoked_at) if row.revoked_at else None,
        revoke_reason=row.revoke_reason,
    )


def _view(row, snapshot, professional, actor, *, sku_current, original_current, signer_current, audit_only=False):
    gov = _governance(row)
    reasons = []
    for condition, reason in (
        (gov.status == "published", "source_not_published"),
        (sku_current, "identity_changed"),
        (original_current, "original_not_current"),
        (professional is not None and professional.governance.status == "signed", "professional_not_current"),
        (signer_current, "signer_not_current"),
    ):
        if not condition:
            reasons.append(reason)
    if audit_only:
        reasons.append("audit_only")
    independent = actor.user_id not in {snapshot.created_by, snapshot.original.snapshot.created_by}
    operational = not audit_only and sku_current and original_current
    return c.SourceRecord(
        schema_version="drug_label_source_record_v1",
        source_id=f"drug_label_source:{row.source_binding_id}:{row.content_hash[:12]}",
        snapshot=snapshot,
        content_hash=row.content_hash,
        governance=gov,
        governance_hash=d.digest(gov),
        professional_review=professional,
        identity_current=sku_current,
        original_current=original_current,
        signer_current=signer_current,
        audit_only=audit_only,
        eligible=not reasons,
        exclusion_reasons=reasons,
        can_sign=operational and actor.user_role == "pharmacist" and independent and row.status == "draft" and professional is None,
        can_review=operational and actor.user_role == "super_admin" and row.status == "draft",
        can_revoke=not audit_only and actor.user_role == "super_admin" and row.status != "revoked",
        clinical_validation="not_provided",
        licensure_verification="not_provided",
        missing_evidence=list(c.UNKNOWN_EVIDENCE),
    )


def _load(db, user, binding_id, *, writing=False, audit_only=False):
    binding_id = _key(binding_id)
    with db.no_autoflush:
        lock_inventory_gate(db)
        # Only opaque locators, never source text; a stale RR hint is rejected
        # after the actual current locked reads, not silently rebound.
        hint = db.query(AIDrugLabelSource.pharmaceutical_id, AIDrugLabelSource.original_id).filter_by(source_binding_id=binding_id).one_or_none()
        sign_hint = db.query(AIDrugLabelProfessionalReview.signed_by).filter_by(source_binding_id=binding_id).one_or_none()
        actor, actors, epoch = _actors(db, user, () if sign_hint is None else (sign_hint[0],))
        if audit_only and actor.user_role != "super_admin":
            raise HTTPException(403, "只有当前超级管理员可读取说明书冻结审计")
        if hint is None:
            raise HTTPException(404, "说明书来源不存在")
        sku = current_inventory_rows(db.query(Pharmaceutical).filter_by(pharmaceutical_id=hint[0]), shared=not writing).one_or_none()
        original = current_inventory_rows(db.query(AIDocumentOriginal).filter_by(original_id=hint[1]), shared=True).one_or_none()
        row = current_inventory_rows(db.query(AIDrugLabelSource).filter_by(source_binding_id=binding_id), shared=not writing).one_or_none()
        prof_row = current_inventory_rows(db.query(AIDrugLabelProfessionalReview).filter_by(source_binding_id=binding_id), shared=not writing).one_or_none()
        if row is None or (row.pharmaceutical_id, row.original_id) != tuple(hint) or (prof_row.signed_by if prof_row else None) != (sign_hint[0] if sign_hint else None):
            raise HTTPException(409, "说明书来源集合已改变，请刷新重读")
        snapshot, professional = _snapshot(row), _professional(prof_row)
        original_value = documents._original_record(original) if original is not None else None
        sku_current = sku is not None and type(sku.status) is int and sku.status == 0 and d.digest(identity(sku)) == snapshot.identity_hash
        original_current = (
            original_value is not None
            and original_value.eligible
            and original_value.content_hash == snapshot.original.content_hash
            and original_value.governance_hash == snapshot.original.governance_hash
        )
        signer = actors.get(prof_row.signed_by) if prof_row else None
        signer_current = signer is not None and signer.user_role == "pharmacist"
        value = _view(row, snapshot, professional, actor, sku_current=sku_current, original_current=original_current, signer_current=signer_current, audit_only=audit_only)
        return actor, epoch, row, prof_row, value


def source_current(db, user, binding_id, *, audit_only=False, execution=False):
    try:
        actor, _, row, _, value = _load(db, user, binding_id, audit_only=audit_only)
        if execution and (audit_only or not value.eligible):
            raise HTTPException(409, "本说明书来源尚未满足当前独立签署和发布条件")
        if not audit_only and (
            not value.identity_current
            or not value.original_current
            or row.status in {"rejected", "revoked"}
            or value.professional_review is not None
            and (not value.signer_current or value.professional_review.governance.status != "signed")
        ):
            raise HTTPException(409, "当前来源已失效；未返回旧原文，超级管理员须明确读取冻结审计")
        return value
    except (ValueError, ValidationError) as exc:
        raise HTTPException(409, "说明书完整原件或签署链无法核对") from exc


def _cas(record, request):
    if (request.expected_revision, request.expected_content_hash, request.expected_governance_hash) != (record.governance.revision, record.content_hash, record.governance_hash):
        raise HTTPException(409, "说明书审核版本已改变，请刷新后显式重审")


def _columns(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _finish(db, user, row, action, *, expected_prof=None):
    expected = _columns(row)
    prof_expected = _columns(expected_prof) if expected_prof is not None else None
    detail = d.canonical_json(
        {"content_hash": row.content_hash, "governance_hash": d.digest(_governance(row)), "professional_content_hash": expected_prof.content_hash if expected_prof is not None else None}
    )
    event = AIAuditEvent(actor_id=user.user_id, action=action, target=row.source_binding_id, detail_json=detail)
    db.add(event)
    db.flush()
    event_id = event.event_id
    actor, _, actual, prof_row, value = _load(db, user, row.source_binding_id, writing=True)
    audit = current_inventory_rows(db.query(AIAuditEvent).filter_by(event_id=event_id), shared=True).one_or_none()
    if (
        _columns(actual) != expected
        or prof_expected is not None
        and (prof_row is None or _columns(prof_row) != prof_expected)
        or audit is None
        or (audit.actor_id, audit.action, audit.target, audit.detail_json) != (actor.user_id, action, row.source_binding_id, detail)
    ):
        raise HTTPException(409, "说明书或具体审计回读不符，整笔未接受")
    if action != "drug_label.source.revoke" and action != "drug_label.professional.revoke" and (not value.identity_current or not value.original_current):
        raise HTTPException(409, "签署后原件或药品身份发生变化，整笔未接受")
    if action == "drug_label.source.review" and actual.status == "published" and not value.eligible:
        raise HTTPException(409, "发布后专业签署不再有效，整笔未接受")
    return value


@_write
def create_source(db, user, values):
    request = values if isinstance(values, c.SourceCreate) else c.SourceCreate.model_validate(values)
    with db.no_autoflush:
        lock_inventory_gate(db)
        actor, _, _ = _actors(db, user, roles={"super_admin"})
        sku = current_inventory_rows(db.query(Pharmaceutical).filter_by(pharmaceutical_id=request.pharmaceutical_id)).one_or_none()
        if sku is None or type(sku.status) is not int or sku.status != 0:
            raise HTTPException(409, "须选择当前明确启用的真实目录药品")
        current_identity = identity(sku)
        if d.digest(current_identity) != request.expected_identity_hash:
            raise HTTPException(409, "目录身份已改变，请重读原身份后绑定")
        original_row = current_inventory_rows(db.query(AIDocumentOriginal).filter_by(original_id=request.original.original_id), shared=True).one_or_none()
        if original_row is None:
            raise HTTPException(404, "完整说明书原件不存在")
        original = documents._original_record(original_row)
        if not original.eligible or (original.snapshot.original_id, original.content_hash, original.governance_hash) != (
            request.original.original_id,
            request.original.content_hash,
            request.original.governance_hash,
        ):
            raise HTTPException(409, "已发布说明书原件已改变，请重新核对")
        snapshot = c.SourceSnapshot(
            schema_version="drug_label_source_immutable_v1",
            source_binding_id=str(uuid.uuid4()),
            created_by=actor.user_id,
            recorded_at=d.utc_text(utcnow()),
            identity=current_identity,
            identity_hash=request.expected_identity_hash,
            original=original,
            comparison_fields=list(c.COMPARISON_FIELDS),
            basis_note=request.basis_note,
        )
        row = AIDrugLabelSource(
            source_binding_id=snapshot.source_binding_id,
            pharmaceutical_id=sku.pharmaceutical_id,
            original_id=original.snapshot.original_id,
            original_content_hash=original.content_hash,
            original_governance_hash=original.governance_hash,
            identity_hash=snapshot.identity_hash,
            snapshot_json=d.canonical_json(snapshot),
            content_hash=d.digest(snapshot),
            created_by=actor.user_id,
            recorded_at=d.clock(snapshot.recorded_at),
            status="draft",
            revision=1,
            professional_review_id=None,
            professional_content_hash=None,
            professional_governance_hash=None,
            reviewed_by=None,
            reviewed_at=None,
            review_basis_note="",
            revoked_by=None,
            revoked_at=None,
            revoke_reason="",
        )
        c.bounded(_view(row, snapshot, None, actor, sku_current=True, original_current=True, signer_current=False))
        db.add(row)
        return _finish(db, actor, row, "drug_label.source.create")


@_write
def sign_source(db, user, binding_id, values):
    request = values if isinstance(values, c.ProfessionalSign) else c.ProfessionalSign.model_validate(values)
    actor, _, row, _, before = _load(db, user, binding_id, writing=True)
    _cas(before, request)
    if not before.can_sign:
        raise HTTPException(403 if actor.user_role != "pharmacist" else 409, "须当前独立药师本人签署未复核的有效原件；不能代签或跨角色自签")
    snapshot = c.ProfessionalSnapshot(
        schema_version="drug_label_professional_immutable_v1",
        professional_review_id=str(uuid.uuid4()),
        source_binding_id=binding_id,
        source_content_hash=row.content_hash,
        original_content_hash=row.original_content_hash,
        original_governance_hash=row.original_governance_hash,
        identity_hash=row.identity_hash,
        signed_by=actor.user_id,
        signed_at=d.utc_text(utcnow()),
        signature_basis="current_application_pharmacist_role",
        catalog_match_review=request.catalog_match_review,
        provided_text_version_review=request.provided_text_version_review,
        basis_note=request.basis_note,
    )
    prof = AIDrugLabelProfessionalReview(
        professional_review_id=snapshot.professional_review_id,
        source_binding_id=binding_id,
        source_content_hash=row.content_hash,
        snapshot_json=d.canonical_json(snapshot),
        content_hash=d.digest(snapshot),
        signed_by=actor.user_id,
        signed_at=d.clock(snapshot.signed_at),
        status="signed",
        revision=1,
        revoked_by=None,
        revoked_at=None,
        revoke_reason="",
    )
    c.bounded(_view(row, before.snapshot, _professional(prof), actor, sku_current=True, original_current=True, signer_current=True))
    db.add(prof)
    return _finish(db, actor, row, "drug_label.professional.sign", expected_prof=prof)


@_write
def review_source(db, user, binding_id, values):
    request = values if isinstance(values, c.SourceReview) else c.SourceReview.model_validate(values)
    actor, _, row, prof, before = _load(db, user, binding_id, writing=True)
    _cas(before, request)
    if not before.can_review:
        raise HTTPException(403 if actor.user_role != "super_admin" else 409, "仅当前超级管理员可审核有效草稿")
    if request.professional is not None:
        actual = before.professional_review
        if actual is None or (request.professional.professional_review_id, request.professional.content_hash, request.professional.governance_hash) != (
            actual.snapshot.professional_review_id,
            actual.content_hash,
            actual.governance_hash,
        ):
            raise HTTPException(409, "专业签署不是本件当前完整原件")
    if request.decision == "approve":
        actual = before.professional_review
        if (
            not before.signer_current
            or actual is None
            or actual.governance.status != "signed"
            or (actual.snapshot.catalog_match_review, actual.snapshot.provided_text_version_review) != ("confirmed", "confirmed")
            or actor.user_id == actual.snapshot.signed_by
        ):
            raise HTTPException(409, "未知、不确认、失效或非独立的专业签署不能技术发布")
    row.status, row.revision = ("published" if request.decision == "approve" else "rejected"), 2
    row.reviewed_by, row.reviewed_at, row.review_basis_note = actor.user_id, utcnow(), request.basis_note
    if request.decision == "approve":
        row.professional_review_id, row.professional_content_hash, row.professional_governance_hash = (
            request.professional.professional_review_id,
            request.professional.content_hash,
            request.professional.governance_hash,
        )
    c.bounded(_view(row, before.snapshot, before.professional_review, actor, sku_current=True, original_current=True, signer_current=before.signer_current))
    return _finish(db, actor, row, "drug_label.source.review", expected_prof=prof)


@_write
def revoke_source(db, user, binding_id, values):
    request = values if isinstance(values, c.RevokeRequest) else c.RevokeRequest.model_validate(values)
    actor, _, row, prof, before = _load(db, user, binding_id, writing=True, audit_only=True)
    _cas(before, request)
    if actor.user_role != "super_admin" or row.status == "revoked":
        raise HTTPException(409, "仅可撤销尚未撤销的实际来源")
    row.status, row.revision = "revoked", row.revision + 1
    row.revoked_by, row.revoked_at, row.revoke_reason = actor.user_id, utcnow(), request.basis_note
    return _finish(db, actor, row, "drug_label.source.revoke", expected_prof=prof)


@_write
def revoke_professional(db, user, binding_id, values):
    request = values if isinstance(values, c.RevokeRequest) else c.RevokeRequest.model_validate(values)
    actor, _, row, prof, before = _load(db, user, binding_id, writing=True)
    if prof is None:
        raise HTTPException(409, "本件尚无实际专业签署")
    _cas(before.professional_review, request)
    if actor.user_role != "super_admin" and actor.user_id != prof.signed_by:
        raise HTTPException(403, "药师只能撤销本人实际签署")
    if prof.status != "signed":
        raise HTTPException(409, "专业签署已撤销")
    prof.status, prof.revision, prof.revoked_by, prof.revoked_at, prof.revoke_reason = "revoked", 2, actor.user_id, utcnow(), request.basis_note
    return _finish(db, actor, row, "drug_label.professional.revoke", expected_prof=prof)


def verify_source_wrapper(value):
    try:
        c.SourceRecord.model_validate(value)
        return True
    except (ValueError, TypeError, UnicodeError):
        return False
