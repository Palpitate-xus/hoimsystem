import asyncio
import datetime
import json
import os
import socket
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text

from app.config import settings
from app.models import Appointment, BreachRecord, DoctorSchedule, Pharmaceutical, SchedulerJobState

JOB_NAMES = {"inventory_alert", "breach_statistics", "breach_scan", "backup", "integration_outbox"}
STANDARD_JOB_NAMES = JOB_NAMES - {"integration_outbox"}
_state = {name: {"last_run": None, "last_result": None} for name in JOB_NAMES}
_task = None
_local_locks = {name: threading.Lock() for name in JOB_NAMES}


@contextmanager
def _job_lock(db, job_name: str):
    """Use a connection-owned PostgreSQL lock, with a cross-process file-lock fallback."""

    if db.bind.dialect.name == "postgresql":
        acquired = bool(
            db.execute(
                text("SELECT pg_try_advisory_lock(hashtext(:lock_name))"),
                {"lock_name": f"hoimsystem.scheduler.{job_name}"},
            ).scalar()
        )
        try:
            yield acquired
        finally:
            if acquired:
                db.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:lock_name))"),
                    {"lock_name": f"hoimsystem.scheduler.{job_name}"},
                )
        return

    # SQLite/local development: flock also coordinates separate Gunicorn processes.
    try:
        import fcntl

        lock_path = Path(tempfile.gettempdir()) / f"hoimsystem-scheduler-{job_name}.lock"
        lock_file = lock_path.open("a+")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield True
        except BlockingIOError:
            yield False
        finally:
            lock_file.close()
    except (ImportError, OSError):
        lock = _local_locks[job_name]
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()


def _run_breach_scan(db) -> dict:
    """前一日"未报到且未取消"的预约记违约并回补号源（违约闭环激活）。

    原缺陷：is_breach 判定在报到时才触发（恒不可达），真正爽约者无人记录，
    30 天 3 次暂停预约机制形同虚设，号源被持续占用不释放。
    """
    now = datetime.datetime.now()
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    stale = (
        db.query(Appointment)
        .filter(Appointment.status == 0, Appointment.time < datetime.date.today())
        .all()
    )
    recorded = 0
    released = 0
    for appt in stale:
        # 幂等：同一预约只记一次违约
        existing = (
            db.query(BreachRecord)
            .filter(BreachRecord.registration_id == appt.registration_uuid)
            .first()
        )
        if existing:
            continue
        db.add(BreachRecord(
            registration_id=appt.registration_uuid,
            breach_time=now,
            breach_type="超时未报到",
        ))
        appt.status = 2  # 违约即取消
        db.add(appt)
        recorded += 1
        # 回补号源（仅扣减过的排班）
        if appt.schedule_id:
            schedule = db.query(DoctorSchedule).filter(DoctorSchedule.schedule_id == appt.schedule_id).first()
            if schedule:
                schedule.number = (schedule.number or 0) + 1
                released += 1
                db.add(schedule)
    db.commit()
    return {"scanned_before": str(yesterday), "breaches_recorded": recorded, "slots_released": released}


def run_job(job_name: str):
    if job_name not in JOB_NAMES:
        raise ValueError("未知定时任务")
    # 运行时读取会话工厂，便于测试环境替换数据库连接，也避免服务启动顺序影响连接配置。
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        with _job_lock(db, job_name) as acquired:
            if not acquired:
                return {"status": "skipped", "reason": "already_running"}

            now = datetime.datetime.now()
            state = db.get(SchedulerJobState, job_name) or SchedulerJobState(job_name=job_name)
            state.status = "running"
            state.owner = f"{socket.gethostname()}:{os.getpid()}"
            state.last_started_at = now
            state.last_error = None
            db.add(state)
            db.commit()

            try:
                if job_name == "inventory_alert":
                    low_stock = db.query(Pharmaceutical).filter(Pharmaceutical.stock <= 0, Pharmaceutical.status == 0).count()
                    result = {"low_stock_count": low_stock}
                elif job_name == "breach_statistics":
                    since = datetime.datetime.now() - datetime.timedelta(days=1)
                    result = {"last_24h_count": db.query(BreachRecord).filter(BreachRecord.breach_time >= since).count()}
                elif job_name == "breach_scan":
                    result = _run_breach_scan(db)
                elif job_name == "integration_outbox":
                    from app.integration_outbox import process_integration_outbox

                    result = process_integration_outbox(db)
                else:
                    # 备份由现有 backup API 执行；调度器只登记触发状态，避免后台任务覆盖用户数据。
                    result = {"status": "delegated_to_backup_service"}
                state = db.get(SchedulerJobState, job_name)
                state.status = "success"
                state.last_finished_at = datetime.datetime.now()
                state.last_result_json = json.dumps(result, ensure_ascii=False, default=str)
                db.commit()
                _state[job_name] = {"last_run": state.last_finished_at, "last_result": result}
                return result
            except Exception as exc:
                db.rollback()
                state = db.get(SchedulerJobState, job_name) or SchedulerJobState(job_name=job_name)
                state.status = "failed"
                state.last_finished_at = datetime.datetime.now()
                state.last_error = str(exc)[:1000]
                db.add(state)
                db.commit()
                raise
    finally:
        db.close()


async def scheduler_loop(run_immediately: bool = False):
    if not run_immediately:
        await asyncio.sleep(min(settings.SCHEDULER_INTERVAL_SECONDS, settings.INTEGRATION_OUTBOX_INTERVAL_SECONDS))
    next_standard_run = 0.0
    while True:
        loop_time = asyncio.get_running_loop().time()
        due_jobs = {"integration_outbox"}
        if loop_time >= next_standard_run:
            due_jobs.update(STANDARD_JOB_NAMES)
            next_standard_run = loop_time + settings.SCHEDULER_INTERVAL_SECONDS
        for job_name in due_jobs:
            try:
                await asyncio.to_thread(run_job, job_name)
            except Exception:
                # 单个任务失败不影响其他任务和主服务。
                continue
        await asyncio.sleep(settings.INTEGRATION_OUTBOX_INTERVAL_SECONDS)


def start_scheduler():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(scheduler_loop())


def stop_scheduler():
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = None


def status(db):
    persisted = {row.job_name: row for row in db.query(SchedulerJobState).all()}
    jobs = []
    for name in sorted(JOB_NAMES):
        row = persisted.get(name)
        result = None
        if row and row.last_result_json:
            try:
                result = json.loads(row.last_result_json)
            except ValueError:
                result = None
        jobs.append({
            "name": name,
            "status": row.status if row else "never_run",
            "owner": row.owner if row else None,
            "last_run": row.last_finished_at if row else None,
            "last_result": result,
            "last_error": row.last_error if row else None,
        })
    return {
        "running": settings.SCHEDULER_ENABLED and _task is not None and not _task.done(),
        "mode": "embedded" if settings.SCHEDULER_ENABLED else "external",
        "interval_seconds": settings.SCHEDULER_INTERVAL_SECONDS,
        "jobs": jobs,
    }
