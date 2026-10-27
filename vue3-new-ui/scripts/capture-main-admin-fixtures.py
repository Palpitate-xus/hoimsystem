"""Capture frontend admin fixtures from the real isolated Main/JWT tests.

Run with the backend Python environment and a new --output-dir under /tmp.
The command writes evidence and candidate fixtures there; it never overwrites
the checked-in fixtures, connects to a server, or opens a repository .env.
"""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


FRONTEND = Path(__file__).resolve().parents[1]
WORKSPACE = FRONTEND.parent
BACKEND = WORKSPACE / "fastapi_be"
FIXTURES = FRONTEND / "e2e/fixtures"
MODES = ("directory-main", "directory-service", "usage")


def capture_test_sources():
    """Freeze the selected tests and their recursive local test imports."""
    pending = [BACKEND / "tests" / name for name in (
        "conftest.py", "__init__.py", "test_ai_admin_task_directory.py",
        "test_ai_admin_usage_main.py", "test_ai_infection_cluster_task_runtime.py",
    )]
    found = set()
    while pending:
        path = pending.pop()
        if path in found or not path.is_file():
            continue
        found.add(path)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = [node.module] if isinstance(node, ast.ImportFrom) else [item.name for item in node.names] if isinstance(node, ast.Import) else []
            for module in modules:
                if module and module.startswith("tests."):
                    pending.append(BACKEND / (module.replace(".", "/") + ".py"))
    return found


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def source_hashes():
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "fastapi_be"],
        cwd=WORKSPACE,
    ).decode().split("\0")
    paths = {
        WORKSPACE / name for name in names
        if name and not name.startswith("fastapi_be/tests/")
        and Path(name).suffix in {".py", ".json", ".toml", ".ini", ".txt", ".md"}
        and not Path(name).name.startswith(".env")
    }
    paths.update(capture_test_sources())
    paths.update(WORKSPACE / name for name in (
        "doc/api-rbac-matrix.md", "doc/ai-prompts.json", "doc/ai-capabilities.md",
    ))
    paths.add(Path(__file__).resolve())
    return {str(path.relative_to(WORKSPACE)): sha256(path) for path in sorted(paths) if path.is_file()}


def isolate(output):
    """Install guards before any application import; keep all data disposable."""
    import builtins
    import io
    import secrets
    import socket

    allowed = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ") if key in os.environ}
    os.environ.clear()
    os.environ.update(allowed)
    os.environ.update({
        "DATABASE_URL": "sqlite:///:memory:",
        "SECRET_KEY": "synthetic-admin-capture-" + secrets.token_hex(32),
        "SCHEDULER_ENABLED": "false", "REDIS_URL": "",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    })
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    os.environ["TRANSPORT_RSA_PRIVATE_KEY_PEM"] = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ).decode("ascii")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(BACKEND))
    guards = {"dotenv_open_attempts": 0, "shared_transport_pem_attempts": 0, "socket_attempts": 0, "engine_urls": []}

    def audit(event, arguments):
        if event == "open" and arguments and isinstance(arguments[0], (str, bytes, os.PathLike)):
            if Path(os.fsdecode(arguments[0])).name == "hoimsystem_transport_key.pem":
                guards["shared_transport_pem_attempts"] += 1
                raise RuntimeError("Shared transport key access is forbidden")

    sys.addaudithook(audit)

    def guard_open(original):
        def guarded(file, *args, **kwargs):
            if not isinstance(file, int) and Path(os.fsdecode(file)).name.startswith(".env"):
                guards["dotenv_open_attempts"] += 1
                raise RuntimeError("Dotenv access is forbidden")
            return original(file, *args, **kwargs)
        return guarded

    builtins.open = guard_open(builtins.open)
    io.open = guard_open(io.open)

    def block_socket(*args, **kwargs):
        guards["socket_attempts"] += 1
        raise RuntimeError("External sockets are forbidden; capture uses ASGITransport")

    socket.socket.connect = block_socket
    socket.socket.connect_ex = block_socket
    socket.create_connection = block_socket
    socket.getaddrinfo = block_socket
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    dotenv.dotenv_values = lambda *args, **kwargs: {}
    from pydantic_settings import BaseSettings
    original_settings_init = BaseSettings.__init__

    def settings_init(self, *args, **kwargs):
        kwargs["_env_file"] = None
        original_settings_init(self, *args, **kwargs)

    BaseSettings.__init__ = settings_init
    import sqlalchemy
    original_engine = sqlalchemy.create_engine

    def create_engine(url, *args, **kwargs):
        parsed = sqlalchemy.engine.make_url(url)
        if parsed.get_backend_name() != "sqlite" or parsed.query.get("uri") or str(parsed.database or "").startswith("file:") or (
            parsed.database not in {None, "", ":memory:"}
            and not Path(parsed.database).resolve().is_relative_to(output)
        ):
            raise RuntimeError("Only in-memory or capture-owned SQLite databases are allowed")
        guards["engine_urls"].append(str(parsed))
        return original_engine(url, *args, **kwargs)

    sqlalchemy.create_engine = create_engine
    return guards


