"""Narrow current child identity discovery after the actual Event parent X.

The immediately closed RC connection returns only child PK/event ID. It is
not authorization and cannot read narrative, grant, review or Case text.
Current main-transaction PK reads must verify both columns before any body.
"""

from fastapi import HTTPException
from sqlalchemy import event, inspect, select

from app.ai import rca_evidence_contract as c

_KEY = "_rca_current_own_flushed_keys"
_LISTENERS = "_rca_current_own_key_listeners"
_OWN_TABLES = {"hoimsystem_ai_rca_purpose_grant", "hoimsystem_ai_rca_evidence_original", "hoimsystem_ai_rca_evidence_case"}


def _descends(transaction, ancestor):
    while transaction is not None:
        if transaction is ancestor:
            return True
        transaction = transaction.parent
    return False


def _state(db):
    if not db.info.get(_LISTENERS):

        def rolled_back(session, previous):
            state = session.info.get(_KEY)
            if state is not None:
                state["keys"] = {key: scope for key, scope in state["keys"].items() if not _descends(scope, previous)}

        def ended(session, transaction):
            if transaction.parent is None:
                session.info.pop(_KEY, None)

        event.listen(db, "after_soft_rollback", rolled_back)
        event.listen(db, "after_transaction_end", ended)
        db.info[_LISTENERS] = True
    outer = db.get_transaction()
    state = db.info.get(_KEY)
    if state is None or state["outer"] is not outer:
        state = {"outer": outer, "keys": {}}
        db.info[_KEY] = state
    return state


def remember_flushed(db, row):
    """A real writer registers only its actual flushed ORM identity in this TX."""
    state = inspect(row, raiseerr=False)
    if state is None or not state.persistent or state.session is not db or state.identity is None or len(state.identity) != 1:
        raise ValueError("Only an actual flushed same-session Source row may register an own key")
    model = state.mapper.class_
    if model.__tablename__ not in _OWN_TABLES or "event_id" not in state.dict or db.get_transaction() is None:
        raise ValueError("Only this Source domain's real event-bound writers register keys")
    scope = db.get_nested_transaction() or db.get_transaction()
    _state(db)["keys"].setdefault((model.__tablename__, state.identity[0], state.dict["event_id"]), scope)


def discover(db, model, key, event_id, *, filters=()):
    """Caller already holds Actor/Event authority; final PK checks are required.

    Main RR ranges are deliberately not SHARE-locked: nonunique event-prefix
    next-key gaps otherwise block unrelated events despite the parent lock.
    SQLite uses its caller connection, never a second StaticPool session.
    """
    statement = select(getattr(model, key), model.event_id).where(model.event_id == event_id, *filters).order_by(getattr(model, key)).limit(c.MAX_MEMBERS + 1)
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb", "postgresql"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                rows = connection.execute(statement).all()
        else:
            rows = db.execute(statement).all()
    identities = {row[0] for row in rows}
    if any(row[1] != event_id for row in rows):
        raise HTTPException(409, "当前技术目录的实际事件身份不一致")
    state = _state(db)
    if state["outer"] is db.get_transaction():
        identities.update(identifier for (table, identifier, parent), _scope in state["keys"].items() if table == model.__tablename__ and parent == event_id)
    if len(identities) > c.MAX_MEMBERS:
        raise HTTPException(413, "完整当前技术目录超过4096上限，未截断或补造根件")
    return sorted(identities)


def current_metadata(db, model, key, identifier, event_id, columns):
    """Exact existing unique PK record lock, with parent match before TEXT."""
    from app.ai.rca_evidence_write_guard import current_rows

    with db.no_autoflush:
        row = current_rows(db.query(*columns).filter(getattr(model, key) == identifier), shared=True).one_or_none()
    if row is None or (row[0], row[1]) != (identifier, event_id):
        raise HTTPException(409, "技术目录或同事务新根的实际当前PK/事件不匹配，未读取其正文")
    return row
