import pytest

import seed_default_accounts


def test_seed_default_accounts_refuses_production_before_database_writes(monkeypatch):
    monkeypatch.setattr(seed_default_accounts.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        seed_default_accounts.Base.metadata,
        "create_all",
        lambda **_kwargs: pytest.fail("database schema must not be touched in production"),
    )

    with pytest.raises(RuntimeError, match="生产环境禁止"):
        seed_default_accounts.seed_default_accounts()
