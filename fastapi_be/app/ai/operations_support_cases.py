"""Finite immutable operations collections with current publication before bodies."""

import uuid
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, TypeAdapter, ValidationError

from app.ai import operations_support_contract as c
from app.ai import operations_support_projection as projection
from app.ai import operations_support_registry as r
from app.ai import operations_support_releases as releases
from app.ai.operations_support_models import AIOperationsCase
from app.ai.operations_support_registry_contract import CaseCreate, SourceRevoke
from app.ai.operations_support_write_guard import current_rows, lock_operations_write

CASE_COLUMNS = (
    "case_id",
    "requested_by",
    "assembled_at",
    "member_bindings_hash",
    "private_hash",
    "public_hash",
    "source_count",
    "creation_event_id",
    "status",
    "revision",
    "revoked_by",
    "revoked_at",
    "revoke_reason",
    "revocation_event_id",
)


class MemberBinding(c.StrictModel):
    original_id: c.Identifier
    original_content_hash: c.Digest
    original_governance_hash: c.Digest
    release_id: c.Identifier
    release_content_hash: c.Digest
    release_governance_hash: c.Digest
    published_review_hash: c.Digest
    original_creation_event_id: c.ActorId
    release_creation_event_id: c.ActorId
    release_review_event_id: c.ActorId


class Membership(c.StrictModel):
    schema_version: Literal["operations_support_membership_v1"]
    case_id: c.Identifier
    members: Annotated[list[MemberBinding], Field(min_length=1, max_length=c.MAX_SOURCES)]


def member_binding(db, header):
    original = r.original_header(db, header["original_id"])
    return MemberBinding(
        original_id=original["original_id"],
        original_content_hash=original["content_hash"],
        original_governance_hash=c.content_hash(r.original_metadata(original)),
        release_id=header["release_id"],
        release_content_hash=header["content_hash"],
        release_governance_hash=c.content_hash(releases.metadata(header)),
        published_review_hash=header["published_review_hash"],
        original_creation_event_id=original["creation_event_id"],
        release_creation_event_id=header["creation_event_id"],
        release_review_event_id=header["review_event_id"],
    )


def creation_detail(header):
    return {
        key: r.utc_text(header[key]) if key == "assembled_at" else header[key]
        for key in ("case_id", "requested_by", "assembled_at", "member_bindings_hash", "private_hash", "public_hash", "source_count")
    }


def case_header(db, user, case_id, *, require_active=True):
    case_id = r.identifier(case_id)
    with db.no_autoflush:
        row = current_rows(db.query(*(getattr(AIOperationsCase, key) for key in CASE_COLUMNS)).filter_by(case_id=case_id), shared=True).one_or_none()
    if row is None:
        raise HTTPException(404, "明确运维材料集不存在")
    h = dict(row._mapping)
    if user.user_role != "super_admin" and user.user_id != h["requested_by"]:
        raise HTTPException(403, "本运维材料集仅供当前创建账户或超级管理员管理")
    try:
        for key in ("member_bindings_hash", "private_hash", "public_hash"):
            TypeAdapter(c.Digest).validate_python(h[key], strict=True)
        if type(h["source_count"]) is not int or not 1 <= h["source_count"] <= c.MAX_SOURCES or h["status"] not in {"active", "revoked"} or h["revision"] != (1 if h["status"] == "active" else 2):
            raise ValueError("Case state differs")
        r.verify_event(db, h["creation_event_id"], h["requested_by"], "operations_case_create", case_id, creation_detail(h), h["assembled_at"])
        # The common revocation receipt uses content_hash; for a collection this
        # is the entire private collection hash, not a public-only substitute.
        r.verify_revocation(db, {**h, "content_hash": h["private_hash"]}, "case", "case_id", h["assembled_at"])
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "运维材料集技术头或具体审计绑定损坏") from exc
    if require_active and h["status"] != "active":
        raise HTTPException(403, "本运维材料集已撤回")
    return h


