from fastapi import APIRouter, Depends

from app.dependencies import ADMIN_ROLES, User, require_roles
from app.scheduler import JOB_NAMES, run_job, status

router = APIRouter()


@router.get("/scheduler/status")
def scheduler_status(current_user: User = Depends(require_roles(*ADMIN_ROLES))):
    return {"code": 200, "msg": "success", "data": status()}


@router.post("/scheduler/run/{job_name}")
def scheduler_run(job_name: str, current_user: User = Depends(require_roles(*ADMIN_ROLES))):
    if job_name not in JOB_NAMES:
        return {"code": 400, "msg": "未知定时任务"}
    return {"code": 200, "msg": "任务执行完成", "data": {"job_name": job_name, "result": run_job(job_name)}}
