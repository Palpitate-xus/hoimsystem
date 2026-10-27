"""Shared routing preserves dedicated research authority and split task bodies."""

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select

from app.ai.models import AIRun
from app.ai.native_task_routing import locate_native_task, opaque_run_id
from app.sql_json import json_extract, json_type, json_valid


def research_marker_expression(*, mysql):
    """SQL technical routing hints only; a hint never supplies Source authority."""
    predicates = []
    for column, schema in (
        (AIRun.input_json, "research_cohort_task_ref_v1"),
        (AIRun.context_metadata_json, "research_cohort_task_metadata_v1"),
    ):
        valid = case((json_valid(column) == 1, column), else_="{}")
        value = json_extract(valid, "$.schema_version")
        predicates.append((func.json_unquote(value) if mysql else value) == schema)
        if column is AIRun.input_json:
            predicates.append(func.json_contains_path(valid, "one", "$.research_cohort_case_id") == 1 if mysql else json_type(valid, "$.research_cohort_case_id").is_not(None))
    return func.coalesce(or_(AIRun.feature_key == "research_cohort", *predicates), False)


def is_research_task(db, run):
    """Opaque durable domain first; orphan markers never grant access."""
    identity = locate_native_task(db, run)
    if identity is not None:
        return identity.domain == "research_cohort"
    identifier = opaque_run_id(run)
    if db is None or type(identifier) is not str:
        return False
    mysql = db.get_bind().dialect.name in {"mysql", "mariadb"}
    statement = select(research_marker_expression(mysql=mysql).label("research_native_marker")).where(AIRun.run_id == identifier)
    with db.no_autoflush:
        bind = db.get_bind()
        if mysql:
            with getattr(bind, "engine", bind).connect().execution_options(isolation_level="READ COMMITTED") as connection:
                row = connection.execute(statement).one_or_none()
        else:
            row = db.execute(statement).one_or_none()
    return row is not None and row[0] is True


def guard_research_task(db, user, run_id):
    """No Super frozen clinical bypass: full current Source precedes Task TEXT."""
    from app.ai.research_cohort_storage import load_artifact

    identity = locate_native_task(db, run_id)
    if identity is None or identity.domain != "research_cohort":
        raise HTTPException(409, "科研任务缺少完整持久分件，未降级读取或执行")
    return load_artifact(db, user, run_id, audit_only=False)


def split_trace(db, user, run_id):
    from app.ai.research_cohort_runtime import describe_research_run

    guard_research_task(db, user, run_id)
    return {
        "schema_version": "research_cohort_split_trace_v1",
        "run": describe_research_run(db, user, run_id),
        "parts_require_independent_current_reads": True,
        "parts": {part: f"/api/ai/research-cohort/tasks/{run_id}/parts/{part}" for part in ("task", "source", "scope", "result")},
    }


def directory_metadata(db, user, run):
    """Super directories quarantine incomplete native rows without private TEXT."""
    from app.ai.research_cohort_runtime import describe_research_run
    from app.ai.research_cohort_sources import utc_text
    from app.ai.research_cohort_write_guard import lock_research_write

    identity = locate_native_task(db, run)
    if identity is not None:
        if identity.domain != "research_cohort":
            raise HTTPException(409, "目录原生域不一致")
        return describe_research_run(db, user, identity.run_id)
    actor = lock_research_write(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "不完整科研任务只提供明确超级管理员技术目录")
    row = db.query(AIRun.run_id, AIRun.feature_key, AIRun.status, AIRun.create_time).filter_by(run_id=opaque_run_id(run)).populate_existing().with_for_update(read=True).one_or_none()
    if row is None:
        raise HTTPException(404, "任务不存在")
    return {
        "schema_version": "research_cohort_incomplete_task_metadata_v1",
        "run_id": row.run_id,
        "feature_key": row.feature_key,
        "status": row.status,
        "create_time": utc_text(row.create_time),
        "split_artifacts": True,
        "incomplete_native_artifact": True,
        "clinical_parts_available": False,
        "binding": None,
        "error_code": "NATIVE_ARTIFACT_REQUIRED",
        "error_message": "原持久分件不完整，仅保留技术元数据；不能读取正文或执行模型",
    }
