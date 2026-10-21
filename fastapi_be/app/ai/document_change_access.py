"""Opaque dispatch identity, never authorization or a retained parent lock.

MySQL's independent READ COMMITTED connection reads exactly three immutable FK
columns and returns immediately. It does not change the caller's isolation or
hold an Artifact SHARE while waiting for its Source. SQLite uses the caller's
connection: a second StaticPool Session could roll back that transaction.
"""

from sqlalchemy import inspect, select

from app.ai.document_change_run_models import AIDocumentChangeRunArtifact

_STAGED = "document_change_staged_identities"


def opaque_run_id(run):
    if isinstance(run, str):
        return run
    state = inspect(run, raiseerr=False)
    if state is not None:
        return state.identity[0] if state.identity else state.dict.get("run_id")
    return getattr(run, "run_id", None)


def remember_staged_identity(db, artifact):
    """Only the actual writer supplies its own still-uncommitted identity."""
    values = tuple(getattr(artifact, key) for key in ("run_id", "scope_id", "requested_by"))
    db.info.setdefault(_STAGED, {})[values[0]] = (db.get_transaction(), values)


def locate_artifact(db, identifier):
    if db is None or type(identifier) is not str:
        return None
    own = db.info.get(_STAGED, {}).get(identifier)
    if own is not None and own[0] is db.get_transaction() and own[0] is not None:
        return own[1]
    statement = select(AIDocumentChangeRunArtifact.run_id, AIDocumentChangeRunArtifact.scope_id, AIDocumentChangeRunArtifact.requested_by).where(AIDocumentChangeRunArtifact.run_id == identifier)
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                row = connection.execute(statement).one_or_none()
        else:
            row = db.execute(statement).one_or_none()
    return tuple(row) if row is not None else None
