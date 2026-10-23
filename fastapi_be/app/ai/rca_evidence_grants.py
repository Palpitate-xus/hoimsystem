"""Current explicit event AND patient-purpose authority before RCA source text.

Only this feature's independently issued, expiring grants count. Super role,
legacy clinical care, research authorization or another AI grant is not a
replacement. Grant metadata locators are technical and never grant authority.
"""

import datetime as dt
import functools
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_current as current_keys
from app.ai import rca_evidence_input as i
from app.ai.models import AIAuditEvent
from app.ai.rca_evidence_models import AIRcaPurposeGrant
from app.ai.rca_evidence_write_guard import current_actor, current_rows, lock_event_identity
from app.models import Patient, User

SOURCE_ROLES = frozenset({"super_admin"})


def utcnow():
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def typed(model, value):
    try:
        return model.model_validate(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "RCA用途授权的完整闭集字段、UTC6或明确签署无效") from exc


def _write(function):
    @functools.wraps(function)
    def call(db, *args, **kwargs):
        try:
            return function(db, *args, **kwargs)
        except HTTPException:
            db.rollback()
            raise
        except (SQLAlchemyError, ValueError, TypeError, UnicodeError) as exc:
            db.rollback()
            raise HTTPException(409, "RCA用途许可、当前父件或具体SQL审计发生冲突，整笔未接受") from exc

    return call


def _audit(db, actor, action, target, detail, when):
    # The existing audit table is second precision. New grant clocks remain
    # UTC6, and the complete real clock has an explicit separate audit field.
    body = {**detail, "recorded_at_utc6": i.utc_text(when), "audit_clock_basis": "legacy_utc_second_storage"}
    event = AIAuditEvent(actor_id=actor.user_id, action=action, target=target, detail_json=c.canonical(body), create_time=when.replace(microsecond=0))
    db.add(event)
    db.flush()
    expected = {column.name: getattr(event, column.name) for column in AIAuditEvent.__table__.columns}
    return event.event_id, expected


def _exact_audit(db, identifier, expected):
    row = current_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one_or_none()
    if row is None or {column.name: getattr(row, column.name) for column in AIAuditEvent.__table__.columns} != expected:
        raise ValueError("The exact newly written audit row changed")


def _grant_body(row):
    if len(c.utf8(row.grant_json)) > 65535:
        raise ValueError("The whole stored grant exceeds its legacy TEXT byte budget")
    identity = i.GrantIdentity.model_validate(c._strict_reply(row.grant_json))
    if c.canonical(identity) != row.grant_json or c.digest(identity) != row.content_hash:
        raise ValueError("The stored whole grant differs from its independent canonical SHA")
    expected = {
        "grant_id": identity.grant_id,
        "event_id": identity.event_id,
        "patient_id_at_grant": identity.patient_id_at_grant,
        "grantee_id": identity.grantee_id,
        "permission_kind": identity.permission_kind,
        "purpose": identity.purpose,
        "issued_by": identity.issued_by,
        "issued_at": c.clock(identity.issued_at).replace(tzinfo=None),
        "valid_until": c.clock(identity.valid_until).replace(tzinfo=None),
    }
    if any(getattr(row, key) != value for key, value in expected.items()):
        raise ValueError("The typed grant and current SQL identity/scope columns differ")
    return identity


def _verify_stored_audit(db, row, identity):
    def verify(identifier, action, actor, when, detail):
        audit = current_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one_or_none()
        expected = {**detail, "recorded_at_utc6": i.utc_text(when), "audit_clock_basis": "legacy_utc_second_storage"}
        if audit is None or (audit.actor_id, audit.action, audit.target, audit.detail_json, audit.create_time) != (actor, action, row.grant_id, c.canonical(expected), when.replace(microsecond=0)):
            raise ValueError("The exact purpose-grant audit PK/identity does not match")

    detail = {"grant_id": row.grant_id, "content_hash": row.content_hash, "permission_kind": row.permission_kind, "purpose": "incident_rca"}
    verify(row.created_audit_event_id, "rca_grant.create", identity.issued_by, row.issued_at, detail)
    if row.status == "revoked":
        verify(row.revoked_audit_event_id, "rca_grant.revoke", row.revoked_by, row.revoked_at, {**detail, "revision": 2})


