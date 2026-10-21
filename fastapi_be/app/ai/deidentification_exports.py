"""Single reviewed output release, exact audit receipts and finite downloads.

A release records documentary authority; no platform role is treated as that
permission. Exports contain the explicitly reviewed output, never original
quotes, review notes, consent text or the old whole-research ZIP.
"""

import datetime as dt
import uuid

from fastapi import HTTPException

from app.ai import deidentification_lifecycle as life
from app.ai import deidentification_reviews as reviews
from app.ai import deidentification_sources as sources
from app.ai.deidentification_contract import LIMITATIONS, GovernanceReview, GovernanceRevoke, ReleaseAuthorityReview, ReleaseCreate
from app.ai.deidentification_models import AIDeidentificationExportRelease
from app.ai.deidentification_spans import canonical, digest, utf8
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_sources import _typed, utc_text, utcnow
from app.ai.research_cohort_write_guard import current_actor, current_research_rows


def export_artifact(identifier, review, source, output):
    """Whole finite output; explicit original metadata is not automatically safe."""
    value = {
        "schema_version": "deidentification_single_export_v1",
        "release_id": identifier,
        "review_id": review.review_id,
        "source_id": source["source_id"],
        "source_content_hash": source["content_hash"],
        "review_content_hash": review.content_hash,
        "selected_output_hash": digest(output),
        "documents": output["documents"],
        "coverage": "complete_explicitly_selected_output_only",
        "limitations": list(LIMITATIONS),
        "anonymity_guaranteed": False,
    }
    life.bounded(value)
    return value


def review_binding(header, review):
    return {
        "review_id": review.review_id,
        "content_hash": review.content_hash,
        "governance_hash": digest(life.governance(header)),
        "output_hash": review.output_hash,
        "manual_review_hash": header["manual_review_json_hash"],
    }


def _published_review_header(header):
    from app.ai.deidentification_spans import text_digest

    if header["reviewed_by"] is None or header["status"] not in {"published", "revoked"} or header["revision"] not in {2, 3}:
        raise HTTPException(409, "放行必须绑定实际已发布复核")
    value = dict(header)
    value.update(status="published", revision=2, revoked_by=None, revoked_at=None, revoke_reason_hash=text_digest(""))
    return value


def original_proof(row, review, header, source, output):
    value = life.original_json(row.release_json)
    keys = {"schema_version", "release_id", "review_id", "created_by", "recorded_at", "review_binding", "request", "artifact_hash", "artifact_bytes", "limitations"}
    if type(value) is not dict or set(value) != keys:
        raise HTTPException(409, "完整导出放行原件须闭合")
    request = _typed(ReleaseCreate, value["request"])
    binding = review_binding(_published_review_header(header), review)
    artifact = export_artifact(row.release_id, review, source, output)
    expected = ("deidentification_release_v1", row.release_id, row.review_id, row.created_by, utc_text(row.created_at), binding, digest(artifact), len(utf8(life.bounded(artifact))), list(LIMITATIONS))
    actual = tuple(value[k] for k in ("schema_version", "release_id", "review_id", "created_by", "recorded_at", "review_binding", "artifact_hash", "artifact_bytes", "limitations"))
    if (
        actual != expected
        or request.review_id != row.review_id
        or (request.expected_content_hash, request.expected_governance_hash) != (review.content_hash, binding["governance_hash"])
        or row.content_hash != digest(value)
        or row.schema_version != expected[0]
        or row.artifact_json != life.bounded(artifact)
        or (row.artifact_hash, row.artifact_bytes) != (digest(artifact), len(utf8(row.artifact_json)))
        or (utc_text(row.valid_from), utc_text(row.valid_until), row.maximum_downloads) != (request.valid_from, request.valid_until, request.maximum_downloads)
    ):
        raise HTTPException(409, "导出原件、独立复核、完整输出或SQL时间/次数锚不符")
    life.verify_manual(row)
    return value, artifact


def locked_release(db, user, identifier, *, audit_only=False, execution=False, writing=False):
    actor = sources.actor_now(db, user)
    header = life.opaque(db, AIDeidentificationExportRelease, "release_id", identifier)
    actor, review_header, source, review, _, output = reviews.locked_review(db, actor, header["review_id"], audit_only=audit_only, execution=execution)
    if review is None:
        return actor, header, source, review, None, None, None
    row = current_research_rows(db.query(AIDeidentificationExportRelease).filter_by(release_id=identifier), shared=not writing).one()
    original, artifact = original_proof(row, review, review_header, source, output)
    return actor, header, source, review, row, original, artifact


