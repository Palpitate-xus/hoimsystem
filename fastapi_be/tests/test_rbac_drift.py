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
from collections import Counter
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


@pytest.mark.parametrize("module", ["inpatient_observations", "ai_observation_windows", "inpatient_laboratory", "ai_lab_mappings", "ai_risk_rules", "ai_news2", "ai_aki"])
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
    from app.ai.lab_mappings import MAPPING_ROLES
    from app.ai.news2_sources import ASSESSMENT_ROLES
    from app.ai.observation_windows import WINDOW_ROLES
    from app.ai.risk_rule_profiles import PROFILE_ROLES
    from app.inpatient_laboratory import LAB_READ_ROLES, LAB_SOURCE_ROLES
    from app.inpatient_observations import OBSERVATION_ROLES

    assert generator["ROLE_GROUPS"]["WINDOW_ROLES"] == set(WINDOW_ROLES)
    assert generator["ROLE_GROUPS"]["OBSERVATION_ROLES"] == set(OBSERVATION_ROLES)
    assert generator["ROLE_GROUPS"]["MAPPING_ROLES"] == set(MAPPING_ROLES)
    assert generator["ROLE_GROUPS"]["LAB_READ_ROLES"] == set(LAB_READ_ROLES)
    assert generator["ROLE_GROUPS"]["LAB_SOURCE_ROLES"] == set(LAB_SOURCE_ROLES)
    assert generator["ROLE_GROUPS"]["PROFILE_ROLES"] == set(PROFILE_ROLES)
    assert generator["ROLE_GROUPS"]["ASSESSMENT_ROLES"] == set(ASSESSMENT_ROLES)


def test_all_matrix_paths_match_actual_main_router_mounts(generator):
    """Include health/metrics mounts without assuming every router uses /api."""
    from fastapi.routing import APIRoute

    from app.main import app

    actual = Counter((method, route.path) for route in app.routes if isinstance(route, APIRoute) and route.endpoint.__module__.startswith("app.routers.") for method in route.methods)
    generated = Counter((row["method"], row["path"]) for row in generator["collect_endpoints"]())
    committed = Counter((row["method"], row["path"]) for row in json.loads((Path(SCRIPT).parents[1] / "rbac_matrix.json").read_text()))
    assert actual
    assert generated == actual
    assert committed == actual


def test_main_router_import_aliases_and_empty_mount_prefix(tmp_path, generator):
    source = tmp_path / "main.py"
    source.write_text('from app.routers import first as renamed, second\napp.include_router(renamed.router)\napp.include_router(second.router, prefix="/api")\n')
    assert generator["mounted_router_prefixes"](source) == {"first.py": "", "second.py": "/api"}


def test_mount_and_router_prefixes_match_actual_fastapi_composition(tmp_path, generator):
    from fastapi import APIRouter, FastAPI
    from fastapi.routing import APIRoute

    source = tmp_path / "main.py"
    source.write_text('from app.routers import scoped\napp.include_router(scoped.router, prefix="/hospital")\n')
    router_source = tmp_path / "scoped.py"
    router_source.write_text('router = APIRouter(prefix="/observations")\n@router.get("/points")\ndef points():\n    pass\n')
    [generated] = generator["analyze_router"](str(router_source), mount_prefix=generator["mounted_router_prefixes"](source)["scoped.py"])
    actual_app, actual_router = FastAPI(), APIRouter(prefix="/observations")
    actual_router.add_api_route("/points", lambda: None, methods=["GET"])
    actual_app.include_router(actual_router, prefix="/hospital")
    assert [generated["path"]] == [route.path for route in actual_app.routes if isinstance(route, APIRoute)]


@pytest.mark.parametrize(
    "mounts, message",
    [
        ("app.include_router(scoped.router, prefix=runtime_prefix)", "prefix must be literal"),
        ("app.include_router(scoped.router, **configuration)", "prefix must be literal"),
        ("app.include_router(unknown.router)", "module cannot be resolved"),
        ('app.include_router(scoped.router)\napp.include_router(scoped.router, prefix="/other")', "multiple mounts"),
        ("if enabled:\n    app.include_router(scoped.router)", "nested or dynamic router mounts"),
    ],
)
def test_dynamic_or_multiple_main_router_mounts_are_explicitly_rejected(tmp_path, generator, mounts, message):
    source = tmp_path / "main.py"
    source.write_text(f"from app.routers import scoped\n{mounts}\n")
    with pytest.raises(ValueError, match=message):
        generator["mounted_router_prefixes"](source)


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
assert endpoints
assert {'inpatient_laboratory.py', 'ai_lab_mappings.py', 'ai_news2.py', 'ai_risk_rules.py', 'ai_aki.py'} <= {item['module'] for item in endpoints}
"""
    result = subprocess.run([sys.executable, "-c", probe, str(Path(SCRIPT).resolve())], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
