"""Immutable physical bed series with current-scope checks and independent Super review."""

import json
import uuid

from fastapi import HTTPException
from pydantic import ValidationError

from app.ai import bed_facts as facts
from app.ai import governance
from app.ai.bed_contract import BedSource, canonical_json, hash_content
from app.ai.bed_series_input import SeriesRequest, capture_input, current_collection, project_source, validate_series_period, verify_snapshot
from app.ai.bed_series_models import SERIES_BYTES, AIBedSeries


class SeriesCreate(facts.StrictInput):
    request: SeriesRequest
    expected_collection_digest: facts.HashText


class SeriesReview(facts.SourceReview):
    pass


class SeriesRevoke(facts.SourceRevoke):
    pass


def bounded_json(value):
    serialized = canonical_json(value)
    if not 0 < len(serialized.encode("utf-8")) <= SERIES_BYTES:
        raise HTTPException(422, "完整床位序列声明或投影超过8MiB；未截断或保存")
    return serialized


def series_row(db, series_id, *, locking=False):
    try:
        facts.canonical_id(series_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "床位序列标识须为规范UUID") from exc
    query = db.query(AIBedSeries).filter_by(series_id=series_id).populate_existing()
    row = (query.with_for_update() if locking else query).one_or_none()
    if row is None:
        raise HTTPException(404, "床位序列不存在")
    return row


def published_governance(row):
    """Retain the exact original publication anchor after later revocation."""
    state = facts.governance_fields(row)
    return {**state, "status": "published", "revision": 2, "revoked_by": None, "revoked_at": None, "revoke_reason": ""}


def metadata(row):
    state = facts.governance_fields(row)
    return {
        "series_id": row.series_id,
        "department_id": row.department_id,
        "ward_id": row.ward_id,
        "schema_version": row.schema_version,
        "as_of": facts.utc_text(row.as_of),
        "created_at": facts.utc_text(row.created_at),
        "created_by": row.created_by,
        "content_hash": row.content_hash,
        "collection_digest": row.collection_digest,
        "projection_hash": row.projection_hash,
        "source_id": f"bed_series:{row.series_id}:{row.content_hash[:12]}",
        **state,
        "governance_hash": hash_content(state),
    }


def series_proof(row):
    """Own-byte integrity is mandatory even for Super frozen audit access."""
    try:
        facts.canonical_id(row.series_id)
        if (
            row.schema_version != "bed_series_private_v1"
            or type(row.department_id) is not int
            or row.department_id < 1
            or type(row.ward_id) is not int
            or row.ward_id < 1
            or type(row.created_by) is not int
            or row.created_by < 1
        ):
            raise ValueError("Invalid original bed series identity")
        snapshot = json.loads(row.snapshot_json)
        if bounded_json(snapshot) != row.snapshot_json or hash_content(snapshot) != row.content_hash:
            raise ValueError("Complete private body differs")
        verify_snapshot(snapshot)
        expected = {
            "schema_version": row.schema_version,
            "series_id": row.series_id,
            "department_id": row.department_id,
            "ward_id": row.ward_id,
            "created_by": row.created_by,
            "as_of": facts.utc_text(row.as_of),
            "captured_at": facts.utc_text(row.created_at),
            "collection_digest": row.collection_digest,
        }
        if any(snapshot[key] != value for key, value in expected.items()) or row.as_of > row.created_at:
            raise ValueError("Immutable table binding differs")
        if type(row.revision) is not int:
            raise ValueError("Invalid governance revision")
        reviewed = row.reviewed_by is not None and row.reviewed_at is not None
        if reviewed:
            if type(row.reviewed_by) is not int or row.reviewed_by < 1 or row.reviewed_at < row.created_at:
                raise ValueError("Invalid review provenance")
            SeriesReview(expected_revision=1, expected_content_hash=row.content_hash, decision="publish", review_basis_note=row.review_basis_note)
        elif row.reviewed_by is not None or row.reviewed_at is not None or row.review_basis_note != "":
            raise ValueError("Partial review provenance")
        if row.status == "draft":
            if row.revision != 1 or reviewed:
                raise ValueError("Invalid original draft")
        elif row.status in {"published", "rejected"}:
            if row.revision != 2 or not reviewed:
                raise ValueError("Invalid original review")
        elif row.status == "revoked":
            if row.revision != (3 if reviewed else 2) or type(row.revoked_by) is not int or row.revoked_by < 1 or row.revoked_at is None:
                raise ValueError("Invalid revocation provenance")
            SeriesRevoke(expected_revision=row.revision - 1, reason=row.revoke_reason)
            if row.revoked_at < (row.reviewed_at if reviewed else row.created_at):
                raise ValueError("Invalid revocation clock")
        else:
            raise ValueError("Unknown bed series status")
        if row.status != "revoked" and (row.revoked_by is not None or row.revoked_at is not None or row.revoke_reason != ""):
            raise ValueError("Unbound revocation metadata")
        has_publication = row.status == "published" or row.status == "revoked" and reviewed
        source = None
        if has_publication:
            source = project_source(snapshot, hash_content(published_governance(row)), validate_current_recipe=False)
            if bounded_json(source) != row.projection_json or hash_content(source) != row.projection_hash:
                raise ValueError("Original published projection differs")
        elif row.projection_json is not None or row.projection_hash is not None:
            raise ValueError("Projection without original publication")
        return snapshot, source
    except (HTTPException, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "床位序列的完整原件、治理、原时刻或投影哈希不一致") from exc


