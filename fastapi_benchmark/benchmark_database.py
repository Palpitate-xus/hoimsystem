"""Database isolation rules shared by benchmark entry points."""

import os
from pathlib import Path

from sqlalchemy.engine import URL, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_BACKEND_DIR = (PROJECT_ROOT / "fastapi_be").resolve()
BACKEND_DIR = _SOURCE_BACKEND_DIR if (_SOURCE_BACKEND_DIR / "app").is_dir() else PROJECT_ROOT
BENCHMARK_DB = BACKEND_DIR / "benchmark.db"
SQLITE_BENCHMARK_URL = f"sqlite:///{BENCHMARK_DB.as_posix()}"
POSTGRES_BENCHMARK_DATABASE = "hoimsystem_benchmark"
RESET_CONFIRMATION = POSTGRES_BENCHMARK_DATABASE


def resolve_benchmark_url() -> str:
    """Use an explicit benchmark URL or the repository-local SQLite smoke DB."""
    return os.getenv("BENCHMARK_DATABASE_URL", "").strip() or SQLITE_BENCHMARK_URL


def validate_benchmark_url(database_url: str, *, destructive: bool = False) -> URL:
    """Reject targets that are not unmistakably dedicated benchmark databases."""
    try:
        url = make_url(database_url)
    except Exception as exc:
        raise RuntimeError("BENCHMARK_DATABASE_URL is invalid") from exc

    backend = url.get_backend_name()
    if backend == "sqlite":
        database = Path(url.database or "")
        if BENCHMARK_DB.is_symlink():
            raise RuntimeError(f"Refusing symlinked benchmark database: {BENCHMARK_DB}")
        if not database.is_absolute() or database.resolve() != BENCHMARK_DB:
            raise RuntimeError(f"Refusing non-benchmark SQLite database: {url.render_as_string(hide_password=True)}")
        return url

    if backend not in {"postgresql", "postgres"} or url.database != POSTGRES_BENCHMARK_DATABASE:
        raise RuntimeError(
            "PostgreSQL benchmarks require a dedicated database named "
            f"{POSTGRES_BENCHMARK_DATABASE!r}"
        )
    if destructive and os.getenv("BENCHMARK_RESET_CONFIRM") != RESET_CONFIRMATION:
        raise RuntimeError(
            "Destructive PostgreSQL initialization requires "
            f"BENCHMARK_RESET_CONFIRM={RESET_CONFIRMATION}"
        )
    return url


def configure_application_environment(*, destructive: bool = False) -> str:
    """Pin application settings before importing any app modules."""
    database_url = resolve_benchmark_url()
    validate_benchmark_url(database_url, destructive=destructive)
    os.environ["DATABASE_URL"] = database_url
    os.environ["ENVIRONMENT"] = "development"
    os.environ["SCHEDULER_ENABLED"] = "false"
    os.environ["REDIS_URL"] = ""
    return database_url


def require_concurrency_safe_database(database_url: str) -> None:
    """Prevent publishing concurrency numbers from SQLite smoke runs."""
    url = validate_benchmark_url(database_url)
    mode = os.getenv("BENCHMARK_MODE", "smoke").strip().lower()
    if mode == "load" and url.get_backend_name() == "sqlite":
        raise RuntimeError("BENCHMARK_MODE=load requires the dedicated PostgreSQL benchmark database")
    if mode not in {"smoke", "load"}:
        raise RuntimeError("BENCHMARK_MODE must be either 'smoke' or 'load'")
