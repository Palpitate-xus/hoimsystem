import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.dependencies import get_current_user
from app.models import User

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
AVATAR_DIR = os.path.join(UPLOAD_DIR, "avatars")
REPORT_DIR = os.path.join(UPLOAD_DIR, "reports")

# 仅信任服务端控制的扩展名白名单 + 魔数校验，客户端 Content-Type 可伪造，不可作为依据
ALLOWED_IMAGE_EXTS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
ALLOWED_DOC_EXTS = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".dcm": "application/dicom"}
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB
MAX_REPORT_SIZE = 20 * 1024 * 1024  # 20MB

# 常见文件头魔数（用于校验文件内容与扩展名一致，防止改后缀绕过）
_MAGIC_SIGNATURES = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)


def _sniff_ext(contents: bytes) -> str | None:
    """根据文件头识别图片真实类型；PDF/DICOM 由各自固定魔数识别。"""
    for magic, ext in _MAGIC_SIGNATURES:
        if contents.startswith(magic):
            return ext
    if contents.startswith(b"%PDF-"):
        return ".pdf"
    if len(contents) > 128 and contents[128:132] == b"DICM":
        return ".dcm"
    return None


def _normalized_ext(filename: str | None) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    # splitext 对 ".png" 这类无主名点文件返回空扩展，此处直接取点后缀
    if not ext and filename:
        base = filename.lower()
        i = base.rfind(".")
        if i == 0:
            ext = base
    return ".jpg" if ext == ".jpeg" else ext


def _save_file(upload_dir: str, file: UploadFile, allowed_exts: dict, max_size: int) -> dict:
    ext = _normalized_ext(file.filename)
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext or '未知'}")

    contents = file.file.read()
    if len(contents) > max_size:
        raise HTTPException(status_code=400, detail=f"文件过大，最大允许 {max_size // 1024 // 1024}MB")
    if not contents:
        raise HTTPException(status_code=400, detail="文件为空")

    # 内容魔数必须与扩展名声明的类型一致（.png 必须真是 PNG……）
    sniffed = _sniff_ext(contents)
    if sniffed is None or _normalized_ext(sniffed) != ext:
        raise HTTPException(status_code=400, detail="文件内容与扩展名不符")

    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(upload_dir, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    return {"filename": filename, "url": f"/uploads/{os.path.basename(upload_dir)}/{filename}"}


def _safe_filepath(base_dir: str, filename: str) -> str:
    if filename != os.path.basename(filename) or filename in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="非法文件名")
    filepath = os.path.realpath(os.path.join(base_dir, filename))
    base_real = os.path.realpath(base_dir)
    if not filepath.startswith(base_real + os.sep):
        raise HTTPException(status_code=400, detail="非法文件名")
    return filepath


def _attachment_response(filepath: str) -> FileResponse:
    """以附件形式返回文件，强制 Content-Disposition 并禁用浏览器内容嗅探。"""
    return FileResponse(
        filepath,
        filename=os.path.basename(filepath),
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.post("/upload/avatar")
def upload_avatar(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    os.makedirs(AVATAR_DIR, exist_ok=True)
    result = _save_file(AVATAR_DIR, file, ALLOWED_IMAGE_EXTS, MAX_AVATAR_SIZE)
    return {"code": 200, "msg": "success", "data": result}


@router.post("/upload/report")
def upload_report(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    os.makedirs(REPORT_DIR, exist_ok=True)
    result = _save_file(REPORT_DIR, file, ALLOWED_DOC_EXTS, MAX_REPORT_SIZE)
    return {"code": 200, "msg": "success", "data": result}


@router.get("/uploads/avatars/{filename}")
def get_avatar(filename: str):
    # 头像必须由本服务上传生成：UUID 十六进制文件名 + 白名单扩展名
    base, ext = os.path.splitext(filename)
    if not base or ext.lower() not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail="非法文件名")
    filepath = _safe_filepath(AVATAR_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")
    # avatars 目录仅存放白名单图片类型，内联展示安全；仍禁用内容嗅探
    return FileResponse(filepath, headers={"X-Content-Type-Options": "nosniff"})


@router.get("/uploads/reports/{filename}")
def get_report(filename: str, current_user: User = Depends(get_current_user)):
    base, ext = os.path.splitext(filename)
    if not base or ext.lower() not in ALLOWED_DOC_EXTS:
        raise HTTPException(status_code=400, detail="非法文件名")
    filepath = _safe_filepath(REPORT_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")
    return _attachment_response(filepath)
