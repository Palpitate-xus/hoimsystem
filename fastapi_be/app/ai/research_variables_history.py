"""Committed76 task directory: narrow current IDs before per-row data access."""

from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy import func, select

from app.ai.models import AIRun
from app.ai.research_cohort_contract import UUID
from app.ai.research_cohort_write_guard import lock_research_write
from app.ai.research_variables_fields import VARIABLE_SOURCE_ROLES
from app.ai.research_variables_run_models import AIResearchVariableRunArtifact
from app.ai.research_variables_task_context import authorize_request
from app.ai.research_variables_task_contract import FEATURE_KEY
from app.ai.research_variables_task_views import describe_variable_run


def list_variable_history(db, user, *, feature_key, batch_id, other_scope=(), admin=False, status=None, requested_by=None, limit=30, offset=0):
    if feature_key != FEATURE_KEY or any(value is not None for value in other_scope):
        raise HTTPException(422, "科研变量历史仅使用明确批次，不接受诊疗、运营或其它原件范围")
    if type(admin) is not bool or type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise HTTPException(422, "科研变量历史需要明确有界分页，未截断完整单件")
    actor = lock_research_write(db, user, allowed_roles={"super_admin"} if admin else VARIABLE_SOURCE_ROLES)
    if batch_id is not None:
        try:
            TypeAdapter(UUID).validate_python(batch_id, strict=True)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, "历史批次须为明确规范UUID") from exc
        # Role alone does not authorize the selected project or its patients.
        authorize_request(db, actor, batch_id)
    statement = select(AIRun.run_id).join(AIResearchVariableRunArtifact, AIResearchVariableRunArtifact.run_id == AIRun.run_id)
    if batch_id is not None:
        statement = statement.where(AIResearchVariableRunArtifact.batch_id == batch_id)
    if not admin:
        statement = statement.where(AIResearchVariableRunArtifact.requested_by == actor.user_id)
    elif requested_by is not None:
        statement = statement.where(AIResearchVariableRunArtifact.requested_by == requested_by)
    if status is not None:
        statement = statement.where(AIRun.status == status)
    count_statement = select(func.count()).select_from(statement.subquery())
    page = statement.order_by(AIRun.create_time.desc(), AIRun.run_id).offset(offset).limit(limit)
    # This public directory lists committed jobs. Creation always commits
    # before its HTTP ack. No Run/Artifact locks or TEXT are taken for counting.
    # The held Research Gate keeps legitimate76 membership stable across the
    # two current metadata statements without substituting the caller's RR.
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                total = connection.execute(count_statement).scalar_one()
                identifiers = list(connection.execute(page).scalars())
        else:
            total = db.execute(count_statement).scalar_one()
            identifiers = list(db.execute(page).scalars())
    rows = []
    for identifier in identifiers:
        try:
            rows.append(describe_variable_run(db, actor, identifier, False, frozen_audit=admin))
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}:
                raise
            # Directory counts are technical task counts, never evidence that
            # this actor may read every old patient's Source or result.
    return rows, total
