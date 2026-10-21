"""Server-owned independent operations publication; private drafts stay private."""

import uuid

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from app.ai import operations_support_contract as c
from app.ai import operations_support_registry as r
from app.ai.models import AIAuditEvent
from app.ai.operations_support_models import AIOperationsRelease
from app.ai.operations_support_projection import _value
from app.ai.operations_support_registry_contract import ReleaseCreate, ReleaseReview, SourceRevoke
from app.ai.operations_support_write_guard import current_rows, lock_operations_write

RELEASE_COLUMNS = (
    "release_id",
    "original_id",
    "original_content_hash",
    "original_captured_by",
    "content_hash",
    "created_by",
    "recorded_at",
    "creation_event_id",
    "status",
    "revision",
    "review_decision",
    "privacy_reviewed",
    "faithfulness_reviewed",
    "applicability_reviewed",
    "model_processing_allowed",
    "reviewed_by",
    "reviewed_at",
    "review_event_id",
    "published_review_hash",
    "revoked_by",
    "revoked_at",
    "revoke_reason",
    "revocation_event_id",
)
REVIEW_FLAGS = ("privacy_reviewed", "faithfulness_reviewed", "applicability_reviewed", "model_processing_allowed")


def creation_detail(header):
    return {
        key: r.utc_text(header[key]) if key == "recorded_at" else header[key]
        for key in (
            "release_id",
            "original_id",
            "original_content_hash",
            "original_captured_by",
            "content_hash",
            "created_by",
            "recorded_at",
        )
    }


def review_detail(header, basis_hash):
    return {
        **{
            key: r.utc_text(header[key]) if key == "reviewed_at" else header[key]
            for key in (
                "release_id",
                "content_hash",
                "review_decision",
                *REVIEW_FLAGS,
                "reviewed_by",
                "reviewed_at",
                "published_review_hash",
            )
        },
        "review_basis_sha256": basis_hash,
        "review_revision": 2,
    }


def release_header(db, release_id, *, require_live=True, require_published=False, execution=False):
    release_id = r.identifier(release_id)
    with db.no_autoflush:
        row = current_rows(db.query(*(getattr(AIOperationsRelease, key) for key in RELEASE_COLUMNS)).filter_by(release_id=release_id), shared=True).one_or_none()
    if row is None:
        raise HTTPException(404, "明确运维发布版本不存在")
    h = dict(row._mapping)
    try:
        TypeAdapter(c.Digest).validate_python(h["content_hash"], strict=True)
        r.verify_event(db, h["creation_event_id"], h["created_by"], "operations_release_create", release_id, creation_detail(h), h["recorded_at"])
        original = r.original_header(db, h["original_id"], require_active=require_live)
        if original["content_hash"] != h["original_content_hash"] or original["captured_by"] != h["original_captured_by"] or h["recorded_at"] < original["captured_at"]:
            raise ValueError("The actual original header differs")
        if h["reviewed_by"] is None:
            if h["status"] not in {"draft", "revoked"} or h["revision"] != (1 if h["status"] == "draft" else 2):
                raise ValueError("Unreviewed state differs")
            if any(h[key] is not None for key in (*REVIEW_FLAGS, "review_decision", "reviewed_at", "review_event_id", "published_review_hash")):
                raise ValueError("Draft contains invented review")
            h["review_basis_sha256"] = None
        else:
            if h["reviewed_by"] in {h["created_by"], h["original_captured_by"]} or h["reviewed_at"] is None or h["reviewed_at"] < h["recorded_at"]:
                raise ValueError("Review is not independent or chronological")
            if h["review_decision"] not in {"published", "rejected"} or h["status"] not in {h["review_decision"], "revoked"} or h["revision"] != (3 if h["status"] == "revoked" else 2):
                raise ValueError("Reviewed state differs")
            if any(type(h[key]) is not int or h[key] not in (0, 1) for key in REVIEW_FLAGS):
                raise ValueError("Review flags are unknown")
            positive = all(h[key] == 1 for key in REVIEW_FLAGS[:3])
            if positive != (h["review_decision"] == "published") or not positive and h["model_processing_allowed"] != 0:
                raise ValueError("Review decision differs from actual flags")
            if positive:
                TypeAdapter(c.Digest).validate_python(h["published_review_hash"], strict=True)
            elif h["published_review_hash"] is not None:
                raise ValueError("A rejection has no invented public review")
            with db.no_autoflush:
                receipt = current_rows(db.query(AIAuditEvent.detail_json).filter_by(event_id=h["review_event_id"]), shared=True).one_or_none()
            if receipt is None:
                raise ValueError("Specific review audit is missing")
            detail = _value(receipt.detail_json)
            if type(detail) is not dict:
                raise ValueError("Closed review audit required")
            basis_hash = TypeAdapter(c.Digest).validate_python(detail.get("review_basis_sha256"), strict=True)
            r.verify_event(db, h["review_event_id"], h["reviewed_by"], "operations_release_review", release_id, review_detail(h, basis_hash), h["reviewed_at"])
            h["review_basis_sha256"] = basis_hash
        r.verify_revocation(db, h, "release", "release_id", h["recorded_at"])
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "运维发布版本技术头、独立审核或具体审计绑定损坏") from exc
    if require_live and h["status"] == "revoked" or require_published and h["status"] != "published":
        raise HTTPException(403, "该运维版本尚未发布、已被拒绝或已撤回")
    if require_published:
        from app.models import User

        with db.no_autoflush:
            reviewer = current_rows(db.query(User.user_id, User.user_role).filter_by(user_id=h["reviewed_by"]), shared=True).one_or_none()
        if reviewer is None or reviewer.user_role != "super_admin":
            raise HTTPException(403, "原独立发布审核人已不具备当前治理角色")
    if execution and (not require_published or h["model_processing_allowed"] != 1):
        raise HTTPException(403, "本运维版本未明确允许模型处理，发布本身不授予此许可")
    return h


