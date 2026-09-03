import datetime

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


def decode_access_token(token: str) -> str:
    try:
        # 强制要求 exp 与 sub 声明：无 exp 的令牌直接拒绝（防止伪造缺失声明的绕过）
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"], options={"require": ["exp", "sub"]})
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def resolve_access_token(access_token: str | None, db: Session) -> User:
    if not access_token:
        raise HTTPException(status_code=401, detail="Missing accesstoken")
    username = decode_access_token(access_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired accesstoken")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid accesstoken")
    # 吊销检查：token 签发时间早于 token_invalid_before 则拒绝（logout/改密后生效）
    if user.token_invalid_before:
        try:
            import jwt as pyjwt

            payload = pyjwt.decode(
                access_token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                options={"verify_exp": False, "require": ["iat", "sub"]},
            )
            issued_at = payload.get("iat")
            if issued_at is not None:
                issued_dt = datetime.datetime.fromtimestamp(issued_at, datetime.UTC).replace(tzinfo=None)
                if issued_dt < user.token_invalid_before:
                    raise HTTPException(status_code=401, detail="Token 已被吊销，请重新登录")
        except pyjwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid accesstoken")
    return user


def get_current_user(
    request: Request,
    access_token: str = Header(None, alias="accesstoken"),
    db: Session = Depends(get_db),
) -> User:
    user = resolve_access_token(access_token, db)
    request.state.current_user = user
    # 中间件在请求级 Session 关闭后仍会运行，只保存不可变标量供审计与指标读取。
    request.state.auth_identity = (user.user_id, user.username, user.user_role)
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
