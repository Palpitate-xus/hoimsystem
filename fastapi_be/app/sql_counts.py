"""Count current rows without PostgreSQL's forbidden aggregate row lock."""

from sqlalchemy import func


def locked_row_count(query, primary_key, *, aggregate=False):
    """The caller retains its domain gate and supplies a locking current read.

    PostgreSQL locks the matching actual PK rows and counts their scalar result;
    it never reads private bodies or drops the requested SHARE/UPDATE lock.
    Existing MySQL/SQLite queries keep their original aggregate form, including
    current-read behavior and feature/time index hints under MySQL RR.
    """
    projected = query.with_entities(primary_key)
    if query.session.get_bind().dialect.name == "postgresql":
        return len(projected.all())
    return query.with_entities(func.count(primary_key)).scalar() if aggregate else projected.count()
