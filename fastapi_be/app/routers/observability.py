"""Infrastructure probes and Prometheus exposition."""

import os

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest, multiprocess
from sqlalchemy import inspect, text
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.database import engine
from app.db_migrate import PROJECT_ROOT

router = APIRouter(include_in_schema=False)


@router.get("/health/live")
def liveness():
    return {"status": "ok"}


@router.get("/health/ready")
def readiness():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            tables = set(inspect(connection).get_table_names())
            if settings.is_production:
                if "alembic_version" not in tables:
                    return JSONResponse(status_code=503, content={"status": "unavailable", "message": "database schema is not versioned"})
                current = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
                config = Config(str(PROJECT_ROOT / "alembic.ini"))
                expected = set(ScriptDirectory.from_config(config).get_heads())
                if current != expected:
                    return JSONResponse(status_code=503, content={"status": "unavailable", "message": "database migration is not current"})
        if settings.REDIS_URL:
            from redis import Redis

            client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
            try:
                client.ping()
            finally:
                client.close()
        return {"status": "ready"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable", "message": "database is unavailable"})


@router.get("/metrics")
def metrics():
    if os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        payload = generate_latest(registry)
    else:
        payload = generate_latest()
    return Response(payload, media_type=CONTENT_TYPE_LATEST)