def metadata(header, *, accessible):
    return {
        **creation_detail(header),
        "creation_event_id": header["creation_event_id"],
        "status": header["status"],
        "revision": header["revision"],
        "revoked_at": r.utc_text(header["revoked_at"]) if header["revoked_at"] is not None else None,
        "revocation_event_id": header["revocation_event_id"],
        "source_accessible": accessible,
        "model_processing_permission": "checked_separately_for_every_member_at_execution",
    }


def current_members(db, header, *, execution=False):
    if header["status"] != "active":
        raise HTTPException(403, "运维材料集已经撤回")
    with db.no_autoflush:
        row = current_rows(db.query(AIOperationsCase.member_bindings_json).filter_by(case_id=header["case_id"]), shared=True).one_or_none()
    try:
        if row is None or len(row.member_bindings_json.encode("utf-8")) > 262144:
            raise ValueError("Complete technical membership exceeds capacity")
        membership = Membership.model_validate(projection._value(row.member_bindings_json), strict=True)
        if membership.case_id != header["case_id"] or c.content_hash(membership) != header["member_bindings_hash"] or len(membership.members) != header["source_count"]:
            raise ValueError("Actual technical membership differs")
        ids = [member.release_id for member in membership.members]
        originals = [member.original_id for member in membership.members]
        if ids != sorted(ids) or len(set(ids)) != len(ids) or len(set(originals)) != len(originals):
            raise ValueError("Explicit complete distinct membership required")
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "运维材料集技术成员清单损坏") from exc
    headers = []
    for member in membership.members:
        live = releases.release_header(db, member.release_id, require_published=True, execution=execution)
        if member_binding(db, live) != member:
            raise HTTPException(409, "材料集原发布版本或治理锚已变化，未读取材料集正文")
        headers.append(live)
    return membership, headers


def read_case_bodies(db, header, membership, current_headers):
    # All current technical permissions were established before reading any member.
    # Recheck actual immutable bytes too; old frozen bodies do not hide a damaged
    # current original, draft or published review with an unchanged SQL header.
    current_values = {h["release_id"]: releases.read_published_body(db, h) for h in current_headers}
    with db.no_autoflush:
        row = current_rows(db.query(AIOperationsCase.private_json, AIOperationsCase.public_json).filter_by(case_id=header["case_id"]), shared=True).one_or_none()
    try:
        if row is None:
            raise ValueError("The exact locked collection disappeared")
        private = projection.verify_private_collection(row.private_json)
        public = projection.OperationsSupportSource.model_validate(projection._value(row.public_json), strict=True)
        if private.collection_id != header["case_id"] or private.requested_by != header["requested_by"] or private.assembled_at != r.utc_text(header["assembled_at"]):
            raise ValueError("Original collection identity differs")
        if (
            c.content_hash(private) != header["private_hash"]
            or c.content_hash(public) != header["public_hash"]
            or len(private.members) != header["source_count"]
            or not projection.verify_public_source(public, private)
        ):
            raise ValueError("Entire private/public collection digest differs")
        actual = {member.review.review_id: member for member in private.members}
        if len(actual) != len(membership.members):
            raise ValueError("Whole collection membership differs")
        for witness in membership.members:
            item = actual.get(witness.release_id)
            if (
                item is None
                or item.original.original_id != witness.original_id
                or c.content_hash(item.original) != witness.original_content_hash
                or c.content_hash(item.review) != witness.published_review_hash
                or (item.original, item.review) != current_values[witness.release_id]
            ):
                raise ValueError("Entire private membership differs from original receipts")
        return private, public
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "完整运维材料集、原件或审核投影损坏") from exc


