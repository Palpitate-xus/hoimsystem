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
import json
import os
import sys
from collections import OrderedDict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

ALL_ROLES = ["admin", "super_admin", "director", "doctor", "nurse", "cashier", "pharmacist", "guide", "patient", "lab_technician", "registrar"]
AUTH_DEPENDENCIES = {"get_current_user", "get_event_identity"}


def read_role_groups(path: Path, names: tuple[str, ...], known_groups: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    """Read actual role constants without importing settings, databases or routers."""
    assignments = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
    resolving = set()

    def value(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id in assignments and node.id not in resolving:
            resolving.add(node.id)
            try:
                return value(assignments[node.id])
            finally:
                resolving.remove(node.id)
        if isinstance(node, ast.Name) and known_groups and node.id in known_groups:
            return set(known_groups[node.id])
        if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
            result = set()
            for item in node.elts:
                if isinstance(item, ast.Starred):
                    group = value(item.value)
                    if not isinstance(group, set):
                        raise ValueError(f"{path}: starred role constant is not a set")
                    result.update(group)
                else:
                    role = value(item)
                    if not isinstance(role, str):
                        raise ValueError(f"{path}: role constant is not a string")
                    result.add(role)
            return result
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            left, right = value(node.left), value(node.right)
            if isinstance(left, set) and isinstance(right, set):
                return left | right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"set", "frozenset"} and len(node.args) == 1 and not node.keywords:
            result = value(node.args[0])
            if isinstance(result, set):
                return result
        raise ValueError(f"{path}: role constants must be statically resolvable")

    groups = {}
    for name in names:
        group = value(ast.Name(id=name))
        if not isinstance(group, set) or not group or not group <= set(ALL_ROLES):
            raise ValueError(f"{path}: invalid role group {name}")
        groups[name] = group
    return groups


ROLE_GROUPS = read_role_groups(
    BACKEND / "app/dependencies.py",
    (
        "ADMIN_ROLES",
        "NOTICE_ROLES",
        "CLINICAL_ROLES",
        "CASHIER_ROLES",
        "PHARMACY_ROLES",
        "NURSING_ROLES",
        "GUIDE_ROLES",
        "LAB_ROLES",
        "REGISTRAR_ROLES",
    ),
)
ROLE_GROUPS.update(read_role_groups(BACKEND / "app/inpatient_observations.py", ("OBSERVATION_ROLES",)))
ROLE_GROUPS.update(read_role_groups(BACKEND / "app/inpatient_gcs.py", ("READ_ROLES",), ROLE_GROUPS))
ROLE_GROUPS.update(read_role_groups(BACKEND / "app/inpatient_support_common.py", ("SUPPORT_ROLES",)))
ROLE_GROUPS.update(read_role_groups(BACKEND / "app/ai/observation_windows.py", ("WINDOW_ROLES",)))
ROLE_GROUPS.update(read_role_groups(BACKEND / "app/inpatient_laboratory.py", ("LAB_SOURCE_ROLES", "LAB_READ_ROLES")))
ROLE_GROUPS.update(read_role_groups(BACKEND / "app/ai/lab_mappings.py", ("MAPPING_ROLES",)))
ROLE_GROUPS.update(read_role_groups(BACKEND / "app/ai/risk_rule_profiles.py", ("PROFILE_ROLES",)))
ROLE_GROUPS.update(read_role_groups(BACKEND / "app/ai/news2_sources.py", ("ASSESSMENT_ROLES",)))
# Preserve the existing matrix's two combined role groups.
ROLE_GROUPS["INPATIENT_FINANCE_ROLES"] = ROLE_GROUPS["CASHIER_ROLES"] | ROLE_GROUPS["NURSING_ROLES"]
ROLE_GROUPS["OPERATE_ROLES"] = ROLE_GROUPS["CLINICAL_ROLES"] | ROLE_GROUPS["NURSING_ROLES"]


def router_prefixes(tree: ast.Module, path: str) -> dict[str, str]:
    """Only literal APIRouter prefixes can safely be added to source paths."""
    prefixes = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        constructor = call.func.id if isinstance(call.func, ast.Name) else call.func.attr if isinstance(call.func, ast.Attribute) else None
        if constructor != "APIRouter":
            continue
        prefix = ""
        for keyword in call.keywords:
            if keyword.arg is None or (keyword.arg == "prefix" and not (isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str))):
                raise ValueError(f"{path}:{node.lineno}: APIRouter prefix must be literal; dynamic configuration cannot be guessed")
            if keyword.arg == "prefix":
                prefix = keyword.value.value
        if prefix and (not prefix.startswith("/") or prefix.endswith("/")):
            raise ValueError(f"{path}:{node.lineno}: invalid APIRouter prefix")
        for target in node.targets:
            if isinstance(target, ast.Name):
                prefixes[target.id] = prefix
    return prefixes


