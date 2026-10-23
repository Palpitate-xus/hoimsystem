"""Governed manual RCA records, with actual authority before private text.

The Event parent is the narrow write boundary. No global gate or clinical
causality approval is introduced. Callers commit once, with exact audits.
"""

import hashlib
import uuid
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import LargeBinary, cast, func, select

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_current as current_keys
from app.ai import rca_evidence_grants as g
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_source_contract as s
from app.ai.models import AIAuditEvent
from app.ai.rca_evidence_models import AIRcaEvidenceOriginal
from app.ai.rca_evidence_write_guard import current_rows
from app.models import AdverseEvent, AdverseEventRca

REVIEW_FIELDS = tuple(s.SourceGovernance.model_fields)


def _naive_clock(value):
    if value is None:
        return None
    if value.tzinfo is not None:
        raise ValueError("A legacy stored naive clock must not acquire an inferred timezone")
    return c.LegacyClock(text=value.isoformat(), basis="stored_naive_no_timezone")


def _bytes_expression(db, column):
    return func.octet_length(column) if db.get_bind().dialect.name in {"mysql", "mariadb"} else func.length(cast(column, LargeBinary))


def _legacy_snapshot(db, kind, identifier, event_id):
    model, key, dtype = (AdverseEvent, "event_id", s.EventSnapshot) if kind == "legacy_event" else (AdverseEventRca, "rca_id", s.RcaSnapshot)
    text_columns = [column for column in model.__table__.columns if column.type.python_type is str]
    with db.no_autoflush:
        metadata = current_rows(
            db.query(getattr(model, key), model.event_id, *[_bytes_expression(db, column) for column in text_columns]).filter(getattr(model, key) == identifier), shared=True
        ).one_or_none()
        if metadata is None or metadata[1] != event_id:
            raise HTTPException(409, "人工衍生原件所引用的实际同事件原始记录不存在")
        if sum(value or 0 for value in metadata[2:]) > c.MAX_WIRE_BYTES:
            raise HTTPException(413, "该完整原始见证超过8MiB，未读取正文或截断")
        row = current_rows(db.query(model).filter(getattr(model, key) == identifier), shared=True).one()
    body = {}
    for column in model.__table__.columns:
        value = getattr(row, column.name)
        if column.name in {"report_time", "create_time", "update_time"}:
            value = _naive_clock(value)
        elif column.name in {"due_date", "completed_date"} and value is not None:
            value = value.isoformat()
        body[column.name] = value
    result = dtype.model_validate(body)
    c.canonical(result)
    return result


def legacy_witness(db, user, event_id, kind, identifier):
    """An explicit authorized raw read, not an automatic provider release."""
    g.authorize_event(db, user, event_id)
    if kind not in {"legacy_event", "legacy_rca"} or type(identifier) is not int or identifier < 1:
        raise HTTPException(422, "须明确实际原始事件或RCA标识")
    result = _legacy_snapshot(db, kind, identifier, event_id)
    return {"kind": kind, "raw_snapshot": result.model_dump(mode="json"), "raw_hash": c.digest(result), "causal_verification": "not_provided"}


def _locator(db, identifier):
    try:
        if str(uuid.UUID(identifier)) != identifier:
            raise ValueError("Noncanonical UUID")
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "原件UUID不规范") from exc
    statement = select(AIRcaEvidenceOriginal.original_id, AIRcaEvidenceOriginal.event_id, AIRcaEvidenceOriginal.patient_id_at_capture).where(AIRcaEvidenceOriginal.original_id == identifier)
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                identity = connection.execute(statement).one_or_none()
            if identity is not None:
                return tuple(identity)
        identity = db.execute(statement).one_or_none()
    return tuple(identity) if identity is not None else None


