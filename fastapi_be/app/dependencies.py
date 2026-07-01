import jwt
from fastapi import Depends, Header, HTTPException
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
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_current_user(access_token: str = Header(None, alias="accesstoken"), db: Session = Depends(get_db)) -> User:
    if not access_token:
        raise HTTPException(status_code=401, detail="Missing accesstoken")
    username = decode_access_token(access_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired accesstoken")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid accesstoken")
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
