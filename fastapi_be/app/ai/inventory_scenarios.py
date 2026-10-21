"""Reviewable whole-candidate inventory scenarios; no stock or purchase execution."""

import functools
import json
import uuid

from fastapi import HTTPException
from sqlalchemy import inspect

from app.ai import governance
from app.ai import inventory_contract as core
from app.ai.inventory_native_source_input import SOURCE_ROLES
from app.ai.inventory_projection import project_source
from app.ai.inventory_scenario_input import ScenarioRequest, bounded_json, capture_input, current_collection, instant, utc_text, utcnow, validate_planning_period
from app.ai.inventory_scenario_models import AIInventoryScenario
from app.ai.inventory_snapshot import local_resolution, verify_snapshot
from app.ai.inventory_write_guard import lock_inventory_gate, lock_inventory_write
from app.ai.supply_source_input import SourceReview, SourceRevoke
from app.models import Consumable, Pharmaceutical, User

GOVERNANCE_FIELDS = ("status", "revision", "reviewed_by", "reviewed_at", "review_basis_note", "revoked_by", "revoked_at", "revoke_reason")


def current_actor(db, user, *, locking=False):
    state = inspect(user, raiseerr=False)
    identifier = state.identity[0] if state is not None and state.identity is not None else getattr(user, "user_id", None)
    query = db.query(User).filter_by(user_id=identifier).populate_existing()
    # A normal MySQL RR SELECT can retain the JWT transaction's old role.
    # Every permission decision must be a current locking read, including audit.
    actor = query.with_for_update(read=True).one_or_none()
    if actor is None or actor.user_role not in SOURCE_ROLES:
        raise HTTPException(403, "当前账户不具有医院库存场景权限")
    return actor


def lock_scope(db, user, item_kind, item_id, *, allow_missing=False):
    return lock_inventory_write(db, user, allowed_roles=SOURCE_ROLES, skus=[(item_kind, item_id)], allow_missing=allow_missing)


def require_sku(db, item_kind, item_id):
    if item_kind not in {"pharmaceutical", "consumable"} or type(item_id) is not int or not 1 <= item_id <= 2147483647:
        raise HTTPException(422, "须明确规范SKU类型和实际正整数标识")
    model, primary = (Pharmaceutical, Pharmaceutical.pharmaceutical_id) if item_kind == "pharmaceutical" else (Consumable, Consumable.consumable_id)
    if db.query(primary).filter(primary == item_id).one_or_none() is None:
        raise HTTPException(409, "原SKU已不存在，只保留授权的冻结审计")


def governance_state(row):
    return {key: (None if getattr(row, key) is None else utc_text(getattr(row, key))) if key in {"reviewed_at", "revoked_at"} else getattr(row, key) for key in GOVERNANCE_FIELDS}


class ScenarioCreate(core.StrictModel):
    request: ScenarioRequest
    expected_collection_digest: core.SHA256


class ScenarioReview(SourceReview):
    pass


class ScenarioRevoke(SourceRevoke):
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


def scenario_row(db, scenario_id, *, locking=False):
    try:
        core.identity(scenario_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "库存场景标识须为规范UUID") from exc
    q = db.query(AIInventoryScenario).filter_by(scenario_id=scenario_id).populate_existing()
    row = (q.with_for_update() if locking else q).one_or_none()
    if row is None:
        raise HTTPException(404, "受审库存场景不存在")
    return row


def published_governance(row):
    return governance_state(row) | {"status": "published", "revision": 2, "revoked_by": None, "revoked_at": None, "revoke_reason": ""}


def metadata(row, *, include_private_governance=False):
    state = governance_state(row)
    return {
        "scenario_id": row.scenario_id,
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
        "source_id": f"inventory_scenario:{row.scenario_id}:{row.content_hash[:12]}",
        **{k: v for k, v in state.items() if include_private_governance or k not in {"review_basis_note", "revoke_reason"}},
        "governance_hash": core.hash_content(state),
    }


