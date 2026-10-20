"""Reviewable immutable hospital SKU series; independent technical governance."""

import functools
import json
import uuid

from fastapi import HTTPException

from app.ai import governance
from app.ai import supply_contract as core
from app.ai import supply_sources as facts
from app.ai.supply_series_input import SeriesRequest, bounded_json, capture_input, current_collection, instant, project_source, utc_text, utcnow, validate_series_period
from app.ai.supply_series_models import AISupplySeries
from app.ai.supply_snapshot import local_resolution, verify_snapshot
from app.ai.supply_source_input import SourceReview, SourceRevoke


class SeriesCreate(core.StrictModel):
    request: SeriesRequest
    expected_capture_digest: core.SHA256


class SeriesReview(SourceReview):
    pass


class SeriesRevoke(SourceRevoke):
    pass


def atomic(fn):
    @functools.wraps(fn)
    def run(db, *args, **kwargs):
        try:
            return fn(db, *args, **kwargs)
        except Exception:
            db.rollback()
            raise

    return run


def series_row(db, series_id, *, locking=False):
    try:
        core.identity(series_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "物资序列标识须为规范UUID") from exc
    q = db.query(AISupplySeries).filter_by(series_id=series_id).populate_existing()
    row = (q.with_for_update() if locking else q).one_or_none()
    if row is None:
        raise HTTPException(404, "受审物资序列不存在")
    return row


def published_governance(row):
    return facts.governance(row) | {"status": "published", "revision": 2, "revoked_by": None, "revoked_at": None, "revoke_reason": ""}


def metadata(row):
    state = facts.governance(row)
    return {
        "series_id": row.series_id,
        "item_kind": row.item_kind,
        "item_id": row.item_id,
        "scope": row.scope,
        "unit_definition_id": row.unit_definition_id,
        "schema_version": row.schema_version,
        "as_of": utc_text(row.as_of),
        "created_at": utc_text(row.created_at),
        "created_by": row.created_by,
        "content_hash": row.content_hash,
        "collection_digest": row.collection_digest,
        "projection_hash": row.projection_hash,
        "source_id": f"supply_series:{row.series_id}:{row.content_hash[:12]}",
        **{k: v for k, v in state.items() if k not in {"review_basis_note", "revoke_reason"}},
        "governance_hash": core.hash_content(state),
    }


def series_proof(row):
    try:
        core.identity(row.series_id)
        value = json.loads(row.snapshot_json)
        if bounded_json(value) != row.snapshot_json or core.hash_content(value) != row.content_hash:
            raise ValueError("Immutable private bytes differ")
        snapshot = verify_snapshot(value)
        expected = {
            "series_id": row.series_id,
            "schema_version": row.schema_version,
            "item_kind": row.item_kind,
            "item_id": row.item_id,
            "scope": row.scope,
            "created_by": row.created_by,
            "as_of": utc_text(row.as_of),
            "captured_at": utc_text(row.created_at),
            "collection_digest": row.collection_digest,
        }
        if any(snapshot[k] != v for k, v in expected.items()) or snapshot["request"]["unit_definition_id"] != row.unit_definition_id or row.as_of > row.created_at or type(row.revision) is not int:
            raise ValueError("Immutable row/period/unit binding differs")
        reviewed = row.reviewed_by is not None and row.reviewed_at is not None
        if reviewed:
            if type(row.reviewed_by) is not int or row.reviewed_by < 1 or row.reviewed_at < row.created_at:
                raise ValueError("Review provenance differs")
            SeriesReview(expected_revision=1, expected_content_hash=row.content_hash, decision="publish", basis_note=row.review_basis_note)
        elif row.reviewed_by is not None or row.reviewed_at is not None or row.review_basis_note != "":
            raise ValueError("Partial review")
        if row.status == "draft":
            if row.revision != 1 or reviewed:
                raise ValueError("Invalid draft")
        elif row.status in {"published", "rejected"}:
            if row.revision != 2 or not reviewed:
                raise ValueError("Invalid review")
        elif row.status == "revoked":
            SeriesRevoke(expected_revision=row.revision - 1, expected_content_hash=row.content_hash, basis_note=row.revoke_reason)
            if row.revision != (3 if reviewed else 2) or type(row.revoked_by) is not int or row.revoked_by < 1 or row.revoked_at is None or row.revoked_at < (row.reviewed_at or row.created_at):
                raise ValueError("Invalid revocation")
        else:
            raise ValueError("Unknown status")
        if row.status != "revoked" and (row.revoked_by is not None or row.revoked_at is not None or row.revoke_reason != ""):
            raise ValueError("Unbound revocation")
        source = None
        if row.status == "published" or row.status == "revoked" and reviewed:
            source = project_source(snapshot, core.hash_content(published_governance(row)), validate_current_recipe=False)
            if bounded_json(source) != row.projection_json or core.hash_content(source) != row.projection_hash:
                raise ValueError("Published whole projection differs")
        elif row.projection_json is not None or row.projection_hash is not None:
            raise ValueError("Projection without publication")
        return snapshot, source
    except (HTTPException, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "物资序列完整原件、真实时钟、参数或公开投影不一致") from exc


