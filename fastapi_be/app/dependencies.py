import datetime
import math
import re

import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"
ROLE_DIRECTOR = "director"
ROLE_DOCTOR = "doctor"
ROLE_NURSE = "nurse"
ROLE_CASHIER = "cashier"
ROLE_PHARMACIST = "pharmacist"
ROLE_GUIDE = "guide"
ROLE_PATIENT = "patient"
ROLE_LAB_TECHNICIAN = "lab_technician"
ROLE_REGISTRAR = "registrar"

VALID_USER_ROLES = {
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_DIRECTOR,
    ROLE_DOCTOR,
    ROLE_NURSE,
    ROLE_CASHIER,
    ROLE_PHARMACIST,
    ROLE_GUIDE,
    ROLE_PATIENT,
    ROLE_LAB_TECHNICIAN,
    ROLE_REGISTRAR,
}

ADMIN_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN}
NOTICE_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_DIRECTOR}
CLINICAL_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_DIRECTOR, ROLE_DOCTOR}
CASHIER_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_CASHIER}
PHARMACY_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_PHARMACIST}
NURSING_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_NURSE}
GUIDE_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_GUIDE}
LAB_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_LAB_TECHNICIAN}
REGISTRAR_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_REGISTRAR}


def _decode_access_payload(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"], options={"require": ["exp", "sub", "iat", "uid", "sid"]})
        if type(payload["uid"]) is not int or not 0 < payload["uid"] < 2**31:
            return None
        if type(payload["sid"]) is not str or re.fullmatch(r"[0-9a-f]{32}", payload["sid"]) is None:
            return None
        if type(payload["sub"]) is not str or not payload["sub"]:
            return None
        for claim in ("iat", "exp"):
            if type(payload[claim]) not in (int, float) or not math.isfinite(payload[claim]):
                return None
        if payload["iat"] < 0 or payload["iat"] > datetime.datetime.now(datetime.UTC).timestamp() or payload["exp"] <= payload["iat"]:
            return None
        return payload
    except (jwt.InvalidTokenError, TypeError, ValueError, OverflowError):
        return None


def decode_access_token(token: str) -> str | None:
    payload = _decode_access_payload(token)
    return payload["sub"] if payload else None


def resolve_access_token(access_token: str | None, db: Session) -> User:
    if not access_token:
        raise HTTPException(status_code=401, detail="Missing accesstoken")
    payload = _decode_access_payload(access_token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired accesstoken")
    user = db.query(User).filter(User.user_id == payload["uid"], User.username == payload["sub"], User.auth_subject == payload["sid"]).populate_existing().first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid accesstoken")
    # 吊销检查：token 签发时间早于 token_invalid_before 则拒绝（logout/改密后生效）
    if user.token_invalid_before:
        invalid_before = user.token_invalid_before
        if invalid_before.tzinfo is None:
            invalid_before = invalid_before.replace(tzinfo=datetime.UTC)
        if payload["iat"] < invalid_before.timestamp():
            raise HTTPException(status_code=401, detail="Token 已被吊销，请重新登录")
    from app.access_control import assert_account_enabled

    assert_account_enabled(db, user)
    return user


def get_current_user(
    request: Request,
    access_token: str = Header(None, alias="accesstoken"),
    db: Session = Depends(get_db),
) -> User:
    user = resolve_access_token(access_token, db)
    from app.access_control import enforce_request_permissions

    request.state.current_user = user
    # 中间件在请求级 Session 关闭后仍会运行，只保存不可变标量供审计与指标读取。
    request.state.auth_identity = (user.user_id, user.username, user.user_role)
    enforce_request_permissions(db, user, request)
    return user


def require_roles(*roles: str):
    allowed_roles = set(roles)

    def _require_roles(current_user: User = Depends(get_current_user)) -> User:
        if current_user.user_role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Forbidden")
        return current_user

    return _require_roles


def is_admin(user: User) -> bool:
    return user.user_role in ADMIN_ROLES