def _load(db, user, identifier):
    # Writers and reads preserve Actor -> technical locator -> Event parent.
    g.current_actor(db, user, g.SOURCE_ROLES)
    identity = _locator(db, identifier)
    if identity is None:
        raise HTTPException(404, "人工调查原件不存在")
    auth = g.authorize_event(db, user, identity[1])
    if identity[2] != auth.identity.patient_id:
        raise HTTPException(403, "该旧原件关联患者与当前事件已不同，当前关联授权不能恢复旧患者正文")
    with db.no_autoflush:
        metadata = current_rows(
            db.query(
                AIRcaEvidenceOriginal.original_id,
                AIRcaEvidenceOriginal.event_id,
                AIRcaEvidenceOriginal.patient_id_at_capture,
                AIRcaEvidenceOriginal.json_bytes,
                _bytes_expression(db, AIRcaEvidenceOriginal.original_json),
            ).filter_by(original_id=identifier)
        ).one_or_none()
        if metadata is None or tuple(metadata[:3]) != identity:
            raise HTTPException(409, "原件的当前不透明父件身份已变化")
        if metadata[3] != metadata[4] or not 0 < metadata[4] <= c.MAX_WIRE_BYTES:
            raise HTTPException(413, "完整原件存储字节预算不一致，未读取或截断正文")
        row = current_rows(db.query(AIRcaEvidenceOriginal).filter_by(original_id=identifier)).one()
    return auth, row


def _governance(row):
    body = {key: getattr(row, key) for key in REVIEW_FIELDS}
    for key in ("reviewed_at", "revoked_at"):
        if body[key] is not None:
            body[key] = i.utc_text(body[key])
    return s.SourceGovernance.model_validate(body)


def _audit_detail(row, action, governance=None):
    detail = {"original_id": row.original_id, "event_id": row.event_id, "patient_id_at_capture": row.patient_id_at_capture, "content_hash": row.content_hash, "origin_kind": row.origin_kind}
    if action != "create":
        keys = (
            ("revision", "privacy_review", "faithfulness_review", "provenance_review", "reviewed_by", "reviewed_at", "review_basis_note")
            if action == "review"
            else ("revision", "revoked_by", "revoked_at", "revoke_reason")
        )
        detail.update({key: governance[key] for key in keys})
        if action == "review":
            detail["status"] = row.status if row.status != "revoked" else ("published" if row.privacy_review == row.faithfulness_review == row.provenance_review == "confirmed" else "rejected")
            detail["revision"] = 2
    return detail


def _verify_audits(db, row, body, governance):
    actual = governance.model_dump(mode="json")
    for action, identifier, actor, when in (
        ("create", row.created_audit_event_id, row.created_by, row.recorded_at),
        ("review", row.reviewed_audit_event_id, row.reviewed_by, row.reviewed_at),
        ("revoke", row.revoked_audit_event_id, row.revoked_by, row.revoked_at),
    ):
        if identifier is None:
            continue
        expected = {**_audit_detail(row, action, actual), "recorded_at_utc6": i.utc_text(when), "audit_clock_basis": "legacy_utc_second_storage"}
        if action == "create":
            expected.update({"event_grant_id": body.event_grant_id, "patient_grant_id": body.patient_grant_id})
        audit = current_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one_or_none()
        if audit is None or (audit.actor_id, audit.action, audit.target, audit.detail_json, audit.create_time) != (
            actor,
            f"rca_original.{action}",
            row.original_id,
            c.canonical(expected),
            when.replace(microsecond=0),
        ):
            raise ValueError("The exact original/signature audit PK does not match its complete SHA and scope")


