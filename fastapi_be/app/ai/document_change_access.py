"""Opaque dispatch identity, never authorization or a retained parent lock.

MySQL's independent READ COMMITTED connection reads exactly three immutable FK
columns and returns immediately. It does not change the caller's isolation or
hold an Artifact SHARE while waiting for its Source. SQLite uses the caller's
connection: a second StaticPool Session could roll back that transaction.
"""

from sqlalchemy import case, func, inspect, or_, select

from app.ai.document_change_run_models import AIDocumentChangeRunArtifact
from app.ai.document_change_view_contract import FEATURE_KEY
from app.ai.models import AIRun
from app.sql_json import json_extract, json_type, json_valid

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
    row = _current_technical(db, statement)
    return tuple(row) if row is not None else None


def _current_technical(db, statement):
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                return connection.execute(statement).one_or_none()
        return db.execute(statement).one_or_none()


def has_native_identity(db, run):
    """Three opaque Artifact columns first, otherwise one exact marker boolean.

    JSON functions execute in SQL but no Task text value is returned. Invalid
    JSON is replaced by an empty object ONLY for this classification predicate;
    it can never make a damaged native task pass its real closed validators.
    A null-valued unique key is still a native marker. No result grants access.
    """
    identifier = opaque_run_id(run)
    if locate_artifact(db, identifier) is not None:
        return True
    if db is None or type(identifier) is not str:
        return False
    mysql = db.get_bind().dialect.name in {"mysql", "mariadb"}
    markers = ("document_change", "document_change_binding", "document_change_source", "document_change_private_scope", "document_change_scope_id")
    predicates = []
    for name in ("input_json", "context_metadata_json", "evidence_json", "result_json"):
        column = getattr(AIRun, name)
        valid = case((json_valid(column) == 1, column), else_="{}")
        paths = ["$." + key for key in markers] + ["$.selected_sources.document_change_scope_id"]
        if name == "input_json":
            paths += ["$.payload.input.document_change_scope_id", "$.payload.context.selected_sources.document_change_scope_id"]
            paths += ["$.payload.context." + key for key in markers]
        if mysql:
            predicates.append(func.json_contains_path(valid, "one", *paths) == 1)
        else:
            predicates += [json_type(valid, path).is_not(None) for path in paths]

        def extract(path, doc=valid, unquote=mysql):
            value = json_extract(doc, path)
            return func.json_unquote(value) if unquote else value

        predicates += [extract(path) == "document_change_review" for path in ("$.scope", "$.source_domain", "$.payload.context.scope", "$.payload.context.source_domain")]
        predicates.append(extract("$.schema_version") == "document_change_result_ref_v1")
        if name == "evidence_json":
            predicates += [extract(f"$[{index}].kind") == "document_change_scope" for index in range(3)]
    value = case((AIRun.feature_key == FEATURE_KEY, True), else_=or_(*predicates)).label("document_change_marker")
    row = _current_technical(db, select(value).where(AIRun.run_id == identifier))
    return row is not None and row[0] is True
