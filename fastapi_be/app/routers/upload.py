import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
AVATAR_DIR = os.path.join(UPLOAD_DIR, "avatars")
REPORT_DIR = os.path.join(UPLOAD_DIR, "reports")

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_DOC_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/dicom"}
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB
MAX_REPORT_SIZE = 20 * 1024 * 1024  # 20MB


def _save_file(upload_dir: str, file: UploadFile, allowed_types: set, max_size: int) -> dict:
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file.content_type}")

    contents = file.file.read()
    if len(contents) > max_size:
        raise HTTPException(status_code=400, detail=f"文件过大，最大允许 {max_size // 1024 // 1024}MB")

    ext = os.path.splitext(file.filename or "")[1] or ".bin"
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(upload_dir, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    return {"filename": filename, "url": f"/uploads/{os.path.basename(upload_dir)}/{filename}"}


@router.post("/upload/avatar")
def upload_avatar(file: UploadFile = File(...)):
    os.makedirs(AVATAR_DIR, exist_ok=True)
    result = _save_file(AVATAR_DIR, file, ALLOWED_IMAGE_TYPES, MAX_AVATAR_SIZE)
    return {"code": 200, "msg": "success", "data": result}


@router.post("/upload/report")
def upload_report(file: UploadFile = File(...)):
    os.makedirs(REPORT_DIR, exist_ok=True)
    result = _save_file(REPORT_DIR, file, ALLOWED_DOC_TYPES, MAX_REPORT_SIZE)
    return {"code": 200, "msg": "success", "data": result}


@router.get("/uploads/avatars/{filename}")
def get_avatar(filename: str):
    filepath = os.path.join(AVATAR_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(filepath)


@router.get("/uploads/reports/{filename}")
def get_report(filename: str):
    filepath = os.path.join(REPORT_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(filepath)