def _record(db, row, event_identity, now):
    identity = _grant_body(row)
    governance = i.GrantGovernance(
        status=row.status,
        revision=row.revision,
        revoked_by=row.revoked_by,
        revoked_at=i.utc_text(row.revoked_at) if row.revoked_at else None,
        revoke_reason=row.revoke_reason,
        created_audit_event_id=row.created_audit_event_id,
        revoked_audit_event_id=row.revoked_audit_event_id,
    )
    _verify_stored_audit(db, row, identity)
    grantee = current_rows(db.query(User.user_id, User.user_role).filter_by(user_id=identity.grantee_id), shared=True).one_or_none()
    reasons = []
    if row.valid_until <= now:
        reasons.append("grant_expired")
    if row.status == "revoked":
        reasons.append("grant_revoked")
    if event_identity.patient_id != row.patient_id_at_grant:
        reasons.append("event_patient_changed")
    current_super = grantee is not None and grantee.user_role == "super_admin"
    if not current_super:
        reasons.append("grantee_not_current_super")
    return i.GrantRecord(
        identity=identity,
        content_hash=row.content_hash,
        governance=governance,
        governance_hash=c.digest({"grant_id": row.grant_id, "content_hash": row.content_hash, "governance": governance}),
        evaluated_at=i.utc_text(now),
        event_patient_id_now=event_identity.patient_id,
        grantee_current_super=current_super,
        current_scope=not reasons,
        scope_reasons=reasons,
    )


def _locator(db, identifier):
    statement = select(AIRcaPurposeGrant.grant_id, AIRcaPurposeGrant.event_id).where(AIRcaPurposeGrant.grant_id == identifier)
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                row = connection.execute(statement).one_or_none()
            if row is not None:
                return tuple(row)
        row = db.execute(statement).one_or_none()
    return tuple(row) if row is not None else None


def _load(db, actor, identifier):
    identity = _locator(db, identifier)
    if identity is None:
        raise HTTPException(404, "RCA用途许可不存在")
    event_identity = lock_event_identity(db, identity[1])
    if event_identity is None:
        raise HTTPException(409, "RCA用途许可的实际事件已不存在")
    row = current_rows(db.query(AIRcaPurposeGrant).filter_by(grant_id=identifier)).one_or_none()
    if row is None or (row.grant_id, row.event_id) != identity:
        raise HTTPException(409, "RCA用途许可实际父件身份已改变")
    return row, event_identity


def grant_detail(db, user, identifier):
    current_actor(db, user, SOURCE_ROLES)
    row, parent = _load(db, user, identifier)
    try:
        return _record(db, row, parent, utcnow())
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(409, "RCA用途许可完整正文、治理或具体审计不一致") from exc


@_write
def create_grant(db, user, values):
    request = typed(i.GrantCreate, values)
    actor = current_actor(db, user, SOURCE_ROLES)
    parent = lock_event_identity(db, request.event_id)
    if parent is None:
        raise HTTPException(404, "实际不良事件不存在")
    if parent.patient_id != request.expected_event_patient_id:
        raise HTTPException(409, "当前事件患者关联已变化，请重新明确审阅用途范围")
    grantee = current_rows(db.query(User.user_id, User.user_role).filter_by(user_id=request.grantee_id), shared=True).one_or_none()
    if grantee is None or grantee.user_role != "super_admin":
        raise HTTPException(403, "本阶段RCA用途仅能明确授权给当前超级管理员")
    when = utcnow()
    identity = i.GrantIdentity(
        schema_version="rca_purpose_grant_v1",
        grant_id=str(uuid.uuid4()),
        event_id=parent.event_id,
        patient_id_at_grant=parent.patient_id,
        grantee_id=grantee.user_id,
        permission_kind=request.permission_kind,
        purpose=request.purpose,
        valid_until=request.valid_until,
        basis_note=request.basis_note,
        explicit_scope_review=request.explicit_scope_review,
        issued_by=actor.user_id,
        issued_at=i.utc_text(when),
    )
    body, content_hash = c.canonical(identity), c.digest(identity)
    if len(c.utf8(body)) > 65535:
        raise ValueError("A whole grant cannot exceed the existing TEXT field")
    audit_id, audit_value = _audit(
        db, actor, "rca_grant.create", identity.grant_id, {"grant_id": identity.grant_id, "content_hash": content_hash, "permission_kind": identity.permission_kind, "purpose": identity.purpose}, when
    )
    row = AIRcaPurposeGrant(
        grant_id=identity.grant_id,
        event_id=parent.event_id,
        patient_id_at_grant=parent.patient_id,
        grantee_id=identity.grantee_id,
        permission_kind=identity.permission_kind,
        purpose=identity.purpose,
        grant_json=body,
        content_hash=content_hash,
        issued_by=actor.user_id,
        issued_at=when,
        valid_until=c.clock(identity.valid_until).replace(tzinfo=None),
        status="active",
        revision=1,
        revoked_by=None,
        revoked_at=None,
        revoke_reason="",
        created_audit_event_id=audit_id,
        revoked_audit_event_id=None,
    )
    expected = {column.name: getattr(row, column.name) for column in AIRcaPurposeGrant.__table__.columns}
    db.add(row)
    db.flush()
    current_keys.remember_flushed(db, row)
    db.expire(row)
    current = current_rows(db.query(AIRcaPurposeGrant).filter_by(grant_id=identity.grant_id)).one()
    if {column.name: getattr(current, column.name) for column in AIRcaPurposeGrant.__table__.columns} != expected:
        raise ValueError("The new exact SQL grant changed after flush")
    _exact_audit(db, audit_id, audit_value)
    current_actor(db, actor, SOURCE_ROLES)
    actual_parent = lock_event_identity(db, parent.event_id)
    if actual_parent is None or tuple(actual_parent) != tuple(parent):
        raise ValueError("The actual Event association changed after grant flush")
    result = _record(db, current, actual_parent, utcnow())
    if not result.current_scope:
        raise ValueError("The newly issued grant no longer has its exact current scope")
    return result


