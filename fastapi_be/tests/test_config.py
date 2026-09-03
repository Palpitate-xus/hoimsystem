import pytest

from app.config import Settings


def test_production_rejects_default_secret_key():
    with pytest.raises(ValueError):
        Settings(
            ENVIRONMENT="production",
            DATABASE_URL="sqlite:///test.db",
            SECRET_KEY="change-me-in-production",
            AUTO_CREATE_SCHEMA=False,
        )


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