def _current(db, actor, row, *, locking=False):
    facts.bed_scope(db, actor, row.department_id, locking=locking)
    snapshot = json.loads(row.snapshot_json)
    collection = current_collection(db, actor, row.ward_id, request=snapshot["request"], locking=locking)
    if collection["collection_digest"] != row.collection_digest:
        raise HTTPException(409, "原病区床位成员、相关原件或来源治理已经变化，请重新捕获并审核床位序列")


def authorize_series(db, user, series_id, *, execution=True, binding=None, locking=False):
    row = series_row(db, series_id, locking=locking)
    actor = facts.bed_scope(db, user, row.department_id, locking=locking)
    snapshot, source = series_proof(row)
    _current(db, actor, row, locking=locking)
    if row.status != "published" or row.revision != 2 or source is None:
        raise HTTPException(409, "床位序列尚未发布或已经失效，不能执行新任务")
    if execution:
        validate_series_period(SeriesRequest.model_validate(snapshot["request"]))
        try:
            BedSource.model_validate(source)
        except ValidationError as exc:
            raise HTTPException(409, "床位序列绑定的原算法或输入政策已改变，请重新捕获审核") from exc
    if binding is not None and (not isinstance(binding, dict) or any(binding.get(key) != value for key, value in binding_for(row, source).items())):
        raise HTTPException(409, "床位任务的完整原序列绑定已经变化")
    return row, snapshot, source


def binding_for(row, source):
    return {
        "series_id": row.series_id,
        "department_id": row.department_id,
        "ward_id": row.ward_id,
        "revision": 2,
        "source_id": source["source_id"],
        "content_hash": row.content_hash,
        "series_governance_hash": hash_content(published_governance(row)),
        "projection_hash": row.projection_hash,
        "scope_token": source["scope_token"],
        "member_manifest_hash": source["member_manifest_hash"],
        "collection_digest": row.collection_digest,
        "historical_collection_digest": source["historical_collection_digest"],
        "current_membership_digest": source["current_membership_digest"],
        "future_scenario_collection_digest": source["future_scenario_collection_digest"],
        "rule_id": source["rule_id"],
        "recipe_digest": source["recipe_digest"],
        "input_policy_digest": source["input_policy_digest"],
    }


def series_current(db, user, series_id, *, audit_only=False):
    row = series_row(db, series_id)
    actor = facts.current_actor(db, user)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "只有超级管理员可读取完整冻结床位序列审计")
    facts.bed_scope(db, actor, row.department_id, allow_missing=actor.user_role in {"admin", "super_admin"})
    snapshot, source = series_proof(row)
    reasons = []
    try:
        _current(db, actor, row)
    except HTTPException as exc:
        if exc.status_code not in {403, 409, 422}:
            raise
        reasons.append("original_collection_changed")
    if row.status != "published":
        reasons.append("series_" + row.status)
    visible = audit_only or not reasons or reasons == ["series_draft"]
    run_reasons = list(reasons)
    if not run_reasons:
        try:
            validate_series_period(SeriesRequest.model_validate(snapshot["request"]))
            BedSource.model_validate(source)
        except (HTTPException, ValidationError):
            run_reasons.append("series_period_or_algorithm_changed")
    return {
        **metadata(row),
        "snapshot": snapshot if visible else None,
        "public_source": source if visible else None,
        "source_current": not any(reason == "original_collection_changed" for reason in reasons),
        "eligible": not run_reasons,
        "exclusion_reasons": run_reasons,
        "can_record": not any(reason == "original_collection_changed" for reason in reasons),
        "can_review": actor.user_role == "super_admin" and row.status == "draft" and "original_collection_changed" not in reasons,
        "can_revoke": row.status in {"draft", "published"} and (actor.user_role == "super_admin" or row.created_by == actor.user_id and "original_collection_changed" not in reasons),
        "review_basis_note": row.review_basis_note if visible else None,
        "revoke_reason": row.revoke_reason if visible else None,
        "audit_only": audit_only,
        "forecast_purpose": "frozen_observed_physical_counts_and_explicit_capacity_scenario_not_unmet_demand_or_admittable_slots",
    }


