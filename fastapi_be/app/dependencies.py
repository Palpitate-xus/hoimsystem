import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User


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
