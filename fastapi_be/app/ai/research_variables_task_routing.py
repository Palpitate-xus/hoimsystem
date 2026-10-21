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
from app.ai.research_variables_task_reader import locate_artifact


def identifier_for(value):
    state = inspect(value, raiseerr=False)
    identifier = value if type(value) is str else state.identity[0] if state is not None and state.identity else getattr(value, "run_id", None)
    try:
        return TypeAdapter(UUID).validate_python(identifier, strict=True)
    except (ValueError, TypeError):
        # Do not force a historical generic non-UUID ID into this task domain.
        return None


def _marker_statement(db, identifier):
    def safe(column):
        return case((func.json_valid(column) == 1, column), else_="{}")

    def item(column, path):
        value = func.json_extract(safe(column), path)
        return func.json_unquote(value) if db.get_bind().dialect.name in {"mysql", "mariadb"} else value

    def present(column, path):
        if db.get_bind().dialect.name in {"mysql", "mariadb"}:
            return func.json_contains_path(safe(column), "one", path) == 1
        return func.json_type(safe(column), path).is_not(None)

    predicate = or_(
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
    # Only one computed bool is returned. No JSON scalar, Task body, identity
    # of another domain, row lock or permission is obtained by this probe.
    return select(predicate).where(AIRun.run_id == identifier)


def is_variable_task(db, value):
    identifier = identifier_for(value)
    if identifier is None:
        return False
    if locate_artifact(db, identifier) is not None:
        return True
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
