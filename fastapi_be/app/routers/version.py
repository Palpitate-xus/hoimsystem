"""系统元信息：版本（公开）。"""
from fastapi import APIRouter

from app.config import settings

router = APIRouter()

APP_VERSION = "2.0.0"


@router.get("/version")
def get_version():
    """系统版本信息（公开，供前端关于页与发布核对）。"""
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "version": APP_VERSION,
            "environment": settings.ENVIRONMENT,
        },
    }