def capture(mode, output):
    output.mkdir(exist_ok=False)
    os.chdir(output)
    guards = isolate(output)
    before = source_hashes()
    write_json(output / "source-freeze.json", {
        "capture_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip(),
        "scope": "Backend production files, selected capture tests and recursive local test imports, public contracts, and this generator; unrelated tests excluded",
        "files": before,
    })
    packets, service_packets = [], []
    import httpx
    original_get = httpx.AsyncClient.get

    async def capture_get(self, url, *args, **kwargs):
        response = await original_get(self, url, *args, **kwargs)
        if mode == "directory-main":
            if str(url) == "/api/ai/admin/task-directory" and response.status_code == 200:
                query = dict(kwargs.get("params") or {})
                packets.append({"path": str(url), "query": query, "response": response.json()})
                if query.get("page_size") == 100:
                    query = {**query, "page_size": 30, "page": 1}
                    page = await original_get(self, url, *args, **{**kwargs, "params": query})
                    assert page.status_code == 200
                    packets.append({"path": str(url), "query": query, "response": page.json()})
            if str(url).startswith("/api/ai/admin/runs/"):
                packets.append({"path": str(url), "status": response.status_code})
        elif mode == "usage" and str(url) == "/api/ai/admin/usage":
            packets.append({"method": "GET", "path": str(url), "transport": "actual_Main_JWT", "status": response.status_code,
                            **({"response": response.json()} if response.status_code == 200 else {})})
        return response

    httpx.AsyncClient.get = capture_get
    if mode == "directory-service":
        from app.ai import admin_task_directory
        original_directory = admin_task_directory.task_directory

        def capture_directory(db, user, **kwargs):
            response = original_directory(db, user, **kwargs)
            packets.append({"query": kwargs, "response": response})
            return response

        admin_task_directory.task_directory = capture_directory
    elif mode == "usage":
        import copy
        from app.ai import admin_usage_summary
        original_summary = admin_usage_summary.usage_summary

        def capture_summary(*args, **kwargs):
            response = original_summary(*args, **kwargs)
            if any(row["feature_key"] == "infection_cluster" for row in response["data"]):
                service_packets.append({"transport": "actual_service_not_HTTP", "response": copy.deepcopy(response)})
            return response

        admin_usage_summary.usage_summary = capture_summary
    selections = {
        "directory-main": ["tests/test_ai_admin_task_directory.py", "-k", "main_technical_directory_is_super_only or super_without_variable_purposes or super_without_rca_purposes"],
        "directory-service": ["tests/test_ai_admin_task_directory.py", "-k", "complete_page_counts_and_feedback_filter"],
        "usage": ["tests/test_ai_admin_usage_main.py", "tests/test_ai_infection_cluster_task_runtime.py::test_actual_async_local_worker_releases_all_sql_before_cpu_and_accepts_only_complete_result"],
    }
    command = [*selections[mode], "-p", "pytest_asyncio.plugin", "-p", "no:cacheprovider", "-q",
               "--rootdir=" + str(BACKEND), "--basetemp=" + str(output / "pytest"), "--junitxml=" + str(output / "junit.xml")]
    # Resolve test paths without changing the safe temporary process directory.
    command = [str(BACKEND / item) if item.startswith("tests/") else item for item in command]
    import contextlib
    import pytest
    started = time.monotonic()
    with (output / "pytest.log").open("x") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        code = pytest.main(command)
    after = source_hashes()
    write_json(output / "capture.json", {"packets": packets, "service_packets": service_packets})
    result = {"mode": mode, "exit_code": int(code), "seconds": time.monotonic() - started,
              "source_stable": before == after, "source_changed": [name for name in before.keys() | after.keys() if before.get(name) != after.get(name)],
              "guards": guards, "command": command, "source_freeze_sha256": sha256(output / "source-freeze.json"),
              "capture_sha256": sha256(output / "capture.json"),
              "transport_key_basis": "Fresh process-only RSA2048; no key material or JWT tokens recorded",
              "scope": "Actual selected Main/JWT requests and separately labelled service calls, synthetic data only; no provider model or clinical validation"}
    write_json(output / "result.json", result)
    print(json.dumps(result))
    return int(code) or int(before != after) or int(any(guards[key] for key in guards if key != "engine_urls"))


