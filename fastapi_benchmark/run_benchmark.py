"""HOIM System isolated benchmark ASGI entry point."""

import os
import sys

from benchmark_database import (
    BACKEND_DIR,
    configure_application_environment,
    require_concurrency_safe_database,
)

sys.path.insert(0, str(BACKEND_DIR))

BENCHMARK_DATABASE_URL = configure_application_environment()
require_concurrency_safe_database(BENCHMARK_DATABASE_URL)

from app.database import engine as bench_engine  # noqa: E402
from app.main import app as app  # noqa: E402


@app.get("/benchmark/info", include_in_schema=False)
def benchmark_info():
    return {"schema_version": 1, "benchmark_database": bench_engine.url.database,
            "mode": os.getenv("BENCHMARK_MODE", "smoke"), "profile": os.getenv("BENCHMARK_PROFILE", "smoke")}

print("Server ready: HOIM System Benchmark")
print(f"Database: {bench_engine.url.render_as_string(hide_password=True)}")
print(f"Mode: {__import__('os').getenv('BENCHMARK_MODE', 'smoke')}")
print(f"Pool: {type(bench_engine.pool).__name__}")
