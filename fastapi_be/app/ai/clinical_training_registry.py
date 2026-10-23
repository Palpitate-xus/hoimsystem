"""Server-owned complete synthetic lessons with exact creation audit receipts.

This module grants no learner or model access. Governance entry points require
the current Super and every internal read proves current source headers first.
"""

import datetime as dt
import hashlib
import uuid

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_reference_contract as refs
from app.ai import clinical_training_references as references
from app.ai.clinical_training_models import AITrainingLesson
from app.ai.clinical_training_registry_contract import TrainingLessonCreate, TrainingSourceRevoke
from app.ai.clinical_training_write_guard import current_rows, lock_training_write
from app.ai.models import AIAuditEvent
from app.models import User

ORIGIN_COLUMNS = ("lesson_id", "schema_version", "title", "version_label", "private_hash", "public_hash", "references_hash", "private_bytes", "public_bytes", "references_bytes", "reference_ids_hash", "reference_ids_bytes", "reference_state_hash", "created_by", "author_role", "author_epoch", "created_at")
STATE_COLUMNS = ("creation_event_id", "status", "revision", "revoked_by", "revoked_at", "revoke_reason", "revocation_event_id")


def utcnow():
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def raw_sha(value):
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


def typed(model, value):
    try:
        return model.model_validate(c.parse_packet(value), strict=True)
    except (ValueError, TypeError, UnicodeError, ValidationError) as exc:
        raise HTTPException(422, "培训输入须符合明确字段、原文及完整容量约束") from exc


def identifier(value):
    try:
        return TypeAdapter(c.Identifier).validate_python(value, strict=True)
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(422, "须提供明确培训来源UUID") from exc


def detail(header, keys):
    return {key: references.utc_text(header[key]) if isinstance(header[key], dt.datetime) else header[key] for key in keys}


def audit_event(db, actor_id, action, target, value, clock):
    raw = c.canonical_json(value)
    if len(raw.encode()) > 65535:
        raise HTTPException(422, "完整培训审计超出实际TEXT容量")
    row = AIAuditEvent(actor_id=actor_id, action=action, target=target, detail_json=raw, create_time=clock.replace(microsecond=0))
    db.add(row)
    db.flush()
    if type(row.event_id) is not int or row.event_id < 1:
        raise HTTPException(409, "未形成具体培训审计主键")
    return row.event_id


def verify_event(db, event_id, actor_id, action, target, value, clock):
    if type(event_id) is not int or event_id < 1:
        raise HTTPException(409, "缺少具体培训审计主键")
    with db.no_autoflush:
        row = current_rows(db.query(AIAuditEvent).filter_by(event_id=event_id), shared=True).one_or_none()
    if row is None or row.actor_id != actor_id or row.action != action or row.target != target or row.create_time != clock.replace(microsecond=0) or row.detail_json != c.canonical_json(value):
        raise HTTPException(409, "培训具体审计行为、时刻或完整技术绑定已损坏")


def verify_actor(db, actor_id, role, epoch):
    with db.no_autoflush:
        row = current_rows(db.query(User.user_id, User.user_role, User.token_invalid_before).filter_by(user_id=actor_id), shared=True).one_or_none()
    if row is None or role != "super_admin" or row.user_role != role or row.token_invalid_before != epoch:
        raise HTTPException(403, "培训版本的作者或审核人当前角色/授权时刻已变化")


