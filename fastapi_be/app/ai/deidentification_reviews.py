"""Explicit literal edits and a separate independent residual-risk review."""

import uuid

from fastapi import HTTPException

from app.ai import deidentification_lifecycle as life
from app.ai import deidentification_sources as sources
from app.ai.deidentification_contract import LIMITATIONS, GovernanceReview, GovernanceRevoke, ResidualReview, ReviewCreate
from app.ai.deidentification_models import AIDeidentificationReview
from app.ai.deidentification_spans import apply_edits, digest, text_digest, utf8
from app.ai.research_cohort_sources import _typed, utc_text, utcnow
from app.ai.research_cohort_write_guard import current_research_rows


def publication_view(db, source):
    """Rebuild the retained original publication, never restore its authority."""
    snapshot = source["snapshot"]
    if snapshot is None:
        raise HTTPException(403, "当前项目和逐患者用途未授权，未读取复核正文")
    header = sources._opaque(db, source["case_id"])
    if header["reviewed_by"] is None or header["status"] not in {"published", "revoked"} or header["revision"] not in {2, 3}:
        raise HTTPException(409, "复核须绑定真实已发布来源")
    header.update(status="published", revision=2, revoked_by=None, revoked_at=None, revoke_reason_hash=text_digest(""))
    meta = sources.metadata(header)
    public = sources.project_snapshot(snapshot, meta)
    binding = {
        "case_id": meta["case_id"],
        "content_hash": meta["content_hash"],
        "governance_hash": meta["governance_hash"],
        "collection_digest": meta["collection_digest"],
        "projection_hash": digest(public),
    }
    return snapshot, public, binding


def original_proof(row, source, db):
    value = life.original_json(row.review_json)
    keys = {"schema_version", "review_id", "case_id", "created_by", "recorded_at", "source_binding", "request", "output_hash", "output_bytes", "limitations"}
    if type(value) is not dict or set(value) != keys:
        raise HTTPException(409, "完整逐字复核原件须闭合")
    request = _typed(ReviewCreate, value["request"])
    _, public, binding = publication_view(db, source)
    try:
        output = apply_edits(public["documents"], [edit.model_dump() for edit in request.edits])
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, "原文/逐字位置/全部明确选择无法复算") from exc
    expected = ("deidentification_review_v1", row.review_id, row.case_id, row.created_by, utc_text(row.created_at), binding, digest(output), len(utf8(life.bounded(output))), list(LIMITATIONS))
    actual = tuple(value[k] for k in ("schema_version", "review_id", "case_id", "created_by", "recorded_at", "source_binding", "output_hash", "output_bytes", "limitations"))
    if (
        actual != expected
        or request.case_id != row.case_id
        or (request.expected_content_hash, request.expected_governance_hash) != (binding["content_hash"], binding["governance_hash"])
        or row.schema_version != expected[0]
        or row.content_hash != digest(value)
        or row.output_json != life.bounded(output)
        or (row.output_hash, row.output_bytes) != (digest(output), len(utf8(row.output_json)))
    ):
        raise HTTPException(409, "复核SQL原件、父发布锚或完整输出不符")
    life.verify_manual(row)
    return value, output


def locked_review(db, user, identifier, *, audit_only=False, execution=False, writing=False):
    actor = sources.actor_now(db, user)
    header = life.opaque(db, AIDeidentificationReview, "review_id", identifier)
    source = sources.source_current(db, actor, header["case_id"], audit_only=audit_only, execution=execution)
    if source["snapshot"] is None:
        return actor, header, source, None, None, None
    row = current_research_rows(db.query(AIDeidentificationReview).filter_by(review_id=identifier), shared=not writing).one()
    original, output = original_proof(row, source, db)
    return actor, header, source, row, original, output


