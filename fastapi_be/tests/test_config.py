import pytest

from app.config import Settings


@pytest.mark.parametrize(
    "secret",
    [
        "change-me-in-production",
        "development-only-change-me",
        "short-production-secret",
    ],
)
def test_production_rejects_weak_or_placeholder_secret_key(secret):
    with pytest.raises(ValueError, match="至少 32 字符"):
        Settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://user:password@db/hoimsystem",
            SECRET_KEY=secret,
            AUTO_CREATE_SCHEMA=False,
            ALLOWED_ORIGINS="https://his.example.com",
        )


def test_production_rejects_sqlite_database():
    with pytest.raises(ValueError, match="必须使用 PostgreSQL"):
        Settings(
            ENVIRONMENT="production",
            DATABASE_URL="sqlite:///production.db",
            SECRET_KEY="a-long-production-secret-key-for-tests",
            AUTO_CREATE_SCHEMA=False,
            ALLOWED_ORIGINS="https://his.example.com",
        )


def test_production_accepts_explicit_postgresql_driver():
    settings = Settings(
        ENVIRONMENT="production",
        DATABASE_URL="postgresql+psycopg2://user:password@db/hoimsystem",
        SECRET_KEY="a-long-production-secret-key-for-tests",
        AUTO_CREATE_SCHEMA=False,
        ALLOWED_ORIGINS="https://his.example.com",
    )

    assert settings.is_production


def test_cors_origins_are_parsed_from_comma_separated_config():
    settings = Settings(
        DATABASE_URL="sqlite:///test.db",
        SECRET_KEY="test-secret",
        ALLOWED_ORIGINS="https://his.example.com, https://portal.example.com",
    )
    assert settings.cors_origins == ["https://his.example.com", "https://portal.example.com"]


def test_development_defaults_to_sqlite_when_database_is_not_configured(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(SECRET_KEY="test-secret")
    assert settings.DATABASE_URL == "sqlite:///./test.db"
