import asyncio
import datetime

from app.models import BreachRecord, Pharmaceutical

JOB_NAMES = {"inventory_alert", "breach_statistics", "backup"}
_state = {name: {"last_run": None, "last_result": None} for name in JOB_NAMES}
_task = None


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
    return {"running": _task is not None and not _task.done(), "interval_seconds": 3600, "jobs": _state}
