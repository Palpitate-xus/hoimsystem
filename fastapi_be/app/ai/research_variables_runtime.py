"""Dedicated76 queue creation and authentic claim, never a generic fallback.

The Research Gate/current purposes and configuration precede Run locks. A
trusted worker may close a pristine queued task after authority loss using its
concrete creation PK; that exception grants no Source or Task body permission.
"""

import datetime as dt
import uuid
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from app.ai import research_variables_attempts as attempts
from app.ai import research_variables_receipts as receipts
from app.ai import research_variables_storage as storage
from app.ai import research_variables_task_reader as reader
from app.ai.models import AIRun
from app.ai.research_cohort_sources import utcnow
from app.ai.research_cohort_write_guard import lock_research_gate
from app.ai.research_variables_configuration import current_configuration
from app.ai.research_variables_gateway import VariableGatewayError, build_request
from app.ai.research_variables_run_models import AIResearchVariableRunArtifact
from app.ai.research_variables_storage_contract import VariableUsageReceipt
from app.ai.research_variables_task_context import prepare_context
from app.ai.research_variables_task_contract import FEATURE_KEY
from app.sql_counts import locked_row_count


def current_daily_count(db, owner, when):
    """Current read while caller retains this feature's Config X and Gate.

    The exact feature/time index avoids locking another feature's Run during
    quota calculation. No Task TEXT or broad queued-task lock is selected.
    """
    start = dt.datetime.combine(when.date(), dt.time.min)
    query = (
        db.query(AIRun)
        .with_hint(AIRun, "FORCE INDEX (idx_ai_run_feature_time)", dialect_name="mysql")
        .filter(AIRun.feature_key == FEATURE_KEY, AIRun.requested_by == owner, AIRun.create_time >= start, AIRun.create_time < start + dt.timedelta(days=1))
        .with_for_update(read=True)
    )
    return locked_row_count(query, AIRun.run_id, aggregate=True)


def create_variable_run(db, user, req):
    """Persist one whole-wire-compatible task and creation audit atomically."""
    try:
        if req.feature_key != FEATURE_KEY or req.patient_id is not None or req.encounter_ref is not None or type(req.preview) is not bool:
            raise HTTPException(422, "变量任务仅接受明确批次及原样可选问题，未接受患者、就诊或其它任务模式")
        prepared = prepare_context(db, user, req.input)
        configured = current_configuration(db, prepared.authority.actor, preview=req.preview, require_credentials=True)
        if type(configured.config.daily_limit) is not int or not 1 <= configured.config.daily_limit <= 10000:
            raise HTTPException(409, "本功能明确日配额无效，未使用默认值覆盖")
        clock = dt.datetime.strptime(prepared.data["snapshot_time"], "%Y-%m-%dT%H:%M:%S.%fZ")
        before = current_daily_count(db, prepared.authority.actor.user_id, clock)
        if before >= configured.config.daily_limit:
            raise HTTPException(429, "该功能今日明确任务额度已用完")
        snapshot = storage.snapshot_for_context(prepared, configured)
        try:
            # Includes the complete System/Task, escaping and protocol headers;
            # independent8MiB Source registration does not promise wire fit.
            build_request(snapshot, prepared.binding, prepared.source)
        except VariableGatewayError as exc:
            raise HTTPException(413, "完整变量来源、System/Task及实际协议请求超限或无法核对；未入队、发送或裁剪") from exc
        run = AIRun(run_id=str(uuid.uuid4()), preview=int(req.preview))
        stored = storage.stage_run(db, prepared.authority.actor, run, prepared, snapshot)
        checked = reader.load_task(db, prepared.authority.actor, run.run_id, exclusive=True, for_execution=True)
        after = current_daily_count(db, prepared.authority.actor.user_id, clock)
        if after != before + 1 or after > configured.config.daily_limit or checked.run.run_id != run.run_id:
            raise HTTPException(409, "实际日配额、新任务集合或原授权已变化，整件未入队")
        db.commit()
        return stored.run
    except Exception:
        db.rollback()
        raise


