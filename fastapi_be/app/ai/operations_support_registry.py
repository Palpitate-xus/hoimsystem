"""Actual operations originals, independent releases and concrete audit receipts.

No live log discovery or process execution. Callers own the database transaction.
Technical headers and exact audit primary keys precede every private body read.
"""

import datetime as dt
import hashlib
import uuid

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from app.ai import operations_support_contract as c
from app.ai.models import AIAuditEvent
from app.ai.operations_support_models import AIOperationsOriginal
from app.ai.operations_support_projection import _value
from app.ai.operations_support_registry_contract import OriginalCreate, SourceRevoke
from app.ai.operations_support_write_guard import current_rows, lock_operations_write

ORIGINAL_COLUMNS = (
    "original_id",
    "content_hash",
    "raw_text_sha256",
    "raw_bytes_length",
    "codepoint_length",
    "captured_by",
    "captured_at",
    "creation_event_id",
    "status",
    "revision",
    "revoked_by",
    "revoked_at",
    "revoke_reason",
    "revocation_event_id",
)


def utcnow():
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def utc_text(value):
    if not isinstance(value, dt.datetime) or value.tzinfo is not None:
        raise ValueError("A stored naive UTC microsecond clock is required")
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def raw_sha(value):
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


def bounded_json(value, limit=c.MAX_WHOLE_BYTES):
    text = c.canonical_json(value)
    if len(text.encode("utf-8")) > limit:
        raise HTTPException(422, "完整运维来源超过UTF8容量，未截断保存")
    return text


def typed(model, value):
    try:
        return model.model_validate(value, strict=True)
    except (ValidationError, ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "运维来源输入须符合明确的完整字段、标量和容量约束") from exc


def identifier(value):
    try:
        return TypeAdapter(c.Identifier).validate_python(value, strict=True)
    except (ValidationError, ValueError, TypeError) as exc:
        raise HTTPException(422, "须提供明确的运维来源UUID") from exc


def audit_event(db, actor_id, action, target, detail, clock):
    event = AIAuditEvent(actor_id=actor_id, action=action, target=target, detail_json=bounded_json(detail, 65535), create_time=clock)
    db.add(event)
    db.flush()
    if type(event.event_id) is not int or event.event_id < 1:
        raise HTTPException(409, "运维来源未形成实际审计主键")
    return event.event_id


def verify_event(db, event_id, actor_id, action, target, detail, clock):
    if type(event_id) is not int or event_id < 1:
        raise HTTPException(409, "运维来源缺少实际审计主键")
    with db.no_autoflush:
        event = current_rows(db.query(AIAuditEvent).filter_by(event_id=event_id), shared=True).one_or_none()
    try:
        if event is None or event.actor_id != actor_id or event.action != action or event.target != target or event.create_time != clock:
            raise ValueError("The specific stored event differs")
        if c.canonical_json(_value(event.detail_json)) != c.canonical_json(detail):
            raise ValueError("The specific event does not bind this complete technical identity")
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "实际运维来源审计主键、行为或完整绑定已损坏") from exc


def original_creation_detail(header):
    return {
        key: utc_text(header[key]) if key == "captured_at" else header[key]
        for key in (
            "original_id",
            "content_hash",
            "raw_text_sha256",
            "raw_bytes_length",
            "codepoint_length",
            "captured_by",
            "captured_at",
        )
    }


def verify_revocation(db, header, kind, key, recorded_at):
    if header["status"] == "revoked":
        if header["revoked_at"] is None or header["revoked_at"] < recorded_at or type(header["revoked_by"]) is not int or not header["revoke_reason"]:
            raise HTTPException(409, "运维来源撤回状态损坏")
        verify_event(
            db,
            header["revocation_event_id"],
            header["revoked_by"],
            "operations_" + kind + "_revoke",
            header[key],
            {
                "id": header[key],
                "content_hash": header["content_hash"],
                "revision": header["revision"],
                "reason_sha256": raw_sha(header["revoke_reason"]),
                "revoked_at": utc_text(header["revoked_at"]),
            },
            header["revoked_at"],
        )
    elif any(header[key] is not None for key in ("revoked_by", "revoked_at", "revocation_event_id")) or header["revoke_reason"] != "":
        raise HTTPException(409, "运维来源活动状态与撤回记录不一致")


def original_header(db, original_id, *, require_active=True):
    original_id = identifier(original_id)
    with db.no_autoflush:
        row = current_rows(db.query(*(getattr(AIOperationsOriginal, key) for key in ORIGINAL_COLUMNS)).filter_by(original_id=original_id), shared=True).one_or_none()
    if row is None:
        raise HTTPException(404, "明确运维原件不存在")
    header = dict(row._mapping)
    try:
        for key in ("content_hash", "raw_text_sha256"):
            TypeAdapter(c.Digest).validate_python(header[key], strict=True)
        TypeAdapter(c.ActorId).validate_python(header["captured_by"], strict=True)
        if header["status"] not in {"active", "revoked"} or header["revision"] != (1 if header["status"] == "active" else 2):
            raise ValueError("Original state differs")
        if (
            type(header["raw_bytes_length"]) is not int
            or not 1 <= header["raw_bytes_length"] <= c.MAX_TEXT_BYTES
            or type(header["codepoint_length"]) is not int
            or not 1 <= header["codepoint_length"] <= c.MAX_TEXT_BYTES
        ):
            raise ValueError("Original whole byte/codepoint count differs")
        verify_event(db, header["creation_event_id"], header["captured_by"], "operations_original_create", original_id, original_creation_detail(header), header["captured_at"])
        verify_revocation(db, header, "original", "original_id", header["captured_at"])
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "运维原件技术头、真实审计或状态已损坏") from exc
    if require_active and header["status"] != "active":
        raise HTTPException(403, "本项运维原件已经撤回")
    return header