def _current(db, user, row, *, locking=False):
    snapshot, _ = series_proof(row)
    collection = current_collection(db, user, request=snapshot["request"], locking=locking)
    if collection["collection_digest"] != row.collection_digest:
        raise HTTPException(409, "原SKU范围、单位、完整候选或专业签署已经变化，请重新捕获并审核")


def _locked(db, user, series_id, *, allow_missing=False):
    actor = facts.current_actor(db, user, locking=True)
    original = series_row(db, series_id)
    actor, _ = facts.lock_supply_scope(db, actor, original.item_kind, original.item_id, allow_missing=allow_missing and actor.user_role == "super_admin")
    return actor, series_row(db, series_id, locking=True)


def binding_for(row, source):
    return {
        "series_id": row.series_id,
        "item_kind": row.item_kind,
        "item_id": row.item_id,
        "scope": row.scope,
        "unit_definition_id": row.unit_definition_id,
        "revision": 2,
        "source_id": source["source_id"],
        "content_hash": row.content_hash,
        "series_governance_hash": core.hash_content(published_governance(row)),
        "projection_hash": row.projection_hash,
        "collection_digest": row.collection_digest,
        **{
            k: source[k]
            for k in (
                "historical_collection_digest",
                "current_membership_digest",
                "member_manifest_hash",
                "profile_id",
                "profile_content_hash",
                "profile_governance_hash",
                "scope_token",
                "item_token",
                "unit_token",
                "rule_id",
                "recipe_digest",
                "input_policy_digest",
            )
        },
    }


def authorize_series(db, user, series_id, horizon_days, *, binding=None, locking=False, execution=True):
    if type(horizon_days) is not int or horizon_days not in (7, 14):
        raise HTTPException(422, "须明确7或14天期限")
    actor, row = _locked(db, user, series_id) if locking else (facts.current_actor(db, user), series_row(db, series_id))
    snapshot, source = series_proof(row)
    _current(db, actor, row, locking=locking)
    if row.status != "published" or row.revision != 2 or source is None:
        raise HTTPException(409, "序列尚未发布或已经失效")
    if execution:
        validate_series_period(snapshot["request"])
        try:
            core.SupplySource.model_validate(source)
        except ValueError as exc:
            raise HTTPException(409, "固定配方或输入政策已改变，请重新捕获审核") from exc
    if binding is not None:
        expected = binding_for(row, source)
        if (
            not isinstance(binding, dict)
            or not set(expected) <= set(binding)
            or set(binding) - set(expected) - {"schema_version", "horizon_days"}
            or any(type(binding.get(k)) is not type(v) or binding[k] != v for k, v in expected.items())
            or "schema_version" in binding
            and binding["schema_version"] != "supply_context_binding_v1"
            or "horizon_days" in binding
            and (type(binding["horizon_days"]) is not int or binding["horizon_days"] != horizon_days)
        ):
            raise HTTPException(409, "任务的完整原序列范围、参数或期限绑定已变化")
    return row, snapshot, source


def series_current(db, user, series_id, *, audit_only=False):
    actor = facts.current_actor(db, user)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "只有超级管理员可进行独立冻结审计")
    row = series_row(db, series_id)
    snapshot, source = series_proof(row)
    reasons = []
    try:
        _current(db, actor, row)
    except HTTPException as exc:
        if exc.status_code not in {403, 409, 422}:
            raise
        reasons.append("original_collection_changed")
    current = not reasons
    if row.status != "published":
        reasons.append("series_" + row.status)
    visible = audit_only or not reasons or reasons == ["series_draft"]
    run_reasons = list(reasons)
    if not run_reasons:
        try:
            validate_series_period(snapshot["request"])
            core.SupplySource.model_validate(source)
        except (HTTPException, ValueError):
            run_reasons.append("series_period_or_algorithm_changed")
    return metadata(row) | {
        "snapshot": snapshot if visible else None,
        "public_source": source if visible else None,
        "local_resolution": local_resolution(snapshot) if visible else None,
        "source_current": current,
        "eligible": not run_reasons,
        "exclusion_reasons": run_reasons,
        "can_review": actor.user_role == "super_admin" and current and row.status == "draft",
        "can_revoke": row.status in {"draft", "published"} and (actor.user_role == "super_admin" or current and row.created_by == actor.user_id),
        "review_basis_note": row.review_basis_note if visible else None,
        "revoke_reason": row.revoke_reason if visible else None,
        "audit_only": audit_only,
        "forecast_purpose": "recorded_request_gross_fulfilled_issue_confirmed_consumption_not_latent_demand_or_purchase_decision",
    }


