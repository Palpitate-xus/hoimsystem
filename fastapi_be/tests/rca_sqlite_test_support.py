"""Own SQLite test connection policy; never a production FK relaxation."""

from contextlib import contextmanager

from sqlalchemy import text


@contextmanager
def preserve_foreign_key_mode(db):
    if db.get_bind().dialect.name != "sqlite":
        yield
        return
    previous = db.execute(text("PRAGMA foreign_keys")).scalar_one()
    try:
        yield
    finally:
        # PRAGMA foreign_keys cannot change during an actual transaction. End
        # this test's transaction before restoring the original pool policy.
        db.rollback()
        db.execute(text(f"PRAGMA foreign_keys={previous}"))
        db.commit()
        assert db.execute(text("PRAGMA foreign_keys")).scalar_one() == previous
