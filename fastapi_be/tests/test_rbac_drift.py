"""RBAC 矩阵漂移检测。

防止 rbac_matrix.json（及由其生成的 doc/api-rbac-matrix.md）与代码脱节：
任何路由的鉴权依赖变更后，必须重新运行 scripts/generate_rbac_matrix.py 并提交。
审计发现旧版矩阵把若干越权漏洞"合法化"（标 PUBLIC/全角色），此测试确保不再发生。
"""

import inspect
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "generate_rbac_matrix.py")


def test_rbac_matrix_matches_code():
    result = subprocess.run(
        [sys.executable, SCRIPT, "--check"],
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, (
        f"RBAC 矩阵与代码不一致:\n{result.stdout}\n{result.stderr}\n请运行: python3 scripts/generate_rbac_matrix.py 并提交更新后的 doc/api-rbac-matrix.md 与 fastapi_be/rbac_matrix.json"
    )


def test_no_known_vulnerable_patterns_in_matrix():
    """回归：此前审计发现的高危越权模式不得再现。"""
    json_path = os.path.join(os.path.dirname(__file__), "..", "rbac_matrix.json")
    eps = {(e["method"], e["path"]): e["auth"] for e in json.load(open(json_path))}

    # 这些接口曾完全无认证泄露 PHI
    for key in [
        ("GET", "/api/surgeryApplication/getList"),
        ("GET", "/api/surgerySchedule/getList"),
        ("GET", "/api/consumable/getList"),
    ]:
        assert key not in eps or eps[key] != "PUBLIC", f"{key} 不得为 PUBLIC（曾泄露全院 PHI）"

    # 审批/资金/管理类接口不得是任意登录用户
    admin_only_prefixes = ("/api/backup/", "/api/log/", "/api/monitor/", "/api/dataImportExport/export")
    for (method, path), auth in eps.items():
        if path.startswith(admin_only_prefixes):
            assert auth not in ("PUBLIC", "ANY"), f"{method} {path} 必须限制管理员角色"


@pytest.fixture(scope="module")
def generator():
    return runpy.run_path(SCRIPT)


@pytest.mark.parametrize("module", ["inpatient_observations", "ai_observation_windows"])
def test_observation_matrix_matches_real_mounted_paths_and_role_guards(module, generator):
    """Use actual mounted routes and closure roles, not a second invented role list."""
    from fastapi.routing import APIRoute

    from app.dependencies import get_current_user, require_roles
    from app.main import app

    def dependencies(dependant):
        for child in dependant.dependencies:
            yield child.call
            yield from dependencies(child)

    mounted = {(method, route.path): route for route in app.routes if isinstance(route, APIRoute) and route.endpoint.__module__ == f"app.routers.{module}" for method in route.methods}
    generated = {(item["method"], item["path"]): item for item in generator["collect_endpoints"]() if item["module"] == f"{module}.py"}
    assert mounted, "测试必须覆盖实际主应用挂载路由"
    assert generated.keys() == mounted.keys()
    committed = {(item["method"], item["path"]): item for item in json.loads((Path(SCRIPT).parents[1] / "rbac_matrix.json").read_text()) if item["module"] == f"{module}.py"}
    assert committed == generated
    for key, route in mounted.items():
        actual = list(dependencies(route.dependant))
        guards = [
            call for call in actual if getattr(call, "__module__", None) == require_roles.__module__ and getattr(call, "__qualname__", None) == f"{require_roles.__qualname__}.<locals>._require_roles"
        ]
        assert len(guards) == 1, f"{key}: expected one real require_roles guard"
        assert get_current_user in actual, f"{key}: missing authentication dependency"
        actual_roles = inspect.getclosurevars(guards[0]).nonlocals["allowed_roles"]
        assert generated[key]["auth"] == sorted(actual_roles), key


def test_observation_groups_come_from_real_module_constants(generator):
    from app.ai.observation_windows import WINDOW_ROLES
    from app.inpatient_observations import OBSERVATION_ROLES

    assert generator["ROLE_GROUPS"]["WINDOW_ROLES"] == set(WINDOW_ROLES)
    assert generator["ROLE_GROUPS"]["OBSERVATION_ROLES"] == set(OBSERVATION_ROLES)


@pytest.mark.parametrize(
    "declaration, expected",
    [
        ("router = APIRouter()", "/api/points"),
        ('router = APIRouter(prefix="/inpatient-observations")', "/api/inpatient-observations/points"),
        ('source = APIRouter(prefix="/two"); router = APIRouter(prefix="/one")', "/api/one/points"),
    ],
)
def test_literal_router_prefix_is_bound_to_decorator_owner(tmp_path, generator, declaration, expected):
    source = tmp_path / "router.py"
    source.write_text(f'{declaration}\n@router.get("/points")\ndef points():\n    pass\n')
    [endpoint] = generator["analyze_router"](str(source))
    assert endpoint["path"] == expected


@pytest.mark.parametrize(
    "declaration",
    [
        "router = APIRouter(prefix=runtime_prefix)",
        "router = APIRouter(prefix=get_prefix())",
        "router = APIRouter(**configuration)",
    ],
)
def test_dynamic_router_prefix_fails_instead_of_inventing_api_path(tmp_path, generator, declaration):
    source = tmp_path / "router.py"
    source.write_text(f'{declaration}\n@router.get("/points")\ndef points():\n    pass\n')
    with pytest.raises(ValueError, match="prefix must be literal"):
        generator["analyze_router"](str(source))


def test_generator_requires_no_settings_env_or_database_import(tmp_path):
    """The inventory can be generated from an empty cwd with .env access forbidden."""
    probe = """
import os
import runpy
import sys
from pathlib import Path
def deny_env(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)) and Path(os.fsdecode(args[0])).name == '.env':
        raise AssertionError('RBAC inventory must not access .env')
sys.addaudithook(deny_env)
scope = runpy.run_path(sys.argv[1])
assert 'app.config' not in sys.modules
assert 'app.database' not in sys.modules
assert scope['ROLE_GROUPS']['OBSERVATION_ROLES']
assert scope['ROLE_GROUPS']['WINDOW_ROLES']
endpoints = scope['collect_endpoints']()
assert len(endpoints) == 654
assert len({item['module'] for item in endpoints}) == 89
"""
    result = subprocess.run([sys.executable, "-c", probe, str(Path(SCRIPT).resolve())], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
