import datetime
import os
import shutil

from fastapi import APIRouter, Depends

from app.dependencies import ADMIN_ROLES, require_roles

router = APIRouter()

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "test.db")


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
    if not os.path.exists(DB_PATH):
        return {"code": 500, "msg": "数据库文件不存在"}
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    try:
        shutil.copy2(DB_PATH, backup_path)
        return {"code": 200, "msg": "success", "data": {"filename": backup_name}}
    except Exception as e:
        return {"code": 500, "msg": f"备份失败: {str(e)}"}


@router.get("/backup/getList")
def get_backup_list(current_user=Depends(require_roles(*ADMIN_ROLES))):
    """获取备份列表"""
    return {"code": 200, "msg": "success", "data": _get_backup_list()}


@router.post("/backup/delete")
def delete_backup(req: dict, current_user=Depends(require_roles(*ADMIN_ROLES))):
    """删除备份文件"""
    filename = req.get("filename", "")
    if not filename or ".." in filename or "/" in filename:
        return {"code": 500, "msg": "非法文件名"}
    fpath = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(fpath):
        return {"code": 500, "msg": "备份文件不存在"}
    try:
        os.remove(fpath)
        return {"code": 200, "msg": "success"}
    except Exception as e:
        return {"code": 500, "msg": f"删除失败: {str(e)}"}


@router.post("/backup/restore")
def restore_backup(req: dict, current_user=Depends(require_roles(*ADMIN_ROLES))):
    """恢复数据库备份"""
    filename = req.get("filename", "")
    if not filename or ".." in filename or "/" in filename:
        return {"code": 500, "msg": "非法文件名"}
    backup_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(backup_path):
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
    except Exception as e:
        return {"code": 500, "msg": f"恢复失败: {str(e)}"}


@router.get("/backup/download/{filename}")
def download_backup(filename: str, current_user=Depends(require_roles(*ADMIN_ROLES))):
    """下载备份文件"""
    from fastapi.responses import FileResponse

    if ".." in filename or "/" in filename:
        return {"code": 500, "msg": "非法文件名"}
    fpath = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(fpath):
        return {"code": 500, "msg": "备份文件不存在"}
    return FileResponse(fpath, filename=filename, media_type="application/octet-stream")
