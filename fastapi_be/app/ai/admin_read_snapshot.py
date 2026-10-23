"""Fresh SELECT-only administrative snapshots, without Source or worker locks."""

from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.sql.visitors import iterate

from app.ai.admin_write_authority import capture_authority
from app.models import User


def _actor_statement(authority):
    return select(User.user_id, User.username, User.user_role, User.token_invalid_before).where(User.user_id == authority.user_id)


def _verify_actor(connection, authority):
    row = connection.execute(_actor_statement(authority)).mappings().one_or_none()
    if row is None or row["user_role"] != "super_admin" or any(row[name] != value for name, value in authority.authenticated):
        raise HTTPException(403, "当前登录身份已无AI超级管理员权限，请重新登录")


@dataclass(frozen=True)
class AdminReadSnapshot:
    _connection: object

    def execute(self, statement):
        if not getattr(statement, "is_select", False) or any(getattr(node, "is_dml", False) or getattr(node, "_for_update_arg", None) is not None for node in iterate(statement)):
            raise ValueError("Administrative snapshots accept only unlocked SELECT statements")
        return self._connection.execute(statement)

    def scalar(self, statement):
        return self.execute(statement).scalar()


@contextmanager
def admin_read_snapshot(db, user):
    """Check the original subject before and after a coherent metadata read.

    MySQL receives a fresh RR transaction containing only unlocked SELECTs.
    Current authority is checked separately at READ COMMITTED, outside the old
    JWT read view. Release the snapshot connection before the final check so
    concurrent readers cannot exhaust the pool while each awaits another one.
    SQLite reuses the caller connection; no second StaticPool Session can roll
    back a caller's transaction. This context never commits caller writes.
    """
    authority = capture_authority(user)
    bind = db.get_bind()
    if bind.dialect.name in {"mysql", "mariadb"}:
        engine = getattr(bind, "engine", bind)
        with engine.connect().execution_options(isolation_level="READ COMMITTED") as current:
            _verify_actor(current, authority)
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                yield AdminReadSnapshot(connection)
        with engine.connect().execution_options(isolation_level="READ COMMITTED") as current:
            _verify_actor(current, authority)
    else:
        with db.no_autoflush:
            connection = db.connection()
            _verify_actor(connection, authority)
            yield AdminReadSnapshot(connection)
            _verify_actor(connection, authority)
