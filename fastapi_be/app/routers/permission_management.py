"""Administrator configuration of bounded role and account permissions."""

import datetime
import json
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access_control import ROLE_LABELS, _decode_permissions, authorization_snapshot, base_permissions, can_manage, permission_catalog
from app.access_models import AccessPolicy, AccessPolicyAudit, AccessPolicyGuard
from app.database import get_db
from app.dependencies import ADMIN_ROLES, get_current_user, require_roles
from app.event_bus import publish_event
from app.models import User

router = APIRouter()


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: StrictInt = Field(ge=0)
    allowed_permissions: list[str] | None = Field(default=None, max_length=2048)
    data_scope: Literal["existing", "assigned"] = "existing"
    disabled: StrictBool = False


def _subject(db, kind, key):
    if kind == "role" and key in ROLE_LABELS:
        return key, ROLE_LABELS[key], None
    if kind == "user" and len(key) <= 10 and key.isascii() and key.isdecimal() and key == str(int(key)) and 0 < int(key) < 2**31:
        user = db.get(User, int(key))
        if user:
            return user.user_role, user.username, user
    raise HTTPException(404, "角色或用户不存在")


def _view(db, actor, kind, key):
    role, label, user = _subject(db, kind, key)
    policy = db.get(AccessPolicy, (kind, key))
    available = base_permissions(role)
    role_policy = None
    if user:
        role_policy = db.get(AccessPolicy, ("role", role))
        role_config = _decode_permissions(role_policy)
        if role_config is not None:
            available.intersection_update(role_config)
    configured = _decode_permissions(policy)
    effective = available if configured is None else available & configured
    scoped = any(item is not None and item.data_scope == "assigned" for item in (policy, role_policy))
    return {
        "kind": kind,
        "key": key,
        "label": label,
        "role": role,
        "version": policy.version if policy else 0,
        "allowed_permissions": None if configured is None else sorted(configured),
        "available_permissions": sorted(available),
        "effective_permissions": sorted(effective),
        "data_scope": policy.data_scope if policy else "existing",
        "effective_data_scope": "assigned" if scoped else "existing",
        "disabled": bool(policy.disabled) if policy else False,
        "editable": can_manage(actor, role),
    }


@router.get("/access/me")
def get_my_access(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"code": 200, "data": authorization_snapshot(db, current_user)["authorization"]}


@router.get("/access/catalog")
def get_access_catalog(current_user: User = Depends(require_roles(*ADMIN_ROLES))):
    items, revision = permission_catalog()
    scopes = [{"value": "existing", "label": "既有业务范围"}, {"value": "assigned", "label": "本人接诊患者"}]
    roles = [{"key": key, "label": label, "manageable": can_manage(current_user, key), "scope_options": scopes if key in {"doctor", "director"} else scopes[:1]} for key, label in ROLE_LABELS.items()]
    return {"code": 200, "data": {"roles": roles, "permissions": list(items.values()), "actor": {"user_id": current_user.user_id, "role": current_user.user_role}, "catalog_revision": revision}}


@router.get("/access/policies/{kind}/{key}")
def get_access_policy(kind: Literal["role", "user"], key: str, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    return {"code": 200, "data": _view(db, current_user, kind, key)}


@router.put("/access/policies/{kind}/{key}")
def update_access_policy(
    kind: Literal["role", "user"], key: str, req: PolicyUpdate, background_tasks: BackgroundTasks, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)
):
    role, _label, target = _subject(db, kind, key)
    authenticated = (current_user.username, current_user.user_role, current_user.token_invalid_before)
    if db.query(AccessPolicyGuard).filter_by(id=1).with_for_update().one_or_none() is None:
        raise HTTPException(503, "权限配置锁未初始化")
    ids = {current_user.user_id} | ({target.user_id} if target else set())
    locked = db.query(User).filter(User.user_id.in_(ids)).order_by(User.user_id).populate_existing().with_for_update().all()
    actor = next((u for u in locked if u.user_id == current_user.user_id), None)
    if not actor or (actor.username, actor.user_role, actor.token_invalid_before) != authenticated or not can_manage(actor, role):
        raise HTTPException(403, "没有配置此角色或用户权限的权限")
    if target and (not any(item.user_id == target.user_id for item in locked) or target.user_role != role):
        raise HTTPException(409, "用户角色已变更，请重新加载")
    from app.access_control import enforce_permission

    enforce_permission(db, actor, "PUT /api/access/policies/{kind}/{key}", fresh=True)
    before = _view(db, actor, kind, key)
    allowed = req.allowed_permissions
    available = set(before["available_permissions"])
    if allowed is not None and (len(allowed) != len(set(allowed)) or not set(allowed) <= available):
        raise HTTPException(422, "所选权限超出此角色的可授权范围")
    if req.data_scope == "assigned" and role not in {"doctor", "director"}:
        raise HTTPException(422, "此角色不能使用本人接诊患者范围")
    if kind == "role" and req.disabled:
        raise HTTPException(422, "请在用户权限中停用具体账号")
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    values = {
        "allowed_json": None if allowed is None else json.dumps(sorted(allowed), ensure_ascii=False),
        "data_scope": req.data_scope,
        "disabled": req.disabled,
        "updated_at": now,
        "version": req.expected_version + 1,
    }
    try:
        if req.expected_version == 0:
            db.add(AccessPolicy(kind=kind, subject_key=key, **values))
            db.flush()
        else:
            changed = db.query(AccessPolicy).filter(AccessPolicy.kind == kind, AccessPolicy.subject_key == key, AccessPolicy.version == req.expected_version).update(values, synchronize_session=False)
            if changed != 1:
                raise HTTPException(409, "权限已被其他管理员修改，请重新加载")
        detail = {
            "before": {k: before[k] for k in ("allowed_permissions", "data_scope", "disabled")},
            "after": {"allowed_permissions": allowed, "data_scope": req.data_scope, "disabled": req.disabled},
        }
        db.add(AccessPolicyAudit(actor_id=actor.user_id, actor=actor.username, subject=f"{kind}:{key}", action="更新权限", detail=json.dumps(detail, ensure_ascii=False)))
        if target and req.disabled:
            target.token_invalid_before = now
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "权限已被其他管理员修改，请重新加载") from error
    db.info.pop("access_policy_cache", None)
    db.expire_all()
    background_tasks.add_task(
        publish_event,
        "access.policy_changed",
        {"kind": kind, "key": key, "version": req.expected_version + 1},
        audience_roles=[role] if kind == "role" else [],
        audience_user_ids=[target.user_id] if target else [],
    )
    return {"code": 200, "msg": "权限已保存", "data": _view(db, actor, kind, key)}


@router.get("/access/audit")
def get_access_audit(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    query = db.query(AccessPolicyAudit)
    total = query.count()
    rows = query.order_by(AccessPolicyAudit.created_at.desc(), AccessPolicyAudit.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "code": 200,
        "data": {"total": total, "list": [{"id": r.id, "actor": r.actor, "subject": r.subject, "action": r.action, "created_at": r.created_at.isoformat(), "detail": r.detail} for r in rows]},
    }