def get_review(db, user, identifier, *, audit_only=False, execution=False):
    actor, header, source, row, original, output = locked_review(db, user, identifier, audit_only=audit_only, execution=execution)
    current = source["eligible"]
    manual_current = False
    if row is not None:
        try:
            manual_current = life.manual_current(db, row, source["snapshot"])
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}:
                raise
    eligible = bool(current and manual_current and header["status"] == "published" and not audit_only)
    if execution and not eligible:
        raise HTTPException(409, "完整来源、独立残余风险复核或技术发布当前失效")
    visible = row is not None and (audit_only or current and header["status"] in {"draft", "published"})
    return {
        **life.metadata(header, "review"),
        "original": original if visible else None,
        "output": output if visible else None,
        "manual_review": life.verify_manual(row) if visible else None,
        "current": bool(current),
        "eligible": eligible,
        "audit_only": audit_only,
        "can_manual_review": bool(current and not audit_only and header["status"] == "draft" and header["manual_status"] == "unknown" and actor.user_id != header["created_by"]),
        "can_review": bool(current and not audit_only and actor.user_role == "super_admin" and header["status"] == "draft"),
        "can_revoke": bool(not audit_only and header["status"] in {"draft", "published"} and (actor.user_role == "super_admin" or actor.user_id == header["created_by"])),
        "limitations": list(LIMITATIONS),
        "anonymity_guaranteed": False,
    }


def _validate(db, actor, identifier):
    _, _, source, row, _, _ = locked_review(db, actor, identifier, execution=True)
    if row is None or not source["eligible"]:
        raise HTTPException(409, "写后当前来源或临床用途失效")
    if row.manual_status == "reviewed_residual_risk_remains" and not life.manual_current(db, row, source["snapshot"]):
        raise HTTPException(409, "原独立人工签署已失权或失效")


def create_review(db, user, values):
    request = _typed(ReviewCreate, values)
    try:
        actor = sources.actor_now(db, user)
        source = sources.source_current(db, actor, request.case_id, execution=True)
        _, public, binding = publication_view(db, source)
        if (request.expected_content_hash, request.expected_governance_hash) != (source["content_hash"], source["governance_hash"]):
            raise HTTPException(409, "明确来源CAS已改变")
        try:
            output = apply_edits(public["documents"], [edit.model_dump() for edit in request.edits])
        except ValueError as exc:
            raise HTTPException(422, "明确逐字编辑不合法，未自动修正") from exc
        raw_output = life.bounded(output)
        identifier, now = str(uuid.uuid4()), utcnow()
        original = dict(
            schema_version="deidentification_review_v1",
            review_id=identifier,
            case_id=request.case_id,
            created_by=actor.user_id,
            recorded_at=utc_text(now),
            source_binding=binding,
            request=request.model_dump(),
            output_hash=digest(output),
            output_bytes=len(utf8(raw_output)),
            limitations=list(LIMITATIONS),
        )
        row = AIDeidentificationReview(
            review_id=identifier,
            case_id=request.case_id,
            schema_version=original["schema_version"],
            review_json=life.bounded(original),
            content_hash=digest(original),
            output_json=raw_output,
            output_hash=digest(output),
            output_bytes=len(utf8(raw_output)),
            created_at=now,
            created_by=actor.user_id,
            **life.initialise(),
        )
        db.add(row)
        life.finish(db, actor, row, "review_id", "review", "deidentification.review.create", lambda current: _validate(db, current, identifier))
        return get_review(db, actor, identifier)
    except Exception:
        db.rollback()
        raise


def review_original(db, user, identifier, values, *, manual=False, revoke=False):
    request = _typed(ResidualReview if manual else GovernanceRevoke if revoke else GovernanceReview, values)
    try:
        actor = sources.actor_now(db, user)
        header = life.opaque(db, AIDeidentificationReview, "review_id", sources._key(identifier), writing=True)
        if revoke:
            updates = life.governance_updates(actor, header, request, revoke=True)
            return life.stop(db, actor, AIDeidentificationReview, "review_id", identifier, header, updates, "review")
        actor, header, source, row, _, _ = locked_review(db, actor, identifier, execution=True, writing=True)
        if row is None:
            raise HTTPException(403, "当前临床目的未授权")
        updates = life.manual_updates(actor, header, request) if manual else life.governance_updates(actor, header, request, revoke=False)
        if not manual and request.decision == "publish" and not life.manual_current(db, row, source["snapshot"]):
            raise HTTPException(409, "技术发布不能代替当前独立签署")
        for key, value in updates.items():
            setattr(row, key, value)
        life.finish(db, actor, row, "review_id", "review", "deidentification.review.manual" if manual else "deidentification.review.review", lambda current: _validate(db, current, identifier))
        return get_review(db, actor, identifier)
    except Exception:
        db.rollback()
        raise
