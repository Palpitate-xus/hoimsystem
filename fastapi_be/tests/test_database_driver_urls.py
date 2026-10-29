"""PostgreSQL connections keep the installed driver after SQLAlchemy upgrades."""

import runpy
from contextlib import nullcontext
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from alembic import context
from app.config import Settings
from app.database import build_engine_options
from app.database_url import normalize_database_url


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "POSTGRESQL"])
def test_bare_postgres_url_preserves_encoded_credentials_and_options(scheme):
    suffix = "test-user:p%40ss%3A%2F%25word@localhost:5432/driver-test?application_name=driver-check&sslmode=require"
    normalized = normalize_database_url(scheme + "://" + suffix)
    assert normalized == "postgresql+psycopg2://" + suffix
    assert normalize_database_url(normalized) == normalized
    engine = create_engine(normalized)
    try:
        assert engine.dialect.driver == "psycopg2"
        assert engine.dialect.dbapi.__name__ == "psycopg2"
        assert engine.url.password == "p@ss:/%word"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///:memory:",
        "mysql+pymysql://user:pass@localhost/test",
        "postgresql+psycopg2://user:pass@localhost/test",
        "postgresql+psycopg://user:pass@localhost/test",
        "postgresql+asyncpg://user:pass@localhost/test",
    ],
)
def test_explicit_drivers_and_other_backends_are_preserved(url):
    assert normalize_database_url(url) == url


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_production_settings_make_legacy_url_driver_explicit(scheme):
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="production",
        DATABASE_URL=scheme + "://test-user:test-pass@localhost/driver-test",
        SECRET_KEY="driver-test-only-long-production-secret",
        AUTO_CREATE_SCHEMA=False,
        ALLOWED_ORIGINS="https://driver-test.example",
    )
    assert make_url(settings.DATABASE_URL).drivername == "postgresql+psycopg2"
    assert "statement_timeout=" in build_engine_options(scheme + "://localhost/driver-test")["connect_args"]["options"]


def test_component_settings_quote_credentials_without_changing_the_installed_driver():
    settings = Settings(
        _env_file=None,
        DATABASE_URL="",
        DB_USER="driver@user",
        DB_PASSWORD="test@:/% password",
        DB_HOST="localhost",
        DB_PORT="5439",
        DB_NAME="driver-test",
        SECRET_KEY="test-only-key",
    )
    parsed = make_url(settings.DATABASE_URL)
    assert parsed.drivername == "postgresql+psycopg2"
    assert parsed.username == "driver@user" and parsed.password == "test@:/% password"
    assert parsed.host == "localhost" and parsed.port == 5439 and parsed.database == "driver-test"


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_alembic_explicit_url_keeps_percent_encoding_and_uses_psycopg2(monkeypatch, scheme):
    config = Config()
    configured = scheme + "://test:p%40ss%25word@localhost/driver-test?application_name=driver-check"
    config.set_main_option("sqlalchemy.url", configured.replace("%", "%%"))
    recorded = {}
    monkeypatch.setattr(context, "config", config, raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    monkeypatch.setattr(context, "configure", lambda **kwargs: recorded.update(kwargs))
    monkeypatch.setattr(context, "begin_transaction", nullcontext)
    monkeypatch.setattr(context, "run_migrations", lambda: None)
    runpy.run_path(str(Path(__file__).parents[1] / "alembic/env.py"))
    assert recorded["url"] == normalize_database_url(configured)
    assert make_url(recorded["url"]).password == "p@ss%word"
