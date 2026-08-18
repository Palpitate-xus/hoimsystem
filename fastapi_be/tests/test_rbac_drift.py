"""RBAC 矩阵漂移检测。

防止 rbac_matrix.json（及由其生成的 doc/api-rbac-matrix.md）与代码脱节：
任何路由的鉴权依赖变更后，必须重新运行 scripts/generate_rbac_matrix.py 并提交。
审计发现旧版矩阵把若干越权漏洞"合法化"（标 PUBLIC/全角色），此测试确保不再发生。
"""
import json
import os
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "generate_rbac_matrix.py")


def test_rbac_matrix_matches_code():
    result = subprocess.run(
        [sys.executable, SCRIPT, "--check"],
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, (
        f"RBAC 矩阵与代码不一致:\n{result.stdout}\n{result.stderr}\n"
        "请运行: python3 scripts/generate_rbac_matrix.py 并提交更新后的 "
        "doc/api-rbac-matrix.md 与 fastapi_be/rbac_matrix.json"
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
