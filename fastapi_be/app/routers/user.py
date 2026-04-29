import json
from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Patient
from app.schemas import LoginRequest, RegisterRequest, UserInfoRequest, TestRequest
from app.dependencies import get_current_user

router = APIRouter()


@router.post("/test")
async def test(request: Request, db: Session = Depends(get_db)):
    body = json.loads(await request.body())
    temp = body.get("data")
    return {"code": 200, "msg": "success", "data": temp}


@router.get("/publicKey")
def get_public_key():
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "publicKey": "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDBT2vr+dhZElF73FJ6xiP181txKWUSNLPQQlid6DUJhGAOZblluafIdLmnUyKE8mMHhT3R+Ib3ssZcJku6Hn72yHYj/qPkCGFv0eFo7G+GJfDIUeDyalBN0QsuiE/XzPHJBuJDfRArOiWvH0BXOv5kpeXSXM8yTt5Na1jAYSiQ/wIDAQAB",
            "mockServer": "False",
        },
    }


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username, User.password == req.password).first()
    if user:
        return {"code": 200, "msg": "success", "data": {"accessToken": req.username}}
    return {"code": 500, "msg": "账户或密码不正确"}


def parse_date_str(val):
    if isinstance(val, str):
        import datetime
        try:
            return datetime.datetime.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            return datetime.datetime.strptime(val, "%Y-%m-%d %H:%M:%S").date()
    return val


@router.post("/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    try:
        patient = Patient(
            name=req.username,
            identity=req.identity,
            address=req.address,
            sex=req.sex,
            phone=req.phone,
            birthday=parse_date_str(req.birthday),
            permission="allow",
        )
        db.add(patient)
        db.flush()
        user = User(username=req.identity, password=req.password, user_role="patient")
        db.add(user)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        return {"code": 500, "msg": "用户注册失败"}


@router.post("/userInfo")
def get_user_info(req: UserInfoRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.accessToken).first()
    if not user:
        return {"code": 500, "msg": "用户不存在"}
    if user.user_role == "admin":
        permissions = ["admin"]
    elif user.user_role == "doctor":
        permissions = ["doctor"]
    elif user.user_role == "director":
        permissions = ["director", "doctor"]
    elif user.user_role == "patient":
        permissions = ["patient"]
    else:
        permissions = []
    avatar_url = "https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fc-ssl.duitang.com%2Fuploads%2Fitem%2F202006%2F07%2F20200607000651_vopye.jpg&refer=http%3A%2F%2Fc-ssl.duitang.com&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1672814873&t=b4388830c9cf3005e51d64f282b07abc"
    return {
        "code": 200,
        "msg": "success",
        "data": {"permissions": permissions, "username": user.username, "avatar": avatar_url},
    }


@router.post("/logout")
def logout():
    return {"code": 200, "msg": "success"}