def _record(db, row):
    body = s.OriginalImmutable.model_validate(c._strict_reply(row.original_json))
    if c.canonical(body) != row.original_json or len(c.utf8(row.original_json)) != row.json_bytes or c.digest(body) != row.content_hash:
        raise ValueError("The stored complete immutable original/bytes/SHA differ")
    expected = {
        "original_id": body.original_id,
        "event_id": body.event_id,
        "patient_id_at_capture": body.patient_id_at_capture,
        "created_by": body.created_by,
        "recorded_at": c.clock(body.recorded_at).replace(tzinfo=None),
        "origin_kind": body.origin_kind,
        "legacy_rca_id": body.provenance.witness_id if body.provenance.method == "human_declared_derivative" and body.provenance.witness_kind == "legacy_rca" else None,
    }
    if any(getattr(row, key) != value for key, value in expected.items()):
        raise ValueError("The current original SQL identities differ from immutable body")
    governance = _governance(row)
    _verify_audits(db, row, body, governance)
    raw_matches = True
    if body.provenance.method == "human_declared_derivative":
        try:
            current = _legacy_snapshot(db, body.provenance.witness_kind, body.provenance.witness_id, body.event_id)
            raw_matches = c.digest(current) == body.provenance.expected_raw_hash
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            raw_matches = False
    return s.OriginalRecord(
        immutable=body,
        content_hash=row.content_hash,
        governance=governance,
        governance_hash=c.digest({"original_id": row.original_id, "content_hash": row.content_hash, "governance": governance}),
        evaluated_at=i.utc_text(g.utcnow()),
        current_raw_witness_matches=raw_matches,
        eligible=row.status == "published" and raw_matches,
        causal_verification="not_provided",
    )


def original_detail(db, user, identifier):
    _, row = _load(db, user, identifier)
    try:
        return _record(db, row)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "完整人工原件、签署治理或具体审计无法核对") from exc


def _initial(row):
    row.status, row.revision = "draft", 1
    row.privacy_review = row.faithfulness_review = row.provenance_review = "unknown"
    row.reviewed_by = row.reviewed_at = row.reviewed_audit_event_id = None
    row.revoked_by = row.revoked_at = row.revoked_audit_event_id = None
    row.review_basis_note = row.revoke_reason = ""


