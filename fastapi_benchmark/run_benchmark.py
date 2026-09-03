"""HOIM System 性能基准测试运行器。

使用 SQLAlchemy 的文件型 SQLite QueuePool，为并发请求提供独立连接。
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = (PROJECT_ROOT / "fastapi_be").resolve()
BENCHMARK_DB = BACKEND_DIR / "benchmark.db"
BENCHMARK_DATABASE_URL = f"sqlite:///{BENCHMARK_DB.as_posix()}"

# Never inherit an ambient application database for an isolated benchmark run.
os.environ["DATABASE_URL"] = BENCHMARK_DATABASE_URL
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings
from app.database import Base
from app.database import engine as bench_engine
from app.main import app as app

# 确保表存在
Base.metadata.create_all(bind=bench_engine)

print("Server ready: HOIM System Benchmark")
print(f"Database: {settings.DATABASE_URL}")
print(f"Pool: {type(bench_engine.pool).__name__} (independent pooled connections)")
