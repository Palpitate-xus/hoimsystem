"""Request-local, deny-by-default permissions bounded by existing business roles."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import and_, or_

from app.access_labels import MODULE_LABELS, permission_label
from app.access_models import AccessPolicy
from app.models import User

ROLE_LABELS = {
    "super_admin": "超级管理员",
    "admin": "管理员",
    "director": "科室主任",
    "doctor": "医生",
    "nurse": "护士",
    "pharmacist": "药师",
    "cashier": "收费员",
    "guide": "导诊员",
    "patient": "患者",
    "lab_technician": "检验技师",
    "registrar": "挂号员",
}
ESSENTIAL = {"POST /api/userInfo", "POST /api/logout", "GET /api/access/me"}


def permission_code(method, path):
    return f"{method.upper()} {path}"


@lru_cache(maxsize=1)
def permission_catalog():
    """Load the reviewed method/template inventory, never infer grants from URLs."""
    from app.ai.catalog import FEATURES

    rows = json.loads((Path(__file__).resolve().parents[1] / "rbac_matrix.json").read_text())
    items = {}
    for row in rows:
        if row["auth"] == "PUBLIC":
            continue
        code = permission_code(row["method"], row["path"])
        module = row["module"].removesuffix(".py")
        roles = list(ROLE_LABELS) if row["auth"] == "ANY" else row["auth"]
        if row["path"].startswith("/api/user/"):
            roles = ["super_admin", "admin"]
        tail = row["path"].rstrip("/").split("/")[-1]
        read = row["method"] == "GET" or tail in {"getList", "list", "search", "report", "stats", "preview", "context"}
        label = permission_label(module, row["method"], row["path"], row["function"])
        items[code] = {
            "code": code,
            "label": label,
            "module": module,
            "module_label": MODULE_LABELS.get(module, module),
            "method": row["method"],
            "path": row["path"],
            "default_roles": sorted(roles),
            "action": "read" if read else "write",
        }
    for spec in FEATURES:
        code = "AI " + spec.key
        items[code] = {
            "code": code,
            "label": spec.name,
            "module": "ai_features",
            "module_label": "AI功能",
            "method": "AI",
            "path": spec.key,
            "default_roles": sorted(set(spec.default_roles) | {"super_admin"}),
            "action": "execute",
        }
    from app.privacy import FULL_PATIENT_IDENTITY_ROLES

    fields = {
        "identity": ("完整身份证与电话", FULL_PATIENT_IDENTITY_ROLES | {"patient"}),
        "address": ("患者地址", {"super_admin", "admin", "doctor", "director", "nurse", "patient"}),
        "allergy": ("患者过敏史", {"super_admin", "admin", "doctor", "director", "nurse", "pharmacist", "patient"}),
    }
    for name, (label, roles) in fields.items():
        code = "FIELD patient_list." + name
        items[code] = {
            "code": code,
            "label": "患者列表：" + label,
            "module": "patient_fields",
            "module_label": "患者列表字段",
            "method": "FIELD",
            "path": "patient_list." + name,
            "default_roles": sorted(roles),
            "action": "read",
        }
    revision = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    return items, revision


def _policies(db, user, *, fresh=False):
    key = (user.user_id, user.user_role)
    cache = db.info.setdefault("access_policy_cache", {})
    if fresh or key not in cache:
        query = (
            db.query(AccessPolicy)
            .filter(or_(and_(AccessPolicy.kind == "role", AccessPolicy.subject_key == user.user_role), and_(AccessPolicy.kind == "user", AccessPolicy.subject_key == str(user.user_id))))
            .order_by(AccessPolicy.kind, AccessPolicy.subject_key)
            .populate_existing()
        )
        if fresh:
            query = query.with_for_update(read=True)
        rows = query.all()
        if any(row.data_scope not in {"existing", "assigned"} for row in rows):
            raise HTTPException(503, "权限数据范围配置无效，请联系管理员")
        cache[key] = {row.kind: row for row in rows}
    return cache[key]


def _decode_permissions(policy):
    if policy is None or policy.allowed_json is None:
        return None
    try:
        values = json.loads(policy.allowed_json)
        if not isinstance(values, list) or any(type(value) is not str for value in values):
            raise ValueError("Invalid permissions")
        return set(values)
    except (TypeError, ValueError) as error:
        raise HTTPException(503, "权限配置无法读取，请联系管理员") from error


def base_permissions(role):
    return {code for code, item in permission_catalog()[0].items() if role in item["default_roles"]}


def effective_permissions(db, user, *, fresh=False):
    policies = _policies(db, user, fresh=fresh)
    allowed = base_permissions(user.user_role)
    for kind in ("role", "user"):
        configured = _decode_permissions(policies.get(kind))
        if configured is not None:
            allowed.intersection_update(configured)
    return allowed


def assert_account_enabled(db, user):
    """Check current persisted disable state for login, body tokens and workers."""
    if user.user_role not in ROLE_LABELS:
        raise HTTPException(403, "账号角色无效")
    if any(policy.disabled for policy in _policies(db, user).values()):
        raise HTTPException(403, "账号已停用，请联系管理员")


def current_data_scope(db, user):
    return "assigned" if any(policy.data_scope == "assigned" for policy in _policies(db, user).values()) else "existing"


def enforce_permission(db, user, code, *, fresh=False):
    """Configured grants only narrow the original business qualification."""
    if fresh:
        _policies(db, user, fresh=True)
    assert_account_enabled(db, user)
    if code in ESSENTIAL:
        return
    if code not in effective_permissions(db, user):
        raise HTTPException(403, "没有执行此操作的权限")


def enforce_request_permissions(db, user, request):
    route = request.scope.get("route")
    if route is None:
        raise HTTPException(403, "无法确认请求权限")
    # Included routers retain the original (unprefixed) route in recent FastAPI.
    # The matched context is server-owned and supplies the actual mounted template.
    context = request.scope.get("fastapi", {}).get("effective_route_context")
    if context is not None and context.original_route is route:
        template = context.path_format
    else:
        template = route.path
        if "app" in request.scope:
            from fastapi.routing import iter_route_contexts

            matches = [item.path_format for item in iter_route_contexts(request.app.routes) if item.original_route is route]
            if len(matches) != 1:
                raise HTTPException(403, "无法确认接口挂载权限")
            template = matches[0]
    enforce_permission(db, user, permission_code(request.method, template))
    from app.access_scope import apply_patient_scope

    apply_patient_scope(db, user, current_data_scope(db, user))


def enforce_feature_permission(db, user, key, *, fresh=False):
    if fresh:
        from sqlalchemy import inspect

        state = inspect(user, raiseerr=False)
        if state is not None and state.persistent:
            current = db.query(User).filter(User.user_id == user.user_id).populate_existing().with_for_update(read=True).one_or_none()
            if current is None:
                raise HTTPException(403, "任务申请账号已不存在")
    enforce_permission(db, user, "AI " + key, fresh=fresh)
    from app.access_scope import apply_patient_scope

    apply_patient_scope(db, user, current_data_scope(db, user))


def authorization_snapshot(db, user):
    codes = effective_permissions(db, user)
    policies = _policies(db, user)
    version = hashlib.sha256((user.user_role + ":" + ":".join(f"{kind}:{policy.version}" for kind, policy in sorted(policies.items())) + ":" + permission_catalog()[1]).encode()).hexdigest()
    route_file = Path(__file__).with_name("access_route_map.json")
    mapping = json.loads(route_file.read_text()) if route_file.exists() else {}
    denied = [name for name, requirements in mapping.items() if requirements and not any(code in codes for code in requirements)]
    return {"authorization": {"version": version, "permission_codes": sorted(codes), "denied_route_names": denied, "data_scope": current_data_scope(db, user)}}


def can_manage(actor, role):
    return actor.user_role == "super_admin" and role != "super_admin" or actor.user_role == "admin" and role not in {"admin", "super_admin"}