def _values(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _postflush(db, auth, row, expected, audit_id, audit_value, *, require_matching_witness=True):
    db.flush()
    current_keys.remember_flushed(db, row)
    identifier = expected["original_id"]
    db.expire(row)
    current_auth = g.authorize_event(db, auth.actor, auth.identity.event_id)
    if tuple(current_auth.identity) != tuple(auth.identity):
        raise ValueError("Actual Event/patient scope changed after flush")
    metadata = current_keys.current_metadata(
        db,
        AIRcaEvidenceOriginal,
        "original_id",
        identifier,
        expected["event_id"],
        (
            AIRcaEvidenceOriginal.original_id,
            AIRcaEvidenceOriginal.event_id,
            AIRcaEvidenceOriginal.patient_id_at_capture,
            AIRcaEvidenceOriginal.content_hash,
            AIRcaEvidenceOriginal.json_bytes,
            _bytes_expression(db, AIRcaEvidenceOriginal.original_json),
        ),
    )
    if tuple(metadata[2:5]) != (expected["patient_id_at_capture"], expected["content_hash"], expected["json_bytes"]) or metadata[5] != expected["json_bytes"]:
        raise ValueError("The actual postflush original scope/hash/bytes changed before any private body read")
    current = current_rows(db.query(AIRcaEvidenceOriginal).filter_by(original_id=identifier)).one()
    if _values(current) != expected:
        raise ValueError("The exact newly written original or review changed after flush")
    g._exact_audit(db, audit_id, audit_value)
    record = _record(db, current)
    if require_matching_witness and not record.current_raw_witness_matches:
        raise ValueError("The actual legacy witness changed after the write; nothing is accepted")
    return record


@g._write
def create_original(db, user, values):
    request = g.typed(s.OriginalCreate, values)
    auth = g.authorize_event(db, user, request.event_id)
    if auth.identity.patient_id != request.expected_event_patient_id:
        raise HTTPException(409, "事件关联患者与明确提交范围已变化")
    raw = None
    if request.provenance.method == "human_declared_derivative":
        raw = _legacy_snapshot(db, request.provenance.witness_kind, request.provenance.witness_id, request.event_id)
        if c.digest(raw) != request.provenance.expected_raw_hash:
            raise HTTPException(409, "实际完整原始见证与人工审阅摘要已变化")
    when = g.utcnow()
    body = s.OriginalImmutable(
        schema_version="rca_evidence_original_v1",
        original_id=str(uuid.uuid4()),
        event_id=request.event_id,
        patient_id_at_capture=auth.identity.patient_id,
        origin_kind=request.origin_kind,
        text=request.text,
        text_hash=hashlib.sha256(c.utf8(request.text)).hexdigest(),
        provenance=request.provenance,
        raw_witness=raw,
        event_grant_id=auth.event_grant.identity.grant_id,
        patient_grant_id=auth.patient_grant.identity.grant_id if auth.patient_grant else None,
        created_by=auth.actor.user_id,
        recorded_at=i.utc_text(when),
        timeline=request.timeline,
        causal_verification="not_provided",
    )
    payload = c.canonical(body)
    row = AIRcaEvidenceOriginal(
        original_id=body.original_id,
        event_id=body.event_id,
        patient_id_at_capture=body.patient_id_at_capture,
        legacy_rca_id=request.provenance.witness_id if request.provenance.method == "human_declared_derivative" and request.provenance.witness_kind == "legacy_rca" else None,
        origin_kind=body.origin_kind,
        original_json=payload,
        json_bytes=len(c.utf8(payload)),
        content_hash=c.digest(body),
        created_by=auth.actor.user_id,
        recorded_at=when,
    )
    _initial(row)
    detail = {**_audit_detail(row, "create"), "event_grant_id": body.event_grant_id, "patient_grant_id": body.patient_grant_id}
    audit_id, audit_value = g._audit(db, auth.actor, "rca_original.create", row.original_id, detail, when)
    row.created_audit_event_id = audit_id
    expected = _values(row)
    db.add(row)
    return _postflush(db, auth, row, expected, audit_id, audit_value)


def _cas(row, request, before):
    if (row.revision, row.content_hash, before.governance_hash) != (request.expected_revision, request.expected_content_hash, request.expected_governance_hash):
        raise HTTPException(409, "人工原件正文或三项审核治理已变化，请重新明确决定")


@g._write
def review_original(db, user, identifier, values):
    request = g.typed(i.SourceReview, values)
    auth, row = _load(db, user, identifier)
    before = _record(db, row)
    _cas(row, request, before)
    if row.status != "draft" or not before.current_raw_witness_matches:
        raise HTTPException(409, "只有实际见证仍匹配的未审核原件可明确审核")
    when = g.utcnow()
    updates = {
        "status": "published" if request.decision == "publish" else "rejected",
        "revision": 2,
        "privacy_review": request.privacy_review,
        "faithfulness_review": request.faithfulness_review,
        "provenance_review": request.provenance_review,
        "reviewed_by": auth.actor.user_id,
        "reviewed_at": when,
        "review_basis_note": request.basis_note,
    }
    draft = SimpleNamespace(**{**_values(row), **updates})
    detail = _audit_detail(draft, "review", {**{key: getattr(draft, key) for key in REVIEW_FIELDS}, "reviewed_at": i.utc_text(when)})
    audit_id, audit_value = g._audit(db, auth.actor, "rca_original.review", row.original_id, detail, when)
    for key, value in updates.items():
        setattr(row, key, value)
    row.reviewed_audit_event_id = audit_id
    return _postflush(db, auth, row, _values(row), audit_id, audit_value)


@g._write
def revoke_original(db, user, identifier, values):
    request = g.typed(i.Revoke, values)
    auth, row = _load(db, user, identifier)
    before = _record(db, row)
    _cas(row, request, before)
    if row.status == "revoked":
        raise HTTPException(409, "不可重复撤销旧版本")
    when = g.utcnow()
    updates = {"status": "revoked", "revision": row.revision + 1, "revoked_by": auth.actor.user_id, "revoked_at": when, "revoke_reason": request.basis_note}
    draft = SimpleNamespace(**{**_values(row), **updates})
    detail = _audit_detail(draft, "revoke", {**{key: getattr(draft, key) for key in REVIEW_FIELDS}, "revoked_at": i.utc_text(when)})
    audit_id, audit_value = g._audit(db, auth.actor, "rca_original.revoke", row.original_id, detail, when)
    for key, value in updates.items():
        setattr(row, key, value)
    row.revoked_audit_event_id = audit_id
    return _postflush(db, auth, row, _values(row), audit_id, audit_value, require_matching_witness=False)