def create_case(db, user, value):
    actor = lock_operations_write(db, user)
    request = r.typed(CaseCreate, value)
    # Authorize and freeze every member before the first raw original/draft read.
    headers = [releases.release_header(db, release_id, require_published=True) for release_id in sorted(request.release_ids)]
    if len({h["original_id"] for h in headers}) != len(headers):
        raise HTTPException(422, "同一原件的多个发布版本不可默默合并为一次材料来源")
    case_id = str(uuid.uuid4())
    membership = Membership(schema_version="operations_support_membership_v1", case_id=case_id, members=[member_binding(db, h) for h in headers])
    membership_json = r.bounded_json(membership, 262144)
    members = []
    for h in headers:
        original, review = releases.read_published_body(db, h)
        members.append(projection.ReviewedMember(original=original, review=review))
    clock = r.utcnow()
    try:
        private = projection.PrivateOperationsCollection(
            schema_version="operations_support_collection_v1", collection_id=case_id, assembled_at=r.utc_text(clock), requested_by=actor.user_id, members=members
        )
        public = projection.project_source(private)
    except (ValidationError, ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "完整有限材料集超限或时钟不一致，未截取前若干项") from exc
    private_json, public_json = r.bounded_json(private), r.bounded_json(public)
    h = dict(
        case_id=case_id,
        requested_by=actor.user_id,
        assembled_at=clock,
        member_bindings_hash=c.content_hash(membership),
        private_hash=c.content_hash(private),
        public_hash=c.content_hash(public),
        source_count=len(members),
    )
    event_id = r.audit_event(db, actor.user_id, "operations_case_create", case_id, creation_detail(h), clock)
    db.add(AIOperationsCase(**h, member_bindings_json=membership_json, private_json=private_json, public_json=public_json, creation_event_id=event_id, status="active", revision=1, revoke_reason=""))
    db.flush()
    saved = case_header(db, actor, case_id)
    current, live_headers = current_members(db, saved)
    if read_case_bodies(db, saved, current, live_headers) != (private, public):
        raise HTTPException(409, "运维材料集实际写入读回不一致")
    return metadata(saved, accessible=True)


def source_current(db, user, case_id, *, execution=False):
    actor = lock_operations_write(db, user)
    header = case_header(db, actor, case_id)
    membership, live_headers = current_members(db, header, execution=execution)
    private, public = read_case_bodies(db, header, membership, live_headers)
    return actor, header, membership, private, public


def get_case_part(db, user, case_id, part):
    if part not in {"source", "private"}:
        raise HTTPException(422, "运维材料集分件仅允许source或private")
    if part == "private":
        lock_operations_write(db, user, governance=True)
    _, _, _, private, public = source_current(db, user, case_id)
    # Each complete canonical body is bounded independently, without an envelope.
    return private.model_dump(mode="json") if part == "private" else public.model_dump(mode="json")


def describe_case(db, user, case_id):
    actor = lock_operations_write(db, user)
    header = case_header(db, actor, case_id, require_active=False)
    try:
        current_members(db, header)
        accessible = True
    except HTTPException as exc:
        if exc.status_code not in (403, 409):
            raise
        accessible = False
    return metadata(header, accessible=accessible)


def revoke_case(db, user, case_id, value):
    actor = lock_operations_write(db, user, governance=True)
    request = r.typed(SourceRevoke, value)
    h = case_header(db, actor, case_id)
    if h["revision"] != request.revision:
        raise HTTPException(409, "运维材料集版本已变化")
    clock = r.utcnow()
    if clock < h["assembled_at"]:
        raise HTTPException(409, "实际撤回时钟早于材料集")
    event_id = r.audit_event(
        db,
        actor.user_id,
        "operations_case_revoke",
        h["case_id"],
        {
            "id": h["case_id"],
            "content_hash": h["private_hash"],
            "revision": 2,
            "reason_sha256": r.raw_sha(request.reason),
            "revoked_at": r.utc_text(clock),
        },
        clock,
    )
    with db.no_autoflush:
        count = (
            db.query(AIOperationsCase)
            .filter_by(case_id=h["case_id"], revision=request.revision, status="active")
            .update(dict(status="revoked", revision=2, revoked_by=actor.user_id, revoked_at=clock, revoke_reason=request.reason, revocation_event_id=event_id), synchronize_session=False)
        )
    if count != 1:
        raise HTTPException(409, "当前运维材料集撤回状态已变化")
    db.flush()
    return metadata(case_header(db, actor, h["case_id"], require_active=False), accessible=False)
