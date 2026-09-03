"""Persist reproducibility metadata next to Locust result files."""

import datetime
import json
import os
import subprocess
from pathlib import Path

from sqlalchemy.engine import make_url


def _git_revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _safe_database_target() -> str:
    raw = os.getenv("BENCHMARK_DATABASE_URL", "sqlite smoke database")
    if raw == "sqlite smoke database":
        return raw
    try:
        return make_url(raw).render_as_string(hide_password=True)
    except Exception:
        return "invalid BENCHMARK_DATABASE_URL"


def build_run_metadata(environment, started_at: datetime.datetime) -> dict:
    total = environment.stats.total
    finished_at = datetime.datetime.now(datetime.UTC)
    return {
        "schema_version": 1,
        "git_revision": _git_revision(),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "host": environment.host,
        "profile": os.getenv("BENCHMARK_PROFILE", "smoke"),
        "mode": os.getenv("BENCHMARK_MODE", "smoke"),
        "database": _safe_database_target(),
        "requests": total.num_requests,
        "failures": total.num_failures,
        "failure_ratio": total.fail_ratio,
        "average_response_time_ms": total.avg_response_time,
        "p95_response_time_ms": total.get_response_time_percentile(0.95),
        "requests_per_second": total.total_rps,
        "users": environment.runner.user_count if environment.runner else 0,
    }


def register_metadata_hooks(events) -> None:
    state = {"started_at": None}

    @events.test_start.add_listener
    def remember_start(_environment, **_kwargs):
        state["started_at"] = datetime.datetime.now(datetime.UTC)

    @events.test_stop.add_listener
    def write_metadata(environment, **_kwargs):
        from locust.runners import WorkerRunner

        if isinstance(environment.runner, WorkerRunner):
            return
        started_at = state["started_at"] or datetime.datetime.now(datetime.UTC)
        output_dir = Path(os.getenv("BENCHMARK_RESULTS_DIR", "benchmark_results")).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        run_id = os.getenv("BENCHMARK_RUN_ID") or started_at.strftime("%Y%m%dT%H%M%SZ")
        output_path = output_dir / f"{run_id}.metadata.json"
        temporary_path = output_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(build_run_metadata(environment, started_at), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(output_path)
