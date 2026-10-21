"""Durable local exact statistics, with no external model or automatic action."""

import asyncio
import datetime as dt
import time
import uuid
from copy import deepcopy
from types import SimpleNamespace

from fastapi import HTTPException

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_registry as r
from app.ai import infection_cluster_statistics as engine
from app.ai import infection_cluster_task_context as context
from app.ai import infection_cluster_task_contract as t
from app.ai import infection_cluster_task_storage as storage
from app.ai.infection_cluster_run_models import AIInfectionRunArtifact as Artifact
from app.ai.infection_cluster_write_guard import current, lock_gate
from app.ai.models import AIAuditEvent, AIRun


def _audit(db, uid, action, rid, detail):
    row = AIAuditEvent(actor_id=uid, action=action, target=rid, detail_json=c.canonical(detail), create_time=r.utcnow().replace(microsecond=0))
    db.add(row)
    db.flush([row])
    return row, r._state(row)


def _verify(db, rid, run, artifact, audits):
    db.flush()
    if storage.actual_run_state(db, rid) != run or storage.actual_artifact_state(db, rid) != artifact:
        raise HTTPException(409, "本地任务实际22字段/明确秒级时钟/完整持久件写后变化")
    for expected in audits:
        r._verify_audit(db, expected)
    storage.creation_audit(db, storage.technical(db, rid))


def _daily_count(db, uid):
    start = r.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=1)
    # Count all old/damaged records too. No fake complete limit. Actual current
    # feature/time index avoids locking unrelated held Run rows in MySQL.
    query = db.query(AIRun.run_id).filter(AIRun.feature_key == t.FEATURE_KEY, AIRun.requested_by == uid, AIRun.create_time >= start, AIRun.create_time < end)
    if db.get_bind().dialect.name == "mysql":
        query = query.with_hint(AIRun, "FORCE INDEX (idx_ai_run_feature_time)", "mysql")
    ids = {row[0] for row in current(query, shared=True).all()}
    native = db.query(Artifact.run_id).filter(Artifact.requested_by == uid, Artifact.created_at >= start, Artifact.created_at < end)
    if db.get_bind().dialect.name == "mysql":
        native = native.with_hint(Artifact, "FORCE INDEX (idx_inf_run_requester_created)", "mysql")
    ids.update(row[0] for row in current(native, shared=True).all())
    return len(ids)


@r.atomic
def create_run(db, user, value):
    req = t.TaskCreate.model_validate(value)
    prepared = context.prepare(db, user, req.infection_cluster_scenario_id, preview=req.preview)
    actor, _, source, profile, config, selection = prepared
    if _daily_count(db, actor.user_id) >= config.daily_limit:
        raise HTTPException(429, "本地任务当日额度已用尽，旧或损坏记录也计入")
    rid = str(uuid.uuid4())
    frozen = context.freeze(rid, prepared, preview=req.preview)
    raw_input, raw_evidence, raw_metadata = t.task_json({"infection_cluster_scenario_id": req.infection_cluster_scenario_id}), "[]", t.task_json(frozen)
    source_json = c.canonical(source)
    run = AIRun(
        run_id=rid,
        feature_key=t.FEATURE_KEY,
        provider_id=None,
        provider_revision=None,
        prompt_version=0,
        prompt_hash=t.LOCAL_PROMPT_HASH,
        context_digest=c.digest(frozen.source_binding),
        patient_id=None,
        encounter_ref=None,
        requested_by=actor.user_id,
        status="queued",
        preview=int(req.preview),
        input_json=raw_input,
        result_json="{}",
        evidence_json=raw_evidence,
        context_metadata_json=raw_metadata,
        error_code=None,
        error_message=None,
        input_tokens=0,
        output_tokens=0,
        latency_ms=None,
        start_time=None,
        lease_token=None,
        create_time=r.clock(frozen.created_at).replace(microsecond=0),
        finish_time=None,
    )
    artifact = Artifact(
        run_id=rid,
        scenario_id=frozen.scenario_id,
        snapshot_id=frozen.source_binding.snapshot_id,
        profile_id=profile.profile_id,
        requested_by=actor.user_id,
        schema_version="infection_local_run_artifact_v1",
        created_at=r.clock(frozen.created_at),
        preview=int(req.preview),
        requester_epoch_hash=c.digest(frozen.requester_epoch),
        configuration_hash=selection.config_hash,
        source_binding_hash=c.digest(frozen.source_binding),
        scenario_content_hash=frozen.scenario_content_hash,
        scenario_governance_hash=frozen.scenario_governance_hash,
        profile_content_hash=profile.content_hash,
        profile_governance_hash=profile.governance_hash,
        recipe_hash=frozen.recipe_hash,
        implementation_hash=frozen.implementation_hash,
        input_hash=c.text_digest(raw_input),
        evidence_hash=c.text_digest(raw_evidence),
        metadata_hash=c.text_digest(raw_metadata),
        source_json=source_json,
        source_hash=c.text_digest(source_json),
        source_bytes=len(c.utf8(source_json)),
        result_json=None,
        result_hash=None,
        result_bytes=None,
        usage_event_id=None,
        accept_event_id=None,
        accepted_lease=None,
        accepted_at=None,
    )
    event, expected_event = _audit(db, actor.user_id, storage.CREATE, rid, {"schema_version": "infection_local_create_audit_v1", "artifact": storage.immutable(artifact)})
    artifact.create_event_id = event.event_id
    expected_run = storage.memory_run_state(run)
    expected_artifact = {key: getattr(artifact, key) for key in storage.TECHNICAL}
    db.add(run)
    db.flush([run])
    db.add(artifact)
    _verify(db, rid, expected_run, expected_artifact, [expected_event])
    storage.authorize(db, actor, rid, execution=True)
    from app.ai.native_task_routing import remember_staged_identity

    remember_staged_identity(db, artifact)
    return dict(run_id=rid, feature_key=t.FEATURE_KEY, status="queued", result_available=False)


