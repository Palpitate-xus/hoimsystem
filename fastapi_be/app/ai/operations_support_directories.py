"""Body-free bounded operations directories; explicit published previews are separate."""

from fastapi import HTTPException

from app.ai import operations_support_cases as cases
from app.ai import operations_support_registry as originals
from app.ai import operations_support_releases as releases
from app.ai.operations_support_models import AIOperationsCase, AIOperationsOriginal, AIOperationsRelease
from app.ai.operations_support_projection import ReleasedOperationsDocument
from app.ai.operations_support_write_guard import current_rows, lock_operations_write
from app.sql_counts import locked_row_count


def pagination(page, size):
    if type(page) is not int or page < 1 or type(size) is not int or not 1 <= size <= 50:
        raise HTTPException(422, "目录页码须为正整数，每页最多50项")


def list_sources(db, user, kind, *, page=1, size=20):
    pagination(page, size)
    if kind not in {"originals", "releases", "cases"}:
        raise HTTPException(422, "未知运维来源目录")
    actor = lock_operations_write(db, user, governance=kind == "originals")
    model, key = {"originals": (AIOperationsOriginal, "original_id"), "releases": (AIOperationsRelease, "release_id"), "cases": (AIOperationsCase, "case_id")}[kind]
    query = db.query(getattr(model, key))
    if actor.user_role != "super_admin":
        query = query.filter(model.status == "published") if kind == "releases" else query.filter(model.requested_by == actor.user_id)
    with db.no_autoflush:
        total = locked_row_count(current_rows(query, shared=True), getattr(model, key))
        ids = current_rows(query.order_by(getattr(model, key)), shared=True).offset((page - 1) * size).limit(size).all()
    items = []
    for (item_id,) in ids:
        if kind == "originals":
            items.append(originals.original_metadata(originals.original_header(db, item_id, require_active=False)))
        elif kind == "releases":
            try:
                h = releases.release_header(db, item_id, require_live=actor.user_role != "super_admin", require_published=actor.user_role != "super_admin")
            except HTTPException as exc:
                if actor.user_role != "super_admin" and exc.status_code in (403, 409):
                    # Keep the finite selected directory slot explicit; no body
                    # or private original/account fields enter an admin row.
                    items.append({"release_id": item_id, "source_accessible": False})
                    continue
                raise
            value = releases.metadata(h) if actor.user_role == "super_admin" else {key: h[key] for key in ("release_id", "status", "revision", "published_review_hash", "model_processing_allowed")}
            try:
                releases.release_header(db, item_id, require_published=True)
                accessible = True
            except HTTPException as exc:
                if exc.status_code not in (403, 409):
                    raise
                accessible = False
            items.append({**value, "source_accessible": accessible})
        else:
            items.append(cases.describe_case(db, actor, item_id))
    return {"items": items, "total": total, "page": page, "size": size, "body_read_policy": "metadata_only_explicit_part_required"}


def preview_release(db, user, release_id):
    lock_operations_write(db, user)
    h = releases.release_header(db, release_id, require_published=True)
    original, review = releases.read_published_body(db, h)
    return ReleasedOperationsDocument(
        source_id=review.review_id,
        kind=original.kind,
        title=review.released_title,
        declared_component=review.released_component,
        declared_version=review.released_version,
        text=review.released_text,
        text_sha256=originals.raw_sha(review.released_text),
    ).model_dump(mode="json")
