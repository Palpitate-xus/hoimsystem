import pytest

from app.config import Settings


def _production_settings(**kwargs):
    values = {
        "ENVIRONMENT": "production",
        "DATABASE_URL": "postgresql://db-user:db-pass@db.example/hoimsystem",
        "SECRET_KEY": "a-long-production-secret-key-for-tests",
        "ALLOWED_ORIGINS": "https://his.example.com",
        "AUTO_CREATE_SCHEMA": False,
    }
    values.update(kwargs)
    return Settings(**values)


def test_production_config_accepts_explicit_origin():
    settings = _production_settings()
    assert settings.is_production is True
    assert settings.cors_origins == ["https://his.example.com"]


def test_production_config_rejects_runtime_schema_changes():
    with pytest.raises(ValueError, match="AUTO_CREATE_SCHEMA"):
        _production_settings(AUTO_CREATE_SCHEMA=True)


@pytest.mark.parametrize(
    "origins",
    [
        "http://localhost:8091,http://127.0.0.1:8091,http://localhost:8080,http://127.0.0.1:8080",
        "*",
        "",
    ],
)
def test_production_config_rejects_unsafe_origins(origins):
    with pytest.raises(ValueError, match="ALLOWED_ORIGINS"):
        _production_settings(ALLOWED_ORIGINS=origins)