def metadata(h):
    return {
        **creation_detail(h),
        **{
            key: r.utc_text(h[key]) if key in {"reviewed_at", "revoked_at"} and h[key] is not None else h[key]
            for key in (
                "creation_event_id",
                "status",
                "revision",
                "review_decision",
                *REVIEW_FLAGS,
                "reviewed_by",
                "reviewed_at",
                "review_event_id",
                "published_review_hash",
                "revoked_at",
                "revocation_event_id",
            )
        },
    }


def read_draft(db, header):
    original_header = r.original_header(db, header["original_id"])
    original = r.read_original_body(db, original_header)
    with db.no_autoflush:
        row = current_rows(db.query(AIOperationsRelease.draft_json).filter_by(release_id=header["release_id"]), shared=True).one_or_none()
    try:
        draft = _value(row.draft_json) if row is not None else None
        expected_keys = {"schema_version", "release_id", "created_by", "recorded_at", "proposal", "released_text"}
        if type(draft) is not dict or set(draft) != expected_keys or draft["schema_version"] != "operations_support_release_draft_v1":
            raise ValueError("Closed entire draft required")
        request = ReleaseCreate.model_validate(draft["proposal"], strict=True)
        if (
            draft["release_id"] != header["release_id"]
            or type(draft["created_by"]) is not int
            or draft["created_by"] != header["created_by"]
            or draft["recorded_at"] != r.utc_text(header["recorded_at"])
        ):
            raise ValueError("Server identity differs")
        if request.original_id != original.original_id or request.original_full_sha256 != c.content_hash(original) or c.content_hash(draft) != header["content_hash"]:
            raise ValueError("Whole draft/original binding differs")
        if c.apply_redactions(original.content_text, request.redactions) != draft["released_text"]:
            raise ValueError("Complete reviewed derivative differs")
        return original, request, draft
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "完整运维草稿、明确码点变换或原件绑定损坏") from exc


def create_release(db, user, value):
    actor = lock_operations_write(db, user, governance=True)
    request = r.typed(ReleaseCreate, value)
    original_header = r.original_header(db, request.original_id)
    if original_header["content_hash"] != request.original_full_sha256:
        raise HTTPException(409, "明确原件SHA已变化，未先读取原件正文")
    original = r.read_original_body(db, original_header)
    clock = r.utcnow()
    if clock < original_header["captured_at"]:
        raise HTTPException(409, "实际服务器时钟早于原件登记")
    release_id = str(uuid.uuid4())
    try:
        released_text = c.apply_redactions(original.content_text, request.redactions)
        TypeAdapter(c.Text).validate_python(released_text, strict=True)
    except (ValidationError, ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "明确码点变换须产生完整、非空且容量允许的衍生材料") from exc
    draft = {
        "schema_version": "operations_support_release_draft_v1",
        "release_id": release_id,
        "created_by": actor.user_id,
        "recorded_at": r.utc_text(clock),
        "proposal": request.model_dump(mode="json"),
        "released_text": released_text,
    }
    draft_json = r.bounded_json(draft)
    h = dict(
        release_id=release_id,
        original_id=original.original_id,
        original_content_hash=c.content_hash(original),
        original_captured_by=original.captured_by,
        content_hash=c.content_hash(draft),
        created_by=actor.user_id,
        recorded_at=clock,
    )
    event_id = r.audit_event(db, actor.user_id, "operations_release_create", release_id, creation_detail(h), clock)
    row = AIOperationsRelease(**h, draft_json=draft_json, creation_event_id=event_id, status="draft", revision=1, review_basis="", revoke_reason="")
    db.add(row)
    db.flush()
    saved = release_header(db, release_id)
    if read_draft(db, saved)[2] != draft:
        raise HTTPException(409, "运维草稿实际写入读回不一致")
    return metadata(saved)


def _declared_review(header, proposal, draft, actor_id, clock, basis):
    return c.DeclaredOperationsReview(
        schema_version="operations_support_declared_review_v1",
        review_id=header["release_id"],
        original_id=header["original_id"],
        original_full_sha256=header["original_content_hash"],
        released_title=proposal.released_title,
        released_component=proposal.released_component,
        released_version=proposal.released_version,
        redactions=proposal.redactions,
        released_text=draft["released_text"],
        privacy_reviewed=True,
        faithfulness_reviewed=True,
        applicability_declaration_reviewed=True,
        review_basis=basis,
        reviewed_at=r.utc_text(clock),
        reviewed_by=actor_id,
    )