def compose(output):
    runs = {mode: json.loads((output / mode / "capture.json").read_text()) for mode in MODES}
    freeze_documents = {mode: json.loads((output / mode / "source-freeze.json").read_text()) for mode in MODES}
    freezes = [freeze_documents[mode]["files"] for mode in MODES]
    assert freezes[0] == freezes[1] == freezes[2], "Backend source changed between real captures"
    for filename, mode in (("task-technical-directory-main.json", "directory-main"), ("usage-summary-main.json", "usage")):
        old = json.loads((FIXTURES / filename).read_text())
        candidate = {key: value for key, value in old.items() if key not in {"packets", "service_packets", "service_pages", "backend_bindings"}}
        candidate.update({"backend_capture_head": freeze_documents[mode]["capture_head"],
                          "backend_source_freeze_sha256": sha256(output / mode / "source-freeze.json"),
                          "backend_bindings": {name: freezes[0][name] for name in old["backend_bindings"]},
                          "capture_sha256": sha256(output / mode / "capture.json"), "packets": runs[mode]["packets"]})
        if mode == "directory-main":
            candidate["service_pages"] = runs["directory-service"]["packets"]
            candidate["service_pages_capture_sha256"] = sha256(output / "directory-service/capture.json")
            assert [len(page["response"]["data"]) for page in candidate["service_pages"][:4]] == [30, 30, 7, 0]
            assert len(candidate["service_pages"]) == 5 and candidate["service_pages"][4]["query"]["outcome"] == "rejected"
            assert [packet["status"] for packet in candidate["packets"] if "status" in packet] == [403, 403]
        else:
            candidate["service_packets"] = runs[mode]["service_packets"]
            assert sum(packet["status"] == 200 for packet in candidate["packets"]) == 7
            assert [packet["status"] for packet in candidate["packets"] if packet["status"] != 200] == [403] * 10 + [401]
            assert len(candidate["service_packets"]) == 1
        write_json(output / filename, candidate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--worker", choices=MODES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to(Path(tempfile.gettempdir()).resolve()) or output.exists():
        parser.error("--output-dir must be a new directory under the system temporary directory")
    if args.worker:
        return capture(args.worker, output)
    output.mkdir()
    environment = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ") if key in os.environ}
    for mode in MODES:
        with (output / (mode + "-worker.log")).open("x") as log:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", mode, "--output-dir", str(output / mode)],
                                    cwd=output, env=environment, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            print(f"Capture failed in {mode}; original log retained under {output}", file=sys.stderr)
            return result.returncode
    compose(output)
    write_json(output / "result.json", {"all_passed": True, "capture_script_sha256": sha256(Path(__file__).resolve()),
                                       "fixtures": {name: sha256(output / name) for name in ("task-technical-directory-main.json", "usage-summary-main.json")}})
    print(f"Real isolated capture complete; candidate fixtures and evidence: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