def lesson_header(db, lesson_id, *, require_active=True, require_author=True):
    lesson_id = identifier(lesson_id)
    with db.no_autoflush:
        row = current_rows(db.query(*(getattr(AITrainingLesson, key) for key in (*ORIGIN_COLUMNS, *STATE_COLUMNS, "reference_ids_json"))).filter_by(lesson_id=lesson_id), shared=True).one_or_none()
    if row is None:
        raise HTTPException(404, "明确培训课程版本不存在")
    h = dict(row._mapping)
    try:
        if h["schema_version"] != "clinical_training_private_lesson_v1" or h["author_role"] != "super_admin":
            raise ValueError("Lesson origin differs")
        for prefix in ("private", "public", "references"):
            TypeAdapter(c.Digest).validate_python(h[prefix + "_hash"], strict=True)
            if type(h[prefix + "_bytes"]) is not int or not 1 <= h[prefix + "_bytes"] <= c.WHOLE_BYTES:
                raise ValueError("Whole source byte count differs")
        for key in ("reference_ids_hash", "reference_state_hash"):
            TypeAdapter(c.Digest).validate_python(h[key], strict=True)
        if type(h["reference_ids_bytes"]) is not int or not 1 <= h["reference_ids_bytes"] <= 131072 or len(h["reference_ids_json"].encode()) != h["reference_ids_bytes"] or raw_sha(h["reference_ids_json"]) != h["reference_ids_hash"]:
            raise ValueError("The complete technical reference-ID selection differs")
        ids = c.parse_packet(h["reference_ids_json"])
        if type(ids) is not list or not 1 <= len(ids) <= 2048 or ids != sorted(set(ids)) or c.canonical_json(ids) != h["reference_ids_json"]:
            raise ValueError("The selected technical reference union is not canonical")
        for key in ids:
            TypeAdapter(c.Identifier).validate_python(key, strict=True)
        verify_event(db, h["creation_event_id"], h["created_by"], "training_lesson_create", lesson_id, detail(h, ORIGIN_COLUMNS), h["created_at"])
        if h["status"] == "active":
            if h["revision"] != 1 or any(h[key] is not None for key in ("revoked_by", "revoked_at", "revocation_event_id")) or h["revoke_reason"] != "":
                raise ValueError("Active source carries invalid revocation")
        elif h["status"] == "revoked":
            if h["revision"] != 2 or h["revoked_at"] is None or h["revoked_at"] < h["created_at"] or type(h["revoked_by"]) is not int or not h["revoke_reason"] or h["creation_event_id"] == h["revocation_event_id"]:
                raise ValueError("Revoked source carries invalid receipt")
            verify_event(db, h["revocation_event_id"], h["revoked_by"], "training_lesson_revoke", lesson_id, revoke_detail(h, "lesson_id", "private_hash"), h["revoked_at"])
        else:
            raise ValueError("Unknown lesson state")
    except (ValueError, TypeError, KeyError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "培训课程技术头或具体审计绑定已损坏") from exc
    if require_active and h["status"] != "active":
        raise HTTPException(403, "培训课程版本已经撤回")
    if require_author:
        verify_actor(db, h["created_by"], h["author_role"], h["author_epoch"])
    return h


def revoke_detail(header, id_key, hash_key):
    return dict(id=header[id_key], source_hash=header[hash_key], revision=2, reason_sha256=raw_sha(header["revoke_reason"]), revoked_at=references.utc_text(header["revoked_at"]))


def metadata(header):
    """Super governance only: includes controlled private-answer fingerprints."""
    return detail(header, (*ORIGIN_COLUMNS, *STATE_COLUMNS))


def _read_current(db, header, actor_id):
    """Internal after exact current header/actor authority; no public shortcut."""
    try:
        current = references._capture_current(db, actor_id, header["lesson_id"], c.parse_packet(header["reference_ids_json"]), expected_state_hash=header["reference_state_hash"])
        with db.no_autoflush:
            row = current_rows(db.query(AITrainingLesson.references_json).filter_by(lesson_id=header["lesson_id"]), shared=True).one_or_none()
        if row is None or len(row.references_json.encode()) != header["references_bytes"] or raw_sha(row.references_json) != header["references_hash"]:
            raise ValueError("Entire stored reference packet differs")
        frozen = refs.TrainingReferenceSnapshot.model_validate(c.parse_packet(row.references_json), strict=True)
        if c.whole(frozen) != row.references_json or frozen.lesson_id != header["lesson_id"] or frozen.captured_by != header["created_by"] or frozen.captured_at != references.utc_text(header["created_at"]):
            raise ValueError("Reference snapshot does not bind the actual lesson")
        if references.reference_state_hash(frozen) != header["reference_state_hash"] or [c.whole(item) for item in current.references] != [c.whole(item) for item in frozen.references]:
            raise ValueError("The full current references differ from the actual frozen packet")
        # Reference currentness precedes private answer key and public body.
        with db.no_autoflush:
            row = current_rows(db.query(AITrainingLesson.private_json, AITrainingLesson.public_json).filter_by(lesson_id=header["lesson_id"]), shared=True).one_or_none()
        if row is None:
            raise ValueError("The locked complete lesson disappeared")
        for prefix in ("private", "public"):
            raw = getattr(row, prefix + "_json")
            if len(raw.encode()) != header[prefix + "_bytes"] or raw_sha(raw) != header[prefix + "_hash"]:
                raise ValueError("Whole stored lesson bytes differ")
        private = c.PrivateTrainingLesson.model_validate(c.parse_packet(row.private_json), strict=True)
        public = c.project_lesson(private)
        if c.whole(private) != row.private_json or c.whole(public) != row.public_json:
            raise ValueError("The complete literal private/public projection differs")
        for key in ("lesson_id", "schema_version", "title", "version_label", "created_by"):
            if getattr(private, key) != header[key]:
                raise ValueError("Server lesson identity differs")
        if private.created_at != references.utc_text(header["created_at"]) or sorted({key for question in private.questions for key in question.reference_ids}) != [item.metadata.document_id for item in frozen.references]:
            raise ValueError("The exact question reference union differs")
        return private, public, frozen
    except (ValueError, TypeError, KeyError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "完整培训课程、隐藏答案或受审参考绑定已损坏") from exc


