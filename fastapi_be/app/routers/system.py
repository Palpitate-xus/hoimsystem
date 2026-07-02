import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, get_current_user, require_roles
from app.models import Config, Dict, OperationLog, User
from app.schemas import (
    ConfigUpdateRequest,
    DictCreateRequest,
    DictDeleteRequest,
    DictListRequest,
    DictUpdateRequest,
    LogListRequest,
)

router = APIRouter()


@router.post("/log/getList")
def get_log_list(req: LogListRequest, keyword: str | None = None, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    query = db.query(OperationLog)
    if req.user_id:
        query = query.filter(OperationLog.user_id == req.user_id)
    if req.username:
        query = query.filter(OperationLog.username.like(f"%{req.username}%"))
    if req.role:
        query = query.filter(OperationLog.role == req.role)
    if req.action:
        query = query.filter(OperationLog.action.like(f"%{req.action}%"))
    if req.target:
        query = query.filter(OperationLog.target.like(f"%{req.target}%"))
    if req.result:
        query = query.filter(OperationLog.result == req.result)
    if req.method:
        query = query.filter(OperationLog.method == req.method)
    if req.ip:
        query = query.filter(OperationLog.ip.like(f"%{req.ip}%"))
    if req.start_time:
        query = query.filter(OperationLog.create_time >= req.start_time)
    if req.end_time:
        query = query.filter(OperationLog.create_time <= req.end_time)
    if keyword:
        kw = f"%{keyword}%"
        query = query.filter(
            OperationLog.username.like(kw)
            | OperationLog.action.like(kw)
            | OperationLog.target.like(kw)
            | OperationLog.path.like(kw)
            | OperationLog.detail.like(kw)
        )

    total = query.count()
    logs = query.order_by(OperationLog.create_time.desc()).offset((req.page - 1) * req.page_size).limit(req.page_size).all()
    data = []
    for item in logs:
        data.append(
            {
                "log_id": item.log_id,
                "user_id": item.user_id,
                "username": item.username,
                "role": item.role,
                "action": item.action,
                "target": item.target,
                "detail": item.detail or "",
                "result": item.result,
                "status_code": item.status_code,
                "method": item.method or "",
                "path": item.path or "",
                "ip": item.ip,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None),
            }
        )
    return {"code": 200, "msg": "success", "data": {"list": data, "total": total}}


@router.get("/log/stats")
def get_log_stats(current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    """审计统计面板。"""
    from sqlalchemy import func

    total = db.query(OperationLog).count()
    failed = db.query(OperationLog).filter(OperationLog.result == "失败").count()
    # 最近 24h
    since = datetime.datetime.now() - datetime.timedelta(hours=24)
    last_24h = db.query(OperationLog).filter(OperationLog.create_time >= since).count()
    # Top 5 操作最多的用户
    top_users = (
        db.query(OperationLog.username, func.count(OperationLog.log_id).label("cnt"))
        .group_by(OperationLog.username)
        .order_by(func.count(OperationLog.log_id).desc())
        .limit(5)
        .all()
    )
    # Top 5 操作类型
    top_actions = (
        db.query(OperationLog.action, func.count(OperationLog.log_id).label("cnt"))
        .group_by(OperationLog.action)
        .order_by(func.count(OperationLog.log_id).desc())
        .limit(5)
        .all()
    )
    return {
        "code": 200, "msg": "success",
        "data": {
            "total": total,
            "failed": failed,
            "success_rate": f"{round((total - failed) / total * 100, 1)}%" if total else "N/A",
            "last_24h": last_24h,
            "top_users": [{"username": u, "count": c} for u, c in top_users],
            "top_actions": [{"action": a, "count": c} for a, c in top_actions],
        },
    }


@router.post("/dict/getList")
def get_dict_list(req: DictListRequest, keyword: str | None = None, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    dicts = db.query(Dict).filter(Dict.dict_type == req.dict_type).order_by(Dict.sort_order).all()
    data = []
    for item in dicts:
        data.append(
            {
                "dict_id": item.dict_id,
                "dict_type": item.dict_type,
                "dict_code": item.dict_code,
                "dict_value": item.dict_value,
                "sort_order": item.sort_order,
                "status": item.status,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/dict/create")
def create_dict(req: DictCreateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    d = Dict(
        dict_type=req.dict_type,
        dict_code=req.dict_code,
        dict_value=req.dict_value,
        sort_order=req.sort_order,
        status=0,
    )
    db.add(d)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/dict/update")
def update_dict(req: DictUpdateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    d = db.query(Dict).filter(Dict.dict_id == req.dict_id).first()
    if not d:
        return {"code": 500, "msg": "字典项不存在"}
    d.dict_code = req.dict_code
    d.dict_value = req.dict_value
    d.sort_order = req.sort_order
    db.add(d)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/dict/delete")
def delete_dict(req: DictDeleteRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    d = db.query(Dict).filter(Dict.dict_id == req.dict_id).first()
    if not d:
        return {"code": 500, "msg": "字典项不存在"}
    db.delete(d)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/config/getList")
def get_config_list(keyword: str | None = None, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    configs = db.query(Config).all()
    data = []
    for item in configs:
        data.append(
            {
                "config_key": item.config_key,
                "config_value": item.config_value,
                "description": item.description,
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/config/update")
def update_config(req: ConfigUpdateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    config = db.query(Config).filter(Config.config_key == req.config_key).first()
    if not config:
        return {"code": 500, "msg": "配置项不存在"}
    config.config_value = req.config_value
    db.add(config)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/message/send")
def send_message(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    """发送消息（模拟短信/站内信）"""
    from app.models import Message

    msg = Message(
        recipient_id=req.get("recipient_id"),
        title=req.get("title", ""),
        content=req.get("content", ""),
        msg_type=req.get("msg_type", "app"),
        is_read=0,
        create_time=datetime.datetime.now(),
    )
    db.add(msg)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/message/getList")
def get_message_list(current_user: User = Depends(get_current_user), keyword: str | None = None, db: Session = Depends(get_db)):
    from app.models import Message

    query = db.query(Message).filter(Message.recipient_id == current_user.user_id).order_by(Message.create_time.desc())
    messages = query.all()
    data = []
    for item in messages:
        data.append(
            {
                "message_id": item.message_id,
                "title": item.title,
                "content": item.content,
                "msg_type": item.msg_type,
                "is_read": item.is_read,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None),
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/message/read")
def read_message(req: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import Message

    msg = db.query(Message).filter(Message.message_id == req.get("message_id"), Message.recipient_id == current_user.user_id).first()
    if msg:
        msg.is_read = 1
        db.add(msg)
        db.commit()
    return {"code": 200, "msg": "success"}