def review_release(db, user, release_id, value):
    actor = lock_operations_write(db, user, governance=True)
    request = r.typed(ReleaseReview, value)
    h = release_header(db, release_id)
    if h["status"] != "draft" or h["revision"] != request.revision:
        raise HTTPException(409, "审核对象必须是明确当前未审核草稿")
    if actor.user_id in {h["created_by"], h["original_captured_by"]}:
        raise HTTPException(403, "发布审核人必须独立于原件登记人与草稿创建人")
    original, proposal, draft = read_draft(db, h)
    clock = r.utcnow()
    if clock < h["recorded_at"]:
        raise HTTPException(409, "审核时钟早于草稿，未伪造时间")
    published = None
    if request.decision == "publish":
        try:
            published = _declared_review(h, proposal, draft, actor.user_id, clock, request.basis)
            c.verify_declared_review(original, published)
        except (ValidationError, ValueError, TypeError, UnicodeError) as exc:
            raise HTTPException(422, "完整原件与独立发布衍生材料超限或绑定无效") from exc
    changes = dict(
        status="published" if published is not None else "rejected",
        revision=2,
        review_decision="published" if published is not None else "rejected",
        privacy_reviewed=int(request.privacy_reviewed),
        faithfulness_reviewed=int(request.faithfulness_reviewed),
        applicability_reviewed=int(request.applicability_reviewed),
        model_processing_allowed=int(request.model_processing_allowed),
        reviewed_by=actor.user_id,
        reviewed_at=clock,
        review_basis=request.basis,
        published_review_json=r.bounded_json(published) if published is not None else None,
        published_review_hash=c.content_hash(published) if published is not None else None,
    )
    detail_header = {**h, **changes}
    changes["review_event_id"] = r.audit_event(db, actor.user_id, "operations_release_review", h["release_id"], review_detail(detail_header, r.raw_sha(request.basis)), clock)
    with db.no_autoflush:
        count = db.query(AIOperationsRelease).filter_by(release_id=h["release_id"], status="draft", revision=request.revision).update(changes, synchronize_session=False)
    if count != 1:
        raise HTTPException(409, "运维草稿审核版本已变化")
    db.flush()
    saved = release_header(db, h["release_id"])
    if published is not None:
        read_published_body(db, saved)
    return metadata(saved)


def read_published_body(db, header):
    original, proposal, draft = read_draft(db, header)
    with db.no_autoflush:
        row = current_rows(db.query(AIOperationsRelease.published_review_json, AIOperationsRelease.review_basis).filter_by(release_id=header["release_id"]), shared=True).one_or_none()
    try:
        if row is None or r.raw_sha(row.review_basis) != header["review_basis_sha256"]:
            raise ValueError("Private review basis differs")
        published = c.DeclaredOperationsReview.model_validate(_value(row.published_review_json), strict=True)
        expected = _declared_review(header, proposal, draft, header["reviewed_by"], header["reviewed_at"], row.review_basis)
        c.verify_declared_review(original, published)
        if published != expected or c.content_hash(published) != header["published_review_hash"]:
            raise ValueError("Whole published review differs")
        return original, published
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "实际独立发布全文、审核依据或SHA损坏") from exc


def get_release(db, user, release_id, *, include_body=False):
    lock_operations_write(db, user, governance=True)
    h = release_header(db, release_id, require_live=include_body)
    if not include_body:
        return metadata(h)
    return read_draft(db, h)[2]


def revoke_release(db, user, release_id, value):
    actor = lock_operations_write(db, user, governance=True)
    request = r.typed(SourceRevoke, value)
    h = release_header(db, release_id, require_live=False)
    if h["status"] == "revoked" or h["revision"] != request.revision:
        raise HTTPException(409, "运维发布版本已变化或撤回")
    clock = r.utcnow()
    if clock < (h["reviewed_at"] or h["recorded_at"]):
        raise HTTPException(409, "实际撤回时钟早于原版本")
    changes = dict(status="revoked", revision=h["revision"] + 1, revoked_by=actor.user_id, revoked_at=clock, revoke_reason=request.reason)
    changes["revocation_event_id"] = r.audit_event(
        db,
        actor.user_id,
        "operations_release_revoke",
        h["release_id"],
        {
            "id": h["release_id"],
            "content_hash": h["content_hash"],
            "revision": changes["revision"],
            "reason_sha256": r.raw_sha(request.reason),
            "revoked_at": r.utc_text(clock),
        },
        clock,
    )
    with db.no_autoflush:
        count = db.query(AIOperationsRelease).filter_by(release_id=h["release_id"], revision=request.revision).update(changes, synchronize_session=False)
    if count != 1:
        raise HTTPException(409, "运维版本撤回时当前状态已变化")
    db.flush()
    return metadata(release_header(db, h["release_id"], require_live=False))
