from app.database import build_engine_options


def test_sqlite_engine_options_avoid_server_pool_arguments():
    options = build_engine_options("sqlite:///:memory:")

    assert options["connect_args"] == {"check_same_thread": False}
    assert "pool_size" not in options
    assert "max_overflow" not in options


def test_postgresql_engine_options_bound_pool_and_queries():
    options = build_engine_options("postgresql://user:password@database/his")

    assert options["pool_size"] > 0
    assert options["max_overflow"] >= 0
    assert options["pool_timeout"] > 0
    assert "statement_timeout=" in options["connect_args"]["options"]
    assert options["connect_args"]["application_name"] == "hoimsystem-api"