@r.atomic
def claim(db, rid):
    from app.models import User

    opaque = storage.locator(db, rid)
    if opaque is None:
        raise HTTPException(404, "本地任务不存在")
    actor = current(db.query(User).filter_by(user_id=opaque.requested_by), shared=True).one_or_none()
    if actor is None:
        raise HTTPException(403, "原请求账户不存在")
    actor, run, artifact, frozen, source = storage.authorize(db, actor, rid, execution=True, write=True)
    if run.status != "queued":
        raise HTTPException(409, "本地任务已被领取或终止")
    run.status, run.lease_token, run.start_time = "running", str(uuid.uuid4()), r.utcnow().replace(microsecond=0)
    expected = storage.memory_run_state(run)
    art = {key: getattr(artifact, key) for key in storage.TECHNICAL}
    _verify(db, rid, expected, art, [])
    storage.authorize(db, actor, rid, execution=True)
    return run.lease_token, source.model_dump(mode="json"), frozen.model_dump(mode="json")


def _usage_value(rid, lease, status, *, attempted, completed, milliseconds, result_hash):
    return t.LocalUsage(
        schema_version="infection_local_usage_v1",
        run_id=rid,
        lease=lease,
        terminal_status=status,
        input_tokens=0,
        output_tokens=0,
        model_call_attempted=False,
        accounting_basis="installed_local_calculation_without_external_model_call_not_a_cpu_cost_estimate",
        calculation_attempted=attempted,
        calculation_completed=completed,
        calculation_ms=milliseconds,
        result_hash=result_hash,
    )