def _authority_ready(original, row):
    request = original["request"]
    now = utcnow()
    return bool(
        request["authority_status"] == "recorded_permitted"
        and request["authority_reference"] is not None
        and request["authority_reference"].strip() != ""
        and request["original_authority_text"] is not None
        and request["original_authority_text"].strip() != ""
        and request["recipient_reference"].strip() != ""
        and row.valid_from is not None
        and row.valid_until is not None
        and row.valid_from <= now < row.valid_until
    )


def get_release(db, user, identifier, *, audit_only=False, execution=False):
    actor, header, source, review, row, original, artifact = locked_release(db, user, identifier, audit_only=audit_only, execution=execution)
    current = bool(source["eligible"] and review is not None and review.status == "published")
    manual_current = False
    if current:
        try:
            current = life.manual_current(db, review, source["snapshot"])
            manual_current = life.manual_current(db, row, source["snapshot"])
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}:
                raise
            current = False
    eligible = bool(current and header["status"] == "published" and manual_current and _authority_ready(original, row) and row.download_count < row.maximum_downloads and not audit_only)
    if execution and not eligible:
        raise HTTPException(409, "导出依据、有效期、次数、独立复核或当前来源未闭合")
    visible = row is not None and (audit_only or current and header["status"] in {"draft", "published"})
    return {
        **life.metadata(header, "release"),
        "original": original if visible else None,
        "artifact": artifact if visible else None,
        "manual_review": life.verify_manual(row) if visible else None,
        "current": bool(current),
        "eligible": eligible,
        "audit_only": audit_only,
        "download_count": header["download_count"],
        "maximum_downloads": header["maximum_downloads"],
        "valid_from": utc_text(header["valid_from"]),
        "valid_until": utc_text(header["valid_until"]),
        "can_manual_review": bool(current and not audit_only and header["status"] == "draft" and header["manual_status"] == "unknown" and actor.user_id != header["created_by"]),
        "can_review": bool(current and not audit_only and actor.user_role == "super_admin" and header["status"] == "draft"),
        "can_revoke": bool(not audit_only and header["status"] in {"draft", "published"} and (actor.user_role == "super_admin" or actor.user_id == header["created_by"])),
        "limitations": list(LIMITATIONS),
        "anonymity_guaranteed": False,
    }


def _validate(db, actor, identifier, *, require_manual=False):
    _, _, source, review, row, _, _ = locked_release(db, actor, identifier, execution=True)
    if row is None or review.status != "published" or not life.manual_current(db, review, source["snapshot"]):
        raise HTTPException(409, "写后当前完整复核或签署失效")
    if require_manual and not life.manual_current(db, row, source["snapshot"]):
        raise HTTPException(409, "放行独立审核当前失效")


def create_release(db, user, values):
    request = _typed(ReleaseCreate, values)
    try:
        actor, header, source, review, _, output = reviews.locked_review(db, user, request.review_id, execution=True)
        if review is None or review.status != "published" or not life.manual_current(db, review, source["snapshot"]):
            raise HTTPException(409, "仅当前已独立复核并技术发布的整件输出可申请单件放行")
        binding = review_binding(header, review)
        if (request.expected_content_hash, request.expected_governance_hash) != (review.content_hash, binding["governance_hash"]):
            raise HTTPException(409, "明确复核CAS已变化")
        identifier, now = str(uuid.uuid4()), utcnow()
        artifact = export_artifact(identifier, review, source, output)
        raw = life.bounded(artifact)
        original = dict(
            schema_version="deidentification_release_v1",
            release_id=identifier,
            review_id=review.review_id,
            created_by=actor.user_id,
            recorded_at=utc_text(now),
            review_binding=binding,
            request=request.model_dump(),
            artifact_hash=digest(artifact),
            artifact_bytes=len(utf8(raw)),
            limitations=list(LIMITATIONS),
        )
        dates = {key: dt.datetime.strptime(getattr(request, key), "%Y-%m-%dT%H:%M:%S.%fZ") if getattr(request, key) is not None else None for key in ("valid_from", "valid_until")}
        row = AIDeidentificationExportRelease(
            release_id=identifier,
            review_id=review.review_id,
            schema_version=original["schema_version"],
            release_json=life.bounded(original),
            content_hash=digest(original),
            artifact_json=raw,
            artifact_hash=digest(artifact),
            artifact_bytes=len(utf8(raw)),
            maximum_downloads=request.maximum_downloads,
            download_count=0,
            last_download_event_id=None,
            last_download_at=None,
            created_at=now,
            created_by=actor.user_id,
            **dates,
            **life.initialise(),
        )
        db.add(row)
        return life.finish(
            db,
            actor,
            row,
            "release_id",
            "release",
            "deidentification.release.create",
            lambda current: _validate(db, current, identifier),
            response=lambda current: get_release(db, current, identifier),
        )
    except Exception:
        db.rollback()
        raise