def scenario_proof(row):
    try:
        core.identity(row.scenario_id)
        value = json.loads(row.snapshot_json)
        if bounded_json(value) != row.snapshot_json or core.hash_content(value) != row.content_hash:
            raise ValueError("Immutable private bytes differ")
        snapshot = verify_snapshot(value)
        expected = {
            "scenario_id": row.scenario_id,
            "schema_version": row.schema_version,
            "item_kind": row.item_kind,
            "item_id": row.item_id,
            "scope": row.scope,
            "created_by": row.created_by,
            "as_of": utc_text(row.as_of),
            "captured_at": utc_text(row.created_at),
            "collection_digest": row.collection_digest,
        }
        if (
            any(snapshot[k] != v for k, v in expected.items())
            or snapshot["request"]["unit_definition_id"] != row.unit_definition_id
            or snapshot["request"]["observation"]["source_record_id"] != row.observation_source_id
            or snapshot["request"]["future_quantity_scenario"]["source_record_id"] != row.quantity_scenario_source_id
            or row.as_of > row.created_at
            or type(row.revision) is not int
        ):
            raise ValueError("Immutable row/period/unit binding differs")
        reviewed = row.reviewed_by is not None and row.reviewed_at is not None
        if reviewed:
            if type(row.reviewed_by) is not int or row.reviewed_by < 1 or row.reviewed_at < row.created_at:
                raise ValueError("Review provenance differs")
            ScenarioReview(expected_revision=1, expected_content_hash=row.content_hash, decision="publish", basis_note=row.review_basis_note)
        elif row.reviewed_by is not None or row.reviewed_at is not None or row.review_basis_note != "":
            raise ValueError("Partial review")
        if row.status == "draft":
            if row.revision != 1 or reviewed:
                raise ValueError("Invalid draft")
        elif row.status in {"published", "rejected"}:
            if row.revision != 2 or not reviewed:
                raise ValueError("Invalid review")
        elif row.status == "revoked":
            ScenarioRevoke(expected_revision=row.revision - 1, expected_content_hash=row.content_hash, basis_note=row.revoke_reason)
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
        raise HTTPException(409, "库存场景完整原件、真实时钟、参数或公开投影不一致") from exc


def _current(db, user, row, *, locking=False):
    snapshot, _ = scenario_proof(row)
    collection = current_collection(db, user, request=snapshot["request"], locking=locking)
    if collection["collection_digest"] != row.collection_digest:
        raise HTTPException(409, "原SKU范围、单位、完整候选或专业签署已经变化，请重新捕获并审核")


def _locked(db, user, scenario_id, *, allow_missing=False):
    lock_inventory_gate(db)
    actor = current_actor(db, user, locking=True)
    original = scenario_row(db, scenario_id)
    actor = lock_scope(db, actor, original.item_kind, original.item_id, allow_missing=allow_missing and actor.user_role == "super_admin")
    return actor, scenario_row(db, scenario_id, locking=True)


def binding_for(row, source):
    return {
        "scenario_id": row.scenario_id,
        "item_kind": row.item_kind,
        "item_id": row.item_id,
        "scope": row.scope,
        "unit_definition_id": row.unit_definition_id,
        "revision": 2,
        "source_id": source["source_id"],
        "content_hash": row.content_hash,
        "scenario_governance_hash": source["governance_hash"],
        "projection_hash": row.projection_hash,
        "collection_digest": row.collection_digest,
        **{
            key: source[key]
            for key in (
                "member_manifest_hash",
                "profile_id",
                "profile_content_hash",
                "profile_governance_hash",
                "item_token",
                "scope_token",
                "quantity_unit_token",
                "cost_unit_token",
                "rule_id",
                "recipe_digest",
                "input_policy_digest",
            )
        },
    }


def authorize_scenario(db, user, scenario_id, *, binding=None, locking=False, execution=True):
    actor, row = _locked(db, user, scenario_id) if locking else (current_actor(db, user), scenario_row(db, scenario_id))
    snapshot, source = scenario_proof(row)
    _current(db, actor, row, locking=locking)
    if row.status != "published" or row.revision != 2 or source is None:
        raise HTTPException(409, "场景尚未发布或已经失效")
    if execution:
        validate_planning_period(snapshot["request"])
        try:
            core.InventorySource.model_validate(source)
        except ValueError as exc:
            raise HTTPException(409, "固定库存配方或输入政策已改变，请重新捕获审核") from exc
    if binding is not None:
        expected = binding_for(row, source)
        if (
            not isinstance(binding, dict)
            or not set(expected) <= set(binding)
            or set(binding) - set(expected) - {"schema_version"}
            or any(type(binding.get(k)) is not type(v) or binding[k] != v for k, v in expected.items())
            or "schema_version" in binding
            and binding["schema_version"] != "inventory_context_binding_v1"
        ):
            raise HTTPException(409, "任务的完整原场景范围、参数或期限绑定已变化")
    return row, snapshot, source


def scenario_current(db, user, scenario_id, *, audit_only=False):
    actor = current_actor(db, user)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "只有超级管理员可进行独立冻结审计")
    row = scenario_row(db, scenario_id)
    snapshot, source = scenario_proof(row)
    reasons = []
    try:
        _current(db, actor, row)
    except HTTPException as exc:
        if exc.status_code not in {403, 409, 422}:
            raise
        reasons.append("original_collection_changed")
    current = not reasons
    if row.status != "published":
        reasons.append("scenario_" + row.status)
    visible = audit_only or not reasons or reasons == ["scenario_draft"]
    run_reasons = list(reasons)
    if not run_reasons:
        try:
            validate_planning_period(snapshot["request"])
            core.InventorySource.model_validate(source)
        except (HTTPException, ValueError):
            run_reasons.append("scenario_period_or_algorithm_changed")
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
        "comparison_purpose": "finite_whole_declared_purchase_candidates_only_not_procurement_execution",
    }