@r.atomic
def terminal(db, rid, lease, *, status, result=None, attempted, completed, milliseconds=None, error_code=None):
    """Trusted local lease terminal. Failure/cancel cannot grant clinical reads."""
    lock_gate(db)
    artifact, before = storage.verify_technical_run(db, rid)
    if before["lease_token"] != lease or before["status"] not in {"queued", "running", "cancelled"} or artifact.usage_event_id is not None:
        raise HTTPException(409, "本地原租约或尚未回执的状态已变化")
    if before["status"] == "queued" and (lease is not None or attempted is not False or completed is not False):
        raise HTTPException(409, "未领取任务不能伪造计算尝试/租约")
    # An already recorded cancellation is permanent even when its genuine CPU
    # completion arrives later. It receives a receipt, never an accepted result.
    if before["status"] == "cancelled":
        status, result, error_code = "cancelled", None, "CANCELLED"
    authorized = None
    if status == "succeeded":
        from app.models import User

        actor = current(db.query(User).filter_by(user_id=artifact.requested_by), shared=True).one()
        authorized = storage.authorize(db, actor, rid, execution=True, write=True)
        if result is None or not engine.verify_analysis_binding(authorized[4], result):
            raise HTTPException(409, "完整统计结果与当前有限声明不一致")
    elif status not in {"failed", "cancelled"} or result is not None:
        raise HTTPException(409, "非成功终态不得接受模型/统计结果")
    result_json = c.canonical(result) if result is not None else None
    result_hash = c.text_digest(result_json) if result_json is not None else None
    value = _usage_value(rid, lease, status, attempted=attempted, completed=completed, milliseconds=milliseconds, result_hash=result_hash)
    event, usage_expected = _audit(db, artifact.requested_by, storage.USAGE, rid, value)
    changes = dict(usage_event_id=event.event_id)
    pointer = "{}"
    audits = [usage_expected]
    if result is not None:
        accepted_at = r.utcnow()
        changes.update(result_json=result_json, result_hash=result_hash, result_bytes=len(c.utf8(result_json)), accepted_at=accepted_at, accepted_lease=lease)
        accepted, expected = _audit(
            db,
            artifact.requested_by,
            storage.ACCEPT,
            rid,
            {
                "schema_version": "infection_local_accept_audit_v1",
                "run_id": rid,
                "lease": lease,
                "source_hash": artifact.source_hash,
                "result_hash": result_hash,
                "result_bytes": changes["result_bytes"],
                "accepted_at": r.utc(accepted_at),
                "usage_event_id": event.event_id,
            },
        )
        changes["accept_event_id"] = accepted.event_id
        audits.append(expected)
        pointer = t.task_json(
            t.ResultPointer(schema_version="infection_statistics_result_pointer_v1", run_id=rid, source_hash=artifact.source_hash, result_hash=result_hash, result_bytes=changes["result_bytes"])
        )
    updates = dict(
        status=status,
        result_json=pointer,
        input_tokens=0,
        output_tokens=0,
        latency_ms=milliseconds,
        error_code=error_code,
        error_message=None if error_code is None else "本地任务已终止；实际用量与计算尝试见独立回执",
        finish_time=r.utcnow().replace(microsecond=0),
    )
    expected_run = deepcopy(before)
    for field, val in updates.items():
        expected_run[field] = {"sha256": c.text_digest(val), "bytes": len(c.utf8(val))} if field in t.RAW_FIELDS else val
    expected_artifact = {key: getattr(artifact, key) for key in storage.TECHNICAL}
    expected_artifact.update({key: val for key, val in changes.items() if key in storage.TECHNICAL})
    db.query(Artifact).filter_by(run_id=rid).update(changes, synchronize_session=False)
    db.query(AIRun).filter_by(run_id=rid).update(updates, synchronize_session=False)
    _verify(db, rid, expected_run, expected_artifact, audits)
    row = storage.technical(db, rid)
    storage.usage(db, row, SimpleNamespace(**{**updates, "lease_token": lease}))
    if authorized is not None:
        storage.load_result(db, authorized[0], rid)
    return dict(run_id=rid, feature_key=t.FEATURE_KEY, status=status, result_available=status == "succeeded")


@r.atomic
def cancel(db, user, rid):
    opaque = storage.locator(db, rid)
    if opaque is None:
        raise HTTPException(404, "本地任务不存在")
    from app.dependencies import VALID_USER_ROLES

    actor = r._start(db, user, roles=VALID_USER_ROLES, related_user_ids={opaque.requested_by})
    if actor.user_id != opaque.requested_by and actor.user_role != "super_admin":
        raise HTTPException(403, "仅本人或当前Super可技术取消，不授予正文权限")
    artifact, before = storage.verify_technical_run(db, rid)
    if before["status"] == "queued":
        return terminal(db, rid, None, status="cancelled", attempted=False, completed=False, error_code="CANCELLED")
    if before["status"] != "running":
        raise HTTPException(409, "任务已终止")
    changes = dict(status="cancelled", error_code="CANCELLED", error_message="已请求停止，真实本地计算尝试待原租约回执", finish_time=r.utcnow().replace(microsecond=0))
    expected = deepcopy(before)
    expected.update(changes)
    db.query(AIRun).filter_by(run_id=rid).update(changes, synchronize_session=False)
    _verify(db, rid, expected, {key: getattr(artifact, key) for key in storage.TECHNICAL}, [])
    return dict(run_id=rid, feature_key=t.FEATURE_KEY, status="cancelled", result_available=False)