@_write
def revoke_grant(db, user, identifier, values):
    request = typed(i.Revoke, values)
    actor = current_actor(db, user, SOURCE_ROLES)
    row, parent = _load(db, actor, identifier)
    before = _record(db, row, parent, utcnow())
    if (row.revision, row.content_hash, before.governance_hash) != (request.expected_revision, request.expected_content_hash, request.expected_governance_hash) or row.status != "active":
        raise HTTPException(409, "RCA用途许可已变化或撤销，不可重复提交旧决定")
    when = utcnow()
    audit_id, audit_value = _audit(
        db, actor, "rca_grant.revoke", row.grant_id, {"grant_id": row.grant_id, "content_hash": row.content_hash, "permission_kind": row.permission_kind, "purpose": row.purpose, "revision": 2}, when
    )
    row.status, row.revision, row.revoked_by, row.revoked_at, row.revoke_reason, row.revoked_audit_event_id = "revoked", 2, actor.user_id, when, request.basis_note, audit_id
    expected = {column.name: getattr(row, column.name) for column in AIRcaPurposeGrant.__table__.columns}
    db.flush()
    db.expire(row)
    current = current_rows(db.query(AIRcaPurposeGrant).filter_by(grant_id=identifier)).one()
    if {column.name: getattr(current, column.name) for column in AIRcaPurposeGrant.__table__.columns} != expected:
        raise ValueError("The exact revocation changed after flush")
    _exact_audit(db, audit_id, audit_value)
    current_actor(db, actor, SOURCE_ROLES)
    actual_parent = lock_event_identity(db, parent.event_id)
    if actual_parent is None or tuple(actual_parent) != tuple(parent):
        raise ValueError("The actual Event association changed after revocation flush")
    return _record(db, current, actual_parent, utcnow())


@dataclass(frozen=True)
class AuthorizedEvent:
    actor: User
    identity: object
    event_grant: i.GrantRecord
    patient_grant: i.GrantRecord | None


def authorize_event(db, user, event_id):
    """No event narrative, RCA/Original/Case TEXT before both real purposes."""
    actor = current_actor(db, user, SOURCE_ROLES)
    parent = lock_event_identity(db, event_id)
    if parent is None:
        raise HTTPException(404, "实际不良事件不存在")
    now = utcnow()
    identities = current_keys.discover(db, AIRcaPurposeGrant, "grant_id", parent.event_id, filters=(AIRcaPurposeGrant.grantee_id == actor.user_id,))
    columns = (
        AIRcaPurposeGrant.grant_id,
        AIRcaPurposeGrant.event_id,
        AIRcaPurposeGrant.permission_kind,
        AIRcaPurposeGrant.patient_id_at_grant,
        AIRcaPurposeGrant.grantee_id,
        AIRcaPurposeGrant.purpose,
        AIRcaPurposeGrant.status,
        AIRcaPurposeGrant.valid_until,
    )
    candidates = []
    for identifier in identities:
        row = current_keys.current_metadata(db, AIRcaPurposeGrant, "grant_id", identifier, parent.event_id, columns)
        if (row.patient_id_at_grant, row.grantee_id, row.purpose, row.status) == (parent.patient_id, actor.user_id, "incident_rca", "active") and row.valid_until > now:
            candidates.append(row)
    chosen = {}
    for row in candidates:
        chosen.setdefault(row.permission_kind, row.grant_id)
    kinds = ["event_investigation"] + (["associated_patient_processing"] if parent.patient_id is not None else [])
    if any(kind not in chosen for kind in kinds):
        raise HTTPException(403, "须分别具备该实际事件调查与关联患者处理用途的当前显式许可；角色和其它用途不代替")
    if parent.patient_id is not None:
        patient = current_rows(db.query(Patient.patient_id, Patient.permission).filter_by(patient_id=parent.patient_id), shared=True).one_or_none()
        if patient is None or patient.permission != "allow":
            raise HTTPException(403, "该实际患者的当前数据许可未明确允许本次处理")
    records = {}
    try:
        for kind in kinds:
            row = current_rows(db.query(AIRcaPurposeGrant).filter_by(grant_id=chosen[kind]), shared=True).one()
            record = _record(db, row, parent, utcnow())
            if not record.current_scope or record.identity.grantee_id != actor.user_id or record.identity.permission_kind != kind or record.identity.event_id != parent.event_id:
                raise ValueError("The actual independent permission changed")
            records[kind] = record
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(409, "当前RCA用途许可的完整独立原件或审计无法核对") from exc
    return AuthorizedEvent(actor, parent, records["event_investigation"], records.get("associated_patient_processing"))