def create_series(db, user, values):
    req = values if isinstance(values, SeriesCreate) else SeriesCreate.model_validate(values)
    actor = facts.current_actor(db, user)
    series_id = str(uuid.uuid4())
    snapshot = capture_input(db, actor, req.request, series_id, expected_collection_digest=req.expected_collection_digest)
    serialized = bounded_json(snapshot)
    row = AIBedSeries(
        series_id=series_id,
        department_id=snapshot["department_id"],
        ward_id=req.request.ward_id,
        schema_version="bed_series_private_v1",
        as_of=facts.instant(snapshot["as_of"]).replace(tzinfo=None),
        created_at=facts.instant(snapshot["captured_at"]).replace(tzinfo=None),
        created_by=actor.user_id,
        snapshot_json=serialized,
        content_hash=hash_content(snapshot),
        collection_digest=snapshot["collection_digest"],
        projection_json=None,
        projection_hash=None,
        status="draft",
        revision=1,
        review_basis_note="",
        revoke_reason="",
    )
    db.add(row)
    db.flush()
    series_proof(row)
    actor = facts.current_actor(db, actor, locking=True)
    _current(db, actor, row, locking=True)
    governance.audit(db, actor.user_id, "bed.series.create", row.series_id, {"content_hash": row.content_hash, "department_id": row.department_id, "collection_digest": row.collection_digest})
    return row


def review_series(db, user, series_id, values):
    req = values if isinstance(values, SeriesReview) else SeriesReview.model_validate(values)
    actor = facts.current_actor(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "只有当前超级管理员可审核床位序列")
    row = series_row(db, series_id)
    snapshot, _ = series_proof(row)
    if row.status != "draft" or row.revision != req.expected_revision or row.content_hash != req.expected_content_hash:
        raise HTTPException(409, "床位原序列或审核版本已变化")
    _current(db, actor, row)
    validate_series_period(SeriesRequest.model_validate(snapshot["request"]))
    now = facts.utcnow()
    if now < row.created_at:
        raise HTTPException(409, "审核服务器时刻早于原序列捕获时刻")
    updates = {"status": "published" if req.decision == "publish" else "rejected", "revision": 2, "reviewed_by": actor.user_id, "reviewed_at": now, "review_basis_note": req.review_basis_note}
    if req.decision == "publish":
        state = {**facts.governance_fields(row), **updates, "reviewed_at": facts.utc_text(now)}
        source = project_source(snapshot, hash_content(state))
        updates.update(projection_json=bounded_json(source), projection_hash=hash_content(source))
    changed = db.query(AIBedSeries).filter_by(series_id=series_id, status="draft", revision=req.expected_revision, content_hash=req.expected_content_hash).update(updates, synchronize_session=False)
    if changed != 1:
        raise HTTPException(409, "床位序列发生并发审核，本次未保存")
    row = series_row(db, series_id)
    series_proof(row)
    actor = facts.current_actor(db, actor, locking=True)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "当前身份已不再具备床位序列审核权限，本次未发布")
    _current(db, actor, row, locking=True)
    governance.audit(
        db,
        actor.user_id,
        "bed.series." + req.decision,
        series_id,
        {"revision": row.revision, "content_hash": row.content_hash, "projection_hash": row.projection_hash, "governance_hash": hash_content(facts.governance_fields(row))},
    )
    return row


def revoke_series(db, user, series_id, values):
    req = values if isinstance(values, SeriesRevoke) else SeriesRevoke.model_validate(values)
    row = series_row(db, series_id)
    actor = facts.current_actor(db, user)
    actor = facts.bed_scope(db, actor, row.department_id, allow_missing=actor.user_role == "super_admin")
    series_proof(row)
    if actor.user_role != "super_admin":
        _current(db, actor, row)
        if row.created_by != actor.user_id:
            raise HTTPException(403, "只有当前原记录人或超级管理员可撤销床位序列")
    if row.status not in {"draft", "published"} or row.revision != req.expected_revision:
        raise HTTPException(409, "床位序列已终结或治理版本已变化")
    now = facts.utcnow()
    if now < (row.reviewed_at or row.created_at):
        raise HTTPException(409, "撤销服务器时刻早于原序列捕获或审核时刻")
    changed = (
        db.query(AIBedSeries)
        .filter_by(series_id=series_id, status=row.status, revision=req.expected_revision, content_hash=row.content_hash)
        .update({"status": "revoked", "revision": req.expected_revision + 1, "revoked_by": actor.user_id, "revoked_at": now, "revoke_reason": req.reason}, synchronize_session=False)
    )
    if changed != 1:
        raise HTTPException(409, "床位序列发生并发变更，本次未撤销")
    row = series_row(db, series_id)
    series_proof(row)
    actor = facts.current_actor(db, actor, locking=True)
    if actor.user_role != "super_admin":
        _current(db, actor, row, locking=True)
        if row.created_by != actor.user_id:
            raise HTTPException(403, "当前身份已不具备撤销该原序列的权限")
    governance.audit(db, actor.user_id, "bed.series.revoke", series_id, {"revision": row.revision, "content_hash": row.content_hash, "governance_hash": hash_content(facts.governance_fields(row))})
    return row
