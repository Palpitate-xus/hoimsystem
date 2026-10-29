"""Real migration logging changes cannot escape the test isolation scope."""

import logging
from pathlib import Path

from alembic.config import Config

from alembic import command

PROBE = logging.getLogger("tests.alembic_logging_isolation")


def test_actual_migration_cannot_silence_logging_after_its_scope(tmp_path, caplog, isolate_logging_disable_state):
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'logging-isolation.db'}")
    with isolate_logging_disable_state():
        command.stamp(config, "head")
        assert PROBE.disabled
    assert not PROBE.disabled
    with caplog.at_level(logging.WARNING, logger=PROBE.name):
        PROBE.warning("Migration logging isolation probe")
    assert "Migration logging isolation probe" in caplog.text


def test_isolation_restores_intentionally_disabled_logging(isolate_logging_disable_state):
    PROBE.disabled = True
    logging.disable(logging.ERROR)
    with isolate_logging_disable_state():
        PROBE.disabled = False
        logging.disable(logging.NOTSET)
        added = logging.getLogger("tests.alembic_logging_isolation.created_inside_scope")
        added.disabled = True
    assert PROBE.disabled
    assert logging.root.manager.disable == logging.ERROR
    assert not added.disabled