def original_metadata(header):
    return {
        **original_creation_detail(header),
        "creation_event_id": header["creation_event_id"],
        "status": header["status"],
        "revision": header["revision"],
        "revoked_at": utc_text(header["revoked_at"]) if header["revoked_at"] is not None else None,
        "revocation_event_id": header["revocation_event_id"],
    }


def read_original_body(db, header):
    """Internal after current authority and header proof; never a raw admin view."""
    with db.no_autoflush:
        row = current_rows(db.query(AIOperationsOriginal.identity_json, AIOperationsOriginal.content_text).filter_by(original_id=header["original_id"]), shared=True).one_or_none()
    try:
        if row is None:
            raise ValueError("The exact locked original disappeared")
        identity = _value(row.identity_json)
        if type(identity) is not dict or "content_text" in identity:
            raise ValueError("Original identity is closed and stores no duplicate raw body")
        original = c.OperationsOriginal.model_validate({**identity, "content_text": row.content_text}, strict=True)
        if original.original_id != header["original_id"] or original.captured_by != header["captured_by"] or original.captured_at != utc_text(header["captured_at"]):
            raise ValueError("Original metadata differs from the concrete receipt")
        if (
            c.content_hash(original) != header["content_hash"]
            or raw_sha(original.content_text) != header["raw_text_sha256"]
            or len(original.content_text.encode("utf-8")) != header["raw_bytes_length"]
            or len(original.content_text) != header["codepoint_length"]
        ):
            raise ValueError("Entire original bytes or identity differ")
        return original
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "运维原件完整内容或SHA损坏，未采用截断或替代内容") from exc


def register_original(db, user, value):
    actor = lock_operations_write(db, user, governance=True)
    request = typed(OriginalCreate, value)
    clock = utcnow()
    original = c.OperationsOriginal(
        schema_version="operations_support_original_v1",
        original_id=str(uuid.uuid4()),
        **request.model_dump(),
        captured_at=utc_text(clock),
        captured_by=actor.user_id,
        clock_basis="capture_only_not_verified_incident_occurrence",
    )
    # Reject whole canonical-wire expansion too, before any receipt/row is staged.
    bounded_json(original)
    header = dict(
        original_id=original.original_id,
        content_hash=c.content_hash(original),
        raw_text_sha256=raw_sha(original.content_text),
        raw_bytes_length=len(original.content_text.encode("utf-8")),
        codepoint_length=len(original.content_text),
        captured_by=actor.user_id,
        captured_at=clock,
    )
    event_id = audit_event(db, actor.user_id, "operations_original_create", original.original_id, original_creation_detail(header), clock)
    row = AIOperationsOriginal(
        **header,
        identity_json=bounded_json(original.model_dump(exclude={"content_text"}), 65535),
        content_text=original.content_text,
        creation_event_id=event_id,
        status="active",
        revision=1,
        revoked_by=None,
        revoked_at=None,
        revoke_reason="",
        revocation_event_id=None,
    )
    db.add(row)
    db.flush()
    stored = original_header(db, original.original_id)
    if read_original_body(db, stored) != original:
        raise HTTPException(409, "运维原件实际写入读回不一致")
    return original_metadata(stored)


def get_original(db, user, original_id, *, include_body=False):
    lock_operations_write(db, user, governance=True)
    header = original_header(db, original_id, require_active=include_body)
    if not include_body:
        return original_metadata(header)
    return read_original_body(db, header).model_dump(mode="json")


def revoke_original(db, user, original_id, value):
    actor = lock_operations_write(db, user, governance=True)
    request = typed(SourceRevoke, value)
    header = original_header(db, original_id)
    if header["revision"] != request.revision:
        raise HTTPException(409, "运维原件版本已变化")
    clock = utcnow()
    if clock < header["captured_at"]:
        raise HTTPException(409, "撤回时钟早于登记，未篡改时间")
    event_id = audit_event(
        db,
        actor.user_id,
        "operations_original_revoke",
        header["original_id"],
        {
            "id": header["original_id"],
            "content_hash": header["content_hash"],
            "revision": 2,
            "reason_sha256": raw_sha(request.reason),
            "revoked_at": utc_text(clock),
        },
        clock,
    )
    with db.no_autoflush:
        count = (
            db.query(AIOperationsOriginal)
            .filter_by(original_id=header["original_id"], status="active", revision=request.revision)
            .update(
                {
                    "status": "revoked",
                    "revision": 2,
                    "revoked_by": actor.user_id,
                    "revoked_at": clock,
                    "revoke_reason": request.reason,
                    "revocation_event_id": event_id,
                },
                synchronize_session=False,
            )
        )
    if count != 1:
        raise HTTPException(409, "运维原件当前状态已变化")
    db.flush()
    return original_metadata(original_header(db, header["original_id"], require_active=False))