def review_release(db, user, identifier, values, *, manual=False, revoke=False):
    request = _typed(ReleaseAuthorityReview if manual else GovernanceRevoke if revoke else GovernanceReview, values)
    try:
        actor = sources.actor_now(db, user)
        header = life.opaque(db, AIDeidentificationExportRelease, "release_id", sources._key(identifier), writing=True)
        if revoke:
            return life.stop(db, actor, AIDeidentificationExportRelease, "release_id", identifier, header, life.governance_updates(actor, header, request, revoke=True), "release")
        actor, header, source, _, row, original, _ = locked_release(db, actor, identifier, execution=True, writing=True)
        if row is None:
            raise HTTPException(403, "当前临床用途未授权")
        updates = life.manual_updates(actor, header, request) if manual else life.governance_updates(actor, header, request, revoke=False)
        if not manual and request.decision == "publish" and (not _authority_ready(original, row) or not life.manual_current(db, row, source["snapshot"])):
            raise HTTPException(409, "技术发布不能填补导出依据、有效期或独立复核未知")
        for key, value in updates.items():
            setattr(row, key, value)
        return life.finish(
            db,
            actor,
            row,
            "release_id",
            "release",
            "deidentification.release.manual" if manual else "deidentification.release.review",
            lambda current: _validate(db, current, identifier, require_manual=row.manual_status == "reviewed_residual_risk_remains"),
            response=lambda current: get_release(db, current, identifier),
        )
    except Exception:
        db.rollback()
        raise


def download_release(db, user, identifier):
    """Commit one finite receipt before returning a single no-store JSON file."""
    try:
        actor, header, source, review, row, original, _ = locked_release(db, user, identifier, execution=True, writing=True)
        if (
            row is None
            or review.status != "published"
            or row.status != "published"
            or not life.manual_current(db, review, source["snapshot"])
            or not life.manual_current(db, row, source["snapshot"])
            or not _authority_ready(original, row)
            or row.download_count >= row.maximum_downloads
        ):
            raise HTTPException(409, "当前导出放行、完整来源或有限次数未闭合")
        # The actual immutable artifact is read only after authority and complete
        # proofs. It includes every reviewed output field, never review quotes.
        raw = row.artifact_json
        event = AIAuditEvent(
            actor_id=actor.user_id,
            action="deidentification.release.download",
            target=identifier,
            detail_json=canonical(
                {
                    "release_id": identifier,
                    "artifact_hash": row.artifact_hash,
                    "artifact_bytes": row.artifact_bytes,
                    "download_number": row.download_count + 1,
                    "recipient_scope": original["request"]["recipient_scope"],
                    "recipient_reference_hash": digest(original["request"]["recipient_reference"]),
                }
            ),
        )
        expected_event = (event.actor_id, event.action, event.target, event.detail_json)
        db.add(event)
        db.flush()
        event_id = event.event_id
        row.download_count += 1
        row.last_download_event_id = event_id
        row.last_download_at = utcnow()
        expected = life.expected(row)
        db.flush()
        current_actor(db, actor, allowed_roles=sources.SOURCE_ROLES)
        actual = life.opaque(db, AIDeidentificationExportRelease, "release_id", identifier, writing=True)
        audit = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=event_id), shared=True).one_or_none()
        if actual != expected or audit is None or (audit.actor_id, audit.action, audit.target, audit.detail_json) != expected_event:
            raise HTTPException(409, "单件下载计数、完整字节或实际审计PK写后不符")
        _validate(db, actor, identifier, require_manual=True)
        # Actual current row, not a stale ORM cache, also closes the final body.
        checked = current_research_rows(db.query(AIDeidentificationExportRelease).filter_by(release_id=identifier), shared=True).one()
        if checked.artifact_json != raw or not _authority_ready(original, checked):
            raise HTTPException(409, "写后完整导出正文或有效期改变")
        db.commit()
        return {
            "filename": "deidentification-" + identifier + ".json",
            "content_type": "application/json; charset=utf-8",
            "body": utf8(raw),
            "sha256": expected["artifact_hash"],
            "audit_event_id": event_id,
            "cache_control": "no-store",
        }
    except Exception:
        db.rollback()
        raise
