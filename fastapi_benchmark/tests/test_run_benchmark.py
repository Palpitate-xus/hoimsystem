import json
import os
import subprocess
import sys
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BENCHMARK_DIR.parent


def test_runner_uses_independent_connections_and_pinned_database(tmp_path):
    unsafe_db = tmp_path / "production.db"
    probe = """
import json
import run_benchmark as target
from app.database import SessionLocal

first = SessionLocal()
second = SessionLocal()
try:
    first_connection = first.connection().connection.driver_connection
    second_connection = second.connection().connection.driver_connection
    print("PROBE=" + json.dumps({
        "database_url": str(target.bench_engine.url),
        "pool_class": type(target.bench_engine.pool).__name__,
        "connections_are_distinct": first_connection is not second_connection,
    }))
finally:
    second.close()
    first.close()
"""

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{unsafe_db.as_posix()}"
    env["PYTHONPATH"] = str(BENCHMARK_DIR)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload_line = next(line for line in result.stdout.splitlines() if line.startswith("PROBE="))
    payload = json.loads(payload_line.removeprefix("PROBE="))

    expected_db = (PROJECT_ROOT / "fastapi_be" / "benchmark.db").resolve()
    assert payload["database_url"] == f"sqlite:///{expected_db.as_posix()}"
    assert payload["pool_class"] == "QueuePool"
    assert payload["connections_are_distinct"] is True
    assert not unsafe_db.exists()
