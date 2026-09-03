import sys
from pathlib import Path

import pytest

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARK_DIR))

import benchmark_database  # noqa: E402


def test_postgresql_target_requires_exact_database_and_reset_confirmation(monkeypatch):
    safe_url = "postgresql://benchmark:secret@db/hoimsystem_benchmark"
    monkeypatch.delenv("BENCHMARK_RESET_CONFIRM", raising=False)

    with pytest.raises(RuntimeError, match="BENCHMARK_RESET_CONFIRM"):
        benchmark_database.validate_benchmark_url(safe_url, destructive=True)

    monkeypatch.setenv("BENCHMARK_RESET_CONFIRM", "hoimsystem_benchmark")
    assert benchmark_database.validate_benchmark_url(safe_url, destructive=True).database == "hoimsystem_benchmark"


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "postgresql://benchmark:secret@db/hoimsystem",
        "mysql://benchmark:secret@db/hoimsystem_benchmark",
        "sqlite:////tmp/production.db",
    ],
)
def test_benchmark_target_rejects_non_benchmark_databases(unsafe_url):
    with pytest.raises(RuntimeError):
        benchmark_database.validate_benchmark_url(unsafe_url)


def test_load_mode_rejects_sqlite(monkeypatch):
    monkeypatch.setenv("BENCHMARK_MODE", "load")

    with pytest.raises(RuntimeError, match="requires.*PostgreSQL"):
        benchmark_database.require_concurrency_safe_database(benchmark_database.SQLITE_BENCHMARK_URL)


def test_database_url_password_is_redacted(monkeypatch):
    from benchmark_metadata import _safe_database_target

    monkeypatch.setenv(
        "BENCHMARK_DATABASE_URL",
        "postgresql://benchmark:do-not-log-this@db/hoimsystem_benchmark",
    )

    target = _safe_database_target()
    assert "do-not-log-this" not in target
    assert "***" in target
