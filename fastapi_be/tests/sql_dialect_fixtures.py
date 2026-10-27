"""Explicit isolated dialect connections for SQL portability regression."""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


@pytest.fixture(params=("sqlite", "postgresql"))
def connection(request):
    if request.param == "postgresql":
        configured = os.environ.get("HOIM_TEST_POSTGRES_DDL_URL")
        if not configured:
            pytest.skip("HOIM_TEST_POSTGRES_DDL_URL must explicitly select an isolated loopback PostgreSQL benchmark database")
        url = make_url(configured)
        assert url.get_backend_name() == "postgresql" and url.host in {"localhost", "127.0.0.1", "::1"} and url.database == "hoimsystem_benchmark"
    else:
        url = "sqlite:///:memory:"
    engine = create_engine(url)
    with engine.connect() as value:
        yield value
    engine.dispose()

