#!/usr/bin/env python3
"""从后端源码自动生成 RBAC 访问矩阵文档与机器可读清单。

用法（在 fastapi_be/ 下运行）：
    python3 scripts/generate_rbac_matrix.py            # 生成 doc/api-rbac-matrix.md 与 rbac_matrix.json
    python3 scripts/generate_rbac_matrix.py --check    # CI 漂移检测：代码与 json 不一致时退出码 1

解析方式：AST 遍历 app/routers/*.py 的每个路由函数，
读取其默认参数中的 Depends(get_current_user / require_roles(...)) 依赖。
"""
import argparse
import ast
import glob
import json
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.dependencies import (  # noqa: E402
    ADMIN_ROLES,
    CASHIER_ROLES,
    CLINICAL_ROLES,
    GUIDE_ROLES,
    LAB_ROLES,
    NOTICE_ROLES,
    NURSING_ROLES,
    PHARMACY_ROLES,
    REGISTRAR_ROLES,
)

ALL_ROLES = ["admin", "super_admin", "director", "doctor", "nurse", "cashier", "pharmacist", "guide", "patient", "lab_technician", "registrar"]

ROLE_GROUPS = {
    "ADMIN_ROLES": set(ADMIN_ROLES),
    "NOTICE_ROLES": set(NOTICE_ROLES),
    "CLINICAL_ROLES": set(CLINICAL_ROLES),
    "CASHIER_ROLES": set(CASHIER_ROLES),
    "PHARMACY_ROLES": set(PHARMACY_ROLES),
    "NURSING_ROLES": set(NURSING_ROLES),
    "GUIDE_ROLES": set(GUIDE_ROLES),
    "LAB_ROLES": set(LAB_ROLES),
    "REGISTRAR_ROLES": set(REGISTRAR_ROLES),
}


def _resolve_decorator_roles(call: ast.Call) -> set[str] | None:
    """把 require_roles(*A, *B, 'x') 的参数解析为具体角色集合。"""
    roles: set[str] = set()
    for arg in call.args:
        if isinstance(arg, ast.Starred):
            name = arg.value.id if isinstance(arg.value, ast.Name) else None
            if name in ROLE_GROUPS:
                roles |= ROLE_GROUPS[name]
            else:
                return None  # 未知角色组，按 any-authenticated 处理
        elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            roles.add(arg.value)
    return roles


def analyze_router(path: str) -> list[dict]:
    tree = ast.parse(open(path).read())
    module = os.path.basename(path)
    endpoints = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        method = route_path = None
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in ("get", "post", "put", "delete", "patch"):
                method = dec.func.attr.upper()
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    route_path = dec.args[0].value
        if not method or route_path is None:
            continue

        auth = "PUBLIC"
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
            found = None
            for sub in ast.walk(default):
                if isinstance(sub, ast.Name) and sub.id == "get_current_user":
                    found = "ANY"
                elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "require_roles":
                    roles = _resolve_decorator_roles(sub)
                    found = roles if roles else "ANY"
            if found is not None:
                auth = found
                break

        endpoints.append(
            {
                "module": module,
                "method": method,
                "path": f"/api{route_path}",
                "function": node.name,
                "auth": sorted(auth) if isinstance(auth, set) else auth,
            }
        )
    return endpoints


def collect_endpoints() -> list[dict]:
    all_eps = []
    for f in sorted(glob.glob("app/routers/*.py")):
        if f.endswith("__init__.py"):
            continue
        all_eps.extend(analyze_router(f))
    return all_eps


def render_markdown(eps: list[dict]) -> str:
    lines = [
        "# HOIMSystem API 角色访问矩阵 (RBAC Matrix)",
        "",
        "> 由 `fastapi_be/scripts/generate_rbac_matrix.py` 从源码自动生成，请勿手改。",
        "> `✓`=可访问 | `PUBLIC`=无需登录 | 留空=不可访问",
        "",
        f"共 **{len(eps)}** 个接口（PUBLIC {sum(1 for e in eps if e['auth'] == 'PUBLIC')} 个 / 需登录 {sum(1 for e in eps if e['auth'] != 'PUBLIC')} 个）。",
        "",
    ]
    by_module = OrderedDict()
    for e in eps:
        by_module.setdefault(e["module"], []).append(e)

    header = "| 方法 | 路径 | " + " | ".join(ALL_ROLES) + " | PUBLIC |"
    sep = "|------|------|" + "|".join(["------"] * len(ALL_ROLES)) + "|------|"

    for module, items in by_module.items():
        lines.append(f"\n### `{module}`\n")
        lines.append(header)
        lines.append(sep)
        for e in items:
            cells = []
            if e["auth"] == "PUBLIC":
                cells = [""] * len(ALL_ROLES) + ["PUBLIC"]
            elif e["auth"] == "ANY":
                cells = ["✓"] * len(ALL_ROLES) + [""]
            else:
                allowed = set(e["auth"])
                cells = ["✓" if r in allowed else "" for r in ALL_ROLES] + [""]
            lines.append(f"| {e['method']} | `{e['path']}` | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="CI 模式：与 rbac_matrix.json 比对，漂移则失败")
    args = parser.parse_args()

    eps = collect_endpoints()
    doc_dir = os.path.join(os.path.dirname(__file__), "..", "..", "doc")
    json_path = os.path.join(os.path.dirname(__file__), "..", "rbac_matrix.json")

    if args.check:
        if not os.path.exists(json_path):
            print("FAIL: rbac_matrix.json 不存在，请先运行生成脚本并提交")
            return 1
        committed = json.load(open(json_path))
        if committed != eps:
            current = {(e["method"], e["path"]): e["auth"] for e in eps}
            old = {(e["method"], e["path"]): e["auth"] for e in committed}
            for k in sorted(set(current) - set(old)):
                print(f"  + {k[0]} {k[1]} -> {current[k]}")
            for k in sorted(set(old) - set(current)):
                print(f"  - {k[0]} {k[1]} (was {old[k]})")
            for k in sorted(set(current) & set(old)):
                if current[k] != old[k]:
                    print(f"  ~ {k[0]} {k[1]}: {old[k]} -> {current[k]}")
            print("FAIL: RBAC 矩阵与代码不一致，请重新运行 scripts/generate_rbac_matrix.py 并提交")
            return 1
        print(f"OK: RBAC 矩阵与代码一致（{len(eps)} 个接口）")
        return 0

    os.makedirs(doc_dir, exist_ok=True)
    md = render_markdown(eps)
    with open(os.path.join(doc_dir, "api-rbac-matrix.md"), "w") as f:
        f.write(md)
    with open(json_path, "w") as f:
        json.dump(eps, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"生成 {len(eps)} 个接口 -> doc/api-rbac-matrix.md, fastapi_be/rbac_matrix.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
