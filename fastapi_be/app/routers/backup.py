import datetime
import os
import shutil

from fastapi import APIRouter, Depends

from app.config import settings
from app.dependencies import ADMIN_ROLES, require_roles

router = APIRouter()

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "test.db")


def _is_sqlite_file_database() -> bool:
    database_url = settings.DATABASE_URL.lower()
    return database_url.startswith("sqlite:") and ":memory:" not in database_url


def _backup_path(filename: str):
    if not filename or os.path.basename(filename) != filename or not filename.endswith(".db"):
        return None
    return os.path.join(BACKUP_DIR, filename)


def _get_backup_list():
    backups = []
    for fname in sorted(os.listdir(BACKUP_DIR), reverse=True):
        fpath = os.path.join(BACKUP_DIR, fname)
        if os.path.isfile(fpath) and fname.endswith(".db"):
            stat = os.stat(fpath)
            backups.append(
                {
                    "filename": fname,
                    "size": stat.st_size,
                    "size_human": f"{stat.st_size / 1024:.1f} KB" if stat.st_size < 1024 * 1024 else f"{stat.st_size / (1024 * 1024):.2f} MB",
                    "create_time": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
    return backups


@router.post("/backup/create")
def create_backup(current_user=Depends(require_roles(*ADMIN_ROLES))):
    """创建数据库备份"""
    if not _is_sqlite_file_database():
        return {"code": 501, "msg": "当前数据库不是 SQLite 文件库，请使用数据库原生备份工具"}
    if not os.path.exists(DB_PATH):
        return {"code": 500, "msg": "数据库文件不存在"}
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    try:
        shutil.copy2(DB_PATH, backup_path)
        return {"code": 200, "msg": "success", "data": {"filename": backup_name}}
    except Exception:
        return {"code": 500, "msg": "备份失败，请稍后重试"}


@router.get("/backup/getList")
def get_backup_list(current_user=Depends(require_roles(*ADMIN_ROLES))):
    """获取备份列表"""
    return {"code": 200, "msg": "success", "data": _get_backup_list()}


@router.post("/backup/delete")
def delete_backup(req: dict, current_user=Depends(require_roles(*ADMIN_ROLES))):
    """删除备份文件"""
    filename = req.get("filename", "")
    fpath = _backup_path(filename)
    if not fpath:
        return {"code": 500, "msg": "非法文件名"}
    if not os.path.isfile(fpath):
        return {"code": 500, "msg": "备份文件不存在"}
    try:
        os.remove(fpath)
        return {"code": 200, "msg": "success"}
    except Exception:
        return {"code": 500, "msg": "删除失败，请稍后重试"}


@router.post("/backup/restore")
def restore_backup(req: dict, current_user=Depends(require_roles(*ADMIN_ROLES))):
    """恢复数据库备份"""
    if not _is_sqlite_file_database():
        return {"code": 501, "msg": "当前数据库不是 SQLite 文件库，请使用数据库原生恢复工具"}
    filename = req.get("filename", "")
    backup_path = _backup_path(filename)
    if not backup_path:
        return {"code": 500, "msg": "非法文件名"}
    if not os.path.isfile(backup_path):
        return {"code": 500, "msg": "备份文件不存在"}
    # 先备份当前数据库
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    current_backup = os.path.join(BACKUP_DIR, f"auto_before_restore_{timestamp}.db")
    try:
        if os.path.exists(DB_PATH):
            shutil.copy2(DB_PATH, current_backup)
        shutil.copy2(backup_path, DB_PATH)
        return {
            "code": 200,
            "msg": "success",
            "data": {
                "need_restart": True,
                "note": "数据库已恢复，请重启后端服务以生效",
            },
        }
    except Exception:
        return {"code": 500, "msg": "恢复失败，请稍后重试"}


@router.get("/backup/download/{filename}")
def download_backup(filename: str, current_user=Depends(require_roles(*ADMIN_ROLES))):
    """下载备份文件"""
    from fastapi.responses import FileResponse

    fpath = _backup_path(filename)
    if not fpath:
        return {"code": 500, "msg": "非法文件名"}
    if not os.path.isfile(fpath):
        return {"code": 500, "msg": "备份文件不存在"}
    return FileResponse(fpath, filename=filename, media_type="application/octet-stream")
