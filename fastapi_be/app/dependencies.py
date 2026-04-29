from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User


def get_current_user(access_token: str = Header(None, alias="accesstoken"), db: Session = Depends(get_db)) -> User:
    if not access_token:
        raise HTTPException(status_code=401, detail="Missing accesstoken")
    user = db.query(User).filter(User.username == access_token).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid accesstoken")
    return user