def _postcheck(db, actor, row, *, super_required=False, current_required=True, author_required=False):
    actor = current_actor(db, actor, locking=True)
    if super_required and actor.user_role != "super_admin":
        raise HTTPException(403, "当前账户已不具有独立审核权限")
    if current_required or actor.user_role != "super_admin":
        _current(db, actor, row, locking=True)
    if author_required and actor.user_role != "super_admin" and row.created_by != actor.user_id:
        raise HTTPException(403, "当前账户不具有原作者撤销权限")
    return actor


@atomic
def create_scenario(db, user, values):
    req = values if isinstance(values, ScenarioCreate) else ScenarioCreate.model_validate(values)
    actor = lock_scope(db, user, req.request.item_kind, req.request.item_id)
    scenario_id = str(uuid.uuid4())
    snapshot = capture_input(db, actor, req.request, scenario_id, expected_collection_digest=req.expected_collection_digest, locking=True)
    row = AIInventoryScenario(
        scenario_id=scenario_id,
        item_kind=req.request.item_kind,
        item_id=req.request.item_id,
        scope=req.request.scope,
        unit_definition_id=req.request.unit_definition_id,
        observation_source_id=req.request.observation.source_record_id,
        quantity_scenario_source_id=req.request.future_quantity_scenario.source_record_id,
        schema_version="inventory_scenario_private_v1",
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
    scenario_proof(row)
    actor = _postcheck(db, actor, row)
    governance.audit(db, actor.user_id, "inventory.scenario.create", row.scenario_id, {"content_hash": row.content_hash, "collection_digest": row.collection_digest})
    db.flush()
    _postcheck(db, actor, row)
    return row


@atomic
def review_scenario(db, user, scenario_id, values):
    req = values if isinstance(values, ScenarioReview) else ScenarioReview.model_validate(values)
    actor, row = _locked(db, user, scenario_id)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "只有当前超级管理员可独立审核库存场景及参数")
    snapshot, _ = scenario_proof(row)
    _current(db, actor, row, locking=True)
    if row.status != "draft" or row.revision != req.expected_revision or row.content_hash != req.expected_content_hash:
        raise HTTPException(409, "完整原件或CAS版本已变化")
    now = utcnow()
    if now < row.created_at:
        raise HTTPException(409, "服务器审核时刻早于原捕获")
    updates = {"status": "published" if req.decision == "publish" else "rejected", "revision": 2, "reviewed_by": actor.user_id, "reviewed_at": now, "review_basis_note": req.basis_note}
    if req.decision == "publish":
        state = governance_state(row) | updates | {"reviewed_at": utc_text(now)}
        source = project_source(snapshot, core.hash_content(state))
        updates |= {"projection_json": bounded_json(source), "projection_hash": core.hash_content(source)}
    count = (
        db.query(AIInventoryScenario)
        .filter_by(scenario_id=scenario_id, status="draft", revision=req.expected_revision, content_hash=req.expected_content_hash)
        .update(updates, synchronize_session=False)
    )
    if count != 1:
        raise HTTPException(409, "发生并发审核，本次未保存")
    row = scenario_row(db, scenario_id, locking=True)
    scenario_proof(row)
    actor = _postcheck(db, actor, row, super_required=True)
    governance.audit(
        db,
        actor.user_id,
        "inventory.scenario." + req.decision,
        row.scenario_id,
        {"revision": row.revision, "content_hash": row.content_hash, "governance_hash": core.hash_content(governance_state(row))},
    )
    db.flush()
    _postcheck(db, actor, row, super_required=True)
    return row


@atomic
def revoke_scenario(db, user, scenario_id, values):
    req = values if isinstance(values, ScenarioRevoke) else ScenarioRevoke.model_validate(values)
    actor, row = _locked(db, user, scenario_id, allow_missing=True)
    scenario_proof(row)
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
        db.query(AIInventoryScenario)
        .filter_by(scenario_id=scenario_id, status=row.status, revision=req.expected_revision, content_hash=req.expected_content_hash)
        .update({"status": "revoked", "revision": req.expected_revision + 1, "revoked_by": actor.user_id, "revoked_at": now, "revoke_reason": req.basis_note}, synchronize_session=False)
    )
    if count != 1:
        raise HTTPException(409, "发生并发变更，本次未撤销")
    row = scenario_row(db, scenario_id, locking=True)
    scenario_proof(row)
    actor = _postcheck(db, actor, row, current_required=False, author_required=True)
    governance.audit(
        db, actor.user_id, "inventory.scenario.revoke", row.scenario_id, {"revision": row.revision, "content_hash": row.content_hash, "governance_hash": core.hash_content(governance_state(row))}
    )
    db.flush()
    _postcheck(db, actor, row, current_required=False, author_required=True)
    return row