def _queued_failure(db, identifier, code):
    """Trusted queue stop; exact creation proof and zero private Task TEXT."""
    lock_research_gate(db)
    identity = reader.locate_artifact(db, identifier)
    if identity is None:
        raise HTTPException(409, "原生变量任务缺失真实Artifact，未降级通用任务")
    header, artifact = reader._headers(db, identity, exclusive=True)
    reader._creation_audit(db, header, artifact)
    return receipts.stage_queued_terminal(
        db,
        identifier,
        expected_create_event_id=artifact["create_event_id"],
        status="failed",
        error_code=code,
        error_message="实际领取前原Source、用途或配置已失效；仅保存确定未调用回执，未恢复正文权限。",
    )


def claim_variable_run(db, identifier):
    """One durable owner; duplicate deliveries never replace an actual claim."""
    try:
        phase = attempts._phase_header(db, identifier)
        if phase is None:
            raise HTTPException(409, "原生变量任务没有实际Artifact领取技术头")
        if phase[1] is not None:
            db.rollback()
            return None
        identity = reader.locate_artifact(db, identifier)
        if identity is None:
            raise HTTPException(409, "变量任务原始身份不存在，不降级通用claim")
        actor = SimpleNamespace(user_id=identity[2])
        try:
            task = reader.load_task(db, actor, identifier, exclusive=True, for_execution=True)
            from app.config import settings

            elapsed = utcnow() - task.artifact.recorded_at
            if elapsed < dt.timedelta(0) or elapsed > dt.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS):
                raise HTTPException(409, "原任务已超出明确队列期限，未重放旧来源")
            claim = attempts.stage_claim(db, task.authority.actor, identifier)
        except HTTPException:
            db.rollback()
            _queued_failure(db, identifier, "VARIABLE_CURRENT_STATE_CHANGED")
            db.commit()
            return None
        if claim is None:
            db.rollback()
            return None
        reader.load_task(db, task.authority.actor, identifier, exclusive=True, for_execution=True)
        db.commit()
        return claim.lease
    except Exception:
        db.rollback()
        raise


def recover_variable_tasks(db, deadline):
    """Trusted body-free interrupted settlement; never replay an HTTP call.

    The bounded polling batch is a queue mechanism, not a claim that omitted
    jobs were checked. RC current committed IDs union own actual-SQL IDs are
    only candidates; every selected row repeats exact current phase proof.
    Each settlement commits before unrelated generic recovery can wait Run X.
    """
    statement = (
        select(AIResearchVariableRunArtifact.run_id)
        .join(AIRun, AIRun.run_id == AIResearchVariableRunArtifact.run_id)
        .where(AIRun.status.in_(["running", "cancelled"]), AIRun.start_time < deadline, AIResearchVariableRunArtifact.usage_event_id.is_(None))
        .order_by(AIResearchVariableRunArtifact.run_id)
        .limit(100)
    )
    with db.no_autoflush:
        identifiers = set()
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                identifiers.update(connection.execute(statement).scalars())
        identifiers.update(db.execute(statement).scalars())
    count = 0
    for identifier in sorted(identifiers):
        try:
            lock_research_gate(db)
            identity = reader.locate_artifact(db, identifier)
            if identity is None:
                raise HTTPException(409, "恢复候选已失去原始Artifact，不处理为通用任务")
            header, artifact = reader._headers(db, identity, exclusive=True)
            reader._creation_audit(db, header, artifact)
            if artifact["usage_event_id"] is not None or header["status"] not in {"running", "cancelled"} or header["start_time"] is None or header["start_time"] >= deadline:
                db.rollback()
                continue
            task = SimpleNamespace(run=SimpleNamespace(**header), artifact=SimpleNamespace(**artifact))
            claim = attempts.verify_claim(db, task)
            delivery = attempts.verify_delivery(db, task) if artifact["dispatch_event_id"] is not None else None
            usage = (
                VariableUsageReceipt(input_tokens=None, output_tokens=None, complete=False, model_call_attempted=None)
                if delivery is not None
                else VariableUsageReceipt(input_tokens=0, output_tokens=0, complete=True, model_call_attempted=False)
            )
            record = receipts.stage_terminal(
                db,
                claim,
                delivery=delivery,
                receipt=usage,
                status="failed",
                error_code="WORKER_INTERRUPTED",
                error_message="实际原领取中断；原分派是否调用及用量未知时保留未知，未重放模型、恢复来源读取或导出。",
                latency_ms=0,
            )
            db.commit()
            count += int(record is not None)
        except Exception:
            db.rollback()
            raise
    return count
