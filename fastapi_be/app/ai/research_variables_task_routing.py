"""Opaque76 dispatch and a boolean orphan probe, never Task authorization.

An actual Artifact remains76 after terminal status, wrong lease or erased Run
feature/JSON markers. No status-filtered miss can fall back to generic work.
The narrow RC/own-SQL locator returns its connection before authority waiting.
"""

from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy import case, func, inspect, or_, select

from app.ai.models import AIRun
from app.ai.research_cohort_contract import UUID
from app.ai.research_variables_task_contract import FEATURE_KEY, REFERENCE_KEY, SOURCE_DOMAIN
from app.ai.research_variables_task_reader import _current_opaque_identity


def identifier_for(value):
    state = inspect(value, raiseerr=False)
    identifier = value if type(value) is str else state.identity[0] if state is not None and state.identity else getattr(value, "run_id", None)
    if type(identifier) is not str:
        return None
    if len(identifier) > 256:
        raise HTTPException(422, "任务技术标识超出实际字段和有界别名查询范围")
    try:
        # Standard UUID case folding is lossless and keeps old non-UUID ASCII
        # IDs such as not-read out of this domain's SQL entirely.
        return TypeAdapter(UUID).validate_python(identifier.lower(), strict=True)
    except (ValueError, TypeError):
        # UCA ai_ci also equates accented Unicode and ignorable controls. Do
        # not approximate its Unicode algorithm or normalize private IDs: ask
        # the actual PK comparator for only opaque identity, by the raw value.
        if not any(not char.isascii() or char.isspace() or ord(char) < 32 or ord(char) == 127 for char in identifier):
            return None
        try:
            if len(identifier.encode("utf-8", errors="strict")) > 256:
                raise ValueError("Alias byte budget exceeded")
        except (UnicodeError, ValueError) as exc:
            raise HTTPException(422, "任务技术别名不是有界完整UTF8，未读取或截断") from exc
        return identifier


def marker_predicate(db):
    def safe(column):
        return case((func.json_valid(column) == 1, column), else_="{}")

    def item(column, path):
        value = func.json_extract(safe(column), path)
        return func.json_unquote(value) if db.get_bind().dialect.name in {"mysql", "mariadb"} else value

    def present(column, path):
        if db.get_bind().dialect.name in {"mysql", "mariadb"}:
            return func.json_contains_path(safe(column), "one", path) == 1
        return func.json_type(safe(column), path).is_not(None)

    return or_(
        AIRun.feature_key == FEATURE_KEY,
        item(AIRun.input_json, "$.schema_version") == "research_variable_task_snapshot_v1",
        present(AIRun.input_json, "$.payload.input." + REFERENCE_KEY),
        present(AIRun.input_json, "$.payload.context.research_variable_binding"),
        present(AIRun.input_json, "$.payload.context.scope.selected_sources." + REFERENCE_KEY),
        item(AIRun.input_json, "$.payload.context.scope.source_domain") == SOURCE_DOMAIN,
        item(AIRun.context_metadata_json, "$.source_domain") == SOURCE_DOMAIN,
        present(AIRun.context_metadata_json, "$.research_variable_binding"),
        item(AIRun.result_json, "$.schema_version") == "research_variable_result_ref_v1",
        present(AIRun.result_json, "$.research_variable_extraction"),
    )


def _marker_statement(db, identifier):
    # Only one computed bool is returned. No JSON scalar, Task body, identity
    # of another domain, row lock or permission is obtained by this probe.
    return select(marker_predicate(db)).where(AIRun.run_id == identifier)


def _current_document_identity(db, identifier):
    """Foreign opaque dispatch only: no Source/Run locks, JSON or authority.

    A known71 anchor must reach its original Super guard before an unrelated76
    orphan JSON probe. Current RC plus actual own-SQL also sees a new committed
    or same-transaction anchor under the caller's older consistent snapshot.
    """
    from app.ai.document_extraction_models import AIDocumentExtractionRunAnchor

    model = AIDocumentExtractionRunAnchor
    statement = select(model.run_id, model.original_id, model.requested_by).where(model.run_id == identifier)
    with db.no_autoflush:
        rows = set()
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                rows.update(tuple(row) for row in connection.execute(statement))
        rows.update(tuple(row) for row in db.execute(statement))
    if len(rows) > 1:
        raise HTTPException(409, "原文任务技术身份与本事务实际记录矛盾，未探测或读取任务正文")
    return next(iter(rows), None)


def is_variable_task(db, value):
    identifier = identifier_for(value)
    if identifier is None:
        return False
    native = _current_opaque_identity(db, identifier)
    document = _current_document_identity(db, identifier)
    if native is not None and document is not None:
        raise HTTPException(409, "同一任务同时绑定科研变量和原文锚，未优先任一域或降级读取")
    if native is not None:
        return True
    if document is not None:
        return False
    statement = _marker_statement(db, identifier)
    with db.no_autoflush:
        found = False
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                found = connection.execute(statement).scalar() is True
        found = db.execute(statement).scalar() is True or found
    if found:
        raise HTTPException(409, "科研变量原生任务保留标记却缺真实Artifact，未降级读取或执行")
    return False


def guard_variable_task_read(db, user, identifier, *, frozen_audit=False):
    if not is_variable_task(db, identifier):
        return None
    from app.ai.research_variables_task_reader import load_task

    return load_task(db, user, identifier, frozen_audit=frozen_audit)
