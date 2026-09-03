import json
import os
import subprocess
import sys
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BENCHMARK_DIR.parent


def test_initializer_pins_and_guards_benchmark_database(tmp_path):
    unsafe_db = tmp_path / "production.db"
    unsafe_url = f"sqlite:///{unsafe_db.as_posix()}"
    probe = """
import json
from sqlalchemy import create_engine
import init_benchmark_data as target

unsafe_engine = create_engine(__UNSAFE_URL__)
try:
    target._assert_benchmark_engine(unsafe_engine)
except RuntimeError:
    guard_rejected = True
else:
    guard_rejected = False

print("PROBE=" + json.dumps({
    "database_url": str(target.engine.url),
    "database_path": str(target.BENCHMARK_DB),
    "guard_rejected": guard_rejected,
}))
""".replace("__UNSAFE_URL__", repr(unsafe_url))

    env = os.environ.copy()
    env["DATABASE_URL"] = unsafe_url
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
    assert Path(payload["database_path"]) == expected_db
    assert payload["database_url"] == f"sqlite:///{expected_db.as_posix()}"
    assert payload["guard_rejected"] is True
    assert not unsafe_db.exists()


def test_initializer_rebuilds_a_stale_benchmark_schema(tmp_path):
    benchmark_db = tmp_path / "benchmark.db"
    probe = """
import json
from pathlib import Path
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
import init_benchmark_data as target

database_path = Path(__DATABASE_PATH__)
replacement_engine = create_engine("sqlite:///" + database_path.as_posix())
with replacement_engine.begin() as connection:
    connection.exec_driver_sql(
        "CREATE TABLE hoimsystem_department "
        "(department_id INTEGER PRIMARY KEY, name VARCHAR(24))"
    )

target.BENCHMARK_DB = database_path
target.engine = replacement_engine
target.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=replacement_engine)
target.init()

columns = {column["name"] for column in inspect(replacement_engine).get_columns("hoimsystem_department")}
with target.SessionLocal() as session:
    user_count = session.query(target.User).count()
print("PROBE=" + json.dumps({"columns": sorted(columns), "user_count": user_count}))
""".replace("__DATABASE_PATH__", repr(benchmark_db.as_posix()))

    env = os.environ.copy()
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

    assert "campus_id" in payload["columns"]
    assert payload["user_count"] == 7