def register_lesson(db, user, value):
    try:
        actor = lock_training_write(db, user, governance=True)
        request = typed(TrainingLessonCreate, value)
        clock = utcnow()
        private = c.PrivateTrainingLesson(schema_version="clinical_training_private_lesson_v1", lesson_id=str(uuid.uuid4()), **request.model_dump(exclude={"synthetic_material_declared"}), created_by=actor.user_id, created_at=references.utc_text(clock), material_basis="author_declared_synthetic_not_independently_verified_by_contract", intended_use="education_only_not_patient_treatment_or_credentialing")
        public = c.project_lesson(private)
        frozen = references._capture_current(db, actor.user_id, private.lesson_id, sorted({key for question in private.questions for key in question.reference_ids}), now=clock)
        packets = dict(private=c.whole(private), public=c.whole(public), references=c.whole(frozen))
        ids_json = c.canonical_json([item.metadata.document_id for item in frozen.references])
        if len(ids_json.encode()) > 131072:
            raise HTTPException(422, "完整培训参考ID集合超过实际容量")
        h = dict(lesson_id=private.lesson_id, schema_version=private.schema_version, title=private.title, version_label=private.version_label, reference_ids_hash=raw_sha(ids_json), reference_ids_bytes=len(ids_json.encode()), reference_state_hash=references.reference_state_hash(frozen), created_by=actor.user_id, author_role=actor.user_role, author_epoch=actor.token_invalid_before, created_at=clock, **{key: value for prefix, raw in packets.items() for key, value in [(prefix + "_hash", raw_sha(raw)), (prefix + "_bytes", len(raw.encode()))]})
        event_id = audit_event(db, actor.user_id, "training_lesson_create", private.lesson_id, detail(h, ORIGIN_COLUMNS), clock)
        db.add(AITrainingLesson(**h, reference_ids_json=ids_json, **{prefix + "_json": raw for prefix, raw in packets.items()}, creation_event_id=event_id, status="active", revision=1, revoke_reason=""))
        db.flush()
        stored = lesson_header(db, private.lesson_id)
        if _read_current(db, stored, actor.user_id) != (private, public, frozen):
            raise HTTPException(409, "培训课程实际完整写入读回不一致")
        return metadata(stored)
    except Exception:
        db.rollback()
        raise


def get_lesson(db, user, lesson_id, *, include_body=False):
    actor = lock_training_write(db, user, governance=True)
    header = lesson_header(db, lesson_id, require_active=include_body, require_author=include_body)
    if not include_body:
        return metadata(header)
    private, public, frozen = _read_current(db, header, actor.user_id)
    return dict(private=private.model_dump(mode="json"), public=public.model_dump(mode="json"), references=frozen.model_dump(mode="json"))


def revoke_lesson(db, user, lesson_id, value):
    try:
        actor = lock_training_write(db, user, governance=True)
        request = typed(TrainingSourceRevoke, value)
        h = lesson_header(db, lesson_id, require_active=False, require_author=False)
        if h["status"] != "active" or h["revision"] != request.revision:
            raise HTTPException(409, "培训课程状态已变化，请刷新后重试")
        clock = utcnow()
        if clock < h["created_at"]:
            raise HTTPException(409, "课程撤回时刻早于实际登记")
        values = dict(status="revoked", revision=2, revoked_by=actor.user_id, revoked_at=clock, revoke_reason=request.reason)
        event_id = audit_event(db, actor.user_id, "training_lesson_revoke", h["lesson_id"], revoke_detail({**h, **values}, "lesson_id", "private_hash"), clock)
        with db.no_autoflush:
            count = db.query(AITrainingLesson).filter_by(lesson_id=h["lesson_id"], status="active", revision=request.revision).update({**values, "revocation_event_id": event_id}, synchronize_session=False)
        if count != 1:
            raise HTTPException(409, "培训课程当前版本已经变化")
        db.flush()
        stored = lesson_header(db, h["lesson_id"], require_active=False, require_author=False)
        if any(stored[key] != value for key, value in {**values, "revocation_event_id": event_id}.items()):
            raise HTTPException(409, "课程撤回实际读回与独立具体审计不一致")
        return metadata(stored)
    except Exception:
        db.rollback()
        raise