def _calculate(value):
    start = time.monotonic()
    result = engine.evaluate(value)
    return result.model_dump(mode="json"), max(0, int((time.monotonic() - start) * 1000))


@r.atomic
def claim_for_shared(db, rid):
    """Dedicated claim adapter; never lets an invalid78 enter generic inference."""
    try:
        lease, _, _ = claim(db, rid)
        db.commit()
        return lease
    except HTTPException:
        db.rollback()
        if storage.locator(db, rid) is not None:
            state = storage.actual_run_state(db, rid)
            if state["status"] == "queued":
                terminal(db, rid, None, status="failed", attempted=False, completed=False, error_code="CURRENT_AUTHORITY_CHANGED")
                db.commit()
        db.rollback()
        return None


async def execute_claimed(session_factory, rid, lease):
    """Recheck dispatch, close SQL, calculate once, then recheck acceptance."""
    from app.models import User

    with session_factory() as db:
        artifact, before = storage.verify_technical_run(db, rid)
        if before["lease_token"] != lease or before["status"] not in {"running", "cancelled"} or artifact.usage_event_id is not None:
            db.rollback()
            return
        if before["status"] == "cancelled":
            terminal(db, rid, lease, status="cancelled", attempted=False, completed=False, error_code="CANCELLED")
            db.commit()
            return
        try:
            actor = current(db.query(User).filter_by(user_id=artifact.requested_by), shared=True).one_or_none()
            if actor is None:
                raise HTTPException(403, "原请求账户已不存在")
            authorized = storage.authorize(db, actor, rid, execution=True)
            source = authorized[4].model_dump(mode="json")
            db.rollback()
        except HTTPException:
            db.rollback()
            terminal(db, rid, lease, status="failed", attempted=False, completed=False, error_code="CURRENT_AUTHORITY_CHANGED")
            db.commit()
            return
    # Session and transaction are closed. A reservation/lease is not an observed
    # CPU entry; an interrupted/unknown thread attempt stays nullable.
    result, elapsed, attempted, completed = None, None, True, False
    try:
        result, elapsed = await asyncio.to_thread(_calculate, source)
        completed = True
    except Exception:
        attempted = None
    with session_factory() as db:
        try:
            terminal(
                db,
                rid,
                lease,
                status="succeeded" if result is not None else "failed",
                result=result,
                attempted=attempted,
                completed=completed if attempted is not None else None,
                milliseconds=elapsed,
                error_code=None if result is not None else "LOCAL_CALCULATION_FAILED",
            )
            db.commit()
        except HTTPException:
            db.rollback()
            # Authority loss discards the result while preserving genuine CPU
            # completion and actual zero external tokens; no calculation retry.
            terminal(db, rid, lease, status="failed", attempted=attempted, completed=completed if attempted is not None else None, milliseconds=elapsed, error_code="CURRENT_AUTHORITY_CHANGED")
            db.commit()


async def execute_run(session_factory, rid):
    with session_factory() as db:
        lease = claim_for_shared(db, rid)
    if lease is not None:
        await execute_claimed(session_factory, rid, lease)


def expire_interrupted_runs(db):
    """Technical source-free closure, never a retry or restored clinical read."""
    from sqlalchemy import and_, or_

    from app.config import settings

    lock_gate(db)
    now = r.utcnow()
    deadline = now - dt.timedelta(minutes=10)
    queue_deadline = now - dt.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS)
    count = 0
    query = (
        db.query(Artifact.run_id, AIRun.status, AIRun.lease_token)
        .join(AIRun, AIRun.run_id == Artifact.run_id)
        .filter(
            Artifact.usage_event_id.is_(None),
            or_(
                and_(AIRun.status == "queued", AIRun.create_time < queue_deadline),
                and_(AIRun.status == "running", AIRun.start_time < deadline),
                and_(AIRun.status == "cancelled", AIRun.finish_time < deadline),
            ),
        )
    )
    for row in current(query.order_by(Artifact.run_id), shared=True).all():
        queued = row.status == "queued"
        terminal(
            db,
            row.run_id,
            row.lease_token,
            status="cancelled" if row.status == "cancelled" else "failed",
            attempted=False if queued else None,
            completed=False if queued else None,
            error_code="WORKER_INTERRUPTED",
        )
        count += 1
    db.commit()
    return count
