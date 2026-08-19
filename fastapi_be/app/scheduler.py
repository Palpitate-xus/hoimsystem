import asyncio
import datetime

from app.models import Appointment, BreachRecord, DoctorSchedule, Pharmaceutical

JOB_NAMES = {"inventory_alert", "breach_statistics", "breach_scan", "backup"}
_state = {name: {"last_run": None, "last_result": None} for name in JOB_NAMES}
_task = None


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
        if job_name == "inventory_alert":
            low_stock = db.query(Pharmaceutical).filter(Pharmaceutical.stock <= 0, Pharmaceutical.status == 0).count()
            result = {"low_stock_count": low_stock}
        elif job_name == "breach_statistics":
            since = datetime.datetime.now() - datetime.timedelta(days=1)
            result = {"last_24h_count": db.query(BreachRecord).filter(BreachRecord.breach_time >= since).count()}
        elif job_name == "breach_scan":
            result = _run_breach_scan(db)
        else:
            # 备份由现有 backup API 执行；调度器只登记触发状态，避免后台任务覆盖用户数据。
            result = {"status": "delegated_to_backup_service"}
        _state[job_name] = {"last_run": datetime.datetime.now(), "last_result": result}
        return result
    finally:
        db.close()


async def scheduler_loop():
    while True:
        await asyncio.sleep(3600)
        for job_name in JOB_NAMES:
            try:
                await asyncio.to_thread(run_job, job_name)
            except Exception:
                # 单个任务失败不影响其他任务和主服务。
                continue


def start_scheduler():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(scheduler_loop())


def stop_scheduler():
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = None


def status():
    jobs = [{"name": name, **details} for name, details in sorted(_state.items())]
    return {"running": _task is not None and not _task.done(), "interval_seconds": 3600, "jobs": jobs}