def mounted_router_prefixes(path: Path) -> dict[str, str]:
    """Resolve the application's literal mounts, including aliased router imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "app.routers":
            for name in node.names:
                if name.name == "*":
                    raise ValueError(f"{path}:{node.lineno}: router imports must be explicit")
                modules[name.asname or name.name] = name.name
    top_level_calls = {id(node.value) for node in tree.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)}
    mounts = {}
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or call.func.attr != "include_router":
            continue
        receiver = call.func.value
        if id(call) not in top_level_calls or not isinstance(receiver, ast.Name) or receiver.id != "app":
            raise ValueError(f"{path}:{call.lineno}: nested or dynamic router mounts cannot be guessed")
        if len(call.args) != 1:
            raise ValueError(f"{path}:{call.lineno}: include_router requires one explicit router")
        router = call.args[0]
        if not isinstance(router, ast.Attribute) or router.attr != "router" or not isinstance(router.value, ast.Name) or router.value.id not in modules:
            raise ValueError(f"{path}:{call.lineno}: mounted router module cannot be resolved")
        module = modules[router.value.id] + ".py"
        prefix = ""
        for keyword in call.keywords:
            if keyword.arg is None or (keyword.arg == "prefix" and not (isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str))):
                raise ValueError(f"{path}:{call.lineno}: include_router prefix must be literal; dynamic configuration cannot be guessed")
            if keyword.arg == "prefix":
                prefix = keyword.value.value
        if prefix and (not prefix.startswith("/") or prefix.endswith("/")):
            raise ValueError(f"{path}:{call.lineno}: invalid include_router prefix")
        if module in mounts:
            raise ValueError(f"{path}:{call.lineno}: multiple mounts of {module} require explicit inventory support")
        mounts[module] = prefix
    return mounts


class StaticRoles:
    """Resolve only literal role expressions and their actual source imports.

    No application module is imported or executed. Rebound names, dynamic
    expressions and imports outside this backend's app package are ambiguous
    and fail rather than broadening a route to any authenticated user.
    """

    def __init__(self, path: Path, modules=None):
        self.path = path.resolve()
        self.modules = modules if modules is not None else {}
        self.modules[self.path] = self
        self.bindings = {}
        self.resolving = set()
        self.tree = ast.parse(self.path.read_text(encoding="utf-8"))
        for statement in self.tree.body:
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        self.bind(target.id, ("value", statement.value))
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                self.bind(statement.target.id, ("value", statement.value))
            elif isinstance(statement, ast.ImportFrom):
                for name in statement.names:
                    self.bind(name.asname or name.name, ("from", (statement.module, statement.level, name.name)))
            elif isinstance(statement, ast.Import):
                for name in statement.names:
                    self.bind(name.asname or name.name.split(".")[0], ("module", name.name if name.asname else name.name.split(".")[0]))
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.bind(statement.name, ("dynamic", None))
            else:
                # A conditional/loop/try rebinding is not an unconditional
                # source constant. Do not silently keep an earlier import.
                for nested in ast.walk(statement):
                    if isinstance(nested, ast.Name) and isinstance(nested.ctx, (ast.Store, ast.Del)):
                        self.bind(nested.id, ("dynamic", None))
                    elif isinstance(nested, ast.ImportFrom):
                        for name in nested.names:
                            self.bind(name.asname or name.name, ("dynamic", None))
                    elif isinstance(nested, ast.Import):
                        for name in nested.names:
                            self.bind(name.asname or name.name.split(".")[0], ("dynamic", None))

    def bind(self, name, definition):
        self.bindings.setdefault(name, []).append(definition)

    def definition(self, name):
        definitions = self.bindings.get(name, [])
        if len(definitions) != 1:
            raise ValueError(f"{self.path}: role name {name!r} must have one explicit static binding")
        return definitions[0]

    def module(self, name):
        if not isinstance(name, str) or not name.startswith("app.") or any(not part.isidentifier() for part in name.split(".")):
            raise ValueError(f"{self.path}: role imports must name an explicit app module")
        relative = BACKEND.joinpath(*name.split("."))
        source = relative.with_suffix(".py")
        if not source.is_file():
            source = relative / "__init__.py"
        if not source.is_file() or not source.resolve().is_relative_to(BACKEND.resolve()):
            raise ValueError(f"{self.path}: role import module cannot be resolved: {name}")
        source = source.resolve()
        return self.modules.get(source) or StaticRoles(source, self.modules)

    def named(self, name):
        if name in self.resolving:
            raise ValueError(f"{self.path}: cyclic role constant {name!r}")
        self.resolving.add(name)
        try:
            kind, value = self.definition(name)
            if kind == "value":
                return self.value(value)
            if kind == "from":
                module, level, symbol = value
                if level == 0 and symbol != "*":
                    return self.module(module).named(symbol)
            raise ValueError(f"{self.path}: role constant {name!r} is not a static value")
        finally:
            self.resolving.remove(name)

    def value(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return self.named(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            kind, binding = self.definition(node.value.id)
            if kind == "from":
                module, level, symbol = binding
                if level == 0 and symbol != "*":
                    return self.module(f"{module}.{symbol}").named(node.attr)
            if kind == "module":
                return self.module(binding).named(node.attr)
        if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
            result = set()
            for item in node.elts:
                value = self.value(item.value if isinstance(item, ast.Starred) else item)
                if isinstance(item, ast.Starred) and isinstance(value, set):
                    result.update(value)
                elif not isinstance(item, ast.Starred) and isinstance(value, str):
                    result.add(value)
                else:
                    raise ValueError(f"{self.path}: role collection members must be strings or explicit starred sets")
            return result
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            left, right = self.value(node.left), self.value(node.right)
            if isinstance(left, set) and isinstance(right, set):
                return left | right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"set", "frozenset"} and node.func.id not in self.bindings and len(node.args) <= 1 and not node.keywords:
            value = self.value(node.args[0]) if node.args else set()
            if isinstance(value, set):
                return value
        raise ValueError(f"{self.path}: role expression must be statically resolvable: {ast.unparse(node) if node is not None else 'None'}")


def _resolve_decorator_roles(call: ast.Call, source: StaticRoles) -> set[str]:
    roles: set[str] = set()
    if call.keywords or not call.args:
        raise ValueError(f"{source.path}:{call.lineno}: require_roles needs explicit positional role arguments")
    for argument in call.args:
        value = source.value(argument.value if isinstance(argument, ast.Starred) else argument)
        if isinstance(argument, ast.Starred) and isinstance(value, set):
            roles.update(value)
        elif not isinstance(argument, ast.Starred) and isinstance(value, str):
            roles.add(value)
        else:
            raise ValueError(f"{source.path}:{call.lineno}: require_roles arguments must be strings or explicit starred sets")
    if not roles or not roles <= set(ALL_ROLES):
        raise ValueError(f"{source.path}:{call.lineno}: require_roles contains empty or unknown roles")
    return roles


def analyze_router(path: str, mount_prefix: str = "/api") -> list[dict]:
    source = StaticRoles(Path(path))
    tree = source.tree
    prefixes = router_prefixes(tree, path)
    module = os.path.basename(path)
    endpoints = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        method = route_path = None
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in ("get", "post", "put", "delete", "patch"):
                method = dec.func.attr.upper()
                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                    receiver = dec.func.value
                    if not isinstance(receiver, ast.Name) or receiver.id not in prefixes:
                        raise ValueError(f"{path}:{node.lineno}: route owner has no statically known APIRouter prefix")
                    route_path = prefixes[receiver.id] + dec.args[0].value
        if not method or route_path is None:
            continue

        authenticated = False
        restricted_roles = []
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
            for sub in ast.walk(default):
                if isinstance(sub, ast.Name) and sub.id in AUTH_DEPENDENCIES:
                    authenticated = True
                elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "require_roles":
                    restricted_roles.append(_resolve_decorator_roles(sub, source))
        if len(restricted_roles) > 1:
            raise ValueError(f"{path}:{node.lineno}: multiple require_roles guards need an explicit dependency model")
        auth = restricted_roles[0] if restricted_roles else "ANY" if authenticated else "PUBLIC"

        endpoints.append(
            {
                "module": module,
                "method": method,
                "path": f"{mount_prefix}{route_path}",
                "function": node.name,
                "auth": sorted(auth) if isinstance(auth, set) else auth,
            }
        )
    return endpoints


def collect_endpoints() -> list[dict]:
    all_eps = []
    for module, prefix in sorted(mounted_router_prefixes(BACKEND / "app/main.py").items()):
        path = BACKEND / "app/routers" / module
        if not path.is_file():
            raise ValueError(f"{path}: mounted router source is missing")
        all_eps.extend(analyze_router(str(path), mount_prefix=prefix))
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

    try:
        eps = collect_endpoints()
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1
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