def _postcheck(db, actor, row, *, super_required=False, current_required=True, author_required=False):
    actor = facts.current_actor(db, actor, locking=True)
    if super_required and actor.user_role != "super_admin":
        raise HTTPException(403, "当前账户已不具有独立审核权限")
    if current_required or actor.user_role != "super_admin":
        _current(db, actor, row, locking=True)
    if author_required and actor.user_role != "super_admin" and row.created_by != actor.user_id:
        raise HTTPException(403, "当前账户不具有原作者撤销权限")
    return actor


@atomic
def create_series(db, user, values):
    req = values if isinstance(values, SeriesCreate) else SeriesCreate.model_validate(values)
    actor, _ = facts.lock_supply_scope(db, user, req.request.item_kind, req.request.item_id)
    series_id = str(uuid.uuid4())
    snapshot = capture_input(db, actor, req.request, series_id, expected_collection_digest=req.expected_capture_digest, locking=True)
    row = AISupplySeries(
        series_id=series_id,
        item_kind=req.request.item_kind,
        item_id=req.request.item_id,
        scope=req.request.scope,
        unit_definition_id=req.request.unit_definition_id,
        schema_version="supply_series_private_v1",
        as_of=instant(snapshot["as_of"]).replace(tzinfo=None),
        created_at=instant(snapshot["captured_at"]).replace(tzinfo=None),
        created_by=actor.user_id,
        snapshot_json=bounded_json(snapshot),
        content_hash=core.hash_content(snapshot),
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
    actor = _postcheck(db, actor, row)
    governance.audit(db, actor.user_id, "supply.series.create", row.series_id, {"content_hash": row.content_hash, "collection_digest": row.collection_digest})
    db.flush()
    _postcheck(db, actor, row)
    return row


@atomic
def review_series(db, user, series_id, values):
    req = values if isinstance(values, SeriesReview) else SeriesReview.model_validate(values)
    actor, row = _locked(db, user, series_id)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "只有当前超级管理员可独立审核物资序列及参数")
    snapshot, _ = series_proof(row)
    _current(db, actor, row, locking=True)
    if row.status != "draft" or row.revision != req.expected_revision or row.content_hash != req.expected_content_hash:
        raise HTTPException(409, "完整原件或CAS版本已变化")
    now = utcnow()
    if now < row.created_at:
        raise HTTPException(409, "服务器审核时刻早于原捕获")
    updates = {"status": "published" if req.decision == "publish" else "rejected", "revision": 2, "reviewed_by": actor.user_id, "reviewed_at": now, "review_basis_note": req.basis_note}
    if req.decision == "publish":
        state = facts.governance(row) | updates | {"reviewed_at": utc_text(now)}
        source = project_source(snapshot, core.hash_content(state))
        updates |= {"projection_json": bounded_json(source), "projection_hash": core.hash_content(source)}
    count = db.query(AISupplySeries).filter_by(series_id=series_id, status="draft", revision=req.expected_revision, content_hash=req.expected_content_hash).update(updates, synchronize_session=False)
    if count != 1:
        raise HTTPException(409, "发生并发审核，本次未保存")
    row = series_row(db, series_id, locking=True)
    series_proof(row)
    actor = _postcheck(db, actor, row, super_required=True)
    governance.audit(
        db, actor.user_id, "supply.series." + req.decision, row.series_id, {"revision": row.revision, "content_hash": row.content_hash, "governance_hash": core.hash_content(facts.governance(row))}
    )
    db.flush()
    _postcheck(db, actor, row, super_required=True)
    return row


@atomic
def revoke_series(db, user, series_id, values):
    req = values if isinstance(values, SeriesRevoke) else SeriesRevoke.model_validate(values)
    actor, row = _locked(db, user, series_id, allow_missing=True)
    series_proof(row)
    if actor.user_role != "super_admin":
        _current(db, actor, row, locking=True)
        if row.created_by != actor.user_id:
            raise HTTPException(403, "只有原作者或超级管理员可撤销")
    if row.status not in {"draft", "published"} or row.revision != req.expected_revision or row.content_hash != req.expected_content_hash:
        raise HTTPException(409, "原件或CAS版本已变化或治理已终结")
    now = utcnow()
    if now < (row.reviewed_at or row.created_at):
        raise HTTPException(409, "撤销时刻早于原捕获或审核")
    count = (
        db.query(AISupplySeries)
        .filter_by(series_id=series_id, status=row.status, revision=req.expected_revision, content_hash=req.expected_content_hash)
        .update({"status": "revoked", "revision": req.expected_revision + 1, "revoked_by": actor.user_id, "revoked_at": now, "revoke_reason": req.basis_note}, synchronize_session=False)
    )
    if count != 1:
        raise HTTPException(409, "发生并发变更，本次未撤销")
    row = series_row(db, series_id, locking=True)
    series_proof(row)
    actor = _postcheck(db, actor, row, current_required=False, author_required=True)
    governance.audit(
        db, actor.user_id, "supply.series.revoke", row.series_id, {"revision": row.revision, "content_hash": row.content_hash, "governance_hash": core.hash_content(facts.governance(row))}
    )
    db.flush()
    _postcheck(db, actor, row, current_required=False, author_required=True)
    return row
